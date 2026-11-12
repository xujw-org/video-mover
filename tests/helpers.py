# -*- coding: utf-8 -*-
"""测试共享辅助（无副作用）：仓库根目录与“能通过校验”的 VideoConfig。

注意：不要把这些辅助放进 tests/conftest.py——pytest 会把 conftest
以顶层模块名 `conftest` 导入一次，而测试文件里 `from tests.conftest
import ...` 又会以 `tests.conftest` 的名字再导入一次，同一份代码跑两遍，
替身模块的状态会被复制两份、互相覆盖。辅助放这里只被 `tests.helpers`
一个名字导入，不存在这个问题。
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _passing_video_config(tmp_path):
    """返回一个能通过 VideoConfig.validate() 的配置。

    注意原版 validate() 有个偏严的设定：font_file / background_music_file /
    subtitles_file 无论对应开关开没开都会校验存在，所以这里都指向真实存在的文件。
    """
    from Dedup.config import VideoConfig

    bgm = tmp_path / "bgm.mp3"
    bgm.write_bytes(b"fake-bgm")
    font = tmp_path / "font.ttf"
    font.write_bytes(b"fake-font")
    config = VideoConfig()
    config.watermark_type = "text"  # 不校验图片水印文件
    config.custom_font_enabled = False
    config.font_file = str(font)
    config.include_background_music = False
    config.background_music_file = str(bgm)
    config.subtitles_file = str(REPO_ROOT / "Dedup" / "assets" / "subtitles.srt")
    config.include_hzh = False
    config.include_subtitles = False
    config.include_titles = False
    config.include_watermark = False
    config.enable_silence_check = False
    return config
