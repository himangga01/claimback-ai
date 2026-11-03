/* ClaimBack-AI case-flow screen (M2b-fix1). Vanilla JS, no build, no external scripts. */
"use strict";

const S = {
  caseId: null,
  caseView: null,
  readings: [],
  review: null,
  drafts: null,
  pkg: null,
  selectedEx: null,
  serverOk: false,
  running: false,
  runGen: 0,
  putting: false,
  redactions: null,
  segments: null,
  // Per flagged exhibit: "confirmed" or "excluded", only from a click.
  redactionChoice: {},
};

const AGENTS = [
  { group: "Forensic Visual", desc: "증거 접수와 목록 정리", descEn: "Takes in the evidence and lists it" },
  { group: "Fact-Timeline Chronology", desc: "증거 읽기와 사실 정리", descEn: "Reads the evidence and organizes the facts" },
  { group: "Financial Auditor", desc: "계산과 숫자 대조", descEn: "Calculates and cross-checks the numbers" },
  { group: "Judicial Form Filler", desc: "서류 묶음 만들기", descEn: "Builds the document package" },
];

const STATE_KO = {
  INTAKE: "접수",
  READING: "판독 중",
  ORGANIZING: "사실 정리 중",
  CHECKPOINT_1: "사실 확인 대기",
  CALCULATING: "계산 중",
  DRAFTING: "문안 작성 중",
  VERIFYING: "검증 중",
  DRAFT_APPROVAL: "문안 승인 대기",
  PACKAGING: "편철 중",
  CHECKPOINT_2: "최종 확인",
  HOLD: "보류",
};

const STATE_EN = {
  INTAKE: "Intake",
  READING: "Reading",
  ORGANIZING: "Organizing facts",
  CHECKPOINT_1: "Waiting for your fact check",
  CALCULATING: "Calculating",
  DRAFTING: "Drafting",
  VERIFYING: "Verifying",
  DRAFT_APPROVAL: "Waiting for draft approval",
  PACKAGING: "Packaging",
  CHECKPOINT_2: "Final check",
  HOLD: "On hold",
};

const STATE_ORDER = [
  "INTAKE", "READING", "ORGANIZING", "CHECKPOINT_1", "CALCULATING",
  "DRAFTING", "VERIFYING", "DRAFT_APPROVAL", "PACKAGING", "CHECKPOINT_2",
];

const STATUS_KO = {
  waiting: "대기",
  running: "실행 중",
  done: "완료",
  hold: "보류",
  skipped: "건너뜀",
};

const STATUS_EN = {
  waiting: "Waiting",
  running: "Running",
  done: "Done",
  hold: "On hold",
  skipped: "Skipped",
};

const TAG_KO = {
  loan_request: "빌려 달라는 말",
  amount_mention: "금액 언급",
  repay_promise: "갚겠다는 말",
  reminder: "갚아 달라는 말",
  other: "기타",
};

const TAG_EN = {
  loan_request: "Asks to borrow",
  amount_mention: "Mentions an amount",
  repay_promise: "Promises to repay",
  reminder: "Asks for repayment",
  other: "Other",
};

const GATE_KO = {
  G1a: "숫자·이름은 슬롯으로만",
  G1b: "최종 서류 검사",
  G3: "문장마다 증거 표시",
  G2: "필수 칸 확인",
  G4: "금액 범위 확인",
  NAMING: "금지 표현 검사",
  DRAFT: "문안 규칙 검사",
};

const GATE_EN = {
  G1a: "Numbers and names only from your confirmed values",
  G1b: "Final document check",
  G3: "Evidence on every sentence",
  G2: "Required fields",
  G4: "Amount range",
  NAMING: "Banned wording check",
  DRAFT: "Drafting rules",
};

const ROLE_OPTIONS = [
  ["loan_transfer", "대여 이체", "Loan transfer"],
  ["repayment", "변제 입금", "Repayment received"],
  ["loan_agreement", "차용증", "IOU"],
  ["other", "기타", "Other"],
];

const KNOWN_ROLES = new Set(ROLE_OPTIONS.map(([val]) => val));

/* ---------- language ---------- */

const LANG_KEY = "claimback:lang";
let LANG = pickLang();

function saveLang(lang) {
  try {
    window.localStorage.setItem(LANG_KEY, lang);
  } catch {
    /* storage blocked: the choice lasts for this page only */
  }
}

// ?lang= wins (and is saved like a click, so links without it keep the
// language), then the saved choice, then the browser's first language.
function pickLang() {
  try {
    const q = new URLSearchParams(window.location.search).get("lang");
    if (q === "ko" || q === "en") {
      saveLang(q);
      return q;
    }
  } catch {
    /* no query string */
  }
  try {
    const saved = window.localStorage.getItem(LANG_KEY);
    if (saved === "ko" || saved === "en") return saved;
  } catch {
    /* storage blocked */
  }
  const first = (navigator.languages && navigator.languages.length
    ? navigator.languages[0] : navigator.language) || "ko";
  return String(first).toLowerCase().startsWith("ko") ? "ko" : "en";
}

function L(ko, en) {
  return LANG === "en" ? en : ko;
}

function stateName(st) {
  return (LANG === "en" ? STATE_EN : STATE_KO)[st] || st;
}

function statusName(status) {
  return (LANG === "en" ? STATUS_EN : STATUS_KO)[status] || status;
}

function tagName(tag) {
  return (LANG === "en" ? TAG_EN : TAG_KO)[tag] || tag;
}

// Fixed backend texts shown on screen (step names, notes, field and file
// labels). Case content such as names, chats and the court text stays as is.
const BACKEND_EN = {
  "접수 담당": "Intake",
  "판독 담당": "Reader",
  "시각 감식 담당": "Visual check (SAM)",
  "사실 정리 담당": "Fact organizer",
  "개인정보 보호 담당": "Privacy",
  "사용자 확인": "Your fact check",
  "계산 담당": "Calculator",
  "문안 작성 담당": "Drafter",
  "검증 담당(G1a·G3)": "Verifier (G1a·G3)",
  "사용자 문장 승인": "Your sentence approval",
  "편철 담당": "Packager",
  "사용자 최종 확인": "Your final check",
  "사실값 확인과 강조할 발화 선택": "Confirm the facts and pick statements to highlight",
  "문장별 수정·승인": "Edit and approve each sentence",
  "최종 서류 확인": "Final document check",
  "채권자 이름": "Creditor name",
  "채권자 주소": "Creditor address",
  "채권자 연락처": "Creditor phone",
  "채무자 이름": "Debtor name",
  "채무자 주소": "Debtor address",
  "원금": "Principal",
  "대여일": "Loan date",
  "변제기": "Due date",
  "약정 이율(연 %)": "Agreed interest rate (% per year)",
  "거래 종류": "Transaction type",
  "받은 돈": "Repayments received",
  "약정 없음": "None agreed",
  "정확한 표기를 확인해 주세요.": "Please confirm the exact spelling.",
  "지연손해금": "Late-payment interest",
  "충당 시 이자 합계": "Interest at repayment",
  "기준일 이자 합계": "Interest as of the date",
  "내용증명": "Demand letter (내용증명)",
  "갑호증": "Exhibit bundle (갑호증)",
  "증거 목록": "Evidence list (증거목록)",
};

const BACKEND_EN_PARTS = [
  [/^증거 (\d+)개$/, "$1 files"],
  [/^SHA-256 기록$/, "SHA-256 recorded"],
  [/^(\d+)개 판독$/, "$1 read"],
  [/^(\d+)개 건너뜀\(영상\)$/, "$1 skipped (video)"],
  [/^(\d+)개 보류$/, "$1 on hold"],
  [/^(\d+)개 검출$/, "$1 found"],
  [/^(\d+)개 미검출$/, "$1 not found"],
  [/^(\d+)개 오류$/, "$1 errors"],
  [/^필드 (\d+)개$/, "$1 fields"],
  [/^충돌 (\d+)$/, "conflicts: $1"],
  [/^질문 (\d+)$/, "questions: $1"],
  [/^가림 (\d+)개$/, (_, n) => (n === "1" ? "1 mask" : `${n} masks`)],
  [/^누출 검사 통과$/, "leak check passed"],
  [/^누출 검사 실패$/, "leak check failed"],
  [/^누출 검사 확인 필요$/, "leak check needs review"],
  [/^확인 필요 증거 (\d+)개$/, (_, n) => exhibitsNeedCheck(n)],
  [/^가린 사본 없는 증거 (\d+)개$/, (_, n) => exhibitsWithoutCopy(n)],
  [/^남은 원금 ([\d,]+)원$/, "principal left ₩$1"],
  [/^(\d+)개 문장$/, "$1 sentences"],
  [/^(\d+)회 수정 후 통과$/, "passed after $1 revisions"],
  [/^G1a·G3·명칭·DRAFT 통과$/, "G1a·G3·NAMING·DRAFT passed"],
  [/^내용증명 PDF$/, "demand letter PDF"],
  [/^전자소송 문구$/, "e-Court text"],
  [/^갑 제(\d+)호증$/, "Exhibit $1"],
];

function exhibitsNeedCheck(n) {
  return n === "1" ? "1 exhibit needs your check" : `${n} exhibits need your check`;
}

function exhibitsWithoutCopy(n) {
  return n === "1" ? "1 exhibit without a redacted copy" : `${n} exhibits without a redacted copy`;
}

// The privacy note when copies are flagged or missing (contract 6d) reads
// "7 masks · 2 exhibits need your check" in English.
const PRIVACY_REVIEW_NOTE_RE = /^가림 \d+개(, (확인 필요 증거|가린 사본 없는 증거) \d+개)+$/;

function tx(text) {
  if (LANG !== "en" || typeof text !== "string" || !text) return text;
  if (Object.prototype.hasOwnProperty.call(BACKEND_EN, text)) return BACKEND_EN[text];
  if (PRIVACY_REVIEW_NOTE_RE.test(text)) {
    return text.split(", ").map((p) => tx(p)).join(" · ");
  }
  const parts = text.split(", ");
  const out = parts.map((p) => {
    for (const [re, en] of BACKEND_EN_PARTS) {
      if (re.test(p)) return p.replace(re, en);
    }
    return null;
  });
  return out.every((p) => p !== null) ? out.join(", ") : text;
}

