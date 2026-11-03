"""Meta Model API pricing table for ClaimBack-AI.

Official pricing source (checked 2026-11-03):
  https://dev.meta.ai/docs/pricing-rate-limits
  - Muse Spark Standard: cached input $0.15 / input $1.25 / output $4.25 per 1M tokens
  - Muse Image: $0.01 per generated image (flat, prompt length and tools included).
    The pricing page states image responses still include a usage object with
    token counts "for reference, but image generation tokens are not included
    in token-based pricing". M0 fixture 5b8897d6 (input 26,345, output 1,635)
    is therefore billed $0.01 flat; the tokens are recorded for reference only.
  - SAM 3.1: image $2.50 per 1,000 images, video $0.20 per 1,000 frames,
    each video request billed for at least 50 frames.
    Response field ``usage.video_frames_processed`` reports billed frames.
  - Rate limits are per team (Spark 3,000 RPM / 4M TPM, SAM 3,000 RPM, Image 150 RPM).

Models doc (checked 2026-11-03):
  https://dev.meta.ai/docs/models
  - Standard IDs: ``muse-spark-1.1`` (Standard only), ``muse-spark-1.3``,
    ``muse-spark-1.2``, ``sam-3.1``, ``muse-image-1.0``.
  - Contributor variants (``-contributor``) exist for Spark 1.3/1.2 but the app
    must never use them (plan 1-2(10)).

Values marked "미확인" below could not be confirmed on the official pricing
page and use a documented assumption.
"""

import math
import os

# Muse Spark (Standard mode, USD per 1M tokens). Confirmed 2026-11-03.
SPARK_INPUT_PER_1M = 1.25
SPARK_CACHED_INPUT_PER_1M = 0.15
SPARK_OUTPUT_PER_1M = 4.25

# Reasoning tokens: the pricing page lists no separate reasoning rate.
# Assume output rate. 미확인.
REASONING_OUTPUT_PER_1M = SPARK_OUTPUT_PER_1M  # 미확인: 공식 페이지에 별도 단가 없음, 출력 단가로 가정

# SAM 3.1 (USD). Confirmed 2026-11-03.
SAM_IMAGE_PER_1000 = 2.50
SAM_VIDEO_PER_1000_FRAMES = 0.20
SAM_VIDEO_MIN_FRAMES = 50

# Muse Image (USD per image). Confirmed 2026-11-03: flat per image, prompt
# tokens not billed (see module docstring). Usage tokens are reference only.
IMAGE_PER_IMAGE = 0.01

# Budget limits (plan 4-7, AGENTS.md 11/3 decision). The code limit is the
# only hard cap because Meta Spend Limit only sends alerts.
# Read from the environment on every call so tests can override via
# monkeypatch without reloading this module.
RUN_CAP_ENV = "META_RUN_CAP_USD"
TOTAL_CAP_ENV = "META_TOTAL_CAP_USD"
DEFAULT_RUN_CAP_USD = 2.0
DEFAULT_TOTAL_CAP_USD = 100.0

# Backwards-compatible defaults (imported by older code). Prefer the
# run_cap_usd()/total_cap_usd() functions, which honour the environment.
BUDGET_PER_RUN_USD = 2.0
BUDGET_TOTAL_USD = 100.0


def _cap_from_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"invalid {name}: {raw!r} (must be a number, e.g. \"2\" or \"0\")"
        ) from exc
    if not math.isfinite(value):
        raise ValueError(f"invalid {name}: {raw!r} (must be finite)")
    if value < 0:
        raise ValueError(f"invalid {name}: {raw!r} (must be >= 0)")
    # "0" is honoured as zero: every billable live call is then refused.
    return value


def run_cap_usd() -> float:
    """Per-run budget cap (META_RUN_CAP_USD, default $2)."""
    return _cap_from_env(RUN_CAP_ENV, DEFAULT_RUN_CAP_USD)


def total_cap_usd() -> float:
    """Cumulative budget cap (META_TOTAL_CAP_USD, default $100)."""
    return _cap_from_env(TOTAL_CAP_ENV, DEFAULT_TOTAL_CAP_USD)


def spark_cost_usd(
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> float:
    """Actual Spark cost from usage. Reasoning tokens use the output rate.

    M0 fixtures confirm output_tokens includes reasoning: bc43d6ae
    (max_output_tokens=300, output=300, reasoning=298) and 4051cfb1
    (max=2000, output=2000, reasoning=1998) would exceed max_output_tokens
    if reasoning were separate, so subtract to avoid double-counting.
    Cached input is likewise a subset of input.
    """
    fresh_input = max(0, int(input_tokens) - int(cached_input_tokens))
    output = int(output_tokens)
    reasoning = int(reasoning_tokens)
    if 0 < reasoning <= output:
        text_tokens = output - reasoning
    else:
        text_tokens = output
    cost = (
        fresh_input * SPARK_INPUT_PER_1M
        + int(cached_input_tokens) * SPARK_CACHED_INPUT_PER_1M
        + text_tokens * SPARK_OUTPUT_PER_1M
        + reasoning * REASONING_OUTPUT_PER_1M
    ) / 1_000_000
    return round(cost, 6)


def estimate_spark_cost_usd(input_tokens_est: int, max_output_tokens: int) -> float:
    """Pre-call Spark estimate. Assumes no cache (conservative)."""
    return round(
        (int(input_tokens_est) * SPARK_INPUT_PER_1M
         + int(max_output_tokens) * SPARK_OUTPUT_PER_1M) / 1_000_000,
        6,
    )


def sam_image_cost_usd(image_count: int) -> float:
    return round(int(image_count) * SAM_IMAGE_PER_1000 / 1000, 6)


def sam_video_cost_usd(frame_count: int) -> float:
    billed = max(int(frame_count), SAM_VIDEO_MIN_FRAMES)
    return round(billed * SAM_VIDEO_PER_1000_FRAMES / 1000, 6)


def image_cost_usd(image_count: int) -> float:
    """Muse Image cost: flat per image; usage tokens are reference only."""
    return round(int(image_count) * IMAGE_PER_IMAGE, 6)
