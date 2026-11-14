# -*- coding: utf-8 -*-
"""第 2 步（播放速度）与第 3 步（音频多样化）。

速度：输出帧率 = 原帧率 × playback_speed，帧数不变，所以输出时长
= 原时长 / 速度；字幕仍按原时间查（_process_frames 拿原 fps），
只有写帧用新帧率，否则字幕会整体漂移。

音频（VideoHandler._apply_audio_effects）：volume 调音量；
asetrate+aresample 变调（需要采样率）；atempo 变速。
变调 + 变速一起上时 atempo 因子是 speed/pitch，保证最终时长
只跟速度走、音调只跟 pitch 走。
"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from Dedup.config import VideoConfig
from Dedup.pipeline import VideoHandler
from tests.helpers import _passing_video_config


def _frame(value, shape=(48, 64, 3)):
    return np.full(shape, value, dtype=np.uint8)


def _quiet_config(tmp_path):
    """全部特效关掉的配置（与 test_dedup_pipeline.py 里的同款）。"""
    config = _passing_video_config(tmp_path)
    config.flip_horizontal = False
    config.rotation_angle = 0
    config.crop_percentage = 0.0
    config.enable_sbc = False
    config.include_watermark = False
    config.include_subtitles = False
    config.include_titles = False
    config.include_hzh = False
    config.enable_color_shift = False
    config.blur_background_enabled = False
    config.scramble_frequency = 0.0
    config.enable_texture_noise = False
    config.enable_blur_edge = False
    config.gaussian_blur_interval = 0
    config.fade_in_frames = 0
    config.fade_out_frames = 0
    return config


# 滤镜链最后总会挂一个限制器（防止 0dBFS 素材削顶），单独拿出来便于断言。
LIMITER = ("filter", ("alimiter",), {"limit": 0.89})


def _filters(ffmpeg):
    return [c for c in ffmpeg.calls if c[0] == "filter"]


def test_audio_effects_defaults_add_no_filter():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    stream = ffmpeg.input("x.wav")
    out = VideoHandler._apply_audio_effects(stream, VideoConfig(), 48000)
    assert out is stream
    # 默认参数不加音色滤镜，但限制器始终在（防削顶）
    assert _filters(ffmpeg) == [LIMITER]


def test_audio_effects_none_stream_returns_none():
    assert VideoHandler._apply_audio_effects(None, VideoConfig(), 48000) is None


def test_audio_effects_volume_only():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    stream = ffmpeg.input("x.wav")
    config = VideoConfig()
    config.audio_volume = 1.05
    out = VideoHandler._apply_audio_effects(stream, config, 48000)
    assert out is stream  # 替身 filter 返回 self
    assert _filters(ffmpeg) == [("filter", ("volume", 1.05), {}), LIMITER]


def test_audio_effects_speed_only_uses_atempo():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    stream = ffmpeg.input("x.wav")
    config = VideoConfig()
    config.playback_speed = 1.05
    VideoHandler._apply_audio_effects(stream, config, 48000)
    assert _filters(ffmpeg) == [("filter", ("atempo", 1.05), {}), LIMITER]


def test_audio_effects_pitch_only():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    stream = ffmpeg.input("x.wav")
    config = VideoConfig()
    config.pitch_shift = 1.02
    VideoHandler._apply_audio_effects(stream, config, 48000)
    # asetrate(48000*1.02=48960) 变调，aresample 回 48000，
    # atempo(1/1.02≈0.9804) 把时长补回原时长。
    assert _filters(ffmpeg) == [
        ("filter", ("asetrate", 48960), {}),
        ("filter", ("aresample", 48000), {"resampler": "soxr"}),
        ("filter", ("atempo", 0.9804), {}),
        LIMITER,
    ]


def test_audio_effects_pitch_and_speed_combined():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    stream = ffmpeg.input("x.wav")
    config = VideoConfig()
    config.playback_speed = 1.05
    config.pitch_shift = 1.02
    VideoHandler._apply_audio_effects(stream, config, 48000)
    # atempo 因子是 speed/pitch = 1.05/1.02 ≈ 1.0294，不是 1.05。
    assert _filters(ffmpeg) == [
        ("filter", ("asetrate", 48960), {}),
        ("filter", ("aresample", 48000), {"resampler": "soxr"}),
        ("filter", ("atempo", 1.0294), {}),
        LIMITER,
    ]


def test_audio_effects_pitch_skipped_without_sample_rate():
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    stream = ffmpeg.input("x.wav")
    config = VideoConfig()
    config.pitch_shift = 1.02
    VideoHandler._apply_audio_effects(stream, config, None)
    # 拿不到采样率就跳过变调，tempo 只按速度走（这里速度是 1.0，只剩限制器）。
    assert _filters(ffmpeg) == [LIMITER]


def test_process_video_speed_fps_split(tmp_path, monkeypatch):
    """原 fps 进处理（字幕计时），新 fps 进写帧（输出帧率）。"""
    import cv2

    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    ffmpeg.probe_result = {
        "streams": [
            {"codec_type": "video", "width": 64, "height": 48, "r_frame_rate": "30/1"},
        ],
        "format": {"duration": "1.0"},
    }
    ffmpeg.probe_error = None
    config = _quiet_config(tmp_path)
    config.playback_speed = 1.05
    handler = VideoHandler(config)
    in_path = tmp_path / "in.mp4"
    in_path.write_bytes(b"fake-video")
    cv2.set_capture_frames(str(in_path), [_frame(0)])

    seen = {}
    orig_process_frames = VideoHandler._process_frames

    def spy_process_frames(self, gen, total, fps, h, w):
        seen["process_fps"] = fps
        return orig_process_frames(self, gen, total, fps, h, w)

    def spy_write_frames(self, gen, out, w, h, fps, audio):
        seen["write_fps"] = fps
        list(gen)  # 消费掉生成器

    monkeypatch.setattr(VideoHandler, "_process_frames", spy_process_frames)
    monkeypatch.setattr(VideoHandler, "_write_frames", spy_write_frames)
    handler.process_video(str(in_path), str(tmp_path / "out.mp4"))
    assert seen["process_fps"] == 30.0
    assert seen["write_fps"] == pytest.approx(31.5)


def test_process_video_default_speed_unchanged(tmp_path, monkeypatch):
    """速度 1.0 时，写帧仍用原帧率（不改变原有行为）。"""
    import cv2

    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    ffmpeg.probe_result = {
        "streams": [
            {"codec_type": "video", "width": 64, "height": 48, "r_frame_rate": "30/1"},
        ],
        "format": {"duration": "1.0"},
    }
    ffmpeg.probe_error = None
    handler = VideoHandler(_quiet_config(tmp_path))
    in_path = tmp_path / "in.mp4"
    in_path.write_bytes(b"fake-video")
    cv2.set_capture_frames(str(in_path), [_frame(0)])

    seen = {}

    def spy_write_frames(self, gen, out, w, h, fps, audio):
        seen["write_fps"] = fps
        list(gen)

    monkeypatch.setattr(VideoHandler, "_write_frames", spy_write_frames)
    handler.process_video(str(in_path), str(tmp_path / "out.mp4"))
    assert seen["write_fps"] == 30.0
