# -*- coding: utf-8 -*-
"""从视频里截一帧当封面（抖音要求横/竖双封面）。

抖音创作者中心发布页的封面是分开设的：``设置竖封面``（3:4）和
``设置横封面``（4:3 左右），两个都设能拿到更多曝光（不设会提示
“横/竖双封面缺失”）。这里用 ffmpeg 从视频里取一帧，按目标比例先等比放大再
居中裁切，保证不变形。
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

# 竖封面 3:4、横封面 4:3（抖音预览就是这么给的）
VERTICAL_SIZE = (1080, 1440)
HORIZONTAL_SIZE = (1440, 1080)


def _ffmpeg_exe() -> str:
    return os.environ.get("FFMPEG_BIN") or "ffmpeg"


def video_duration(video_path) -> float:
    """视频时长（秒），拿不到返回 0。"""
    try:
        completed = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(video_path)],
            capture_output=True, text=True,
        )
        return float((completed.stdout or "").strip() or 0)
    except (OSError, ValueError):
        return 0.0


def frame_brightness(video_path, at_seconds: float) -> float:
    """某一时刻画面的平均亮度（0-255）：先缩成 1x1 灰度再读那一个像素，很便宜。"""
    try:
        completed = subprocess.run(
            [_ffmpeg_exe(), "-hide_banner", "-loglevel", "error",
             "-ss", f"{at_seconds:.3f}", "-i", str(video_path),
             "-frames:v", "1", "-vf", "scale=1:1", "-f", "rawvideo",
             "-pix_fmt", "gray", "-"],
            capture_output=True,
        )
        data = completed.stdout
        return float(data[0]) if data else 0.0
    except (OSError, IndexError):
        return 0.0


def pick_bright_second(video_path) -> tuple:
    """挑最亮的一帧当年封面（避开黑场/片头），返回 (秒, 亮度 0-255)。

    在 5%~95% 之间取 10 个候选点，每个点只读 1 个灰度像素（缩成 1x1），
    成本几乎为零。素材本身就暗时，返回的亮度会很小，调用方据此提亮。
    """
    duration = video_duration(video_path)
    if not duration:
        return 1.0, 0.0
    fractions = [0.05 + 0.1 * i for i in range(10)]
    scored = [(frame_brightness(video_path, duration * f), duration * f) for f in fractions]
    scored = [(b, t) for b, t in scored if t < duration]
    if not scored:
        return 1.0, 0.0
    best_brightness, best_time = max(scored)
    logging.info(
        "封面候选帧亮度: %s -> 选 %.2fs（亮度 %.0f）",
        [(round(b), round(t, 1)) for b, t in scored], best_time, best_brightness,
    )
    return best_time, best_brightness


# 低于这个亮度就认为封面偏黑，需要提亮（0-255）
DARK_THRESHOLD = 70


def make_cover(video_path, out_path, size=VERTICAL_SIZE, at_seconds: float | None = None) -> Path:
    """截一帧做成 ``size`` 大小的封面（等比放大 + 居中裁切，不变形）。

    素材偏暗时（夜景、雨夜、室内暗光），直接截出来的封面是“黑图”，用户在抖音里
    看到就是一片黑。所以先量亮度，低于 ``DARK_THRESHOLD`` 就用 ``normalize`` 拉开
    动态范围，再补一点亮度/对比度/饱和度。
    """
    video_path, out_path = Path(video_path), Path(out_path)
    width, height = size
    brightness = 0.0
    if at_seconds is None:
        at_seconds, brightness = pick_bright_second(video_path)
    else:
        brightness = frame_brightness(video_path, at_seconds)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height}"
    )
    if brightness and brightness < DARK_THRESHOLD:
        # 0 = 很暗，1 = 接近阈值；越暗补得越多（亮度 +0.10~0.22，对比 1.1~1.25）
        ratio = 1.0 - brightness / DARK_THRESHOLD
        vf += (
            ",normalize=blackpt=black:whitept=white"
            f",eq=brightness={0.10 + 0.12 * ratio:.3f}"
            f":contrast={1.10 + 0.15 * ratio:.2f}"
            f":saturation={1.10 + 0.10 * ratio:.2f}"
        )
        logging.info(
            "封面偏暗（亮度 %.0f/255），已提亮（+%.2f 亮度 / %.2f 对比）",
            brightness, 0.10 + 0.12 * ratio, 1.10 + 0.15 * ratio,
        )
    cmd = [
        _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{at_seconds:.3f}", "-i", str(video_path),
        "-frames:v", "1", "-q:v", "2", "-vf", vf, str(out_path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True)
    if completed.returncode != 0 or not out_path.is_file():
        raise RuntimeError(
            f"生成封面失败（{video_path.name}）: {(completed.stderr or '').strip()[:300]}"
        )
    logging.info("封面已生成: %s (%dx%d)", out_path, width, height)
    return out_path


def make_covers(video_path, out_dir) -> dict[str, Path]:
    """同时生成横、竖两张封面。"""
    video_path, out_dir = Path(video_path), Path(out_dir)
    stem = video_path.stem
    return {
        "vertical": make_cover(video_path, out_dir / f"{stem}_cover_3x4.jpg", VERTICAL_SIZE),
        "horizontal": make_cover(video_path, out_dir / f"{stem}_cover_4x3.jpg", HORIZONTAL_SIZE),
    }
