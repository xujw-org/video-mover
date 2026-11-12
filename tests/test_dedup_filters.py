# -*- coding: utf-8 -*-
"""VideoEffects：纯逻辑（颜色、水印位置）与带开关的帧特效。"""
from __future__ import annotations

import numpy as np
import pytest

from Dedup.config import VideoConfig
from Dedup.filters import VideoEffects
from tests.helpers import _passing_video_config


def test_parse_color_hex_and_names():
    assert VideoEffects.parse_color("#FF0000") == (0, 0, 255)  # 返回 BGR
    assert VideoEffects.parse_color("#00FF00") == (0, 255, 0)
    assert VideoEffects.parse_color("yellow") == (0, 255, 255)
    assert VideoEffects.parse_color("white") == (255, 255, 255)
    assert VideoEffects.parse_color("black") == (0, 0, 0)


def test_parse_color_unknown_defaults_to_white():
    assert VideoEffects.parse_color("no-such-color") == (255, 255, 255)


@pytest.mark.parametrize(
    "direction",
    ["left_to_right", "right_to_left", "top_to_bottom", "bottom_to_top",
     "lt_to_rb", "rt_to_lb", "lb_to_rt", "rb_to_lt"],
)
def test_watermark_position_directions_stay_inside(direction):
    # 100x80 的视频、10x5 的水印，起点 / 终点都要落在画面内。
    for frame_idx in (0, 50, 99):
        x, y = VideoEffects.get_watermark_position(direction, frame_idx, 100, 100, 80, 10, 5)
        assert 0 <= x <= 100 - 10
        assert 0 <= y <= 80 - 5


def test_watermark_position_random_stays_inside():
    for _ in range(20):
        x, y = VideoEffects.get_watermark_position("random", 0, 100, 200, 100, 10, 5)
        assert 20 <= x <= 200 - 10 - 20
        assert 20 <= y <= 100 - 5 - 20


def test_watermark_position_unknown_direction_is_centered():
    x, y = VideoEffects.get_watermark_position("nope", 0, 100, 100, 80, 10, 5)
    assert (x, y) == ((100 - 10) // 2, (80 - 5) // 2)


def _frame(value=100, shape=(48, 64, 3)):
    return np.full(shape, value, dtype=np.uint8)


def test_disabled_effects_return_frame_unchanged(tmp_path):
    config = _passing_video_config(tmp_path)
    # 下面几项默认就是开启的，先关掉再验证“关闭时原样返回”。
    config.enable_sbc = False
    config.enable_color_shift = False
    config.enable_blur_edge = False
    config.blur_background_enabled = False
    frame = _frame()
    assert np.array_equal(VideoEffects.rotate_frame(frame, config), frame)
    assert np.array_equal(VideoEffects.adjust_sbc(frame, config), frame)
    assert np.array_equal(VideoEffects.color_shift(frame, config), frame)
    assert np.array_equal(VideoEffects.blur_background(frame, config), frame)
    assert np.array_equal(VideoEffects.scramble_phase(frame, config), frame)
    assert np.array_equal(VideoEffects.add_texture_noise(frame, config), frame)
    assert np.array_equal(VideoEffects.apply_edge_blur(frame, config), frame)
    assert np.array_equal(VideoEffects.apply_gaussian_blur(frame, config, 3), frame)


def test_rotate_zero_angle_returns_same_frame(tmp_path):
    config = _passing_video_config(tmp_path)
    config.rotation_angle = 0
    frame = _frame()
    assert np.array_equal(VideoEffects.rotate_frame(frame, config), frame)


def test_fade_in_first_frame_is_black(tmp_path):
    config = _passing_video_config(tmp_path)
    config.fade_in_frames = 5
    config.fade_out_frames = 20
    frame = _frame(100)
    out = VideoEffects.apply_fade_effect(frame, config, 0, 100)
    assert out.max() == 0  # 第 0 帧 alpha=0，全黑


def test_fade_out_last_frame_is_almost_black(tmp_path):
    config = _passing_video_config(tmp_path)
    config.fade_in_frames = 5
    config.fade_out_frames = 20
    frame = _frame(100)
    out = VideoEffects.apply_fade_effect(frame, config, 99, 100)
    # alpha=(100-99)/20=0.05，亮度应为 100*0.05=5
    assert out.max() == 5


def test_fade_middle_frame_unchanged(tmp_path):
    config = _passing_video_config(tmp_path)
    config.fade_in_frames = 5
    config.fade_out_frames = 20
    frame = _frame(100)
    out = VideoEffects.apply_fade_effect(frame, config, 50, 100)
    assert np.array_equal(out, frame)


def test_color_shift_moves_blue_up_and_green_down(tmp_path):
    import random

    config = _passing_video_config(tmp_path)
    config.enable_color_shift = True
    config.color_shift_range = 3
    random.seed(7)
    frame = _frame(100)
    out = VideoEffects.color_shift(frame, config)
    assert out.shape == frame.shape and out.dtype == np.uint8
    assert out[0, 0, 2] == 100  # R 通道不动
    shift = int(out[0, 0, 0]) - 100
    assert -3 <= shift <= 3
    assert int(out[0, 0, 1]) == 100 - shift  # G 通道反向移动同样幅度


def test_gaussian_blur_applies_only_on_interval_frames(tmp_path):
    config = _passing_video_config(tmp_path)
    config.gaussian_blur_interval = 15
    frame = _frame(100)
    # 替身 cv2 的 GaussianBlur 是恒等函数，这里只验证“到步长才调用”这层逻辑：
    # 非步长帧必须原样返回，步长帧走模糊分支（仍返回同尺寸帧）。
    assert np.array_equal(VideoEffects.apply_gaussian_blur(frame, config, 3), frame)
    out = VideoEffects.apply_gaussian_blur(frame, config, 15)
    assert out.shape == frame.shape
