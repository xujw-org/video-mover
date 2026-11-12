# -*- coding: utf-8 -*-
"""VideoHandler：帧生成 / 分批 / 单帧处理链顺序 / 帧交换 / 写帧。

全部用替身跑：假 cv2（numpy 实现）、假 ffmpeg（只记录调用）、
合成小帧，不碰真实视频、GPU 与网络。
"""
from __future__ import annotations

import sys

import numpy as np
import pytest

from Dedup.config import VideoConfig
from Dedup.filters import VideoEffects
from Dedup.pipeline import VideoHandler
from tests.helpers import REPO_ROOT, _passing_video_config


def _frame(value, shape=(48, 64, 3)):
    return np.full(shape, value, dtype=np.uint8)


class _FakeCap:
    """_frame_generator 用的假 VideoCapture。"""

    def __init__(self, frames):
        self._frames = list(frames)
        self._idx = 0

    def isOpened(self):
        return True

    def read(self):
        if self._idx >= len(self._frames):
            return False, None
        frame = self._frames[self._idx]
        self._idx += 1
        return True, frame


def _quiet_config(tmp_path):
    """全部特效关掉、只留流程本身的配置（单帧应原样返回）。"""
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


def test_process_video_missing_input_raises(tmp_path):
    handler = VideoHandler(_quiet_config(tmp_path))
    with pytest.raises(FileNotFoundError, match="不存在"):
        handler.process_video(str(tmp_path / "no-such.mp4"), str(tmp_path / "out.mp4"))


def test_frame_generator_yields_indexed_frames(tmp_path):
    handler = VideoHandler(_passing_video_config(tmp_path))
    frames = [_frame(0), _frame(1), _frame(2)]
    out = list(handler._frame_generator(_FakeCap(frames)))
    assert [idx for idx, _ in out] == [0, 1, 2]
    assert all(np.array_equal(f, _frame(i)) for i, (_, f) in enumerate(out))


def test_process_batch_sorts_by_frame_index(tmp_path, monkeypatch):
    handler = VideoHandler(_quiet_config(tmp_path))
    monkeypatch.setattr(
        VideoHandler, "_process_single_frame",
        lambda self, frame, idx, config, fps, total, h, w: (idx, frame),
    )
    batch = [(2, _frame(2)), (0, _frame(0)), (1, _frame(1))]
    result = handler._process_batch(batch, 3, 30.0, 48, 64)
    assert [idx for idx, _ in result] == [0, 1, 2]


def test_single_frame_chain_order_all_enabled(tmp_path, monkeypatch):
    """处理链顺序是行为的一部分：记录每个特效的调用顺序并断言。"""
    config = _quiet_config(tmp_path)
    config.include_watermark = True
    config.include_subtitles = True
    config.include_titles = True
    config.include_hzh = True
    hzh = tmp_path / "hzh.mp4"
    hzh.write_bytes(b"fake-hzh")
    config.hzh_video_file = str(hzh)  # include_hzh 开启时 validate() 要求文件存在
    config.enable_color_shift = True
    config.blur_background_enabled = True
    config.scramble_frequency = 0.5
    config.enable_texture_noise = True
    config.enable_blur_edge = True
    config.gaussian_blur_interval = 5
    config.fade_in_frames = 5
    config.fade_out_frames = 20
    handler = VideoHandler(config)
    handler.subs = [object()]  # 有字幕对象才会调 add_subtitles

    calls = []

    def recorder(name):
        def _fake(*args, **kwargs):
            calls.append(name)
            return args[0]
        return _fake

    for name in ("rotate_frame", "adjust_sbc", "add_watermark", "add_subtitles",
                 "add_titles", "add_hzh_effect", "color_shift", "blur_background",
                 "scramble_phase", "add_texture_noise", "apply_edge_blur",
                 "apply_gaussian_blur", "apply_fade_effect"):
        monkeypatch.setattr(VideoEffects, name, staticmethod(recorder(name)))

    handler._process_single_frame(_frame(100), 10, config, 30.0, 100, 48, 64)
    assert calls == [
        "rotate_frame", "adjust_sbc", "add_watermark", "add_subtitles", "add_titles",
        "add_hzh_effect", "color_shift", "blur_background", "scramble_phase",
        "add_texture_noise", "apply_edge_blur", "apply_gaussian_blur", "apply_fade_effect",
    ]


