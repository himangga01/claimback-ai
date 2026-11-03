"""Video keyframes (M4b): ffmpeg extraction + perceptual-hash dedupe.

Design 3-10: intake pulls 2 frames per second out of a video with ffmpeg,
drops near-duplicate frames, and hands the remaining keyframes (with
timestamps) to the reader. This module is pure rules + ffmpeg: it never
calls a model and never reads test-only answer files.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

KEYFRAME_FPS = 2.0
DEDUP_HAMMING = 6


def ffmpeg_available() -> bool:
    """True when ffmpeg and ffprobe binaries are on PATH."""
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def probe_video(video_path: Any) -> Tuple[float, Optional[int]]:
    """(frames/second, frame count) of the first video stream (ffprobe).

    Frame count is None when the container does not report nb_frames.
    """
    src = Path(str(video_path))
    cmd = ["ffprobe", "-v", "error", "-select_streams", "v:0",
           "-show_entries", "stream=r_frame_rate,nb_frames", "-of",
           "default=noprint_wrappers=1", str(src)]
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {proc.stderr[-300:]}")
    fields: Dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    text = fields.get("r_frame_rate", "")
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            rate = float(num) / float(den)
        else:
            rate = float(text)
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError(f"프레임 속도를 읽지 못했습니다: {text!r}") from exc
    if rate <= 0:
        raise RuntimeError(f"프레임 속도가 0 이하입니다: {text!r}")
    count: Optional[int] = None
    try:
        count = int(fields.get("nb_frames", ""))
        if count is not None and count <= 0:
            count = None
    except (ValueError, TypeError):
        count = None
    return (rate, count)


def probe_frame_rate(video_path: Any) -> float:
    """Frames/second of the first video stream (ffprobe r_frame_rate)."""
    return probe_video(video_path)[0]


def extract_frames(
    video_path: Any,
    fps: float = KEYFRAME_FPS,
) -> List[Dict[str, Any]]:
    """Extract ``fps`` frames/second from ``video_path`` (M4b brief item 4).

    Frame-exact: the ``select`` filter passes input frames 0, step,
    2*step, ... (step = round(in_fps / fps)) plus the final frame, so
    output frame k is a known input frame with ``frame_ts = n / in_fps``.
    (The ``fps`` filter was tried first and silently shifted every frame
    by +2 on ffmpeg 9, which moved every box by the scroll delta; see
    reports/M4b.md.) The tail frame keeps content that only becomes
    fully visible after the last grid point.
    Raises RuntimeError when ffmpeg/ffprobe is missing or fails.
    """
    if not ffmpeg_available():
        raise RuntimeError("ffmpeg를 찾을 수 없어 영상 프레임을 뽑을 수 없습니다.")
    src = Path(str(video_path))
    if not src.exists():
        raise RuntimeError(f"영상 파일이 없습니다: {src}")
    in_fps, total = probe_video(src)
    step = max(1, round(in_fps / float(fps)))
    wanted: Optional[List[int]] = None
    if total is not None and total > 1:
        # Grid indices plus the final frame (tail content guard).
        last = total - 1
        wanted = [0]
        index = step
        while index < last:
            wanted.append(index)
            index += step
        wanted.append(last)
        selector = "+".join(f"eq(n,{i})" for i in wanted)
    else:
        # No frame count: plain grid, timestamps from output order.
        selector = f"not(mod(n,{step}))"
    tmp = Path(tempfile.mkdtemp(prefix="m4b_frames_"))
    try:
        pattern = str(tmp / "frame_%04d.png")
        cmd = [
            "ffmpeg", "-y", "-v", "error", "-i", str(src),
            "-vf", f"select='{selector}'",
            "-fps_mode", "passthrough", pattern,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 프레임 추출 실패: {proc.stderr[-500:]}")
        from PIL import Image

        paths = sorted(tmp.glob("frame_*.png"))
        if wanted is None:
            wanted = [k * step for k in range(len(paths))]
        if len(paths) != len(wanted):
            raise RuntimeError(
                f"예상 {len(wanted)}장과 달리 {len(paths)}장을 뽑았습니다.")
        frames: List[Dict[str, Any]] = []
        for number, path in zip(wanted, paths):
            data = path.read_bytes()
            with Image.open(path) as image:
                width, height = int(image.width), int(image.height)
            frames.append({
                "frame_ts": round(number / in_fps, 3),
                "png": bytes(data),
                "width": width,
                "height": height,
            })
        if not frames:
            raise RuntimeError("영상에서 프레임을 한 장도 뽑지 못했습니다.")
        return frames
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def dhash(png_bytes: bytes, size: int = 8) -> int:
    """64-bit difference hash of an image (perceptual hash, M4b brief 4)."""
    from PIL import Image
    import io

    with Image.open(io.BytesIO(bytes(png_bytes))) as image:
        gray = image.convert("L").resize((size + 1, size))
        pixels = list(bytes(gray.tobytes()))
    bits = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    """Hamming distance between two hashes."""
    return bin(int(a) ^ int(b)).count("1")


def select_keyframes(
    frames: List[Dict[str, Any]],
    threshold: int = DEDUP_HAMMING,
) -> List[Dict[str, Any]]:
    """Drop near-duplicate frames, keeping the earliest of each run.

    A frame is kept when its dHash differs by more than ``threshold`` bits
    from every kept frame. The first frame is always kept.
    """
    kept: List[Dict[str, Any]] = []
    hashes: List[int] = []
    for frame in frames:
        digest = dhash(frame["png"])
        if not kept:
            kept.append(frame)
            hashes.append(digest)
            continue
        if all(hamming(digest, known) > threshold for known in hashes):
            kept.append(frame)
            hashes.append(digest)
    return kept
