# -*- coding: utf-8 -*-
"""Upload/cover.py 的 ffmpeg/ffprobe 解析（不依赖真实 ffmpeg，CI 也能跑）。

原因：封面生成以前只找 PATH。上传脚本被单独启动（没经过 main.py 的 PATH
注入）时，找不到 ffmpeg 就封面失败，发布出去就是“封面缺失”。现在回退到
仓库自带的 tools/ffmpeg/bin。
"""
from __future__ import annotations

import importlib.util
import os

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location("cover_mod_tools", REPO_ROOT / "Upload" / "cover.py")
cover = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cover)


def _bundled(tmp_path, name: str):
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    if name == "ffprobe":
        exe = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    target = tmp_path / "tools" / "ffmpeg" / "bin" / exe
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    return target


def test_env_override_wins(monkeypatch):
    monkeypatch.setenv("FFMPEG_BIN", r"D:\custom\ffmpeg.exe")
    assert cover._ffmpeg_exe() == r"D:\custom\ffmpeg.exe"


def test_path_is_preferred(monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(cover.shutil, "which", lambda name: f"/usr/bin/{name}")
    assert cover._ffmpeg_exe() == "/usr/bin/ffmpeg"
    assert cover._ffprobe_exe() == "/usr/bin/ffprobe"


def test_falls_back_to_bundled_ffmpeg(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(cover, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cover.shutil, "which", lambda name: None)
    bundled = _bundled(tmp_path, "ffmpeg")
    assert cover._ffmpeg_exe() == str(bundled)


def test_falls_back_to_bundled_ffprobe(tmp_path, monkeypatch):
    monkeypatch.setattr(cover, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cover.shutil, "which", lambda name: None)
    bundled = _bundled(tmp_path, "ffprobe")
    assert cover._ffprobe_exe() == str(bundled)


def test_bare_name_when_nothing_exists(tmp_path, monkeypatch):
    monkeypatch.delenv("FFMPEG_BIN", raising=False)
    monkeypatch.setattr(cover, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cover.shutil, "which", lambda name: None)
    assert cover._ffmpeg_exe() == "ffmpeg"
    assert cover._ffprobe_exe() == "ffprobe"
