# -*- coding: utf-8 -*-
"""音频处理（AudioHandler）：静音去除与背景音乐混合。

拆分自 Dedup/dedup.py（第二批改进）。pydub 在模块级用 try/except 导入，
缺失时为 None；只有真正处理音频时才会用到它。"""

from __future__ import annotations

import logging
import math
import os
import tempfile
from typing import TYPE_CHECKING

try:
    from pydub import AudioSegment
    from pydub.silence import split_on_silence
except ImportError:  # 未安装 pydub 时为 None，调用方法时再报错
    AudioSegment = None  # type: ignore[assignment]
    split_on_silence = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from .config import VideoConfig


class AudioHandler:
    """
    音频处理类，用于静音去除和背景音乐混合。
    """
    @staticmethod
    def remove_silence(audio_path: str, config: VideoConfig) -> str:
        """
        删除音频中的静音部分，保留所有非静音内容。

        参数:
            audio_path: 输入音频文件路径
            config: 视频处理配置对象

        返回:
            str: 处理后的音频文件路径
        """
        if not config.enable_silence_check:
            return audio_path

        try:
            audio = AudioSegment.from_file(audio_path)
            chunks = split_on_silence(audio, min_silence_len=config.silent_duration,
                                      silence_thresh=config.silence_threshold)
            if not chunks:
                logging.warning("未检测到非静音片段，返回原始音频")
                return audio_path
            processed_audio = AudioSegment.silent(duration=0)  # 初始化空音频
            for chunk in chunks:
                processed_audio += chunk  # 直接拼接所有非静音片段
                if config.silence_retention_ratio > 0:  # 可选：在片段间添加少量静音
                    silence_duration = int(config.silent_duration * config.silence_retention_ratio)
                    processed_audio += AudioSegment.silent(duration=silence_duration)
            output_path = tempfile.mktemp(suffix='.wav')
            processed_audio.export(output_path, format='wav')
            logging.info(f"静音处理完成，输出到 {output_path}")
            return output_path
        except Exception as e:
            logging.error(f"静音处理失败: {str(e)}")
            raise

    @staticmethod
    def mix_bgm(original_audio_path: str, bgm_path: str, background_music_volume: float = 0.5) -> str:
        """
        将原始音频与背景音乐混合，支持音量调节。
        参数:
            original_audio_path: 原始音频文件路径
            bgm_path: 背景音乐文件路径
            background_music_volume: 背景音乐音量，范围0-1
        返回:
            str: 混合后的音频文件路径
        """
        if not bgm_path or not os.path.exists(bgm_path):
            logging.warning("背景音乐路径无效，返回原始音频")
            return original_audio_path
        try:
            original = AudioSegment.from_file(original_audio_path)
            bgm = AudioSegment.from_file(bgm_path)
            # 调整BGM音量：转换为分贝调整，0时静音，1时保持原音量
            bgm = bgm + 20 * math.log10(background_music_volume) if background_music_volume > 0 else bgm - 60  # -60dB接近静音
            mixed = original.overlay(bgm, loop=True)
            mixed_path = tempfile.mktemp(suffix='.wav')
            mixed.export(mixed_path, format='wav')
            logging.info(f"背景音乐混合完成，输出到 {mixed_path}")
            return mixed_path
        except Exception as e:
            logging.error(f"背景音乐混合失败: {str(e)}")
            raise
