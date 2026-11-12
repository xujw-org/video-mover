# -*- coding: utf-8 -*-
"""Dedup/dedup.py 垫片：re-export 与三种运行方式（与 main.py 的 subprocess 调用约定一致）。"""
from __future__ import annotations

import os
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


def _run(args, cwd, env_extra=None):
    # 子进程的 stdio 必须显式按 UTF-8 处理：GitHub Windows runner 是
    # 美区系统，默认编码是 cp1252（charmap），编不了中文。
    # 不加这句，--help 打印“输入视频文件路径”时会抛 UnicodeEncodeError，
    # 而 stderr 里的中文会被 backslashreplace 转成 \uXXXX，导致
    # test_cli_missing_input_fails_like_original 里 "不存在" 断言失败。
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, *args], cwd=str(cwd),
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace", env=env,
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
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-c", "import dedup; print(dedup.VideoHandler.__module__)"],
        cwd=str(REPO_ROOT / "Dedup"), capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace", env=env,
    )
    assert proc.returncode == 0
    assert "Dedup.pipeline" in proc.stdout


def test_cli_help_with_charmap_stdio():
    """回归测试：模拟美区 Windows（stdio 编码 cp1252）跑 --help 也不崩。

    复现 CI 第三次运行的 3 个 --help 失败：子进程 stdio 是 cp1252 时，
    argparse 打印中文帮助会抛 UnicodeEncodeError。
    修复后 Dedup/dedup.py 启动时把 stdio 重设为 UTF-8，所以即使
    PYTHONIOENCODING=cp1252 也应正常退出且帮助里有中文。
    注意：必须同时把 PYTHONUTF8 设为 0，否则它会优先于
    PYTHONIOENCODING 强制 UTF-8 模式，模拟就失效了。
    """
    proc = _run(
        ["Dedup/dedup.py", "--help"], REPO_ROOT,
        env_extra={"PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"},
    )
    assert proc.returncode == 0
    assert "输入视频文件路径" in proc.stdout


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
