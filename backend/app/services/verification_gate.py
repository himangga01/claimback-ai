import hashlib
import os
import re
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR
from typing import Tuple, List, Optional, Dict, Any

from app.schemas.loan_fact import (
    LoanFactSchema,
    GeneratedClaimDraft,
    VerificationResult,
    VerificationStatusEnum,
    CurrencyEnum,
    EvidenceTypeEnum,
    TransactionKindEnum,
    ContractFormEnum,
    Calculation,
    CalculationStep,
    AllocationItem,
    RateClause,
    ReferenceTotal,
    LimitCheck,
)


def verify_file_bytes_sha256(file_path: str, expected_hash: str) -> bool:
    """실제 파일 바이트를 읽어 SHA-256 해시가 일치하는지 확인"""
    if not os.path.exists(file_path):
        return False
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower() == expected_hash.strip().lower()


_D365 = Decimal("365")
_KR_SMALL_THRESHOLD = Decimal("30000000")
_US_SC100_THRESHOLD = Decimal("12500.00")
_US_ANNUAL_COUNT_THRESHOLD = Decimal("2500.00")


def _kr_days(start_exclusive: date, end_inclusive: date) -> int:
    diff = (end_inclusive - start_exclusive).days
    return diff if diff > 0 else 0


def _kr_numer(principal: Decimal, days: int, rate_percent: Decimal) -> Decimal:
    if days <= 0 or principal <= Decimal("0") or rate_percent <= Decimal("0"):
        return Decimal("0")
    return principal * rate_percent * Decimal(days)


def _kr_interest_exact(principal: Decimal, days: int, rate_percent: Decimal) -> Decimal:
    if days <= 0 or principal <= Decimal("0") or rate_percent <= Decimal("0"):
        return Decimal("0")
    return (principal * rate_percent * Decimal(days)) / Decimal("36500")


def _floor_krw(amount: Decimal) -> Decimal:
    if amount <= Decimal("0"):
        return Decimal("0")
    return amount.to_integral_value(rounding=ROUND_FLOOR)


def _format_rate(rate: Decimal) -> str:
    d = rate.normalize()
    return format(d, "f")


def _format_kr_date(d: date) -> str:
    return f"{d.year}. {d.month}. {d.day}."


def _format_exact_2(amount: Decimal) -> str:
    q = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"{q:,.2f}"


def _build_rate_sentence(
    remaining: Decimal, accrual: date, pre_rate: Decimal, post_rate: Decimal
) -> str:
    amt = f"{int(remaining):,}"
    when = _format_kr_date(accrual)
    if pre_rate == post_rate:
        return (
            f"채무자는 채권자에게 {amt}원 및 이에 대하여 {when}부터 "
            f"다 갚는 날까지 연 {_format_rate(pre_rate)}%의 비율로 계산한 돈을 지급하라."
        )
    return (
        f"채무자는 채권자에게 {amt}원 및 이에 대하여 {when}부터 "
        f"이 사건 지급명령 정본 송달일까지는 연 {_format_rate(pre_rate)}%, "
        f"그 다음 날부터 다 갚는 날까지는 연 {_format_rate(post_rate)}%의 "
        "각 비율로 계산한 돈을 지급하라."
    )


_UNSUPPORTED_REPAYMENT_MSG = (
    "이 변제 형태(이자보다 적은 변제)의 청구취지 문구는 아직 지원하지 않습니다. "
    "확인할 칸: 변제 내역"
)


_UNSUPPORTED_RATE_MSG = (
    "이 이율 조합의 청구취지 문구는 아직 지원하지 않습니다. "
    "확인할 칸: 약정 이율"
)


