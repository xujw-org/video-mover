# -*- coding: utf-8 -*-
"""download_assets.py：单文件下载校验与 --check 模式（不碰真实网络）。"""
from __future__ import annotations

import importlib.util
import io
import sys
import urllib.error
from pathlib import Path

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "download_assets", REPO_ROOT / "scripts" / "download_assets.py"
)
assets = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assets)


class _FakeResponse:
    def __init__(self, data: bytes):
        self._data = data

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._data


def _urlopen_ok(data: bytes):
    def _fake(req, timeout=None):
        return _FakeResponse(data)

    return _fake


def test_download_one_success_writes_file(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_ok(b"1234"))
    dest = tmp_path / "a.bin"
    ok, msg = assets.download_one("http://example.invalid/a.bin", dest, 4)
    assert ok is True
    assert dest.read_bytes() == b"1234"
    assert "4" in msg


def test_download_one_size_mismatch_is_failure(tmp_path, monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", _urlopen_ok(b"1234"))
    dest = tmp_path / "a.bin"
    ok, msg = assets.download_one("http://example.invalid/a.bin", dest, 999)
    assert ok is False
    assert "大小校验失败" in msg
    assert not dest.exists()


def test_download_one_http_error(tmp_path, monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.HTTPError("http://example.invalid/a.bin", 404, "Not Found", None, None)

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    ok, msg = assets.download_one("http://example.invalid/a.bin", tmp_path / "a.bin", 4)
    assert ok is False
    assert "404" in msg


def test_download_one_url_error(tmp_path, monkeypatch):
    def _raise(req, timeout=None):
        raise urllib.error.URLError("dns fail")

    monkeypatch.setattr("urllib.request.urlopen", _raise)
    ok, msg = assets.download_one("http://example.invalid/a.bin", tmp_path / "a.bin", 4)
    assert ok is False
    assert "网络错误" in msg


def test_main_check_reports_missing(monkeypatch, capsys):
    monkeypatch.setattr(assets, "ASSETS", [("__missing_test_asset__.bin", 4)])
    monkeypatch.setattr(sys, "argv", ["download_assets.py", "--check"])
    assert assets.main() == 1
    assert "缺失" in capsys.readouterr().out


def test_main_check_all_present(monkeypatch, capsys):
    readme = REPO_ROOT / "README.md"
    monkeypatch.setattr(assets, "ASSETS", [("README.md", readme.stat().st_size)])
    monkeypatch.setattr(sys, "argv", ["download_assets.py", "--check"])
    assert assets.main() == 0
    assert "资产齐全" in capsys.readouterr().out


def test_main_check_empty_list(monkeypatch, capsys):
    monkeypatch.setattr(assets, "ASSETS", [])
    monkeypatch.setattr(sys, "argv", ["download_assets.py", "--check"])
    assert assets.main() == 0


def test_main_check_wrong_size_reports_missing(monkeypatch, capsys):
    # README.md 存在但预期大小不对：应视为缺失（需重新下载），返回 1。
    monkeypatch.setattr(assets, "ASSETS", [("README.md", 999999)])
    monkeypatch.setattr(sys, "argv", ["download_assets.py", "--check"])
    assert assets.main() == 1
    assert "缺失" in capsys.readouterr().out
