# -*- coding: utf-8 -*-
"""VideoConfig：默认值、校验与颜色检查。"""
from __future__ import annotations

import pytest

from Dedup.config import VideoConfig
from tests.helpers import _passing_video_config


def test_defaults():
    config = VideoConfig()
    assert config.include_subtitles is False
    assert config.use_whisper is True
    assert config.whisper_model_name == "base"
    # 默认不加 BGM：自带 assets/bgm.mp3 是 220/440Hz 合成嗡鸣，听感像噪音
    assert config.include_background_music is False
    assert config.background_music_volume == 0.1
    assert config.crop_percentage == 0.1
    assert config.enable_frame_swap is True
    assert config.frame_swap_interval == 15
    assert config.scramble_frequency == 0.0
    assert config.enable_texture_noise is False


def test_validate_passes_with_existing_files(tmp_path):
    config = _passing_video_config(tmp_path)
    config.validate()  # 不抛异常即通过


def test_validate_rejects_bad_opacity(tmp_path):
    config = _passing_video_config(tmp_path)
    config.subtitles_opacity = 1.5
    with pytest.raises(ValueError, match="subtitles_opacity"):
        config.validate()


def test_validate_rejects_bad_crop(tmp_path):
    config = _passing_video_config(tmp_path)
    config.crop_percentage = 0.6
    with pytest.raises(ValueError, match="crop_percentage"):
        config.validate()


def test_validate_rejects_even_blur_kernel(tmp_path):
    config = _passing_video_config(tmp_path)
    config.gaussian_blur_kernel_size = 4
    with pytest.raises(ValueError, match="gaussian_blur_kernel_size"):
        config.validate()


def test_validate_rejects_bad_color(tmp_path):
    config = _passing_video_config(tmp_path)
    config.subtitles_color = "not-a-color"
    with pytest.raises(ValueError, match="subtitles_color"):
        config.validate()


def test_validate_rejects_missing_bgm_file(tmp_path):
    config = _passing_video_config(tmp_path)
    config.background_music_file = str(tmp_path / "no-such-bgm.mp3")
    with pytest.raises(FileNotFoundError, match="背景音乐文件"):
        config.validate()


def test_validate_rejects_bad_watermark_type(tmp_path):
    config = _passing_video_config(tmp_path)
    config.watermark_type = "sparkles"
    with pytest.raises(ValueError, match="watermark_type"):
        config.validate()


def test_validate_rejects_bad_frame_swap_interval(tmp_path):
    config = _passing_video_config(tmp_path)
    config.frame_swap_interval = 0
    with pytest.raises(ValueError, match="frame_swap_interval"):
        config.validate()


def test_is_valid_color():
    assert VideoConfig.is_valid_color("yellow") is True
    assert VideoConfig.is_valid_color("Yellow") is True
    assert VideoConfig.is_valid_color("#FF0000") is True
    assert VideoConfig.is_valid_color("#ff0000") is True
    assert VideoConfig.is_valid_color("not-a-color") is False
    assert VideoConfig.is_valid_color("#GGGGGG") is False
    assert VideoConfig.is_valid_color("#FFF") is False


def test_bgm_can_be_enabled_with_a_custom_track(tmp_path, monkeypatch):
    """--bgm 指定自己的音乐时应当自动开启 BGM 混音。"""
    import Dedup.dedup as shim
    from tests.helpers import REPO_ROOT

    # 配置里的字体/水印等是相对路径（相对 Dedup/），validate 会检查它们存在
    monkeypatch.chdir(REPO_ROOT / "Dedup")
    bgm = tmp_path / "my-music.mp3"
    bgm.write_bytes(b"x")
    video = tmp_path / "in.mp4"
    video.write_bytes(b"x")
    out = tmp_path / "out.mp4"

    configs = []
    fake_handler = type("H", (), {"__init__": lambda self, cfg: configs.append(cfg),
                                  "process_video": lambda self, i, o: None})
    # 用 monkeypatch 打补丁，别直接改模块属性（会影响别的测试）
    monkeypatch.setattr(shim, "VideoHandler", fake_handler)
    shim.main(["-i", str(video), "-o", str(out), "--bgm", str(bgm), "--bgm-volume", "0.2"])

    assert len(configs) == 1
    assert configs[0].include_background_music is True
    assert configs[0].background_music_file == str(bgm)
    assert configs[0].background_music_volume == 0.2
