# -*- coding: utf-8 -*-
"""上传发布遇到短信验证码：无窗口模式下自动切到有界面浏览器让用户输入。

以前无窗口模式只会报错/等到超时；现在 main() 捕获 ManualVerificationRequired，
关掉无头浏览器后重走一遍上传（有界面），在窗口里等用户输入验证码。
"""
from __future__ import annotations

import asyncio
import importlib.util
import sys

import pytest

from tests.helpers import REPO_ROOT

pytest.importorskip("playwright.async_api")

sys.path.insert(0, str(REPO_ROOT / "Upload"))

SPEC = importlib.util.spec_from_file_location(
    "dy_uploader_sms_switch",
    REPO_ROOT / "Upload" / "uploader" / "douyin_uploader" / "main.py",
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


def _video() -> mod.DouYinVideo:
    return mod.DouYinVideo(
        title="t", file_path="f.mp4", tags=[], publish_date=0, account_file="c.json"
    )


def test_headless_sms_switches_to_headed(monkeypatch):
    calls = []

    async def fake_run(self, headless):
        calls.append(headless)
        if headless:
            raise mod.ManualVerificationRequired("需要验证码")

    monkeypatch.setattr(mod.DouYinVideo, "_run_browser", fake_run)
    monkeypatch.setattr(mod, "upload_headless", lambda: True)

    asyncio.run(_video().main())

    assert calls == [True, False]


def test_headless_success_does_not_relaunch(monkeypatch):
    calls = []

    async def fake_run(self, headless):
        calls.append(headless)

    monkeypatch.setattr(mod.DouYinVideo, "_run_browser", fake_run)
    monkeypatch.setattr(mod, "upload_headless", lambda: True)

    asyncio.run(_video().main())

    assert calls == [True]


def test_headed_env_starts_headed(monkeypatch):
    calls = []

    async def fake_run(self, headless):
        calls.append(headless)

    monkeypatch.setattr(mod.DouYinVideo, "_run_browser", fake_run)
    monkeypatch.setattr(mod, "upload_headless", lambda: False)

    asyncio.run(_video().main())

    assert calls == [False]


def test_upload_records_headless_for_publish(monkeypatch):
    """publish_video 里判断的是本次运行的 headless，而不是环境变量。"""

    class FakePlaywright:
        class chromium:
            @staticmethod
            async def launch(**kwargs):
                raise RuntimeError("stop here")  # 只验证 _headless 已写入

    video = _video()
    with pytest.raises(RuntimeError):
        asyncio.run(video.upload(FakePlaywright(), headless=False))
    assert video._headless is False
