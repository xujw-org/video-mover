# -*- coding: utf-8 -*-
"""Dedup：视频去重处理包。

第二批改进（2026-11-12）由单文件 Dedup/dedup.py（1312 行）拆分而来，
各模块职责与新旧映射见 Dedup/README.md。

包导入本身不要求安装 cv2 / ffmpeg / whisper 等重依赖（它们在各模块里
是 try/except 导入，缺失时为 None），只有真正处理视频时才需要。
"""

from __future__ import annotations

from .audio import AudioHandler
from .config import VideoConfig
from .ffmpeg_utils import FFmpegHandler
from .filters import VideoEffects
from .pipeline import VideoHandler
from .subtitles import SubtitleHandler

__all__ = [
    "VideoConfig",
    "FFmpegHandler",
    "AudioHandler",
    "SubtitleHandler",
    "VideoEffects",
    "VideoHandler",
]
