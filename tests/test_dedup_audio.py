# -*- coding: utf-8 -*-
"""AudioHandler：静音去除与背景音乐混合（用 pydub 替身，不碰真实音频）。"""
from __future__ import annotations

import os
import sys

import pytest

from Dedup.audio import AudioHandler
from tests.helpers import _passing_video_config


def test_remove_silence_disabled_returns_original(tmp_path):
    config = _passing_video_config(tmp_path)
    config.enable_silence_check = False
    assert AudioHandler.remove_silence(str(tmp_path / "a.wav"), config) == str(tmp_path / "a.wav")


def test_remove_silence_no_chunks_returns_original(tmp_path):
    config = _passing_video_config(tmp_path)
    config.enable_silence_check = True
    pydub = sys.modules["pydub"]
    old = pydub.silence.split_result
    pydub.silence.split_result = []
    try:
        out = AudioHandler.remove_silence(str(tmp_path / "a.wav"), config)
    finally:
        pydub.silence.split_result = old
    assert out == str(tmp_path / "a.wav")


def test_remove_silence_enabled_joins_chunks_and_writes_wav(tmp_path):
    config = _passing_video_config(tmp_path)
    config.enable_silence_check = True
    config.silence_retention_ratio = 0.5
    config.silent_duration = 500
    config.silence_threshold = -50
    out = AudioHandler.remove_silence(str(tmp_path / "a.wav"), config)
    assert out.endswith(".wav")
    assert os.path.exists(out)


def test_remove_silence_failure_raises(tmp_path, monkeypatch):
    config = _passing_video_config(tmp_path)
    config.enable_silence_check = True
    pydub = sys.modules["pydub"]

    def boom(*args, **kwargs):
        raise RuntimeError("解码失败")

    monkeypatch.setattr(pydub.AudioSegment, "from_file", classmethod(boom))
    with pytest.raises(RuntimeError, match="解码失败"):
        AudioHandler.remove_silence(str(tmp_path / "a.wav"), config)


def test_mix_bgm_missing_file_returns_original(tmp_path):
    out = AudioHandler.mix_bgm(str(tmp_path / "a.wav"), str(tmp_path / "no-bgm.mp3"), 0.5)
    assert out == str(tmp_path / "a.wav")


def test_mix_bgm_zero_volume_uses_minus_60db_path(tmp_path):
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"x")
    out = AudioHandler.mix_bgm(str(tmp_path / "a.wav"), str(bgm), 0.0)
    assert out.endswith(".wav")
    assert os.path.exists(out)


def test_mix_bgm_half_volume_writes_mixed_wav(tmp_path):
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"x")
    out = AudioHandler.mix_bgm(str(tmp_path / "a.wav"), str(bgm), 0.5)
    assert out.endswith(".wav")
    assert os.path.exists(out)