const LANG_ATTRS = ["aria-label", "alt", "content"];

// Korean is the markup; English lives in data-en (markup) and data-en-<attr>.
function applyStaticLang() {
  document.documentElement.lang = LANG;
  document.querySelectorAll("[data-en]").forEach((el) => {
    if (el.dataset.ko === undefined) el.dataset.ko = el.innerHTML;
    el.innerHTML = LANG === "en" ? el.dataset.en : el.dataset.ko;
  });
  for (const attr of LANG_ATTRS) {
    document.querySelectorAll(`[data-en-${attr}]`).forEach((el) => {
      const koAttr = `data-ko-${attr}`;
      if (!el.hasAttribute(koAttr)) el.setAttribute(koAttr, el.getAttribute(attr) || "");
      el.setAttribute(attr, LANG === "en"
        ? el.getAttribute(`data-en-${attr}`) : el.getAttribute(koAttr));
    });
  }
  document.querySelectorAll("[data-lang]").forEach((btn) => {
    btn.setAttribute("aria-pressed", btn.dataset.lang === LANG ? "true" : "false");
  });
}

function setLang(next) {
  if ((next !== "ko" && next !== "en") || next === LANG) return;
  LANG = next;
  saveLang(next);
  applyStaticLang();
  rerenderForLang();
}

// Which sentence views are open (edit box, slot view) and which notices show,
// so a redraw can bring them back.
function draftUiState() {
  const ui = {};
  document.querySelectorAll('#sentence-list [data-testid^="sentence-"]').forEach((box) => {
    const sid = box.dataset.testid.slice("sentence-".length);
    const edit = box.querySelector(`[data-testid="edit-${sid}"]`);
    const slots = box.querySelector(`[data-testid="slots-${sid}"]`);
    const notice = box.querySelector(`[data-testid="notice-${sid}"]`);
    ui[sid] = {
      editOpen: !!edit && !edit.hidden,
      slotsOpen: !!slots && !slots.hidden,
      notice: notice && !notice.hidden
        ? { kind: notice.dataset.kind || "", text: notice.textContent } : null,
    };
  });
  return ui;
}

// Redraw what is on screen from state, keeping what the user typed or ticked.
function rerenderForLang() {
  if (!S.caseView) return;
  const kept = {};
  document.querySelectorAll(".paper-stack input[data-testid], .paper-stack select[data-testid], .paper-stack textarea[data-testid]")
    .forEach((el) => { kept[el.dataset.testid] = { value: el.value, checked: el.checked }; });
  const draftUi = draftUiState();
  renderCaseMeta();
  renderBoard();
  if (S.review && !$("checkpoint-section").hidden) {
    renderFields();
    renderConflicts();
    renderUtterances();
    renderRoles();
    if (S.selectedEx) selectEvidence(S.selectedEx);
    else renderEvidenceList();
  }
  const draftsRedrawn = !!(S.drafts && !$("calc-section").hidden);
  if (draftsRedrawn) {
    renderCalc();
    renderDrafts(draftUi);
  }
  if (S.pkg && !$("package-section").hidden) renderPackage();
  document.querySelectorAll(".paper-stack input[data-testid], .paper-stack select[data-testid], .paper-stack textarea[data-testid]")
    .forEach((el) => {
      const k = kept[el.dataset.testid];
      if (!k) return;
      if (el.type === "checkbox") el.checked = k.checked;
      else el.value = k.value;
    });
  // A save or run still in flight: the redrawn approve and re-check controls
  // stay locked until it finishes and restoreDraftInputs() unlocks them.
  if (draftsRedrawn && (S.putting || S.running)) setDraftInputsDisabled(true);
}

function $(id) {
  return document.getElementById(id);
}

function setStatus(msg, kind) {
  const el = $("status-line");
  el.textContent = msg || "";
  el.classList.toggle("is-neutral", kind === "neutral");
}

function errText(data) {
  if (data && data.detail) {
    if (typeof data.detail === "string") return data.detail;
    let msg = data.detail.message || "";
    const miss = data.detail.missing_requirements;
    if (Array.isArray(miss) && miss.length > 0) {
      msg += L(` (필요: ${miss.join(", ")})`, ` (needed: ${miss.join(", ")})`);
    }
    return msg;
  }
  return "";
}

async function api(method, path, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
  }
  return { ok: res.ok, status: res.status, data };
}

function fmtLatency(ms) {
  return (ms / 1000).toFixed(1) + L("초", "s");
}

// Korean: "2026. 6. 1."; English: ISO "2026-06-01".
function fmtDateDots(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!m) return iso || "";
  if (LANG === "en") return m[0];
  return `${m[1]}. ${Number(m[2])}. ${Number(m[3])}.`;
}

function exLabel(exId) {
  const m = /^EX(\d+)$/.exec(exId || "");
  return m ? L(`갑 제${m[1]}호증`, `Exhibit ${m[1]}`) : exId;
}

function sentenceNo(sid) {
  const m = /^s(\d+)$/.exec(sid || "");
  return L("문장 ", "Sentence ") + (m ? Number(m[1]) : sid);
}

function gateName(g) {
  return (LANG === "en" ? GATE_EN : GATE_KO)[g] || g;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- boot ---------- */

document.addEventListener("DOMContentLoaded", () => {
  $("btn-sample").addEventListener("click", loadSample);
  $("btn-run").addEventListener("click", runCase);
  $("btn-delete").addEventListener("click", deleteCase);
  $("btn-confirm").addEventListener("click", confirmFacts);
  $("btn-approve-continue").addEventListener("click", approveAndContinue);
  $("upload-input").addEventListener("change", uploadFiles);
  document.querySelectorAll(".copy-btn").forEach((btn) => {
    btn.addEventListener("click", () => copyBlock(btn.dataset.copy, btn));
  });
  document.querySelectorAll("[data-lang]").forEach((btn) => {
    btn.addEventListener("click", () => setLang(btn.dataset.lang));
  });
  applyStaticLang();
  initChrome();
  checkServer();
});

/* ---------- portal chrome: step dividers and guide ---------- */

const PAPERS = ["board-section", "checkpoint-section", "calc-section",
  "drafts-section", "package-section"];

function reduceMotion() {
  return !!(window.matchMedia
    && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
}

// A divider opens once its paper is shown; the last shown paper is the current step.
function syncDividers() {
  let current = null;
  for (const id of PAPERS) {
    const btn = document.querySelector(`[data-goto="${id}"]`);
    const open = !$(id).hidden;
    if (btn) btn.disabled = !open;
    if (open) current = id;
  }
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    const on = btn.dataset.goto === current;
    btn.parentElement.classList.toggle("file-selected", on);
    if (on) btn.setAttribute("aria-current", "step");
    else btn.removeAttribute("aria-current");
  });
}

function initChrome() {
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const paper = $(btn.dataset.goto);
      if (paper && !paper.hidden) {
        paper.scrollIntoView({ block: "start", behavior: reduceMotion() ? "auto" : "smooth" });
      }
    });
  });
  const watch = new MutationObserver(syncDividers);
  for (const id of PAPERS) watch.observe($(id), { attributes: true, attributeFilter: ["hidden"] });
  syncDividers();
  const guide = $("guide-dialog");
  document.querySelectorAll("[data-open-guide]").forEach((btn) => {
    btn.addEventListener("click", () => guide.showModal());
  });
  $("guide-close").addEventListener("click", () => guide.close());
  // Clicks on the dialog's own padding also target it; close only on the
  // backdrop, which lies outside the dialog box.
  guide.addEventListener("click", (ev) => {
    if (ev.target !== guide) return;
    const r = guide.getBoundingClientRect();
    const outside = ev.clientX < r.left || ev.clientX > r.right
      || ev.clientY < r.top || ev.clientY > r.bottom;
    if (outside) guide.close();
  });
}

async function checkServer() {
  try {
    const res = await fetch("/health", { cache: "no-store" });
    if (!res.ok) throw new Error("bad");
    S.serverOk = true;
    $("offline-notice").hidden = true;
    $("app").hidden = false;
  } catch {
    S.serverOk = false;
    $("offline-notice").hidden = false;
    $("app").hidden = true;
  }
}

function revealSection(sectionId, titleId) {
  $(sectionId).hidden = false;
  const t = titleId ? $(titleId) : null;
  if (t) {
    t.focus({ preventScroll: true });
    // Scroll the whole paper so its running head stays in view.
    $(sectionId).scrollIntoView({ block: "start", behavior: reduceMotion() ? "auto" : "smooth" });
  }
}

/* ---------- case lifecycle ---------- */

function setRunningUI(on) {
  for (const id of ["btn-sample", "btn-run", "btn-confirm", "btn-approve-continue", "btn-delete"]) {
    const el = $(id);
    if (!el) continue;
    if (id === "btn-run" || id === "btn-delete") {
      el.disabled = on || !S.caseId;
    } else {
      el.disabled = on;
    }
  }
  // Unlock sentence controls that a language switch redrew during the run.
  if (!on && S.drafts && !S.putting) restoreDraftInputs();
  refreshRedactionUi();
}

async function loadSample() {
  if (S.running || S.putting) return;
  setStatus("");
  const res = await api("POST", "/api/cases/sample", { set: "kr" });
  if (!res.ok) {
    setStatus(L("사건을 불러오지 못했습니다. ", "Could not load the case. ") + errText(res.data));
    return;
  }
  resetCaseState(res.data);
  renderCaseMeta();
  renderBoard();
  $("btn-delete").disabled = false;
  const ran = await runWithPolling();
  if (ran && S.caseView && S.caseView.state === "CHECKPOINT_1") {
    await loadCheckpoint1();
  }
}

function resetCaseState(view) {
  S.caseId = view.case_id;
  S.caseView = view;
  S.readings = [];
  S.review = null;
  S.drafts = null;
  S.pkg = null;
  S.selectedEx = null;
  S.redactions = null;
  S.segments = null;
  S.redactionChoice = {};
}

async function runCase() {
  if (!S.caseId || S.running || S.putting) return;
  setStatus("");
  const ran = await runWithPolling();
  if (!ran || !S.caseView) return;
  await openStagesForState();
}

