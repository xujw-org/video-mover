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


def _state_with(*pairs):
    cookie = "; ".join(f"{k}={v}" for k, v in pairs)
    return export_cookie.to_storage_state(cookie)


def test_sid_issued_at_reads_second_field():
    cookies = {"sid_guard": "abc|1794645733|5184000|Wed%2C+13-Jan-2027"}
    assert export_cookie.sid_issued_at(cookies) == 1794645733
    # 字段不全 / 不是数字 / 没有 cookie 都返回 0
    assert export_cookie.sid_issued_at({}) == 0
    assert export_cookie.sid_issued_at({"sid_guard": "abc"}) == 0
    assert export_cookie.sid_issued_at({"sid_guard": "abc|notanumber|1|x"}) == 0


def test_export_refuses_to_clobber_newer_session(tmp_path, capsys):
    config = REPO_ROOT / "my_apps.yaml"
    output = tmp_path / "douyin_default.json"
    # 输出文件里的 session 是新的（签发时间更晚）
    newer = _state_with(
        ("sessionid", "new"), ("ttwid", "t"),
        ("sid_guard", "guardsig|1794649999|5184000|Fri%2C+14-Jan-2027"),
    )
    output.write_text(__import__("json").dumps(newer), encoding="utf-8")
    before = output.read_text(encoding="utf-8")

    code = export_cookie.main(["--config", str(config), "--output", str(output)])
    assert code == 1
    assert output.read_text(encoding="utf-8") == before        # 没被覆盖
    assert "跳过" in capsys.readouterr().out


def test_export_overwrites_with_force(tmp_path):
    config = REPO_ROOT / "my_apps.yaml"
    output = tmp_path / "douyin_default.json"
    newer = _state_with(
        ("sessionid", "new"), ("ttwid", "t"),
        ("sid_guard", "guardsig|1794649999|5184000|Fri%2C+14-Jan-2027"),
    )
    output.write_text(__import__("json").dumps(newer), encoding="utf-8")

    code = export_cookie.main(["--config", str(config), "--output", str(output), "--force"])
    assert code == 0
    after = __import__("json").loads(output.read_text(encoding="utf-8"))
    names = {c["name"]: c["value"] for c in after["cookies"]}
    assert names.get("sessionid") != "new"      # 被 yaml 里的覆盖了
