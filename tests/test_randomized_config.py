# -*- coding: utf-8 -*-
"""VideoConfig.randomized() / randomized_for()：每视频随机参数。

同一粒种子 → 同一套参数；不同种子 → 参数组合不同；取值全部落在
validate() 允许的范围内；randomized_for() 只按输入文件名派生种子。
"""
from __future__ import annotations

import os
import subprocess
import sys

from Dedup.config import VideoConfig
from tests.helpers import REPO_ROOT, _passing_video_config

# randomized() 会改写的全部字段：同一种子下这些字段必须逐一相同。
RANDOMIZED_FIELDS = [
    "rotation_angle",
    "crop_percentage",
    "saturation",
    "brightness",
    "contrast",
    "frame_swap_interval",
    "gaussian_blur_interval",
    "gaussian_blur_kernel_size",
    "gaussian_blur_area_percentage",
    "watermark_opacity",
    "background_music_volume",
    "flip_horizontal",
    "fade_in_frames",
    "fade_out_frames",
    "color_shift_range",
    "enable_texture_noise",
    "texture_noise_strength",
    "scramble_frequency",
    "hzh_opacity",
    "hzh_scale",
    "top_blur_percentage",
    "bottom_blur_percentage",
    "side_blur_percentage",
    # 第 2 步：播放速度、色相、缩放；第 3 步：主音频音量、音调。
    "playback_speed",
    "hue_shift",
    "zoom_factor",
    "audio_volume",
    "pitch_shift",
]


def _params(config):
    return tuple(sorted(
        (name, getattr(config, name)) for name in RANDOMIZED_FIELDS
    ))


def test_same_seed_same_params():
    assert _params(VideoConfig.randomized(42)) == _params(VideoConfig.randomized(42))


def test_different_seeds_differ():
    seen = {_params(VideoConfig.randomized(seed)) for seed in range(20)}
    # 20 粒种子不可能撞成同一套参数；顺带说明随机化真的在起作用。
    assert len(seen) > 1
    rotations = {VideoConfig.randomized(seed).rotation_angle for seed in range(20)}
    assert len(rotations) > 1


def test_randomized_for_uses_basename_only():
    a = VideoConfig.randomized_for("/some/dir/video_a.mp4")
    b = VideoConfig.randomized_for("/other/dir/video_a.mp4")
    assert _params(a) == _params(b)
    assert a.random_seed == b.random_seed
    c = VideoConfig.randomized_for("/some/dir/video_b.mp4")
    assert _params(a) != _params(c)


def test_randomized_values_stay_in_valid_ranges():
    for seed in range(50):
        config = VideoConfig.randomized(seed)
        assert -6 <= config.rotation_angle <= 6
        assert 0 <= config.crop_percentage <= 0.5
        assert config.saturation >= 0
        assert -1 <= config.brightness <= 1
        assert config.contrast >= 0
        assert config.frame_swap_interval >= 1
        assert config.gaussian_blur_interval >= 0
        assert config.gaussian_blur_kernel_size % 2 == 1
        assert 0 <= config.gaussian_blur_area_percentage <= 100
        assert 0 <= config.watermark_opacity <= 1
        assert 0 <= config.background_music_volume <= 1
        assert 0 <= config.scramble_frequency <= 1
        assert 0 <= config.texture_noise_strength <= 1
        assert 0 < config.hzh_scale <= 1
        assert 0 <= config.hzh_opacity <= 1
        assert 0 <= config.top_blur_percentage <= 100
        assert 0 <= config.bottom_blur_percentage <= 100
        assert 0 <= config.side_blur_percentage <= 100
        assert 0.95 <= config.playback_speed <= 1.05
        assert -10 <= config.hue_shift <= 10
        assert 1.02 <= config.zoom_factor <= 1.08
        assert 0.90 <= config.audio_volume <= 1.10
        assert 0.98 <= config.pitch_shift <= 1.02


def test_randomized_params_pass_validate(tmp_path):
    # 在一份能通过校验的配置上套用随机参数，validate() 仍应通过。
    base = _passing_video_config(tmp_path)
    for seed in (0, 1, 42):
        randomized = VideoConfig.randomized(seed)
        for name in RANDOMIZED_FIELDS:
            setattr(base, name, getattr(randomized, name))
        base.validate()


def test_defaults_are_unchanged():
    config = VideoConfig()
    assert config.random_seed is None
    assert config.rotation_angle == -6
    assert config.crop_percentage == 0.1
    assert config.saturation == 1.05
    assert config.frame_swap_interval == 15
    assert config.flip_horizontal is False
    assert config.scramble_frequency == 0.0
    assert config.enable_texture_noise is False
    assert config.playback_speed == 1.0
    assert config.hue_shift == 0
    assert config.zoom_factor == 1.0
    assert config.audio_volume == 1.0
    assert config.pitch_shift == 1.0


def test_cli_help_lists_seed_flags():
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "Dedup/dedup.py", "--help"], cwd=str(REPO_ROOT),
        capture_output=True, text=True, timeout=60,
        encoding="utf-8", errors="replace", env=env,
    )
    assert proc.returncode == 0
    assert "--seed" in proc.stdout
    assert "--no-randomize" in proc.stdout
