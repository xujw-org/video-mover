# -*- coding: utf-8 -*-
"""抖音自动化不能再暴露“无头浏览器”指纹（cookie 反复失效的元凶）。"""
from __future__ import annotations

import importlib.util
import sys

from tests.helpers import REPO_ROOT

# 上传器模块依赖 Upload/ 下的 conf.py，先把目录塞进 sys.path
sys.path.insert(0, str(REPO_ROOT / "Upload"))


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # 必须先注册到 sys.modules：模块里用了 dataclass，否则 dataclasses 解析
    # 字段类型时找不到 cls.__module__
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


uploader = _load("dy_uploader_main", REPO_ROOT / "Upload" / "uploader" / "douyin_uploader" / "main.py")
_fetch = _load("dy_fetch", REPO_ROOT / "douyin_fetch.py")


def test_context_options_look_like_real_chrome():
    opts = uploader.context_options()
    # UA 里绝不能出现 HeadlessChrome
    assert "Headless" not in opts["user_agent"]
    assert "Chrome/" in opts["user_agent"]
    assert opts["viewport"] == {"width": 1920, "height": 1080}
    assert opts["locale"] == "zh-CN"
    assert opts["timezone_id"] == "Asia/Shanghai"
    # 客户端提示也不能暴露 HeadlessChrome：实测服务器读的是这个头
    headers = opts["extra_http_headers"]
    assert "Headless" not in headers["sec-ch-ua"]
    assert headers["sec-ch-ua-platform"] == '"Windows"'
    assert headers["sec-ch-ua-mobile"] == "?0"


def test_launch_options_disable_automation_flag():
    opts = uploader.launch_options(True)
    assert opts["headless"] is True
    assert "--disable-blink-features=AutomationControlled" in opts["args"]
    assert "executable_path" not in opts
    assert uploader.launch_options(False, "C:/chrome.exe")["executable_path"] == "C:/chrome.exe"


def test_fetch_client_hints_do_not_say_headless():
    assert "Headless" not in _fetch.DESKTOP_CH_UA
    assert "Headless" not in _fetch.DEFAULT_USER_AGENT
    assert "Chrome/" in _fetch.DEFAULT_USER_AGENT
