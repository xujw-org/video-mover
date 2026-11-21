# -*- coding: utf-8 -*-
"""上传器 Chrome 路径解析：写死的路径不存在时不能直接炸。

背景：Upload/conf.py 以前写死 ``C:/Program Files/Google/Chrome/Application/chrome.exe``，
没装 Chrome（或装在用户目录）的机器上上传报
``Failed to launch chromium because executable doesn't exist``。
现在按 环境变量 -> 常见安装位置 解析，找不到返回 None，用 Playwright 自带 Chromium。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "upload_conf", REPO_ROOT / "Upload" / "conf.py"
)
conf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(conf)


def _make_exe(tmp_path: Path) -> Path:
    exe = tmp_path / "chrome.exe"
    exe.write_bytes(b"")
    return exe


def test_resolve_picks_first_existing_candidate(tmp_path):
    exe = _make_exe(tmp_path)
    found = conf.resolve_chrome_path([str(tmp_path / "missing.exe"), str(exe)])
    assert found == str(exe)


def test_resolve_returns_none_when_nothing_exists(tmp_path):
    assert conf.resolve_chrome_path([str(tmp_path / "missing.exe"), None]) is None


def test_env_override_wins(monkeypatch, tmp_path):
    exe = _make_exe(tmp_path)
    monkeypatch.setenv("DOUYIN_CHROME_PATH", str(exe))
    assert conf.resolve_chrome_path() == str(exe)


def test_missing_env_override_falls_through(tmp_path, monkeypatch):
    """环境变量指向不存在的文件时继续找后面的候选。"""
    exe = _make_exe(tmp_path)
    monkeypatch.setenv("DOUYIN_CHROME_PATH", str(tmp_path / "nope.exe"))
    assert conf.resolve_chrome_path([str(tmp_path / "nope.exe"), str(exe)]) == str(exe)


def test_local_chrome_path_is_optional():
    assert conf.LOCAL_CHROME_PATH is None or Path(conf.LOCAL_CHROME_PATH).is_file()