async function openStagesForState() {
  const st = S.caseView && S.caseView.state;
  if (!st) return;
  const at = (s) => STATE_ORDER.indexOf(st) >= STATE_ORDER.indexOf(s);
  if (at("CHECKPOINT_1")) await loadCheckpoint1({ reveal: st === "CHECKPOINT_1" });
  if (at("DRAFT_APPROVAL")) await loadDrafts({ reveal: st === "DRAFT_APPROVAL" });
  if (st === "CHECKPOINT_2") await loadPackage({ reveal: true });
}

async function runWithPolling() {
  if (S.running) return false;
  S.running = true;
  const gen = ++S.runGen;
  setRunningUI(true);
  $("run-progress").hidden = false;
  const poll = async () => {
    if (gen !== S.runGen || !S.running) return;
    try {
      const res = await api("GET", `/api/cases/${S.caseId}`);
      if (gen !== S.runGen || !S.running) return;
      if (res.ok) {
        S.caseView = res.data;
        renderCaseMeta();
        renderBoard();
      }
    } catch {
      /* a failed poll must not stop the run; the final fetch decides */
    }
    if (gen === S.runGen && S.running) setTimeout(poll, 500);
  };
  setTimeout(poll, 500);
  try {
    const res = await api("POST", `/api/cases/${S.caseId}/run`, {});
    if (gen !== S.runGen) return false;
    if (!res.ok) {
      setStatus(L("실행하지 못했습니다. ", "Could not run. ") + errText(res.data));
    } else {
      S.caseView = res.data;
    }
  } finally {
    if (gen === S.runGen) {
      S.running = false;
      setRunningUI(false);
      $("run-progress").hidden = true;
    }
  }
  if (gen !== S.runGen) return false;
  const cur = await api("GET", `/api/cases/${S.caseId}`);
  if (gen !== S.runGen) return false;
  if (cur.ok) S.caseView = cur.data;
  renderCaseMeta();
  renderBoard();
  return true;
}

async function deleteCase() {
  if (!S.caseId || S.running) return;
  const res = await api("DELETE", `/api/cases/${S.caseId}`);
  if (!res.ok && res.status !== 404) {
    setStatus(L("삭제하지 못했습니다. ", "Could not delete. ") + errText(res.data));
    return;
  }
  S.caseId = null;
  S.caseView = null;
  S.readings = [];
  S.review = null;
  S.drafts = null;
  S.pkg = null;
  S.selectedEx = null;
  S.redactions = null;
  S.segments = null;
  S.redactionChoice = {};
  $("btn-delete").disabled = true;
  $("btn-run").disabled = true;
  for (const id of ["board-section", "checkpoint-section", "calc-section",
    "drafts-section", "package-section"]) {
    $(id).hidden = true;
  }
  document.querySelector(".case-meta").hidden = true;
  $("stub-banner").hidden = true;
  $("replay-badge").hidden = true;
  setStatus(L("사건을 삭제했습니다.", "Case deleted."), "neutral");
}

async function uploadFiles(ev) {
  const files = ev.target.files;
  if (!files || files.length === 0) return;
  if (!S.caseId) {
    const created = await api("POST", "/api/cases", { jurisdiction: "KR" });
    if (!created.ok) {
      setStatus(L("사건을 만들지 못했습니다. ", "Could not create the case. ") + errText(created.data));
      return;
    }
    resetCaseState(created.data);
    $("btn-delete").disabled = false;
  }
  const form = new FormData();
  for (const f of files) form.append("files", f);
  try {
    const res = await fetch(`/api/cases/${S.caseId}/evidence`, {
      method: "POST",
      body: form,
    });
    const data = await res.json();
    if (!res.ok) {
      setStatus(L("올리지 못했습니다. ", "Could not upload. ") + errText(data));
      return;
    }
    S.caseView = data;
    renderCaseMeta();
    renderBoard();
    setStatus("");
  } catch {
    setStatus(L("올리지 못했습니다.", "Could not upload."));
  }
  ev.target.value = "";
}

/* ---------- board ---------- */

function renderCaseMeta() {
  const v = S.caseView;
  if (!v) return;
  document.querySelector(".case-meta").hidden = false;
  $("case-id").textContent = v.case_id;
  const st = $("case-state");
  st.textContent = stateName(v.state);
  st.setAttribute("data-state", v.state);
  $("stub-banner").hidden = !v.stub;
  $("replay-badge").hidden = v.meta_mode !== "replay";
  $("board-section").hidden = false;
  $("btn-run").disabled = S.running || !S.caseId;
  $("btn-delete").disabled = S.running || !S.caseId;
}

function stepOrder(v, s) {
  return v.steps.indexOf(s) + 1;
}

function modelBadgeText(s) {
  const base = s.model || L("규칙", "rules");
  if (s.key === "reading" && s.substeps && s.substeps.length > 0) {
    const n = s.substeps.filter((x) => x.status === "done").length;
    return L(`${base} · 판독 ${n}건`, `${base} · ${n} read`);
  }
  return base;
}

function countModelCalls(v) {
  let calls = 0;
  for (const s of (v.steps || [])) {
    if (!s.model) continue;
    if ((s.key === "reading" || s.key === "vision")
      && Array.isArray(s.substeps) && s.substeps.length > 0) {
      // Real calls per evidence (reading tiles, SAM nouns + retry) when the
      // backend reports them; otherwise one per finished evidence.
      for (const x of s.substeps) {
        if (!x) continue;
        const n = Number(x.calls || 0);
        if (n > 0) calls += n;
        else if (x.status === "done") calls += 1;
      }
    } else {
      calls += Number(s.attempts || 0);
    }
  }
  return calls;
}

function renderBoardSummary(v) {
  const el = $("board-summary");
  const calls = countModelCalls(v);
  const cost = v.run_cost_usd || "0";
  const mode = v.meta_mode === "replay" ? L("(재생)", "(replay)") : L("실제 호출", "live calls");
  el.textContent = L(`Meta 모델 호출 ${calls}회 · $${cost} · ${mode}`,
    `Meta model calls: ${calls} · $${cost} · ${mode}`);
  el.dataset.calls = String(calls);
}

function renderBoard() {
  const v = S.caseView;
  if (!v) return;
  renderHold(v);
  renderBoardSummary(v);
  const board = $("agent-board");
  board.innerHTML = "";
  for (const a of AGENTS) {
    const steps = v.steps.filter((s) => s.group === a.group);
    if (steps.length === 0) continue;
    const card = document.createElement("div");
    card.className = "agent-card";
    card.dataset.testid = `agent-card-${a.group}`;
    const h = document.createElement("h3");
    h.textContent = a.group;
    card.appendChild(h);
    const d = document.createElement("p");
    d.className = "agent-desc";
    d.textContent = L(a.desc, a.descEn);
    card.appendChild(d);
    for (const s of steps) {
      const row = document.createElement("div");
      row.className = "step-row" + (s.status === "skipped" ? " is-skipped" : "")
        + (s.status === "running" ? " is-running" : "");
      row.dataset.testid = `step-${s.key}`;
      row.dataset.status = s.status;
      const head = document.createElement("div");
      head.className = "step-head";
      const order = document.createElement("span");
      order.className = "step-order";
      order.textContent = String(stepOrder(v, s));
      head.appendChild(order);
      const agent = document.createElement("span");
      agent.className = "step-agent";
      agent.textContent = tx(s.agent);
      head.appendChild(agent);
      const model = document.createElement("span");
      model.className = "model-badge";
      model.textContent = modelBadgeText(s);
      head.appendChild(model);
      const st = document.createElement("span");
      st.className = "step-status";
      st.dataset.status = s.status;
      st.textContent = statusName(s.status);
      head.appendChild(st);
      if (s.status !== "waiting" && s.status !== "skipped") {
        const meta = document.createElement("span");
        meta.className = "step-meta";
        meta.textContent = v.meta_mode === "replay"
          ? `$${s.cost_usd || "0"}`
          : `${fmtLatency(s.latency_ms || 0)} · $${s.cost_usd || "0"}`;
        head.appendChild(meta);
      }
      row.appendChild(head);
      const noteText = s.status === "skipped"
        ? L("이 버전에서는 사용하지 않음", "Not used in this version")
        : tx(s.note || "");
      if (noteText) {
        const note = document.createElement("div");
        note.className = "step-note";
        note.dataset.testid = `step-note-${s.key}`;
        // Flagged or missing redacted copies stand out on the board.
        if (s.key === "privacy" && /확인 필요|사본 없는/.test(s.note || "")) {
          note.classList.add("is-review");
        }
        note.textContent = noteText;
        row.appendChild(note);
      }
      if (s.substeps && s.substeps.length > 0) {
        const ul = document.createElement("ul");
        ul.className = "substeps";
        for (const sub of s.substeps) {
          const li = document.createElement("li");
          li.textContent = v.meta_mode === "replay"
            ? `${exLabel(sub.ex_id)} · ${statusName(sub.status)}`
            : `${exLabel(sub.ex_id)} · ${statusName(sub.status)} · ${fmtLatency(sub.latency_ms || 0)}`;
          ul.appendChild(li);
        }
        row.appendChild(ul);
      }
      card.appendChild(row);
    }
    board.appendChild(card);
  }
  renderUserStrip(v);
}

function renderUserStrip(v) {
  const strip = $("user-strip");
  strip.innerHTML = "";
  const users = v.steps.filter((s) => s.group === "User");
  if (users.length === 0) {
    strip.hidden = true;
    return;
  }
  strip.hidden = false;
  const label = document.createElement("span");
  label.className = "user-strip-label";
  label.textContent = L("사용자 확인", "Your checks");
  strip.appendChild(label);
  for (const s of users) {
    const chip = document.createElement("span");
    chip.className = "user-chip";
    chip.dataset.testid = `step-${s.key}`;
    chip.dataset.status = s.status;
    const label = s.status === "running" ? L("확인 기다림", "Waiting for you") : statusName(s.status);
    chip.textContent = `${stepOrder(v, s)}. ${tx(s.agent)} · ${label}`;
    strip.appendChild(chip);
  }
}