def _kr_interval_interest(
    loan_fact: LoanFactSchema,
    principal: Decimal,
    start_exc: date,
    end_inc: date,
    capped_agreed: Optional[Decimal],
    pre_rate: Decimal,
    post_rate: Decimal,
):
    total = Decimal("0")
    pre_part = Decimal("0")
    post_part = Decimal("0")
    cont_part = Decimal("0")
    details: List[Tuple[str, int, Decimal, Decimal, date, date]] = []
    if end_inc <= start_exc or principal <= Decimal("0"):
        return total, pre_part, post_part, cont_part, details
    if capped_agreed is not None:
        o_start = max(start_exc, loan_fact.loan_date)
        o_end = min(end_inc, loan_fact.due_date)
        days = _kr_days(o_start, o_end)
        if days > 0:
            exact = _kr_interest_exact(principal, days, capped_agreed)
            cont_part += exact
            total += exact
            details.append(("약정 이자", days, capped_agreed, exact, o_start, o_end))
    if loan_fact.service_date is not None:
        o_start = max(start_exc, loan_fact.due_date)
        o_end = min(end_inc, loan_fact.service_date)
    else:
        o_start = max(start_exc, loan_fact.due_date)
        o_end = end_inc
    if o_end > loan_fact.due_date and o_end > o_start:
        days_pre = _kr_days(o_start, o_end)
        if days_pre > 0:
            exact_pre = _kr_interest_exact(principal, days_pre, pre_rate)
            pre_part += exact_pre
            total += exact_pre
            label_pre = "지연손해금(송달 전)" if loan_fact.service_date is not None else "지연손해금"
            details.append((label_pre, days_pre, pre_rate, exact_pre, o_start, o_end))
    if loan_fact.service_date is not None:
        o_start_post = max(start_exc, loan_fact.service_date)
        o_end_post = end_inc
        if o_end_post > loan_fact.service_date and o_end_post > o_start_post:
            days_post = _kr_days(o_start_post, o_end_post)
            if days_post > 0:
                exact_post = _kr_interest_exact(principal, days_post, post_rate)
                post_part += exact_post
                total += exact_post
                details.append(
                    ("지연손해금(송달 후)", days_post, post_rate, exact_post, o_start_post, o_end_post)
                )
    return total, pre_part, post_part, cont_part, details


def _kr_interval_numer(
    loan_fact: LoanFactSchema,
    principal: Decimal,
    start_exc: date,
    end_inc: date,
    capped_agreed: Optional[Decimal],
    pre_rate: Decimal,
    post_rate: Decimal,
) -> Decimal:
    numer_total = Decimal("0")
    if end_inc <= start_exc or principal <= Decimal("0"):
        return numer_total
    if capped_agreed is not None:
        o_start = max(start_exc, loan_fact.loan_date)
        o_end = min(end_inc, loan_fact.due_date)
        days = _kr_days(o_start, o_end)
        if days > 0:
            numer_total += _kr_numer(principal, days, capped_agreed)
    if loan_fact.service_date is not None:
        o_start = max(start_exc, loan_fact.due_date)
        o_end = min(end_inc, loan_fact.service_date)
    else:
        o_start = max(start_exc, loan_fact.due_date)
        o_end = end_inc
    if o_end > loan_fact.due_date and o_end > o_start:
        days_pre = _kr_days(o_start, o_end)
        if days_pre > 0:
            numer_total += _kr_numer(principal, days_pre, pre_rate)
    if loan_fact.service_date is not None:
        o_start_post = max(start_exc, loan_fact.service_date)
        o_end_post = end_inc
        if o_end_post > loan_fact.service_date and o_end_post > o_start_post:
            days_post = _kr_days(o_start_post, o_end_post)
            if days_post > 0:
                numer_total += _kr_numer(principal, days_post, post_rate)
    return numer_total


