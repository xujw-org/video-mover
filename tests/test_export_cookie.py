# -*- coding: utf-8 -*-
"""Upload/export_cookie.py：网页 cookie -> 上传器 storage_state（不碰真实网络）。"""
from __future__ import annotations

import importlib.util

import pytest

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "export_cookie", REPO_ROOT / "Upload" / "export_cookie.py"
)
export_cookie = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(export_cookie)


def test_to_storage_state_basic():
    state = export_cookie.to_storage_state("sessionid=abc; ttwid=1%7Cxyz; ;bad")
    names = {c["name"]: c["value"] for c in state["cookies"]}
    assert names == {"sessionid": "abc", "ttwid": "1%7Cxyz"}
    assert state["origins"] == []
    for cookie in state["cookies"]:
        assert cookie["domain"] == ".douyin.com"
        assert cookie["path"] == "/"


def test_to_storage_state_keeps_values_with_equals():
    state = export_cookie.to_storage_state("sid_guard=abc|123|456|x=1")
    assert state["cookies"][0]["value"] == "abc|123|456|x=1"


def test_to_storage_state_rejects_empty():
    for value in ("", "  ", "no-equals-here"):
        with pytest.raises(ValueError):
            export_cookie.to_storage_state(value)


def test_load_web_cookie(tmp_path):
    config = tmp_path / "my_apps.yaml"
    config.write_text('douyin:\n  cookie: "a=1; b=2"\n', encoding="utf-8")
    assert export_cookie.load_web_cookie(config) == "a=1; b=2"

    empty = tmp_path / "empty.yaml"
    empty.write_text("douyin:\n  cookie: ''\n", encoding="utf-8")
    with pytest.raises(ValueError):
        export_cookie.load_web_cookie(empty)

    with pytest.raises(FileNotFoundError):
        export_cookie.load_web_cookie(tmp_path / "nope.yaml")
