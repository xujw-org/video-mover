# -*- coding: utf-8 -*-
"""VideoEffects：纯逻辑（颜色、水印位置）与带开关的帧特效。"""
from __future__ import annotations

import threading

import numpy as np
import pytest

from Dedup.config import VideoConfig
from Dedup.filters import FADE_IN_FLOOR, VideoEffects
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
     "lt_to_rb", "rt_to_lb", "lb_to_rt", "rb_to_lt",
     "top_left", "top_right", "bottom_left", "bottom_right"],
)
def test_watermark_position_directions_stay_inside(direction):
    # 100x80 的视频、10x5 的水印，起点 / 终点都要落在画面内。
    for frame_idx in (0, 50, 99):
        x, y = VideoEffects.get_watermark_position(direction, frame_idx, 100, 100, 80, 10, 5)
        assert 0 <= x <= 100 - 10
        assert 0 <= y <= 80 - 5


def test_watermark_bottom_left_is_fixed_corner():
    # 720x1280 画面、144x144 水印：边距 = 短边 3% ≈ 21px，整片不动。
    for frame_idx in (0, 150, 299):
        x, y = VideoEffects.get_watermark_position(
            "bottom_left", frame_idx, 300, 720, 1280, 144, 144)
        assert (x, y) == (21, 1280 - 144 - 21)


def test_watermark_position_random_stays_inside():
    for _ in range(20):
        x, y = VideoEffects.get_watermark_position("random", 0, 100, 200, 100, 10, 5)
        assert 20 <= x <= 200 - 10 - 20
        assert 20 <= y <= 100 - 5 - 20