def calculate_kr(loan_fact: LoanFactSchema, as_of: date) -> Calculation:
    warnings: List[str] = []
    missing_fields: List[str] = []
    steps: List[CalculationStep] = []
    allocations: List[AllocationItem] = []

    agreed = loan_fact.agreed_interest_rate
    capped: Optional[Decimal] = None
    if agreed is not None:
        if agreed > Decimal("20.0"):
            warnings.append(
                f"입력한 약정 이율(연 {_format_rate(agreed)}%)이 계산 상한 연 20%보다 높아 "
                "연 20%로 계산했습니다. 확인할 칸: 약정 이율"
            )
            capped = Decimal("20.0")
        else:
            capped = agreed

    statutory = (
        Decimal("6.0")
        if loan_fact.transaction_kind == TransactionKindEnum.COMMERCIAL
        else Decimal("5.0")
    )
    if capped is not None and capped > statutory:
        pre_rate = capped
    else:
        pre_rate = statutory
    if capped is not None:
        post_rate = capped if capped > Decimal("12.0") else Decimal("12.0")
    else:
        post_rate = Decimal("12.0")

    if loan_fact.due_date > as_of:
        missing_fields.append("due_date")

    sorted_reps = sorted(
        [r for r in loan_fact.repayments if r.payment_date <= as_of],
        key=lambda x: x.payment_date,
    )
    if any(r.payment_date > as_of for r in loan_fact.repayments):
        warnings.append(
            f"기준일({_format_kr_date(as_of)}) 뒤의 변제가 있어 받지 않은 것으로 계산했습니다. "
            "확인할 칸: 변제 내역"
        )

    current_principal = loan_fact.principal_amount
    overpayment = Decimal("0")
    carry_unpaid = Decimal("0")
    unsupported = False
    pre_total = Decimal("0")
    post_total = Decimal("0")

    prev_exc = loan_fact.loan_date
    for rep in sorted_reps:
        total_exact, pre_exact, post_exact, _cont, details = _kr_interval_interest(
            loan_fact, current_principal, prev_exc, rep.payment_date,
            capped, pre_rate, post_rate,
        )
        pre_total += pre_exact
        post_total += post_exact
        for label, days, rate, exact, _s, _e in details:
            principal_str = f"{int(current_principal):,}"
            formula = (
                f"{principal_str} × {_format_rate(rate)}% × {days}/365 = "
                f"{_format_exact_2(exact)}"
            )
            steps.append(CalculationStep(label=label, formula=formula, amount=exact))
        numer_total = _kr_interval_numer(
            loan_fact, current_principal, prev_exc, rep.payment_date,
            capped, pre_rate, post_rate,
        )
        combined_numer = carry_unpaid * Decimal("36500") + numer_total
        combined_exact = combined_numer / Decimal("36500")
        floored = combined_numer // Decimal("36500")
        steps.append(
            CalculationStep(
                label="충당 시 이자 합계",
                formula=f"{_format_exact_2(combined_exact)} → {int(floored):,}원",
                amount=floored,
            )
        )
        if rep.amount < floored:
            unsupported = True
            if "repayments" not in missing_fields:
                missing_fields.append("repayments")
            allocations.append(
                AllocationItem(
                    payment_date=rep.payment_date,
                    payment_amount=rep.amount,
                    applied_to_cost=Decimal("0"),
                    applied_to_interest=rep.amount,
                    applied_to_principal=Decimal("0"),
                    remaining_principal_after=current_principal,
                )
            )
            carry_unpaid = floored - rep.amount
            prev_exc = rep.payment_date
            continue
        applied_interest = floored
        rem = rep.amount - floored
        if rem >= current_principal and current_principal > Decimal("0"):
            overpayment += rem - current_principal
            allocations.append(
                AllocationItem(
                    payment_date=rep.payment_date,
                    payment_amount=rep.amount,
                    applied_to_cost=Decimal("0"),
                    applied_to_interest=applied_interest,
                    applied_to_principal=current_principal,
                    remaining_principal_after=Decimal("0"),
                )
            )
            current_principal = Decimal("0")
        else:
            if current_principal > Decimal("0"):
                applied_principal = rem
                current_principal -= rem
            else:
                applied_principal = Decimal("0")
                overpayment += rem
            allocations.append(
                AllocationItem(
                    payment_date=rep.payment_date,
                    payment_amount=rep.amount,
                    applied_to_cost=Decimal("0"),
                    applied_to_interest=applied_interest,
                    applied_to_principal=applied_principal,
                    remaining_principal_after=current_principal,
                )
            )
        carry_unpaid = Decimal("0")
        prev_exc = rep.payment_date

    if current_principal > Decimal("0"):
        total_exact_f, pre_exact_f, post_exact_f, _cont_f, details_f = _kr_interval_interest(
            loan_fact, current_principal, prev_exc, as_of, capped, pre_rate, post_rate
        )
        pre_total += pre_exact_f
        post_total += post_exact_f
        for label, days, rate, exact, _s, _e in details_f:
            principal_str = f"{int(current_principal):,}"
            formula = (
                f"{principal_str} × {_format_rate(rate)}% × {days}/365 = "
                f"{_format_exact_2(exact)}"
            )
            steps.append(CalculationStep(label=label, formula=formula, amount=exact))
        numer_final = _kr_interval_numer(
            loan_fact, current_principal, prev_exc, as_of, capped, pre_rate, post_rate
        )
        combined_numer_f = carry_unpaid * Decimal("36500") + numer_final
        combined_final = combined_numer_f / Decimal("36500")
        floored_final = combined_numer_f // Decimal("36500")
        steps.append(
            CalculationStep(
                label="기준일 이자 합계",
                formula=f"{_format_exact_2(combined_final)} → {int(floored_final):,}원",
                amount=floored_final,
            )
        )
        accrued = floored_final
        reference_amount = current_principal + accrued
    else:
        accrued = Decimal("0")
        reference_amount = Decimal("0")

    unsupported_rate = capped is not None and capped < statutory
    if unsupported_rate and "agreed_interest_rate" not in missing_fields:
        missing_fields.append("agreed_interest_rate")
    if capped is not None and capped >= statutory:
        if sorted_reps:
            accrual_start = sorted_reps[-1].payment_date + timedelta(days=1)
        else:
            accrual_start = loan_fact.loan_date + timedelta(days=1)
    else:
        if sorted_reps:
            last_rep_date = sorted_reps[-1].payment_date
            due_next = loan_fact.due_date + timedelta(days=1)
            last_next = last_rep_date + timedelta(days=1)
            accrual_start = due_next if due_next > last_next else last_next
        else:
            accrual_start = loan_fact.due_date + timedelta(days=1)

    if unsupported or unsupported_rate or current_principal <= Decimal("0"):
        sentence = ""
    else:
        sentence = _build_rate_sentence(current_principal, accrual_start, pre_rate, post_rate)

    exceeded = current_principal > _KR_SMALL_THRESHOLD
    limit_msg: Optional[str] = None
    if exceeded:
        limit_msg = (
            f"청구 원금 {int(current_principal):,}원이 소액사건 기준 금액 "
            "30,000,000원보다 큽니다. 확인할 칸: 원금"
        )
        warnings.append(limit_msg)
    limit_check = LimitCheck(
        jurisdiction="KR",
        threshold=_KR_SMALL_THRESHOLD,
        compared_amount=current_principal,
        exceeded=exceeded,
        message=limit_msg,
    )

    if unsupported and "repayments" not in missing_fields:
        missing_fields.append("repayments")

    return Calculation(
        allocations=allocations,
        remaining_principal=current_principal,
        accrual_start_date=accrual_start,
        rate_clause=RateClause(
            pre_service_rate=pre_rate, post_service_rate=post_rate, sentence=sentence
        ),
        reference_total=ReferenceTotal(as_of=as_of, amount=reference_amount),
        limit_check=limit_check,
        missing_fields=missing_fields,
        warnings=warnings,
        calculation_steps=steps,
        overpayment_amount=overpayment,
        accrued_interest=accrued,
    )


