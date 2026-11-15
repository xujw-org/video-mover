# -*- coding: utf-8 -*-
"""Upload/cover.py：从视频截一帧做横/竖封面（用真实 ffmpeg）。"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess

import pytest

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location("cover_mod", REPO_ROOT / "Upload" / "cover.py")
cover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cover)

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")


def _make_video(path, seconds=3, color="navy"):
    subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", f"color=c={color}:s=360x640:d={seconds}:r=25",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)],
        check=True,
    )


def _size(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.strip()
    width, height = out.split(",")[:2]
    return int(width), int(height)


def test_covers_have_expected_ratios(tmp_path):
    video = tmp_path / "v.mp4"
    _make_video(video)
    covers = cover.make_covers(video, tmp_path / "covers")
    assert _size(covers["vertical"]) == cover.VERTICAL_SIZE      # 3:4
    assert _size(covers["horizontal"]) == cover.HORIZONTAL_SIZE  # 4:3
    assert covers["vertical"].is_file() and covers["horizontal"].is_file()


def test_missing_video_raises(tmp_path):
    with pytest.raises(RuntimeError):
        cover.make_cover(tmp_path / "nope.mp4", tmp_path / "out.jpg")


def test_video_duration_and_brightness(tmp_path):
    video = tmp_path / "v.mp4"
    _make_video(video)
    assert cover.video_duration(video) > 2.5
    # 纯色 navy 帧亮度很低但不为 0；pick_bright_second 必须在时长内
    at, bright = cover.pick_bright_second(video)
    assert 0 <= at <= cover.video_duration(video)
    assert 0 <= bright <= 255