function renderHold(v) {
  const box = $("hold-box");
  const list = $("hold-list");
  list.innerHTML = "";
  const reasons = v.hold_reasons || [];
  box.hidden = reasons.length === 0;
  reasons.forEach((r, i) => {
    const li = document.createElement("li");
    const label = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.testid = `hold-check-${i}`;
    const msgText = r.code === "replay_fixture_missing"
      ? L("기록된 응답이 없는 입력입니다", "No recorded response for this input")
      : (r.message || r.code || "");
    check.setAttribute("aria-label", L(`보류 사유 확인: ${msgText}`, `Mark hold reason as read: ${msgText}`));
    label.appendChild(check);
    const msg = document.createElement("span");
    msg.textContent = " " + msgText;
    label.appendChild(msg);
    li.appendChild(label);
    list.appendChild(li);
  });
}

/* ---------- checkpoint 1 ---------- */

async function loadCheckpoint1(opts) {
  const [rd, rv, red, seg] = await Promise.all([
    api("GET", `/api/cases/${S.caseId}/readings`),
    api("GET", `/api/cases/${S.caseId}/review`),
    api("GET", `/api/cases/${S.caseId}/redactions`),
    api("GET", `/api/cases/${S.caseId}/segments`),
  ]);
  if (!rd.ok || !rv.ok) {
    setStatus(L("사실 확인 자료를 불러오지 못했습니다.", "Could not load the fact check."));
    return;
  }
  S.readings = rd.data;
  S.review = rv.data;
  S.redactions = red.ok ? red.data : null;
  S.segments = seg.ok ? seg.data : null;
  // A choice only stands for a copy that is still flagged.
  for (const exId of Object.keys(S.redactionChoice)) {
    if (redactionFlag(exId) !== "review") delete S.redactionChoice[exId];
  }
  renderCheckpoint();
  revealSection("checkpoint-section", opts && opts.reveal === false ? null : "checkpoint-title");
}

function readingsFor(exId) {
  const r = (S.readings || []).find((x) => x.ex_id === exId);
  return r ? r.items : [];
}

function readingSide(exId, itemId) {
  const items = readingsFor(exId);
  const it = items.find((x) => x.item_id === itemId);
  return it ? it.side : null;
}

function redactionPreview(exId) {
  const previews = S.redactions && S.redactions.previews;
  if (!Array.isArray(previews)) return null;
  return previews.find((x) => x && x.ex_id === exId) || null;
}

function redactionPreviewUrl(exId) {
  const p = redactionPreview(exId);
  return p ? p.url : null;
}

/* ---------- flagged redaction copies ---------- */

// "review": a redacted copy the backend flagged (needs_review); it stays out
// of exhibits.pdf until the user confirms it. "missing": no copy at all.
function redactionFlag(exId) {
  const p = redactionPreview(exId);
  if (!p) return null;
  if (p.status === "not_redacted") return "missing";
  if (p.needs_review === true && p.url) return "review";
  return null;
}

// review | confirmed | excluded | missing | null
function redactionState(exId) {
  const flag = redactionFlag(exId);
  if (flag !== "review") return flag;
  return S.redactionChoice[exId] || "review";
}

// The choice goes out with the confirmed facts, so it locks once they are
// sent. It stays locked in a later HOLD too: a fix through PUT /drafts would
// never carry a changed choice, and the notice must not claim otherwise.
function redactionLocked() {
  if (S.running || S.putting || !S.caseView) return true;
  return S.caseView.state !== "CHECKPOINT_1";
}

// Flagged copies the user has not decided on yet (they stay out).
function undecidedRedactionExIds() {
  const ids = [];
  for (const e of ((S.caseView && S.caseView.evidence) || [])) {
    if (redactionState(e.ex_id) === "review") ids.push(e.ex_id);
  }
  return ids;
}

// Plan masks flagged for review on this exhibit (outlined on the copy).
function flaggedMaskBoxes(exId) {
  const plan = S.redactions && S.redactions.plan;
  if (!Array.isArray(plan)) return [];
  return plan.filter((x) => x && x.ex_id === exId && x.needs_review === true
    && x.mask_box && x.mask_box.ref_w && x.mask_box.ref_h).map((x) => x.mask_box);
}

function confirmedRedactionExIds() {
  const ids = Object.keys(S.redactionChoice).filter((exId) =>
    S.redactionChoice[exId] === "confirmed" && redactionFlag(exId) === "review");
  ids.sort((a, b) => exNum(a) - exNum(b));
  return ids;
}

const REDACTION_KIND_PREFIX = {
  "계좌번호 끝 4자리 유지": ["계좌번호", "Account number"],
  "주민번호 뒷 7자리 가림": ["주민번호", "ID number"],
  "전화번호 가운데 4자리 가림": ["전화번호", "Phone number"],
};

// Fixed reason texts from services/redaction.py and agents/privacy_guard.py.
const REDACTION_REASON_EN = {
  "가림 상자 밖에 글자가 남아 있을 수 있음": "Characters may remain outside the mask",
  "판독 상자 밖에 글자가 남아 있을 수 있음": "Characters may remain outside the box that was read",
  "가림 상자가 판독 위치에서 한 줄 이상 옮겨져 확인 필요": "The mask moved a full line or more from where the number was read",
  "가린 줄이 판독한 번호와 맞는지 확인할 수 없어 확인 필요": "Could not confirm that the masked line holds the number that was read",
  "다른 번호와 같은 줄을 가려 확인 필요": "Two different numbers were masked on the same line",
  "글자 위치를 확인할 수 없어 확인 필요": "Could not find where the characters are on the image",
  "판독한 번호와 같은 모양의 줄이 가려지지 않았을 수 있음": "A line shaped like the number that was read may still be visible",
  "판독한 번호가 가려졌는지 확인할 수 없음": "Could not check that the number that was read is hidden",
  "문장 안 숫자: 줄 단위로 넓게 가림, 확인 필요": "Number inside a sentence: the whole line is masked",
  "남긴 영역이 원본과 다릅니다.": "The part left visible differs from the original.",
  "원본 가림 영역이 비어 있어 박스 확인이 필요합니다.": "The masked area is blank in the original, so the box may be off.",
  "미리보기가 없어 가린 사본을 만들 수 없음": "There is no preview, so no redacted copy could be made",
  "판독이 보류되어 가림 대상을 알 수 없음": "Reading is on hold, so it is unknown what to mask",
};

const REDACTION_REASON_EN_PARTS = [
  [/^시각 감식에 실패해 얼굴 가림을 확인할 수 없음(.*)$/, "The visual check failed, so faces could not be checked$1"],
  [/^가림 계획이 없어\((.*)\)$/, "No redaction plan for $1"],
];

function reasonText(ko) {
  if (LANG !== "en") return ko;
  if (Object.prototype.hasOwnProperty.call(REDACTION_REASON_EN, ko)) return REDACTION_REASON_EN[ko];
  for (const [re, en] of REDACTION_REASON_EN_PARTS) {
    if (re.test(ko)) return ko.replace(re, en);
  }
  return ko;
}

// The preview reason joins entries with " / " and an entry's parts with
// "; " (first part names the kind). One bullet per reason, kind first.
function redactionReasonLines(reason) {
  const lines = [];
  for (const group of String(reason || "").split(" / ")) {
    const parts = group.split("; ").map((t) => t.trim()).filter(Boolean);
    if (parts.length === 0) continue;
    let label = null;
    const kind = REDACTION_KIND_PREFIX[parts[0]];
    if (kind) {
      label = L(kind[0], kind[1]);
      parts.shift();
    }
    for (const part of parts) {
      const text = reasonText(part);
      const line = label ? `${label}: ${text}` : text;
      if (!lines.includes(line)) lines.push(line);
    }
  }
  return lines;
}

function redactionListText(state) {
  return {
    review: L("가림 확인 필요", "Redaction to check"),
    confirmed: L("묶음에 넣음", "Included"),
    excluded: L("묶음에서 뺌", "Left out"),
    missing: L("가린 사본 없음", "No redacted copy"),
  }[state] || "";
}

function redactionNoticeBody(state, locked) {
  if (state === "review") {
    return locked
      ? L("묶음에 넣기를 고르지 않아 이 증거의 이미지는 갑호증 묶음(exhibits.pdf)에 들어가지 않습니다.",
        "You did not include it, so this exhibit's image stays out of the exhibit bundle (exhibits.pdf).")
      : L("고르기 전까지 이 증거의 이미지는 갑호증 묶음(exhibits.pdf)에 들어가지 않습니다. 아래 가린 사본에서 계좌·주민번호·전화번호가 모두 가려졌는지 보고 고르세요.",
        "Until you choose, this exhibit's image stays out of the exhibit bundle (exhibits.pdf). Look at the redacted copy below. If every number is fully covered, include it; if not, leave it out.");
  }
  if (state === "confirmed") {
    return locked
      ? L("가린 사본을 확인했습니다. 이 가린 사본이 갑호증 묶음에 들어갑니다.",
        "You checked the redacted copy. It goes into the exhibit bundle.")
      : L("가린 사본을 확인했습니다. '확인하고 계속'을 누르면 이 가린 사본이 갑호증 묶음에 들어갑니다.",
        "You checked the redacted copy. When you press Confirm and continue, it goes into the exhibit bundle.");
  }
  if (state === "excluded") {
    return L("이 증거의 이미지는 갑호증 묶음에 넣지 않습니다. 그 쪽에는 안내 한 줄만 들어갑니다.",
      "This exhibit's image stays out of the exhibit bundle. Its page holds a one-line note instead.");
  }
  return L("가린 사본을 만들지 못해 이 증거의 이미지는 갑호증 묶음(exhibits.pdf)에 들어가지 않습니다.",
    "No redacted copy could be made, so this exhibit's image stays out of the exhibit bundle (exhibits.pdf).");
}

// Whether this state ends with the image out of the bundle.
function redactionLeftOut(state, locked) {
  return state === "excluded" || state === "missing" || (state === "review" && locked);
}

function redactionNextStep() {
  return L("서류에는 이 증거가 계속 인용됩니다. 직접 가린 사본을 만들어 제출 전에 더하세요.",
    "The documents still cite this exhibit. Mask it yourself and add it before filing.");
}

