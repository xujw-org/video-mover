# -*- coding: utf-8 -*-
"""抖音浏览器参数：上传用固定视口，扫码登录跟随真实窗口。

背景：登录窗口以前复用上传的 1920x1080 视口，小屏 / 高分屏缩放的机器上
窗口比屏幕还大，抖音登录页把二维码画在视口中央，二维码直接跑到屏幕外，
只能手动 Ctrl+- 缩小才看得到。登录改成 no_viewport + --start-maximized。
"""
from __future__ import annotations

import importlib.util

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "douyin_browser_options",
    REPO_ROOT / "Upload" / "uploader" / "douyin_uploader" / "browser_options.py",
)
options = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(options)


def test_upload_context_keeps_fixed_viewport():
    ctx = options.context_options()
    assert ctx["viewport"] == {"width": 1920, "height": 1080}
    assert ctx["device_scale_factor"] == 1
    assert ctx["locale"] == "zh-CN"
    assert ctx["timezone_id"] == "Asia/Shanghai"
    assert ctx["extra_http_headers"]["sec-ch-ua"] == options.DESKTOP_CH_UA


def test_login_context_follows_real_window():
    ctx = options.login_context_options()
    assert "viewport" not in ctx
    assert "device_scale_factor" not in ctx
    assert ctx["no_viewport"] is True


def test_login_context_keeps_http_fingerprint():
    """二维码要能看到，但进 HTTP 头的 UA / 语言 / 时区不能变。"""
    login = options.login_context_options()
    upload = options.context_options()
    for key in ("user_agent", "locale", "timezone_id", "extra_http_headers"):
        assert login[key] == upload[key]


def test_login_window_is_maximized_and_headed():
    launch = options.login_launch_options()
    assert launch["headless"] is False
    assert "--start-maximized" in launch["args"]
    assert "--disable-blink-features=AutomationControlled" in launch["args"]


def test_upload_launch_is_not_maximized():
    launch = options.launch_options(headless=True)
    assert "--start-maximized" not in launch["args"]


def test_login_honours_ua_env_override(monkeypatch):
    monkeypatch.setenv("DOUYIN_UPLOAD_UA", "custom-agent")
    assert options.login_context_options()["user_agent"] == "custom-agent"
