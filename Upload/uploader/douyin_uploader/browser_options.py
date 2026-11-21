# -*- coding: utf-8 -*-
"""抖音上传/登录的浏览器参数（不含 playwright 导入，便于单测）。

上传与抓取要用固定的 1920x1080 视口做“设备指纹”；但**扫码登录窗口**不能
用这个视口：老机器（1366x768）或高分屏缩放时，1920x1080 的窗口比屏幕还大，
抖音登录页把二维码画在视口中央，二维码就跑到屏幕外，只能手动 Ctrl+- 缩小
才看得到。登录走 ``login_*`` 参数：no_viewport + --start-maximized，页面跟
真实窗口走，二维码始终在屏幕内。
"""

from __future__ import annotations

import os

# 抖音风控会比对“sessionid 的签发设备”和“正在使用它的浏览器”是否同一台。
# Playwright 的 headless Chromium 默认 UA 是
#   ...HeadlessChrome/158.0.8127.18 Safari/537.36
# 服务器一看就知道是无头浏览器，于是把这个 session 判成可疑并强制登出 ——
# 这正是发布几次之后 cookie 就失效的元凶（stealth.min.js 只改 JS 层，
# 屏蔽不了 HTTP 头里的 UA）。所以所有抖音上下文统一用真 Chrome 的 UA/视口/语言/时区。
DESKTOP_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)

# Chromium 的 UA 伪造了，但 **客户端提示（Client Hints）** 还是暴露真实身份：实测
#   sec-ch-ua: "Chromium";v="158", "Not.A/Brand";v="24", "HeadlessChrome";v="158"
# 服务端只要读这个头就知道是无头浏览器，所以必须一起覆盖。
DESKTOP_CH_UA = '"Google Chrome";v="157", "Chromium";v="157", "Not.A/Brand";v="24"'


def context_options() -> dict:
    """抖音浏览器上下文统一参数（UA/客户端提示/视口/语言/时区/DPR）。"""
    return {
        "user_agent": os.environ.get("DOUYIN_UPLOAD_UA", DESKTOP_UA),
        "viewport": {"width": 1920, "height": 1080},
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "device_scale_factor": 1,
        "extra_http_headers": {
            "sec-ch-ua": DESKTOP_CH_UA,
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
        },
    }


def launch_options(headless: bool, executable_path: str | None = None) -> dict:
    """Chromium 启动参数：关掉 AutomationControlled，避免 navigator.webdriver。"""
    options: dict = {
        "headless": headless,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if executable_path:
        options["executable_path"] = executable_path
    return options


def login_context_options() -> dict:
    """扫码登录的上下文：去掉固定视口，跟随真实窗口大小。

    UA / 语言 / 时区 / Client Hints 与上传阶段保持一致（这些才进 HTTP 头、
    参与风控判定）；只放弃 1920x1080 的视口，否则小屏机器上二维码会落在
    屏幕外。
    """
    options = context_options()
    options.pop("viewport", None)
    options.pop("device_scale_factor", None)
    options["no_viewport"] = True
    return options


def login_launch_options(executable_path: str | None = None) -> dict:
    """扫码登录的启动参数：有窗口 + 最大化，保证二维码在屏幕内。"""
    options = launch_options(headless=False, executable_path=executable_path)
    options["args"] = [*options["args"], "--start-maximized"]
    return options
