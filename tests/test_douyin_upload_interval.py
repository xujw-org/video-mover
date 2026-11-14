# -*- coding: utf-8 -*-
"""发布节奏：两次发布至少间隔 15 分钟（状态文件跨进程生效）。"""
from __future__ import annotations

import importlib.util

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "douyin_upload_interval", REPO_ROOT / "Upload" / "douyin_upload.py"
)
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def test_default_interval_is_15_minutes():
    assert mod.DEFAULT_MIN_INTERVAL_MINUTES == 15


def test_first_publish_allowed(tmp_path):
    allowed, wait = mod.publish_gate(15, tmp_path / ".last_publish", now=1000.0)
    assert allowed is True
    assert wait == 0.0


def test_blocked_within_interval(tmp_path):
    state = tmp_path / ".last_publish"
    mod.record_publish(state, now=1000.0)
    allowed, wait = mod.publish_gate(15, state, now=1000.0 + 5 * 60)
    assert allowed is False
    assert abs(wait - 10.0) < 0.01


def test_allowed_after_interval(tmp_path):
    state = tmp_path / ".last_publish"
    mod.record_publish(state, now=1000.0)
    allowed, _ = mod.publish_gate(15, state, now=1000.0 + 16 * 60)
    assert allowed is True


def test_state_is_process_independent(tmp_path):
    state = tmp_path / ".last_publish"
    mod.record_publish(state, now=5000.0)
    assert mod.read_last_publish(state) == 5000.0
    # 换一个“进程”只读文件也能看到
    assert mod.publish_gate(15, state, now=5000.0 + 60)[0] is False


def test_readable_timestamp_also_parsed(tmp_path):
    state = tmp_path / "t"
    state.write_text("2026-11-14 18:07:00", encoding="utf-8")
    assert mod.read_last_publish(state) is not None


def test_garbage_state_treated_as_no_record(tmp_path):
    state = tmp_path / "t"
    state.write_text("junk", encoding="utf-8")
    assert mod.read_last_publish(state) is None
    assert mod.publish_gate(15, state, now=100.0)[0] is True


def test_desc_hashtag_moves_to_tags_not_title():
    """单行描述 “🖤💖 #Moonride”：标题只留正文，话题单独一个。"""
    title, tags = mod.parse_desc_text("🖤💖 #Moonride")
    assert title == "🖤💖"
    assert tags == ["Moonride"]


def test_desc_title_kept_when_only_hashtags():
    title, tags = mod.parse_desc_text("#onlytag")
    assert title == "#onlytag"     # 全被删空时退回原文，不留空标题
    assert tags == ["onlytag"]


def test_desc_multiline_still_works():
    title, tags = mod.parse_desc_text("今天天气真好 #旅行 #vlog\n第二行不算标题")
    assert title == "今天天气真好"
    assert tags == ["旅行", "vlog"]