function renderRedactionNotice(exId) {
  const box = $("redaction-notice");
  if (!box) return;
  box.innerHTML = "";
  const state = redactionState(exId);
  if (!state) {
    box.hidden = true;
    delete box.dataset.state;
    return;
  }
  const p = redactionPreview(exId);
  const locked = redactionLocked();
  box.hidden = false;
  box.dataset.state = state;
  const title = document.createElement("p");
  title.className = "redaction-notice-title";
  title.dataset.testid = "redaction-notice-title";
  title.textContent = {
    review: L("가림 확인 필요", "Check this redaction"),
    confirmed: L("묶음에 넣음", "Included in the bundle"),
    excluded: L("묶음에서 뺌", "Left out of the bundle"),
    missing: L("가린 사본 없음", "No redacted copy"),
  }[state];
  box.appendChild(title);
  const lines = redactionReasonLines(p && p.reason);
  if (lines.length === 0 && state !== "missing") {
    lines.push(L("가림 결과를 사람이 확인해야 합니다.", "A person needs to check this redaction."));
  }
  if (lines.length > 0) {
    const ul = document.createElement("ul");
    ul.className = "redaction-reasons";
    ul.dataset.testid = "redaction-reasons";
    for (const line of lines) {
      const li = document.createElement("li");
      li.textContent = line;
      ul.appendChild(li);
    }
    box.appendChild(ul);
  }
  const body = document.createElement("p");
  body.className = "redaction-notice-body";
  body.dataset.testid = "redaction-notice-body";
  body.textContent = redactionNoticeBody(state, locked);
  box.appendChild(body);
  if (redactionLeftOut(state, locked)) {
    const next = document.createElement("p");
    next.className = "redaction-notice-body redaction-next-step";
    next.dataset.testid = "redaction-next-step";
    next.textContent = redactionNextStep();
    box.appendChild(next);
  }
  if (p && p.url) {
    const extra = document.createElement("p");
    extra.className = "redaction-notice-body";
    if (flaggedMaskBoxes(exId).length > 0) {
      extra.appendChild(document.createTextNode(
        L("빨간 테두리는 확인이 필요한 가림 상자입니다. ", "Red outlines mark the masks to check. ")));
    }
    const open = document.createElement("a");
    open.href = p.url;
    open.target = "_blank";
    open.rel = "noopener";
    open.className = "redaction-open";
    open.dataset.testid = "redaction-open";
    open.textContent = L("가린 사본 크게 보기", "Open the redacted copy full size");
    extra.appendChild(open);
    box.appendChild(extra);
  }
  if (state === "missing") return;
  const actions = document.createElement("div");
  actions.className = "redaction-actions";
  for (const [choice, testid, ko, en] of [
    ["confirmed", "redaction-confirm", "묶음에 넣기", "Include it"],
    ["excluded", "redaction-leave-out", "묶음에서 빼기", "Leave it out"],
  ]) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.testid = testid;
    btn.textContent = L(ko, en);
    btn.setAttribute("aria-pressed", state === choice ? "true" : "false");
    btn.disabled = locked;
    btn.addEventListener("click", () => chooseRedaction(exId, choice, testid));
    actions.appendChild(btn);
  }
  box.appendChild(actions);
}

// One explicit click per exhibit; nothing is confirmed automatically.
function chooseRedaction(exId, choice, testid) {
  if (redactionLocked() || redactionFlag(exId) !== "review") return;
  S.redactionChoice[exId] = choice;
  renderEvidenceList();
  renderRedaction(exId);
  const again = document.querySelector(`#redaction-notice [data-testid="${testid}"]`);
  if (again) again.focus();
}

function refreshRedactionUi() {
  if (!S.review || !S.caseView || $("checkpoint-section").hidden) return;
  renderEvidenceList();
  if (S.selectedEx) renderRedaction(S.selectedEx);
}

// One line above "확인하고 계속" while flagged copies are still undecided.
function renderRedactionPending() {
  const el = $("redaction-pending");
  if (!el) return;
  const ids = redactionLocked() ? [] : undecidedRedactionExIds();
  if (ids.length === 0) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  const names = ids.map(exLabel).join(", ");
  el.hidden = false;
  el.textContent = L(
    `확인 필요 증거 ${ids.length}개(${names})가 아직 남아 있어 묶음에서 빠집니다.`,
    ids.length === 1
      ? `1 exhibit (${names}) still needs a redaction check and will be left out.`
      : `${ids.length} exhibits (${names}) still need a redaction check and will be left out.`);
}

function renderRedactionBoxes(exId) {
  const layer = $("redaction-box-layer");
  if (!layer) return;
  layer.innerHTML = "";
  for (const box of flaggedMaskBoxes(exId)) {
    const div = document.createElement("div");
    div.className = "redaction-flag-box";
    div.dataset.testid = `redaction-flag-box-${exId}`;
    div.style.left = (box.x1 / box.ref_w * 100) + "%";
    div.style.top = (box.y1 / box.ref_h * 100) + "%";
    div.style.width = (Math.max(box.x2 - box.x1, 1) / box.ref_w * 100) + "%";
    div.style.height = (Math.max(box.y2 - box.y1, 1) / box.ref_h * 100) + "%";
    layer.appendChild(div);
  }
}

function segmentsFor(exId) {
  if (!Array.isArray(S.segments)) return [];
  const entry = S.segments.find((x) => x && x.ex_id === exId);
  if (!entry || !Array.isArray(entry.objects)) return [];
  return entry.objects.filter((o) => o && o.box && o.box.ref_w && o.box.ref_h);
}

function renderCheckpoint() {
  renderEvidenceList();
  const first = (S.caseView.evidence.find((e) => e.preview_url) || S.caseView.evidence[0]);
  if (first) selectEvidence(first.ex_id);
  renderFields();
  renderConflicts();
  renderUtterances();
  renderRoles();
}

function renderEvidenceList() {
  const ul = $("evidence-list");
  ul.innerHTML = "";
  for (const e of S.caseView.evidence) {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.dataset.testid = `evidence-${e.ex_id}`;
    btn.setAttribute("aria-pressed", S.selectedEx === e.ex_id ? "true" : "false");
    const evStatus = (LANG === "en"
      ? { ok: "Read", hold: "On hold", skipped: "Skipped" }
      : { ok: "읽음", hold: "보류", skipped: "건너뜀" })[e.status] || e.status;
    const red = redactionState(e.ex_id);
    if (red) btn.dataset.redaction = red;
    const redText = red ? ` · ${redactionListText(red)}` : "";
    btn.textContent = `${tx(e.label)} · ${(e.sha256 || "").slice(0, 8)} · ${evStatus}${redText}`;
    btn.addEventListener("click", () => selectEvidence(e.ex_id));
    li.appendChild(btn);
    ul.appendChild(li);
  }
  renderRedactionPending();
}

function selectEvidence(exId) {
  S.selectedEx = exId;
  renderEvidenceList();
  const e = S.caseView.evidence.find((x) => x.ex_id === exId);
  const img = $("viewer-img");
  const layer = $("box-layer");
  const empty = $("viewer-empty");
  layer.innerHTML = "";
  $("viewer-title").textContent = e ? tx(e.label) : L("증거 보기", "View evidence");
  $("viewer-meta").textContent = e ? `${(e.sha256 || "").slice(0, 8)} · ${e.filename}` : "";
  const items = readingsFor(exId);
  if (!e || !e.preview_url) {
    img.hidden = true;
    img.removeAttribute("src");
    empty.hidden = false;
    empty.textContent = L("미리보기가 없습니다.", "No preview.");
    $("reading-note").textContent = "";
    const legend = $("segment-legend");
    if (legend) legend.hidden = true;
    renderRedaction(exId);
    return;
  }
  empty.hidden = true;
  img.hidden = false;
  img.src = e.preview_url;
  if (items.length === 0) {
    $("reading-note").textContent = L("판독 결과 없음", "No readings");
    renderSegments(exId, layer);
    renderRedaction(exId);
    return;
  }
  $("reading-note").textContent = L(`판독 ${items.length}개`, `${items.length} readings`);
  for (const item of items) {
    const box = item.box;
    if (!box || !box.ref_w || !box.ref_h) continue;
    const div = document.createElement("div");
    div.className = "reading-box";
    div.dataset.testid = `reading-box-${exId}-${item.item_id}`;
    div.style.left = (box.x1 / box.ref_w * 100) + "%";
    div.style.top = (box.y1 / box.ref_h * 100) + "%";
    div.style.width = (Math.max(box.x2 - box.x1, 1) / box.ref_w * 100) + "%";
    div.style.height = (Math.max(box.y2 - box.y1, 1) / box.ref_h * 100) + "%";
    div.title = item.text_verbatim || "";
    layer.appendChild(div);
  }
  renderSegments(exId, layer);
  renderRedaction(exId);
}

function renderSegments(exId, layer) {
  const legend = $("segment-legend");
  const objs = segmentsFor(exId);
  if (legend) legend.hidden = objs.length === 0;
  for (const o of objs) {
    const box = o.box;
    const div = document.createElement("div");
    div.className = "segment-box";
    div.dataset.testid = `segment-box-${exId}`;
    div.style.left = (box.x1 / box.ref_w * 100) + "%";
    div.style.top = (box.y1 / box.ref_h * 100) + "%";
    div.style.width = (Math.max(box.x2 - box.x1, 1) / box.ref_w * 100) + "%";
    div.style.height = (Math.max(box.y2 - box.y1, 1) / box.ref_h * 100) + "%";
    div.title = o.target || "";
    layer.appendChild(div);
  }
}

function renderRedaction(exId) {
  const col = $("redaction-col");
  const img = $("redaction-img");
  if (!col || !img) return;
  const url = redactionPreviewUrl(exId);
  const missing = redactionFlag(exId) === "missing";
  renderRedactionNotice(exId);
  renderRedactionBoxes(url ? exId : null);
  if (!url && !missing) {
    col.hidden = true;
    img.removeAttribute("src");
    return;
  }
  col.hidden = false;
  const viewer = $("redaction-viewer");
  if (url) {
    img.src = url;
    if (viewer) viewer.hidden = false;
  } else {
    // No copy: the notice says why, and there is no picture to show.
    img.removeAttribute("src");
    if (viewer) viewer.hidden = true;
  }
}

function blinkBox(exId, itemId) {
  selectEvidence(exId);
  requestAnimationFrame(() => {
    const el = document.querySelector(`[data-testid="reading-box-${exId}-${itemId}"]`);
    if (el) {
      el.scrollIntoView({ block: "nearest", inline: "nearest" });
      el.classList.remove("flash");
      void el.offsetWidth;
      el.classList.add("flash");
    }
  });
}

