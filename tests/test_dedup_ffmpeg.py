# -*- coding: utf-8 -*-
"""FFmpegHandler：流分离与视频属性（用 ffmpeg 替身，不调真实 ffmpeg）。"""
from __future__ import annotations

import sys

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