def test_watermark_position_unknown_direction_is_centered():
    x, y = VideoEffects.get_watermark_position("nope", 0, 100, 100, 80, 10, 5)
    assert (x, y) == ((100 - 10) // 2, (80 - 5) // 2)


def test_random_watermark_position_is_fixed_per_video(tmp_path, monkeypatch):
    """direction='random' 时坐标整片只抽一次，不能每帧乱跳。"""
    from types import SimpleNamespace

    from PIL import Image

    config = _passing_video_config(tmp_path)
    config.watermark_type = 'image'
    config.watermark_direction = 'random'
    wm = Image.new('RGBA', (10, 5), (255, 255, 255, 255))
    handler = SimpleNamespace(
        watermark_img=wm,
        wm_rgb=np.full((5, 10, 3), 200, np.uint8),
        wm_alpha=np.full((5, 10), 0.1, np.float32),
        wm_random_pos=None,
        wm_lock=threading.Lock(),
    )
    calls = []

    def fake_pos(*args):
        calls.append(args)
        return (10, 10)

    monkeypatch.setattr(VideoEffects, "get_watermark_position",
                        staticmethod(fake_pos))
    frame = np.full((48, 64, 3), 100, np.uint8)
    VideoEffects.add_watermark(frame, config, 0, 100, handler)
    VideoEffects.add_watermark(frame, config, 1, 100, handler)
    assert handler.wm_random_pos == (10, 10)
    assert len(calls) == 1  # 第二帧直接复用缓存


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
    assert np.array_equal(VideoEffects.adjust_sbc(frame, config), frame)
    assert np.array_equal(VideoEffects.color_shift(frame, config), frame)
    assert np.array_equal(VideoEffects.blur_background(frame, config), frame)
    assert np.array_equal(VideoEffects.scramble_phase(frame, config), frame)
    assert np.array_equal(VideoEffects.add_texture_noise(frame, config), frame)
    assert np.array_equal(VideoEffects.apply_edge_blur(frame, config), frame)
    assert np.array_equal(VideoEffects.apply_gaussian_blur(frame, config, 3), frame)


def test_apply_geometry_identity_returns_same_frame(tmp_path):
    """旋转为 0、不裁剪、zoom=1、输出尺寸不变时不做重采样（免一次插值）。"""
    config = _passing_video_config(tmp_path)
    config.rotation_angle = 0
    config.crop_percentage = 0.0
    config.zoom_factor = 1.0
    frame = _frame()
    assert np.array_equal(
        VideoEffects.apply_geometry(frame, config, 64, 48), frame)


def test_fade_in_first_frame_not_black(tmp_path):
    """首帧不能压成纯黑：平台默认截第 0 帧当封面，纯黑就是黑缩略图。"""
    config = _passing_video_config(tmp_path)
    config.fade_in_frames = 5
    config.fade_out_frames = 20
    frame = _frame(100)
    out = VideoEffects.apply_fade_effect(frame, config, 0, 100)
    assert out.min() > 0
    assert out.max() == round(100 * FADE_IN_FLOOR)


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


def test_color_shift_uses_fixed_per_video_value(tmp_path):
    """色偏整片固定：每帧重新随机会造成颜色闪烁（编码后就是噪点）。"""
    config = _passing_video_config(tmp_path)
    config.enable_color_shift = True
    config.color_shift_range = 3
    config.color_shift_value = 2
    frame = _frame(100)
    out = VideoEffects.color_shift(frame, config)
    assert out.shape == frame.shape and out.dtype == np.uint8
    assert int(out[0, 0, 0]) == 102  # B +2
    assert int(out[0, 0, 1]) == 98   # G -2
    assert int(out[0, 0, 2]) == 100  # R 通道不动
    # 同一配置重复调用结果一致（不再依赖全局 random 流）。
    assert np.array_equal(VideoEffects.color_shift(frame, config), out)


def test_hue_shift_zero_returns_same_frame(tmp_path):
    config = _passing_video_config(tmp_path)
    config.hue_shift = 0
    frame = _frame()
    assert np.array_equal(VideoEffects.apply_hue_shift(frame, config), frame)


def test_hue_shift_moves_hue_channel(tmp_path):
    config = _passing_video_config(tmp_path)
    config.hue_shift = 10
    frame = _frame(100)
    out = VideoEffects.apply_hue_shift(frame, config)
    assert out.shape == frame.shape and out.dtype == np.uint8
    # 替身 cv2 的 HSV 转换是恒等函数，H 通道就是第 0 通道：
    # 10° 对应 OpenCV 的 5 个单位，100 -> 105，其余通道不动。
    assert int(out[0, 0, 0]) == 105
    assert int(out[0, 0, 1]) == 100


def test_gaussian_blur_applies_only_on_interval_frames(tmp_path):
    config = _passing_video_config(tmp_path)
    config.gaussian_blur_interval = 15
    frame = _frame(100)
    # 替身 cv2 的 GaussianBlur 是恒等函数，这里只验证“到步长才调用”这层逻辑：
    # 非步长帧必须原样返回，步长帧走模糊分支（仍返回同尺寸帧）。
    assert np.array_equal(VideoEffects.apply_gaussian_blur(frame, config, 3), frame)
    out = VideoEffects.apply_gaussian_blur(frame, config, 15)
    assert out.shape == frame.shape


def test_scramble_phase_downscales_fft_for_large_frames(monkeypatch):
    """4K 帧必须走“缩小再 FFT”的快路径：全尺寸 FFT 每帧 5 秒多。"""
    from Dedup.filters import VideoEffects

    seen = []
    original = VideoEffects._scramble_fft

    def spy(frame, frequency):
        seen.append(frame.shape)
        return original(frame, frequency)

    monkeypatch.setattr(VideoEffects, "_scramble_fft", staticmethod(spy))

    cfg = VideoConfig()
    cfg.scramble_frequency = 0.09
    big = np.random.randint(0, 255, (1080, 1920, 3), dtype=np.uint8)
    out = VideoEffects.scramble_phase(big, cfg)

    assert out.shape == big.shape
    assert seen, "_scramble_fft 没被调用"
    assert max(seen[0][:2]) <= VideoEffects._SCRAMBLE_MAX_SIDE

    # 小图仍然走全尺寸，效果保持原样
    seen.clear()
    small = np.random.randint(0, 255, (240, 180, 3), dtype=np.uint8)
    VideoEffects.scramble_phase(small, cfg)
    assert seen and seen[0][:2] == small.shape[:2]
