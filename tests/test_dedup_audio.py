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


def _run_mix(monkeypatch, tmp_path, volume):
    """把 subprocess.run 换成记录器：混音现在走 ffmpeg 命令行，不碰真实音频。"""
    import subprocess

    calls = []

    class _Done:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        # 造一个假输出文件，让调用方以为混音成功
        with open(cmd[-1], "wb") as fh:
            fh.write(b"FAKEWAV")
        return _Done()

    monkeypatch.setattr(subprocess, "run", fake_run)
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"x")
    out = AudioHandler.mix_bgm(str(tmp_path / "a.wav"), str(bgm), volume)
    return out, calls


def test_mix_bgm_zero_volume_uses_minus_60db_path(tmp_path, monkeypatch):
    out, calls = _run_mix(monkeypatch, tmp_path, 0.0)
    assert out.endswith(".wav")
    assert os.path.exists(out)
    graph = calls[0][calls[0].index("-filter_complex") + 1]
    assert "volume=-60.00dB" in graph


def test_mix_bgm_half_volume_writes_mixed_wav(tmp_path, monkeypatch):
    out, calls = _run_mix(monkeypatch, tmp_path, 0.5)
    assert out.endswith(".wav")
    assert os.path.exists(out)
    cmd = calls[0]
    graph = cmd[cmd.index("-filter_complex") + 1]
    # BGM 按分贝衰减；amix 必须 normalize=0，否则 ffmpeg 会把原声也减半
    assert "volume=-6.02dB" in graph
    assert "amix=inputs=2:duration=first" in graph
    assert "normalize=0" in graph
    # BGM 要循环铺满原音长度
    assert "-stream_loop" in cmd and "-1" in cmd
    # 中间不做任何 resample（这正是以前 audioop 产生噪音的地方）
    assert "aresample" not in graph
    # 中间结果用浮点 wav，避免在 0dBFS 素材上叠加时被整型削顶
    assert cmd[cmd.index("-c:a") + 1] == "pcm_f32le"


def test_mix_bgm_ffmpeg_failure_raises(tmp_path, monkeypatch):
    import subprocess

    class _Fail:
        returncode = 1
        stderr = "boom"

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: _Fail())
    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"x")
    with pytest.raises(RuntimeError):
        AudioHandler.mix_bgm(str(tmp_path / "a.wav"), str(bgm), 0.5)


def test_remove_silence_pads_back_to_original_duration(tmp_path, monkeypatch):
    """拼接掉静音后会变短，必须补回原时长（否则音画错位 + -shortest 截断视频）。"""
    import Dedup.audio as audio_mod

    chunks = [_FakeChunk(200), _FakeChunk(200)]

    monkeypatch.setattr(audio_mod.AudioSegment, "from_file",
                        classmethod(lambda cls, path: _FakeChunk(3000)))
    monkeypatch.setattr(audio_mod, "split_on_silence", lambda *a, **k: chunks)

    config = _passing_video_config(tmp_path)
    config.enable_silence_check = True
    config.silence_retention_ratio = 0

    out = AudioHandler.remove_silence(str(tmp_path / "a.wav"), config)
    assert out.endswith(".wav")
    assert os.path.exists(out)


class _FakeChunk:
    """最小的 AudioSegment 替身：只要 len() 和加法、导出能用。"""

    def __init__(self, duration_ms):
        self.duration_ms = duration_ms
        self.added = []

    def __len__(self):
        return self.duration_ms

    def __add__(self, other):
        result = _FakeChunk(self.duration_ms + len(other))
        result.added = self.added + [len(other)]
        return result

    @classmethod
    def silent(cls, duration=0):
        return cls(duration)

    def export(self, path, format=None):
        with open(path, "wb") as fh:
            fh.write(b"FAKEWAV")
        return self
