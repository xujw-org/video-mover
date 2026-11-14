# -*- coding: utf-8 -*-
"""FFmpegHandler：流分离与视频属性（用 ffmpeg 替身，不调真实 ffmpeg）。"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from Dedup.ffmpeg_utils import FFmpegHandler


@pytest.fixture(autouse=True)
def _reset_fake_ffmpeg():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    ffmpeg.processes.clear()
    ffmpeg.probe_error = None
    ffmpeg.probe_result = {
        "streams": [
            {"codec_type": "video", "width": 640, "height": 360, "r_frame_rate": "30/1"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
        "format": {"duration": "10.0"},
    }
    yield
    ffmpeg.calls.clear()
    ffmpeg.probe_error = None


def test_split_av_streams_with_audio():
    video, audio = FFmpegHandler.split_av_streams("in.mp4")
    assert video is not None
    assert audio is not None
    assert ("probe", "in.mp4") in sys.modules["ffmpeg"].calls


def test_split_av_streams_without_audio_returns_none_audio():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.probe_result = {
        "streams": [
            {"codec_type": "video", "width": 640, "height": 360, "r_frame_rate": "30/1"},
        ],
        "format": {"duration": "10.0"},
    }
    video, audio = FFmpegHandler.split_av_streams("in.mp4")
    assert video is not None
    assert audio is None


def test_split_av_streams_without_video_raises():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.probe_result = {
        "streams": [{"codec_type": "audio", "codec_name": "aac"}],
        "format": {"duration": "10.0"},
    }
    with pytest.raises(ValueError, match="未找到视频流"):
        FFmpegHandler.split_av_streams("in.mp4")


def test_split_av_streams_probe_error_raises():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.probe_error = ffmpeg.Error("probe failed")
    with pytest.raises(ffmpeg.Error):
        FFmpegHandler.split_av_streams("in.mp4")


def test_get_video_properties():
    width, height, fps = FFmpegHandler.get_video_properties("in.mp4")
    assert (width, height) == (640, 360)
    assert fps == pytest.approx(30.0)


def test_get_video_properties_fractional_fps():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.probe_result["streams"][0]["r_frame_rate"] = "30000/1001"
    _, _, fps = FFmpegHandler.get_video_properties("in.mp4")
    assert fps == pytest.approx(29.97, abs=0.01)


def test_get_video_properties_probe_error_raises():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.probe_error = ffmpeg.Error("probe failed")
    with pytest.raises(ffmpeg.Error):
        FFmpegHandler.get_video_properties("in.mp4")


def test_write_frames_encodes_yuv420p_and_shortest(monkeypatch, tmp_path):
    """编码必须显式 yuv420p，并且加 -shortest。

    历史上两个坑都在这里：
    - 不写 pix_fmt 时 x264 选 yuv444p（High 4:4:4），手机/抖音解不了，
      表现成“前几秒正常后面一帧卡住”；
    - 不加 -shortest 时容器时长跟音频走，视频流短，播放器把最后一帧定住。
    """
    from Dedup.pipeline import VideoHandler

    captured = {}

    class _FakeInput:
        def __init__(self, *a, **k):
            pass

        def output(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return self

        def overwrite_output(self):
            return self

        def run_async(self, **kwargs):
            return _FakeProcess()

    class _FakeProcess:
        stdin = type("S", (), {"write": lambda self, b: None, "close": lambda self: None})()

        def wait(self):
            return 0

    class _FakeFfmpeg:
        @staticmethod
        def input(*a, **k):
            return _FakeInput(*a, **k)

    monkeypatch.setattr("Dedup.pipeline.ffmpeg", _FakeFfmpeg)

    handler = VideoHandler.__new__(VideoHandler)  # 跳过 __init__ 的配置校验
    frames = [np.zeros((4, 4, 3), dtype=np.uint8) for _ in range(3)]
    handler._write_frames(iter(frames), str(tmp_path / "out.mp4"), 4, 4, 30.0, None)

    assert captured["kwargs"]["pix_fmt"] == "yuv420p"
    assert "shortest" in captured["kwargs"]