function displayHint(f) {
  if (!f.display) return null;
  if (typeof f.value === "string" && f.display === f.value) return null;
  const hint = document.createElement("span");
  hint.className = "display-hint";
  hint.dataset.testid = `display-field-${f.field}`;
  hint.textContent = tx(f.display);
  return hint;
}

function renderFields() {
  const body = $("fields-body");
  body.innerHTML = "";
  for (const f of S.review.fields) {
    const tr = document.createElement("tr");
    const th = document.createElement("td");
    th.textContent = tx(f.label) + (f.conflict ? L(" (충돌)", " (conflict)") : "");
    tr.appendChild(th);
    const tdVal = document.createElement("td");
    if (f.field === "repayments" && Array.isArray(f.value)) {
      const rows = f.value.length > 0 ? f.value : [{ date: "", amount: "" }];
      rows.forEach((r, i) => {
        const wrap = document.createElement("div");
        const d = document.createElement("input");
        d.type = "date";
        d.value = r.date || "";
        d.dataset.testid = `field-repayments-${i}-date`;
        d.setAttribute("aria-label", L(`받은 돈 ${i + 1} 날짜`, `Repayment ${i + 1} date`));
        const a = document.createElement("input");
        a.type = "text";
        a.value = r.amount || "";
        a.dataset.testid = `field-repayments-${i}-amount`;
        a.setAttribute("aria-label", L(`받은 돈 ${i + 1} 금액`, `Repayment ${i + 1} amount`));
        wrap.appendChild(d);
        wrap.appendChild(a);
        const aErr = document.createElement("span");
        aErr.className = "field-error";
        aErr.dataset.testid = `error-field-repayments-${i}-amount`;
        aErr.hidden = true;
        wrap.appendChild(aErr);
        tdVal.appendChild(wrap);
      });
      const hint = displayHint(f);
      if (hint) tdVal.appendChild(hint);
    } else if (f.field === "transaction_kind") {
      const sel = document.createElement("select");
      sel.dataset.testid = "field-transaction_kind";
      sel.setAttribute("aria-label", tx(f.label));
      for (const [val, label] of [["civil", L("개인 간 거래", "Personal (not business)")],
        ["commercial", L("사업 거래", "Business")]]) {
        const opt = document.createElement("option");
        opt.value = val;
        opt.textContent = label;
        if (f.value === val) opt.selected = true;
        sel.appendChild(opt);
      }
      tdVal.appendChild(sel);
    } else {
      const input = document.createElement("input");
      input.type = "text";
      input.value = f.value ?? "";
      input.dataset.testid = `field-${f.field}`;
      input.setAttribute("aria-label", tx(f.label));
      tdVal.appendChild(input);
      const hint = displayHint(f);
      if (hint) tdVal.appendChild(hint);
      if (AMOUNT_FIELDS.has(f.field)) {
        const err = document.createElement("span");
        err.className = "field-error";
        err.dataset.testid = `error-field-${f.field}`;
        err.hidden = true;
        tdVal.appendChild(err);
      }
    }
    tr.appendChild(tdVal);
    const tdSrc = document.createElement("td");
    for (const src of (f.sources || [])) {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "source-chip";
      chip.dataset.testid = `source-chip-${f.field}-${src.ex_id}-${src.item_id}`;
      chip.textContent = exLabel(src.ex_id);
      chip.addEventListener("click", () => blinkBox(src.ex_id, src.item_id));
      tdSrc.appendChild(chip);
    }
    tr.appendChild(tdSrc);
    body.appendChild(tr);
  }
}

function conflictText(c) {
  if (typeof c === "string") return c || null;
  if (c && typeof c === "object" && !Array.isArray(c)) {
    const labels = {};
    for (const f of ((S.review && S.review.fields) || [])) labels[f.field] = tx(f.label) || f.field;
    let names = "";
    if (Array.isArray(c.fields)) {
      names = c.fields.map((f) => labels[f] || f).join(", ");
    } else if (typeof c.fields === "string") {
      names = c.fields;
    }
    const note = c.note || c.message || "";
    if (names && note) return `${names}: ${note}`;
    return note || names || null;
  }
  return null;
}

function renderConflicts() {
  const ul = $("conflict-list");
  ul.innerHTML = "";
  const items = [];
  for (const c of ((S.review && S.review.conflicts) || [])) {
    const t = conflictText(c);
    if (t) items.push(t);
  }
  for (const q of ((S.review && S.review.questions) || [])) {
    items.push(tx(q.question) || L(`${q.field} 입력 필요`, `${q.field} needed`));
  }
  if (items.length === 0) {
    const li = document.createElement("li");
    li.textContent = L("없음", "None");
    ul.appendChild(li);
    return;
  }
  for (const t of items) {
    const li = document.createElement("li");
    li.textContent = t;
    ul.appendChild(li);
  }
}

function speakerLabel(u) {
  if (u.speaker !== null && u.speaker !== undefined && u.speaker !== "" && u.speaker !== "null") {
    return u.speaker;
  }
  const side = readingSide(u.ex_id, u.item_id);
  if (side === "right") return L("오른쪽 말풍선", "Right bubble");
  if (side === "left") return L("왼쪽 말풍선", "Left bubble");
  return L("말한 사람 모름", "Speaker unknown");
}

function exNum(exId) {
  const m = /^EX(\d+)$/.exec(exId || "");
  return m ? Number(m[1]) : 0;
}

function itemNum(itemId) {
  const m = /(\d+)/.exec(itemId || "");
  return m ? Number(m[1]) : 0;
}

function firstRepayPromiseKey() {
  const promised = (S.review.utterances || []).filter((u) => (u.tags || []).includes("repay_promise"));
  promised.sort((a, b) => (exNum(a.ex_id) - exNum(b.ex_id)) || (itemNum(a.item_id) - itemNum(b.item_id)));
  return promised.length > 0 ? `${promised[0].ex_id}:${promised[0].item_id}` : null;
}

function renderUtterances() {
  const ul = $("utterance-list");
  ul.innerHTML = "";
  const firstPromise = firstRepayPromiseKey();
  for (const u of (S.review.utterances || [])) {
    const li = document.createElement("li");
    li.dataset.testid = `utterance-${u.ex_id}-${u.item_id}`;
    li.dataset.tags = (u.tags || []).join(" ");
    const who = speakerLabel(u);
    const label = document.createElement("label");
    const check = document.createElement("input");
    check.type = "checkbox";
    check.dataset.testid = `highlight-${u.ex_id}-${u.item_id}`;
    check.setAttribute("aria-label", L(`강조: ${who}: ${u.text}`, `Highlight: ${who}: ${u.text}`));
    if (firstPromise === `${u.ex_id}:${u.item_id}`) check.checked = true;
    label.appendChild(check);
    li.appendChild(label);
    const body = document.createElement("span");
    body.lang = "ko";
    body.textContent = `${who}: ${u.text} `;
    li.appendChild(body);
    for (const tag of (u.tags || [])) {
      const chip = document.createElement("span");
      chip.className = "tag";
      chip.textContent = tagName(tag);
      li.appendChild(chip);
    }
    ul.appendChild(li);
  }
}

function renderRoles() {
  const ul = $("role-list");
  ul.innerHTML = "";
  for (const r of (S.review.evidence_roles || [])) {
    const li = document.createElement("li");
    const label = document.createElement("label");
    label.textContent = `${exLabel(r.ex_id)} `;
    const sel = document.createElement("select");
    sel.dataset.testid = `role-${r.ex_id}`;
    sel.setAttribute("aria-label", L(`${exLabel(r.ex_id)} 역할`, `${exLabel(r.ex_id)} role`));
    const current = KNOWN_ROLES.has(r.suggested_role) ? r.suggested_role : "other";
    for (const [val, name, nameEn] of ROLE_OPTIONS) {
      const opt = document.createElement("option");
      opt.value = val;
      opt.textContent = L(name, nameEn);
      if (current === val) opt.selected = true;
      sel.appendChild(opt);
    }
    label.appendChild(sel);
    li.appendChild(label);
    ul.appendChild(li);
  }
}

const DISPLAY_AMOUNT_RE = /^\s*\d[\d,]*\s*원?\s*$/;

function parseAmountInput(raw) {
  const t = String(raw ?? "").trim();
  if (t === "") return "";
  if (!DISPLAY_AMOUNT_RE.test(t)) return t;
  return t.replace(/[\s,원]/g, "");
}

const AMOUNT_FIELDS = new Set(["principal"]);

function gatherFacts() {
  const fields = {};
  for (const f of S.review.fields) {
    if (f.field === "repayments") {
      const rows = [];
      for (let i = 0; ; i++) {
        const d = document.querySelector(`[data-testid="field-repayments-${i}-date"]`);
        const a = document.querySelector(`[data-testid="field-repayments-${i}-amount"]`);
        if (!d || !a) break;
        if (d.value || a.value) rows.push({ date: d.value, amount: parseAmountInput(a.value) });
      }
      fields.repayments = rows;
    } else if (f.field === "transaction_kind") {
      fields[f.field] = document.querySelector('[data-testid="field-transaction_kind"]').value;
    } else {
      const el = document.querySelector(`[data-testid="field-${f.field}"]`);
      let val = el.value.trim();
      if (AMOUNT_FIELDS.has(f.field)) val = parseAmountInput(val);
      fields[f.field] = (val === "" && f.value === null) ? null : val;
    }
  }
  const evidence_roles = {};
  for (const r of (S.review.evidence_roles || [])) {
    evidence_roles[r.ex_id] = document.querySelector(`[data-testid="role-${r.ex_id}"]`).value;
  }
  const highlight = [];
  for (const u of (S.review.utterances || [])) {
    const el = document.querySelector(`[data-testid="highlight-${u.ex_id}-${u.item_id}"]`);
    if (el && el.checked) highlight.push(`${u.ex_id}:${u.item_id}`);
  }
  const body = { fields, evidence_roles, highlight, as_of: $("asof").value };
  // Contract 6d: only the flagged exhibits the user confirmed one by one.
  const confirmedEx = confirmedRedactionExIds();
  if (confirmedEx.length > 0) body.redaction_confirmed = confirmedEx;
  return body;
}

function clearFactsErrors() {
  document.querySelectorAll('[data-testid^="error-field-"]').forEach((el) => {
    el.hidden = true;
    el.textContent = "";
  });
}

