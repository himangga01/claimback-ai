"""Meta Model API pricing table for ClaimBack-AI.

Official pricing source (checked 2026-11-03):
  https://dev.meta.ai/docs/pricing-rate-limits
  - Muse Spark Standard: cached input $0.15 / input $1.25 / output $4.25 per 1M tokens
  - Muse Image: $0.01 per generated image (flat, prompt length and tools included)
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

# Muse Image (USD per image). Confirmed 2026-11-03.
IMAGE_PER_IMAGE = 0.01

# Budget limits (plan 4-7). The code limit is the only hard cap because Meta
# Spend Limit only sends alerts.
BUDGET_PER_RUN_USD = 2.0
BUDGET_TOTAL_USD = 20.0


def spark_cost_usd(
    input_tokens: int,
    output_tokens: int,
    cached_input_tokens: int = 0,
    reasoning_tokens: int = 0,
) -> float:
    """Actual Spark cost from usage. Reasoning tokens use the output rate.

    Live P1 (2026-11-03) shows output_tokens includes reasoning
    (output=300, reasoning=298 with max_output_tokens=300), so subtract
    to avoid double-counting. Cached input is likewise a subset of input.
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
    return round(int(image_count) * IMAGE_PER_IMAGE, 6)