class DeterministicLegalCalculator:
    """
    한·미 이자 및 일부변제 충당 계산기
    - 한국: 초일불산입, 말일 포함, 365일 고정, 원 미만 버림(충당 시점)
    - 미국: 연 10% 단리, 센트 단위(기존 방식 유지)
    """

    calculate_kr = staticmethod(calculate_kr)

    @staticmethod
    def is_leap_year(year: int) -> bool:
        return (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)

    @classmethod
    def calculate_statutory_interest_daily(
        cls,
        principal: Decimal,
        start_date: date,
        end_date: date,
        annual_rate: Decimal,
    ) -> Decimal:
        """
        일할 이자 계산(미국 트랙 호환용, 기존 방식 유지):
        각 일자별로 해당 연도가 윤년(366일)인지 평년(365일)인지에 따라 합산
        """
        if end_date <= start_date or principal <= Decimal("0.00"):
            return Decimal("0.00")

        total_interest = Decimal("0.00")
        rate_fraction = annual_rate / Decimal("100.0")

        curr = start_date
        while curr < end_date:
            next_year_start = date(curr.year + 1, 1, 1)
            block_end = min(end_date, next_year_start)

            days = Decimal(str((block_end - curr).days))
            days_in_year = Decimal("366") if cls.is_leap_year(curr.year) else Decimal("365")

            period_interest = principal * rate_fraction * (days / days_in_year)
            total_interest += period_interest
            curr = block_end

        return total_interest.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    calculate_statutory_interest = calculate_statutory_interest_daily

    @classmethod
    def calculate_segmented_interest(
        cls,
        principal: Decimal,
        start_date: date,
        end_date: date,
        loan_fact: LoanFactSchema,
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        송달일 경계가 포함된 구간의 2단계 분할 이자 계산
        반환값: (총이자, 송달전이자, 송달후이자)
        """
        if end_date <= start_date or principal <= Decimal("0.00"):
            return Decimal("0.00"), Decimal("0.00"), Decimal("0.00")

        if loan_fact.currency == CurrencyEnum.USD:
            i = cls.calculate_statutory_interest_daily(principal, start_date, end_date, Decimal("10.0"))
            return i, i, Decimal("0.00")

        if loan_fact.agreed_interest_rate is not None:
            # 상한 20% 적용 (주석의 판례 번호는 참고용)
            agreed_in = loan_fact.agreed_interest_rate
            agreed = agreed_in if agreed_in <= Decimal("20.0") else Decimal("20.0")
            service_d = loan_fact.service_date
            post_service_start = (service_d + timedelta(days=1)) if service_d else None

            if post_service_start and start_date < post_service_start < end_date:
                post_rate = agreed if agreed > Decimal("12.0") else Decimal("12.0")
                i1 = cls.calculate_statutory_interest_daily(principal, start_date, post_service_start, agreed)
                i2 = cls.calculate_statutory_interest_daily(principal, post_service_start, end_date, post_rate)
                return (i1 + i2), i1, i2
            elif post_service_start and start_date >= post_service_start:
                post_rate = agreed if agreed > Decimal("12.0") else Decimal("12.0")
                i = cls.calculate_statutory_interest_daily(principal, start_date, end_date, post_rate)
                return i, Decimal("0.00"), i
            else:
                i = cls.calculate_statutory_interest_daily(principal, start_date, end_date, agreed)
                return i, i, Decimal("0.00")

        pre_rate = Decimal("6.0") if loan_fact.transaction_kind == TransactionKindEnum.COMMERCIAL else Decimal("5.0")
        post_rate = Decimal("12.0")

        service_d = loan_fact.service_date
        post_service_start = (service_d + timedelta(days=1)) if service_d else None

        if post_service_start and start_date < post_service_start < end_date:
            i1 = cls.calculate_statutory_interest_daily(principal, start_date, post_service_start, pre_rate)
            i2 = cls.calculate_statutory_interest_daily(principal, post_service_start, end_date, post_rate)
            return (i1 + i2), i1, i2
        elif post_service_start and start_date >= post_service_start:
            i = cls.calculate_statutory_interest_daily(principal, start_date, end_date, post_rate)
            return i, Decimal("0.00"), i
        else:
            i = cls.calculate_statutory_interest_daily(principal, start_date, end_date, pre_rate)
            return i, i, Decimal("0.00")

    @classmethod
    def apply_repayments_and_calculate_balance(
        cls,
        loan_fact: LoanFactSchema,
        calculation_date: date,
    ) -> Tuple[Decimal, Decimal, Decimal, List[str], Dict[str, Any]]:
        """
        일부변제 충당 계산: 비용 -> 이자 -> 원금 순서 (순수함수 처리)
        - 한국: 초일불산입·말일 포함, 365일 고정, 충당 시점 버림
        - 미국: 기존 센트 단위 방식 유지
        """
        if loan_fact.currency == CurrencyEnum.USD:
            return cls._apply_us(loan_fact, calculation_date)
        return cls._apply_kr(loan_fact, calculation_date)

    @classmethod
    def _apply_us(
        cls,
        loan_fact: LoanFactSchema,
        calculation_date: date,
    ) -> Tuple[Decimal, Decimal, Decimal, List[str], Dict[str, Any]]:
        audit_log: List[str] = []
        interest_breakdown: Dict[str, Any] = {
            "pre_service_interest": Decimal("0.00"),
            "post_service_interest": Decimal("0.00"),
        }
        current_principal = loan_fact.principal_amount
        accrued_interest = Decimal("0.00")
        overpayment_amount = Decimal("0.00")
        last_date = loan_fact.due_date + timedelta(days=1)
        if calculation_date < last_date and not loan_fact.repayments:
            return current_principal, Decimal("0.00"), Decimal("0.00"), audit_log, interest_breakdown
        sorted_repayments = sorted(deepcopy(loan_fact.repayments), key=lambda x: x.payment_date)
        for rep in sorted_repayments:
            rep_date = rep.payment_date
            if rep_date > calculation_date:
                continue
            p_interest, pre_i, post_i = cls.calculate_segmented_interest(
                current_principal, last_date, rep_date, loan_fact
            )
            accrued_interest += p_interest
            interest_breakdown["pre_service_interest"] += pre_i
            interest_breakdown["post_service_interest"] += post_i
            audit_log.append(f"{last_date} ~ {rep_date} interest {p_interest} accrued")
            last_date = rep_date
            rem_payment = rep.amount
            if accrued_interest > Decimal("0.00"):
                if rem_payment >= accrued_interest:
                    rem_payment -= accrued_interest
                    audit_log.append(f"{rep_date} interest {accrued_interest} covered")
                    accrued_interest = Decimal("0.00")
                else:
                    accrued_interest -= rem_payment
                    audit_log.append(f"{rep_date} interest partly covered")
                    rem_payment = Decimal("0.00")
            if rem_payment > Decimal("0.00"):
                if rem_payment >= current_principal:
                    overpayment_amount += rem_payment - current_principal
                    audit_log.append(f"{rep_date} principal fully paid (overpayment: {rem_payment - current_principal})")
                    current_principal = Decimal("0.00")
                else:
                    current_principal -= rem_payment
                    audit_log.append(f"{rep_date} principal {rem_payment} covered")
        if calculation_date >= last_date and current_principal > Decimal("0.00"):
            final_interest, pre_i, post_i = cls.calculate_segmented_interest(
                current_principal, last_date, calculation_date, loan_fact
            )
            accrued_interest += final_interest
            interest_breakdown["pre_service_interest"] += pre_i
            interest_breakdown["post_service_interest"] += post_i
            audit_log.append(f"{last_date} ~ {calculation_date} interest(10.0%) {final_interest} accrued")
        return current_principal, accrued_interest, overpayment_amount, audit_log, interest_breakdown

    @classmethod
    def _apply_kr(
        cls,
        loan_fact: LoanFactSchema,
        calculation_date: date,
    ) -> Tuple[Decimal, Decimal, Decimal, List[str], Dict[str, Any]]:
        calc = calculate_kr(loan_fact, calculation_date)
        audit_log: List[str] = []
        for w in calc.warnings:
            audit_log.append(w)
        for step in calc.calculation_steps:
            audit_log.append(f"{step.label}: {step.formula}")

        agreed = loan_fact.agreed_interest_rate
        if agreed is not None:
            capped_log = agreed if agreed <= Decimal("20.0") else Decimal("20.0")
            audit_log.append(f"약정 이율 연 {_format_rate(capped_log)}%로 계산")
        else:
            base_rate = (
                Decimal("6.0")
                if loan_fact.transaction_kind == TransactionKindEnum.COMMERCIAL
                else Decimal("5.0")
            )
            audit_log.append(f"기준 이율 연 {_format_rate(base_rate)}%로 계산")

        for alloc in calc.allocations:
            audit_log.append(
                f"{alloc.payment_date} 변제액 중 이자 {alloc.applied_to_interest} 충당, "
                f"원금 {alloc.applied_to_principal} 충당 (남은 원금: {alloc.remaining_principal_after})"
            )
            if calc.overpayment_amount > Decimal("0") and alloc.remaining_principal_after == Decimal("0"):
                audit_log.append(
                    f"{alloc.payment_date} 변제액으로 원금 전액 완제 "
                    f"(초과 과오납: {calc.overpayment_amount})"
                )
                break

        pre_total = Decimal("0.00")
        post_total = Decimal("0.00")
        has_service = loan_fact.service_date is not None
        if has_service:
            for step in calc.calculation_steps:
                if step.label == "지연손해금(송달 전)":
                    pre_total += step.amount
                elif step.label == "지연손해금(송달 후)":
                    post_total += step.amount
            if pre_total > Decimal("0") and post_total > Decimal("0"):
                start_inc = loan_fact.due_date + timedelta(days=1)
                audit_log.append(
                    f"{start_inc} ~ {calculation_date} 소촉법 송달 후 지연손해금(연 12%) "
                    f"{_format_exact_2(post_total)} 발생"
                )
                pre_rate = calc.rate_clause.pre_service_rate
                audit_log.append(
                    f"{start_inc} ~ {calculation_date} 송달 전 지연손해금(연 {_format_rate(pre_rate)}%) "
                    f"{_format_exact_2(pre_total)} 발생"
                )
        else:
            for step in calc.calculation_steps:
                if step.label in ("지연손해금", "지연손해금(송달 전)"):
                    pre_total += step.amount
            if pre_total > Decimal("0"):
                pass

        if not has_service:
            q_pre = pre_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if pre_total > 0 else Decimal("0.00")
            breakdown: Dict[str, Any] = {
                "pre_service_interest": q_pre,
                "post_service_interest": Decimal("0.00"),
            }
        else:
            q_pre = pre_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if pre_total > 0 else Decimal("0.00")
            q_post = post_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if post_total > 0 else Decimal("0.00")
            breakdown = {"pre_service_interest": q_pre, "post_service_interest": q_post}

        if loan_fact.service_date is not None and calculation_date <= loan_fact.service_date:
            breakdown["post_service_interest"] = Decimal("0.00")

        remaining = calc.remaining_principal
        accrued = calc.accrued_interest
        overp = calc.overpayment_amount
        return remaining, accrued, overp, audit_log, breakdown


class VerificationGateService:
    """
    결정론적 규칙 검증 게이트
    - 원본 증거 수치와 입력값 교차 대조
    - 실 파일 SHA-256 바이트 대조 연동
    - 통화 불일치 및 전액 변제 확인
    - 관할별 청구 한도 확인
    - 초일불산입 및 송달 익일 기산점 적용
    """

    @classmethod
    def verify_and_reconcile(
        cls,
        loan_fact: LoanFactSchema,
        claim_draft: GeneratedClaimDraft,
        target_date: Optional[date] = None,
        evidence_files_dir: Optional[str] = None,
    ) -> VerificationResult:
        if target_date is not None:
            today = target_date
        else:
            latest = loan_fact.due_date
            for r in loan_fact.repayments:
                if r.payment_date > latest:
                    latest = r.payment_date
            if loan_fact.loan_date > latest:
                latest = loan_fact.loan_date
            today = latest
        audit_notes: List[str] = []
        missing_requirements: List[str] = []
        tampering_reconciliations: List[str] = []
        is_valid = True
        status = VerificationStatusEnum.PASS

        for rep in loan_fact.repayments:
            if rep.currency is not None and rep.currency != loan_fact.currency:
                missing_requirements.append(
                    f"변제 통화({rep.currency.value})가 대여 원금 통화({loan_fact.currency.value})와 다릅니다. "
                    "확인할 칸: 변제 내역"
                )

        for ev in loan_fact.evidences:
            if ev.currency is not None and ev.currency != loan_fact.currency:
                missing_requirements.append(
                    f"증거 통화({ev.currency.value})가 대여 원금 통화({loan_fact.currency.value})와 다릅니다. "
                    "확인할 칸: 증거 내역"
                )

        if evidence_files_dir and os.path.exists(evidence_files_dir):
            for ev in loan_fact.evidences:
                fpath = os.path.join(evidence_files_dir, ev.source_filename)
                if os.path.exists(fpath):
                    if not verify_file_bytes_sha256(fpath, ev.sha256_hash):
                        missing_requirements.append(
                            f"증거 파일({ev.source_filename})의 실제 SHA-256 해시가 선언값과 다릅니다. "
                            "확인할 칸: 증거 파일"
                        )
                    else:
                        audit_notes.append(
                            f"증거 파일({ev.source_filename})의 SHA-256 해시가 선언값과 일치합니다."
                        )

        transfer_evidences = [
            e for e in loan_fact.evidences if e.evidence_type == EvidenceTypeEnum.TRANSFER_RECEIPT
        ]
        has_any_role = any(getattr(e, "role", None) is not None for e in transfer_evidences)
        if has_any_role:
            loan_transfers = [
                e for e in transfer_evidences if getattr(e, "role", None) == "loan_transfer"
            ]
        else:
            loan_transfers = transfer_evidences
        primary_pool = loan_transfers
        if not loan_transfers:
            missing_requirements.append("대여 이체 증빙이 없습니다. 확인할 칸: 이체 내역")

        has_due_agreement = any(
            e.evidence_type in (EvidenceTypeEnum.LOAN_AGREEMENT, EvidenceTypeEnum.MESSENGER_CHAT)
            for e in loan_fact.evidences
        )
        if not has_due_agreement:
            missing_requirements.append("변제기 근거가 없습니다. 확인할 칸: 변제기")

        if not loan_fact.creditor.name or not loan_fact.creditor.name.strip():
            missing_requirements.append("채권자 이름이 비어 있습니다. 확인할 칸: 당사자 이름")
        if not loan_fact.debtor.name or not loan_fact.debtor.name.strip():
            missing_requirements.append("채무자 이름이 비어 있습니다. 확인할 칸: 당사자 이름")

        if loan_fact.due_date > today:
            missing_requirements.append(
                f"변제기({loan_fact.due_date})가 기준일({today})보다 뒤입니다. 확인할 칸: 변제기"
            )

        if primary_pool:
            primary_transfer = primary_pool[0]
            if primary_transfer.extracted_amount is not None:
                if primary_transfer.extracted_amount != loan_fact.principal_amount:
                    missing_requirements.append(
                        f"이체증빙 추출액({primary_transfer.extracted_amount})과 입력 원금({loan_fact.principal_amount})이 "
                        "일치하지 않습니다. 확인할 칸: 대여 원금"
                    )

        calc_obj: Optional[Calculation] = None
        if loan_fact.currency == CurrencyEnum.KRW:
            calc_obj = calculate_kr(loan_fact, today)
            remaining_principal = calc_obj.remaining_principal
            calculated_interest = calc_obj.accrued_interest
            overpayment = calc_obj.overpayment_amount
            for w in calc_obj.warnings:
                audit_notes.append(w)
            for step in calc_obj.calculation_steps:
                audit_notes.append(f"{step.label}: {step.formula}")
            breakdown: Dict[str, Any] = {
                "pre_service_interest": Decimal("0.00"),
                "post_service_interest": Decimal("0.00"),
            }
            pre_sum = Decimal("0")
            post_sum = Decimal("0")
            for step in calc_obj.calculation_steps:
                if step.label == "지연손해금(송달 전)":
                    pre_sum += step.amount
                elif step.label == "지연손해금(송달 후)":
                    post_sum += step.amount
                elif step.label == "지연손해금":
                    pre_sum += step.amount
            if pre_sum > 0:
                breakdown["pre_service_interest"] = pre_sum.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            if post_sum > 0:
                breakdown["post_service_interest"] = post_sum.quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            if loan_fact.service_date is not None and today <= loan_fact.service_date:
                breakdown["post_service_interest"] = Decimal("0.00")
            expected_total = calc_obj.reference_total.amount
            if "repayments" in calc_obj.missing_fields and calc_obj.rate_clause.sentence == "":
                missing_requirements.append(_UNSUPPORTED_REPAYMENT_MSG)
            if "agreed_interest_rate" in calc_obj.missing_fields and calc_obj.rate_clause.sentence == "":
                missing_requirements.append(_UNSUPPORTED_RATE_MSG)
        else:
            remaining_principal, calculated_interest, overpayment, calc_logs, breakdown = (
                DeterministicLegalCalculator.apply_repayments_and_calculate_balance(
                    loan_fact=loan_fact,
                    calculation_date=today,
                )
            )
            audit_notes.extend(calc_logs)
            expected_total = remaining_principal + calculated_interest

        is_satisfied = remaining_principal == Decimal("0.00") and calculated_interest == Decimal("0.00")
        if is_satisfied:
            if not any("변제 내역" in m for m in missing_requirements):
                missing_requirements.append("입력한 변제 합계가 원리금 이상입니다. 확인할 칸: 변제 내역")

        if loan_fact.currency == CurrencyEnum.KRW:
            if calc_obj is not None and calc_obj.limit_check is not None and calc_obj.limit_check.exceeded:
                pass
        else:
            if expected_total > _US_SC100_THRESHOLD:
                missing_requirements.append(
                    f"청구 금액 ${expected_total:,.2f}가 이 도구의 SC-100 작성 범위($12,500 이하)를 넘어 "
                    "서류를 만들지 않습니다."
                )
            if expected_total > _US_ANNUAL_COUNT_THRESHOLD and loan_fact.prior_claims_over_2500_this_year >= 2:
                missing_requirements.append("SC-100 양식의 연간 청구 건수 항목을 확인하세요.")

        reconciled_amount = remaining_principal
        draft_claimed = claim_draft.claim_amount_claimed
        matches_remaining = draft_claimed == remaining_principal
        matches_total = draft_claimed == expected_total
        if not matches_remaining and not matches_total:
            tampering_reconciliations.append(
                f"초안 금액({draft_claimed})이 계산값(남은 원금 {remaining_principal}, "
                f"참고 총액 {expected_total})과 다릅니다."
            )
            missing_requirements.append("초안의 금액이 계산값과 다릅니다. 확인할 칸: 청구 금액")

        valid_evidence_ids = {e.id for e in loan_fact.evidences}
        cited_ids = set(claim_draft.cited_evidence_ids)
        text_citations = set(
            re.findall(r"\[(갑 제\d+호증(?:의\d+)?|Exhibit [A-Z0-9]+)\]", claim_draft.statement_of_facts)
        )
        all_found_citations = cited_ids.union(text_citations)

        invalid_citations = all_found_citations - valid_evidence_ids
        if invalid_citations:
            missing_requirements.append(
                f"목록에 없는 증거 ID({', '.join(sorted(invalid_citations))})가 인용되었습니다. "
                "확인할 칸: 증거 인용"
            )

        if len(all_found_citations) == 0:
            missing_requirements.append("청구원인 본문에 증거 인용이 없습니다. 확인할 칸: 증거 인용")
            citations_valid = False
        else:
            citations_valid = len(invalid_citations) == 0

        if missing_requirements:
            is_valid = False
            status = VerificationStatusEnum.HUMAN_CHECK_REQUIRED
            audit_notes.append("확인할 칸이 비어 있어 서류 생성이 보류되었습니다.")
        elif tampering_reconciliations:
            status = VerificationStatusEnum.RECONCILED
            audit_notes.append("초안 금액과 계산값이 다릅니다.")
        else:
            status = VerificationStatusEnum.PASS
            audit_notes.append("모든 확인 항목을 통과하였습니다.")

        return VerificationResult(
            status=status,
            is_valid=is_valid,
            reconciled_amount=reconciled_amount,
            calculated_interest=calculated_interest,
            total_claim_amount=expected_total,
            overpayment_amount=overpayment,
            is_debt_fully_satisfied=is_satisfied,
            citations_valid=citations_valid,
            missing_requirements=missing_requirements,
            tampering_reconciliations=tampering_reconciliations,
            audit_notes=audit_notes,
            interest_breakdown=breakdown,
            calculation=calc_obj,
        )