function showFactsErrorsFor(msg) {
  if (!msg) return;
  if (msg.includes("principal")) {
    const el = document.querySelector('[data-testid="error-field-principal"]');
    if (el) {
      el.textContent = msg;
      el.hidden = false;
    }
  }
  if (msg.includes("repayments.amount")) {
    document.querySelectorAll('[data-testid^="error-field-repayments-"]').forEach((el) => {
      el.textContent = msg;
      el.hidden = false;
    });
  }
}

async function confirmFacts() {
  if (S.putting || S.running) return;
  setStatus("");
  clearFactsErrors();
  S.putting = true;
  $("btn-confirm").disabled = true;
  refreshRedactionUi();
  try {
    const body = gatherFacts();
    const put = await api("PUT", `/api/cases/${S.caseId}/facts`, body);
    if (!put.ok) {
      const msg = errText(put.data);
      setStatus(L("확정값을 저장하지 못했습니다. ", "Could not save the confirmed facts. ") + msg);
      if (put.status === 400) showFactsErrorsFor(msg);
      return;
    }
    S.caseView = put.data;
    renderCaseMeta();
    renderBoard();
  } finally {
    S.putting = false;
    $("btn-confirm").disabled = false;
    refreshRedactionUi();
  }
  await runWithPolling();
  if (S.caseView && S.caseView.state === "DRAFT_APPROVAL") {
    await loadDrafts();
  }
}

/* ---------- calculation + draft approval ---------- */

async function loadDrafts(opts) {
  const res = await api("GET", `/api/cases/${S.caseId}/drafts`);
  if (!res.ok) {
    setStatus(L("초안을 불러오지 못했습니다. ", "Could not load the drafts. ") + errText(res.data));
    return;
  }
  S.drafts = res.data;
  renderCalc();
  renderDrafts();
  const reveal = !opts || opts.reveal !== false;
  $("calc-section").hidden = false;
  $("drafts-section").hidden = false;
  if (reveal) revealSection("calc-section", "calc-title");
}

function fmtWon(amountStr) {
  const n = Number(String(amountStr).split(".")[0]);
  if (!Number.isFinite(n)) return String(amountStr);
  return L(n.toLocaleString("ko-KR") + "원", "₩" + n.toLocaleString("en-US"));
}

function renderCalc() {
  const calc = S.drafts.calculation;
  const ref = calc.reference_total || {};
  $("calc-title").textContent = L(
    `입력한 사실 기준 계산 (기준일 ${fmtDateDots(ref.as_of)})`,
    `Calculation from your confirmed facts (as of ${fmtDateDots(ref.as_of)})`);
  const body = $("alloc-body");
  body.innerHTML = "";
  for (const a of (calc.allocations || [])) {
    const tr = document.createElement("tr");
    for (const cell of [fmtDateDots(a.payment_date), fmtWon(a.payment_amount),
      fmtWon(a.applied_to_interest), fmtWon(a.applied_to_principal),
      fmtWon(a.remaining_principal_after)]) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }
  $("remaining-principal").textContent = fmtWon(calc.remaining_principal);
  $("accrual-start").textContent = fmtDateDots(calc.accrual_start_date);
  $("reference-total").textContent = ref.amount != null ? fmtWon(ref.amount) : "—";
  $("reference-asof").textContent = fmtDateDots(ref.as_of);
  const ol = $("calc-steps");
  ol.innerHTML = "";
  for (const s of (calc.calculation_steps || [])) {
    const li = document.createElement("li");
    li.textContent = `${tx(s.label)}: ${s.formula}`;
    ol.appendChild(li);
  }
}

function slotChips(text) {
  const frag = document.createDocumentFragment();
  const re = /\{\{([^}]*)\}\}/g;
  let last = 0;
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) frag.appendChild(document.createTextNode(text.slice(last, m.index)));
    const chip = document.createElement("span");
    chip.className = "slot-chip";
    chip.textContent = `{{${m[1]}}}`;
    frag.appendChild(chip);
    last = m.index + m[0].length;
  }
  if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
  return frag;
}

function renderDrafts(ui) {
  const d = S.drafts;
  const rev = $("revision-note");
  if (d.revisions && d.revisions.length > 0) {
    rev.hidden = false;
    rev.textContent = L(`문안 작성 → 검증 → 수정 ${d.revision_rounds}회`,
      `Draft → check → revise: ${d.revision_rounds} round(s)`);
  } else {
    rev.hidden = true;
  }
  renderDraftsGateSummary();
  const list = $("sentence-list");
  list.innerHTML = "";
  for (const s of (d.sentences || [])) {
    list.appendChild(sentenceEl(s, d.gate_results || [], ui && ui[s.sentence_id]));
  }
}

function noticeText(kind) {
  if (kind === "blocked") return L("지적이 있어 승인할 수 없습니다.", "Fix the issues before approving.");
  return null;
}

function slotsToggleText(open) {
  return open ? L("문장 보기", "Show sentence") : L("슬롯 보기", "Show slots");
}

function editToggleText(open) {
  return open ? L("접기", "Close") : L("고치기", "Edit");
}

function showGate(g) {
  return !(g.gate === "G1b" && g.status === "skipped");
}

function gateRow(g) {
  const row = document.createElement("div");
  row.className = "gate-row";
  row.dataset.testid = `gate-${g.gate}`;
  row.dataset.gate = g.gate;
  row.dataset.status = g.status;
  const state = g.status === "pass" ? L("✓ 통과", "✓ passed")
    : g.status === "fail" ? L("지적 있음", "issues found")
    : g.status === "skipped" ? L("건너뜀", "skipped") : g.status;
  row.textContent = `${gateName(g.gate)} (${g.gate}): ${state}`;
  return row;
}

// ui (optional): { editOpen, slotsOpen, notice: { kind, text } } kept from
// before a language redraw.
function sentenceEl(s, gateResults, ui) {
  const st = ui || {};
  const box = document.createElement("div");
  box.className = "sentence";
  box.dataset.testid = `sentence-${s.sentence_id}`;
  box.dataset.sentenceType = s.type || "";

  const head = document.createElement("div");
  head.className = "sentence-head";
  const id = document.createElement("span");
  id.className = "sentence-id";
  id.textContent = sentenceNo(s.sentence_id);
  head.appendChild(id);
  for (const ex of (s.ex_refs || [])) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = ex === "USER" ? L("(사용자 진술)", "(your statement)") : `[${exLabel(ex)}]`;
    head.appendChild(tag);
  }
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.dataset.testid = `slots-toggle-${s.sentence_id}`;
  toggle.textContent = slotsToggleText(!!st.slotsOpen);
  head.appendChild(toggle);
  const editToggle = document.createElement("button");
  editToggle.type = "button";
  editToggle.dataset.testid = `edit-toggle-${s.sentence_id}`;
  editToggle.textContent = editToggleText(!!st.editOpen);
  head.appendChild(editToggle);
  box.appendChild(head);

  const rendered = document.createElement("p");
  rendered.className = "rendered-text";
  rendered.dataset.testid = `rendered-${s.sentence_id}`;
  rendered.lang = "ko";
  rendered.textContent = s.rendered_text;
  rendered.hidden = !!st.slotsOpen;
  box.appendChild(rendered);

  const slots = document.createElement("p");
  slots.className = "slots-view";
  slots.dataset.testid = `slots-${s.sentence_id}`;
  slots.lang = "ko";
  slots.hidden = !st.slotsOpen;
  slots.appendChild(slotChips(s.text_with_slots));
  box.appendChild(slots);
  toggle.addEventListener("click", () => {
    slots.hidden = !slots.hidden;
    rendered.hidden = !slots.hidden;
    toggle.textContent = slotsToggleText(!slots.hidden);
  });

  const findings = document.createElement("div");
  findings.className = "findings";
  findings.dataset.testid = `findings-${s.sentence_id}`;
  box.appendChild(findings);
  renderFindings(findings, s, gateResults);

  const notice = document.createElement("p");
  notice.className = "sentence-notice";
  notice.dataset.testid = `notice-${s.sentence_id}`;
  notice.hidden = true;
  if (st.notice) {
    // Known notices are redrawn in the new language; others keep their text.
    if (st.notice.kind) notice.dataset.kind = st.notice.kind;
    notice.textContent = noticeText(st.notice.kind) || st.notice.text;
    notice.hidden = false;
  }
  box.appendChild(notice);

  const edit = document.createElement("textarea");
  edit.dataset.testid = `edit-${s.sentence_id}`;
  edit.lang = "ko";
  edit.hidden = !st.editOpen;
  edit.value = s.text_with_slots;
  edit.setAttribute("aria-label", L(`${sentenceNo(s.sentence_id)} 고치기`, `Edit ${sentenceNo(s.sentence_id)}`));
  box.appendChild(edit);
  editToggle.addEventListener("click", () => {
    edit.hidden = !edit.hidden;
    editToggle.textContent = editToggleText(!edit.hidden);
  });

  const row = document.createElement("div");
  row.className = "row";
  const update = document.createElement("button");
  update.type = "button";
  update.dataset.testid = `update-${s.sentence_id}`;
  update.textContent = L("다시 검사", "Re-check");
  row.appendChild(update);
  const approveLabel = document.createElement("label");
  approveLabel.className = "approve-label";
  const approve = document.createElement("input");
  approve.type = "checkbox";
  approve.dataset.testid = `approve-${s.sentence_id}`;
  approve.checked = !!s.approved;
  approve.disabled = (s.findings || []).length > 0;
  approve.setAttribute("aria-label", L(`${sentenceNo(s.sentence_id)} 승인`, `Approve ${sentenceNo(s.sentence_id)}`));
  approveLabel.appendChild(approve);
  approveLabel.appendChild(document.createTextNode(L(" 승인", " Approve")));
  row.appendChild(approveLabel);
  box.appendChild(row);

  update.addEventListener("click", () => updateSentence(s.sentence_id));
  approve.addEventListener("change", () => approveSentence(s.sentence_id));
  return box;
}