def test_single_frame_chain_order_all_disabled(tmp_path, monkeypatch):
    config = _quiet_config(tmp_path)
    handler = VideoHandler(config)
    calls = []

    def recorder(name):
        def _fake(*args, **kwargs):
            calls.append(name)
            return args[0]
        return _fake

    for name in ("rotate_frame", "adjust_sbc", "add_watermark", "add_subtitles",
                 "add_titles", "add_hzh_effect", "color_shift", "blur_background",
                 "scramble_phase", "add_texture_noise", "apply_edge_blur",
                 "apply_gaussian_blur", "apply_fade_effect"):
        monkeypatch.setattr(VideoEffects, name, staticmethod(recorder(name)))

    handler._process_single_frame(_frame(100), 10, config, 30.0, 100, 48, 64)
    # 全部开关关闭时，只剩无条件执行的 10 步。
    assert calls == [
        "rotate_frame", "adjust_sbc", "add_hzh_effect", "color_shift", "blur_background",
        "scramble_phase", "add_texture_noise", "apply_edge_blur",
        "apply_gaussian_blur", "apply_fade_effect",
    ]


def test_single_frame_quiet_config_returns_same_pixels(tmp_path):
    config = _quiet_config(tmp_path)
    handler = VideoHandler(config)
    frame = _frame(100)
    _, out = handler._process_single_frame(frame, 10, config, 30.0, 100, 48, 64)
    assert out.shape == frame.shape
    assert np.array_equal(out, frame)


def test_write_frames_uses_libx264_aac(tmp_path, monkeypatch):
    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    ffmpeg.processes.clear()
    handler = VideoHandler(_quiet_config(tmp_path))
    frames = iter([_frame(1), _frame(2)])
    handler._write_frames(frames, str(tmp_path / "out.mp4"), 64, 48, 30.0, None)
    proc = ffmpeg.processes[-1]
    assert proc.waited is True
    assert len(proc.stdin.getvalue()) == 2 * 48 * 64 * 3
    outputs = [c for c in ffmpeg.calls if c[0] == "output"]
    assert outputs, "应调用过 ffmpeg output"
    kwargs = outputs[-1][2]
    assert kwargs.get("vcodec") == "libx264"
    assert kwargs.get("acodec") == "aac"
    assert kwargs.get("preset") == "fast"
    assert kwargs.get("crf") == 23


def _end_to_end(tmp_path, *, frame_swap):
    """用替身跑通整条 process_video：帧交换开 / 关两种顺序都要对。"""
    import cv2

    ffmpeg = sys.modules["ffmpeg"]
    ffmpeg.calls.clear()
    ffmpeg.processes.clear()
    ffmpeg.probe_result = {
        "streams": [
            {"codec_type": "video", "width": 64, "height": 48, "r_frame_rate": "30/1"},
        ],
        "format": {"duration": "1.0"},
    }
    ffmpeg.probe_error = None
    config = _quiet_config(tmp_path)
    config.enable_frame_swap = frame_swap
    config.frame_swap_interval = 15
    handler = VideoHandler(config)
    in_path = tmp_path / "in.mp4"
    in_path.write_bytes(b"fake-video")
    cv2.set_capture_frames(str(in_path), [_frame(0), _frame(1), _frame(2)])
    handler.process_video(str(in_path), str(tmp_path / "out.mp4"))
    proc = ffmpeg.processes[-1]
    assert proc.waited is True
    raw = proc.stdin.getvalue()
    frame_bytes = 48 * 64 * 3
    assert len(raw) == 3 * frame_bytes
    values = [raw[i * frame_bytes] for i in range(3)]
    return values


def test_process_video_end_to_end_frame_swap_on(tmp_path):
    # interval=15、共 3 帧时 get_original_idx 会把前两帧交换：[1, 0, 2]。
    assert _end_to_end(tmp_path, frame_swap=True) == [1, 0, 2]


def test_process_video_end_to_end_frame_swap_off(tmp_path):
    assert _end_to_end(tmp_path, frame_swap=False) == [0, 1, 2]
