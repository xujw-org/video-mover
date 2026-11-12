# -*- coding: utf-8 -*-
"""SubtitleHandler：SRT 时间格式与 Whisper 生成字幕（用替身，不联网、不加载模型）。"""
from __future__ import annotations

import sys

import pytest

from Dedup.subtitles import SubtitleHandler


def test_format_time():
    assert SubtitleHandler.format_time(0) == "00:00:00,000"
    assert SubtitleHandler.format_time(1.5) == "00:00:01,500"
    assert SubtitleHandler.format_time(61.25) == "00:01:01,250"
    assert SubtitleHandler.format_time(3661.5) == "01:01:01,500"


def test_generate_subtitles_writes_srt_with_simplified_text(tmp_path):
    whisper = sys.modules["whisper"]
    srt_path = SubtitleHandler.generate_subtitles(str(tmp_path / "in.mp4"), "base")
    text = open(srt_path, encoding="utf-8").read()
    assert text == (
        "1\n00:00:00,000 --> 00:00:01,500\n你好世界\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n中国语\n\n"
    )
    assert whisper is not None  # 替身模块确实被用到了


def test_generate_subtitles_propagates_transcribe_error(tmp_path):
    whisper = sys.modules["whisper"]
    whisper.transcribe_error = RuntimeError("模型炸了")
    try:
        with pytest.raises(RuntimeError, match="模型炸了"):
            SubtitleHandler.generate_subtitles(str(tmp_path / "in.mp4"), "base")
    finally:
        whisper.transcribe_error = None


def test_generate_subtitles_uses_given_model_name(tmp_path):
    whisper = sys.modules["whisper"]
    seen = {}
    orig_load = whisper.load_model

    def spy(name="base"):
        seen["name"] = name
        return orig_load(name)

    whisper.load_model = spy
    try:
        SubtitleHandler.generate_subtitles(str(tmp_path / "in.mp4"), "tiny")
    finally:
        whisper.load_model = orig_load
    assert seen["name"] == "tiny"