function renderFindings(el, s, gateResults) {
  el.innerHTML = "";
  const mine = s.findings || [];
  if (mine.length === 0) {
    el.textContent = L("지적 없음", "No issues");
    el.dataset.status = "pass";
    el.classList.remove("is-bad");
    el.classList.add("is-ok");
    return;
  }
  el.dataset.status = "fail";
  el.classList.remove("is-ok");
  el.classList.add("is-bad");
  const byGate = {};
  for (const g of gateResults) {
    for (const f of (g.findings || [])) {
      if (f.sentence_id === s.sentence_id) {
        if (!byGate[g.gate]) byGate[g.gate] = [];
        byGate[g.gate].push(f);
      }
    }
  }
  const gates = Object.keys(byGate);
  const groups = gates.length > 0 ? gates : ["검사"];
  for (const gate of groups) {
    const line = document.createElement("div");
    line.dataset.gate = gate;
    const name = document.createElement("span");
    name.className = "gate-name";
    name.textContent = gate === "검사" ? L("검사: ", "Check: ") : `${gateName(gate)} (${gate}): `;
    line.appendChild(name);
    const items = byGate[gate] || mine;
    line.appendChild(document.createTextNode(
      items.map((f) => (f.fix_hint ? `${f.message} (${f.fix_hint})` : f.message)).join(" / ")));
    el.appendChild(line);
  }
}

function setDraftInputsDisabled(on) {
  document.querySelectorAll('input[data-testid^="approve-"]').forEach((el) => {
    el.disabled = on;
  });
  document.querySelectorAll('[data-testid^="update-"]').forEach((el) => {
    el.disabled = on;
  });
  $("btn-approve-continue").disabled = on;
}

function restoreDraftInputs() {
  const byId = {};
  for (const s of ((S.drafts && S.drafts.sentences) || [])) byId[s.sentence_id] = s;
  document.querySelectorAll('input[data-testid^="approve-"]').forEach((el) => {
    const sid = el.dataset.testid.slice("approve-".length);
    const s = byId[sid];
    el.checked = !!(s && s.approved);
    el.disabled = s ? (s.findings || []).length > 0 : false;
  });
  document.querySelectorAll('[data-testid^="update-"]').forEach((el) => {
    el.disabled = false;
  });
  $("btn-approve-continue").disabled = false;
}

async function refreshSentence(sid) {
  const res = await api("GET", `/api/cases/${S.caseId}/drafts`);
  if (!res.ok) {
    setStatus(L("초안을 불러오지 못했습니다. ", "Could not load the drafts. ") + errText(res.data));
    return;
  }
  S.drafts = res.data;
  const s = S.drafts.sentences.find((x) => x.sentence_id === sid);
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  if (s && box) {
    renderFindings(
      box.querySelector(`[data-testid="findings-${sid}"]`), s, S.drafts.gate_results || []);
    const rendered = box.querySelector(`[data-testid="rendered-${sid}"]`);
    rendered.textContent = s.rendered_text;
  }
  renderDraftsGateSummary();
  restoreDraftInputs();
}

function renderDraftsGateSummary() {
  const gates = $("gate-summary");
  gates.innerHTML = "";
  for (const g of (S.drafts.gate_results || [])) {
    if (showGate(g)) gates.appendChild(gateRow(g));
  }
}

async function updateSentence(sid) {
  if (S.putting || S.running) return;
  setStatus("");
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  const text = box.querySelector(`[data-testid="edit-${sid}"]`).value;
  S.putting = true;
  setDraftInputsDisabled(true);
  try {
    const res = await api("PUT", `/api/cases/${S.caseId}/drafts`, {
      sentences: [{ sentence_id: sid, text_with_slots: text }],
    });
    if (!res.ok) {
      setStatus(L("다시 검사하지 못했습니다. ", "Could not re-check. ") + errText(res.data));
      return;
    }
    S.drafts = res.data;
    await refreshSentence(sid);
    const s = S.drafts.sentences.find((x) => x.sentence_id === sid);
    // Look the notice up again: a language switch may have redrawn the box.
    const notice = document.querySelector(`[data-testid="notice-${sid}"]`);
    if (notice && s && (s.findings || []).length > 0) {
      notice.dataset.kind = "blocked";
      notice.textContent = noticeText("blocked");
      notice.hidden = false;
    } else if (notice) {
      delete notice.dataset.kind;
      notice.hidden = true;
    }
  } finally {
    S.putting = false;
    restoreDraftInputs();
  }
}

async function approveSentence(sid) {
  if (S.putting || S.running) {
    const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
    if (box) {
      const cur = (S.drafts.sentences || []).find((x) => x.sentence_id === sid);
      box.querySelector(`[data-testid="approve-${sid}"]`).checked = !!(cur && cur.approved);
    }
    return;
  }
  setStatus("");
  const box = document.querySelector(`[data-testid="sentence-${sid}"]`);
  const want = box.querySelector(`[data-testid="approve-${sid}"]`).checked;
  S.putting = true;
  setDraftInputsDisabled(true);
  try {
    const res = await api("PUT", `/api/cases/${S.caseId}/drafts`, {
      sentences: [{ sentence_id: sid, approved: want }],
    });
    if (!res.ok) {
      setStatus(L("승인하지 못했습니다. ", "Could not approve. ") + errText(res.data));
      return;
    }
    S.drafts = res.data;
    await refreshSentence(sid);
  } finally {
    S.putting = false;
    restoreDraftInputs();
  }
}

async function approveAndContinue() {
  if (S.putting || S.running) return;
  setStatus("");
  S.running = true;
  const gen = ++S.runGen;
  setRunningUI(true);
  $("run-progress").hidden = false;
  try {
    const res = await api("POST", `/api/cases/${S.caseId}/run`, {});
    if (gen !== S.runGen) return;
    if (!res.ok) {
      setStatus(L("계속하지 못했습니다. ", "Could not continue. ") + errText(res.data));
      return;
    }
    S.caseView = res.data;
    renderCaseMeta();
    renderBoard();
    if (S.caseView.state === "CHECKPOINT_2") {
      await loadPackage();
    }
  } finally {
    if (gen === S.runGen) {
      S.running = false;
      setRunningUI(false);
      $("run-progress").hidden = true;
    }
  }
}

/* ---------- package ---------- */

async function loadPackage(opts) {
  const res = await api("GET", `/api/cases/${S.caseId}/package`);
  if (!res.ok) {
    setStatus(L("서류 묶음을 불러오지 못했습니다. ", "Could not load the package. ") + errText(res.data));
    return;
  }
  S.pkg = res.data;
  renderPackage();
  revealSection("package-section", opts && opts.reveal === false ? null : "package-title");
}

function renderPackage() {
  const files = $("file-list");
  files.innerHTML = "";
  for (const f of (S.pkg.files || [])) {
    const li = document.createElement("li");
    const a = document.createElement("a");
    a.href = f.url;
    a.textContent = tx(f.label);
    a.dataset.testid = `file-${f.name}`;
    li.appendChild(a);
    files.appendChild(li);
  }
  const parties = (S.pkg.ecourt || {}).parties || "";
  if ($("claim-parties")) {
    $("claim-parties").textContent = parties;
    $("parties-wrap").hidden = !parties;
  }
  $("claim-purpose").textContent = (S.pkg.ecourt || {}).claim_purpose || "";
  $("claim-cause").textContent = (S.pkg.ecourt || {}).claim_cause_payment_order || "";
  $("pkg-notice").textContent = (S.pkg.notices || {}).notice_ko || "";
  $("pkg-disclaimer").textContent = (S.pkg.notices || {}).disclaimer_ko || "";
  const gates = $("pkg-gates");
  const gateList = $("pkg-gate-list");
  if (gates && gateList) {
    const results = (S.pkg.gate_results || []).filter(showGate);
    gateList.innerHTML = "";
    gates.hidden = results.length === 0;
    for (const g of results) {
      gateList.appendChild(gateRow(g));
    }
    renderLeftOut(results);
  }
}

// G1b notes name exhibits whose image stayed out of exhibits.pdf.
const LEFT_OUT_NOTE_RE = /^exhibits\.pdf: 갑 제(\d+)호증\((EX\d+)\)의 (.+)$/;
const LEFT_OUT_WHY_EN = [
  [/^가림 확인이 필요해 이미지를 넣지 않았습니다\.$/, "redaction not confirmed"],
  [/^가림 사본이 원본과 같아 이미지를 넣지 않았습니다\.$/, "the redacted copy equals the original"],
  [/^가림 사본\(.*\)이 없어 이미지를 넣지 않았습니다\.$/, "no redacted copy"],
];

function leftOutNoteText(note) {
  const m = LEFT_OUT_NOTE_RE.exec(note || "");
  if (LANG !== "en" || !m) return note;
  for (const [re, why] of LEFT_OUT_WHY_EN) {
    if (re.test(m[3])) return `exhibits.pdf: Exhibit ${m[1]}, image left out (${why}).`;
  }
  return note;
}

function renderLeftOut(results) {
  const box = $("pkg-left-out");
  if (!box) return;
  box.innerHTML = "";
  const notes = [];
  for (const g of results) {
    for (const n of (g.notes || [])) {
      if (typeof n === "string" && n && !notes.includes(n)) notes.push(n);
    }
  }
  box.hidden = notes.length === 0;
  if (notes.length === 0) return;
  const title = document.createElement("p");
  title.className = "redaction-notice-title";
  title.textContent = L("갑호증 묶음에서 이미지를 뺀 증거", "Left out of the exhibit bundle (image)");
  box.appendChild(title);
  const ul = document.createElement("ul");
  ul.className = "redaction-reasons";
  for (const n of notes) {
    const li = document.createElement("li");
    const m = LEFT_OUT_NOTE_RE.exec(n);
    if (m) li.dataset.testid = `pkg-left-out-${m[2]}`;
    li.textContent = leftOutNoteText(n);
    ul.appendChild(li);
  }
  box.appendChild(ul);
  const next = document.createElement("p");
  next.className = "redaction-notice-body";
  next.textContent = L("서류에는 이 증거가 계속 인용됩니다. 직접 가린 사본을 만들어 제출 전에 더하세요.",
    "The documents still cite these exhibits. Mask them yourself and add them before filing.");
  box.appendChild(next);
}

async function copyBlock(preId, btn) {
  const text = $(preId).textContent;
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
    } catch {
      /* ignore */
    }
    ta.remove();
  }
  const orig = btn.textContent;
  btn.textContent = L("복사 완료", "Copied");
  setTimeout(() => { btn.textContent = orig; }, 1200);
}
