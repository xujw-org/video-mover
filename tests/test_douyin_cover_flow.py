# -*- coding: utf-8 -*-
"""封面弹层处理：设完封面后平台会弹“设置横封面获更多流量”，必须点“暂不设置”。

不关它的话弹层盖住整页，后面的“地理位置”点击会一直被子树拦截
（subtree intercepts pointer events），页面提示也停在“横/竖双封面缺失”。
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
    "dy_uploader_cover_flow",
    REPO_ROOT / "Upload" / "uploader" / "douyin_uploader" / "main.py",
)
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)


class FakeLocator:
    """足够让 helper 走到 JS 兜底路径：没有可点的真实按钮。"""

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    async def count(self):
        return 0

    async def is_visible(self):
        return False

    async def is_enabled(self):
        return False

    async def click(self, timeout=0):
        raise RuntimeError("no clickable button in fake page")


class FakePage:
    def __init__(self, states):
        self.states = list(states)

    def locator(self, selector):
        return FakeLocator()

    async def evaluate(self, script, arg=None):
        return self.states.pop(0) if self.states else "none"


@pytest.fixture
def no_sleep(monkeypatch):
    async def _noop(_seconds):
        return None

    monkeypatch.setattr(mod.asyncio, "sleep", _noop)


def test_upsell_is_dismissed_with_skip_button(monkeypatch, no_sleep):
    clicks = []

    async def fake_click(page, text):
        clicks.append(text)
        return True

    monkeypatch.setattr(mod, "_js_click_modal_button", fake_click)

    assert asyncio.run(mod._dismiss_cover_upsell(FakePage(["upsell", "none"]))) is True
    assert clicks == ["暂不设置"]


def test_pending_editor_is_not_reclicked(monkeypatch, no_sleep):
    """编辑器还在收尾时只等待，不重复点“完成”（异步提交重复点会出问题）。"""
    clicks = []

    async def fake_click(page, text):
        clicks.append(text)
        return True

    monkeypatch.setattr(mod, "_js_click_modal_button", fake_click)

    assert asyncio.run(mod._dismiss_cover_upsell(FakePage(["other", "none"]))) is True
    assert clicks == []


def test_no_modal_returns_immediately(monkeypatch, no_sleep):
    async def should_not_click(page, text):
        raise AssertionError("没有弹窗时不应点击")

    monkeypatch.setattr(mod, "_js_click_modal_button", should_not_click)
    assert asyncio.run(mod._dismiss_cover_upsell(FakePage(["none"]))) is True
