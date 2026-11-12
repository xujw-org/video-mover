# -*- coding: utf-8 -*-
"""Dedup/dedup.py 垫片：re-export 与三种运行方式（与 main.py 的 subprocess 调用约定一致）。"""
from __future__ import annotations

import subprocess
import sys

import Dedup
import Dedup.dedup as shim
from Dedup import audio as dedup_audio
from Dedup import config as dedup_config
from Dedup import ffmpeg_utils as dedup_ffmpeg
from Dedup import filters as dedup_filters
from Dedup import pipeline as dedup_pipeline
from Dedup import subtitles as dedup_subtitles
from tests.helpers import REPO_ROOT

EXPECTED = {
    "VideoConfig": dedup_config.VideoConfig,
    "FFmpegHandler": dedup_ffmpeg.FFmpegHandler,
    "AudioHandler": dedup_audio.AudioHandler,
    "SubtitleHandler": dedup_subtitles.SubtitleHandler,
    "VideoEffects": dedup_filters.VideoEffects,
    "VideoHandler": dedup_pipeline.VideoHandler,
}


def test_shim_reexports_are_the_new_modules():
    for name, cls in EXPECTED.items():
        assert getattr(shim, name) is cls, name


def test_package_reexports_are_the_new_modules():
    for name, cls in EXPECTED.items():
        assert getattr(Dedup, name) is cls, name


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
    )


def test_cli_help_from_repo_root_as_script():
    proc = _run(["Dedup/dedup.py", "--help"], REPO_ROOT)
    assert proc.returncode == 0
    assert "python dedup.py -i input.mp4 -o output.mp4" in proc.stdout


def test_cli_help_from_repo_root_as_module():
    proc = _run(["-m", "Dedup.dedup", "--help"], REPO_ROOT)
    assert proc.returncode == 0
    assert "python dedup.py -i input.mp4 -o output.mp4" in proc.stdout


def test_cli_help_from_dedup_dir():
    proc = _run(["dedup.py", "--help"], REPO_ROOT / "Dedup")
    assert proc.returncode == 0
    assert "python dedup.py -i input.mp4 -o output.mp4" in proc.stdout


def test_top_level_import_from_dedup_dir():
    proc = subprocess.run(
        [sys.executable, "-c", "import dedup; print(dedup.VideoHandler.__module__)"],
        cwd=str(REPO_ROOT / "Dedup"), capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert "Dedup.pipeline" in proc.stdout


def test_cli_missing_args_exits_nonzero():
    proc = _run(["Dedup/dedup.py"], REPO_ROOT)
    assert proc.returncode != 0
    assert "required" in proc.stderr


def test_cli_missing_input_fails_like_original(tmp_path):
    """不存在的输入应在 VideoHandler 初始化/校验阶段失败，而不是静默成功。"""
    proc = _run(
        ["Dedup/dedup.py", "-i", str(tmp_path / "no-such.mp4"), "-o", str(tmp_path / "o.mp4")],
        REPO_ROOT,
    )
    assert proc.returncode != 0
    assert "不存在" in proc.stderr
