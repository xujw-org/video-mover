# -*- coding: utf-8 -*-
"""FFmpeg 工具（FFmpegHandler）：音视频流分离与视频属性读取。

拆分自 Dedup/dedup.py（第二批改进）。ffmpeg-python 在模块级用 try/except
导入，缺失时为 None；只有真正调用分离 / 探测方法时才会用到它。"""

from __future__ import annotations

import logging
from typing import Tuple

try:
    import ffmpeg
except ImportError:  # 未安装 ffmpeg-python 时为 None，调用方法时再报错
    ffmpeg = None  # type: ignore[assignment]


class FFmpegHandler:
    """
    FFmpeg 工具类，用于处理音视频流。
    """
    @staticmethod
    def split_av_streams(input_path: str) -> Tuple[ffmpeg.Stream, ffmpeg.Stream]:
        """
        分离输入视频的音频流和视频流。

        参数:
            input_path: 输入视频文件路径

        返回:
            Tuple[ffmpeg.Stream, ffmpeg.Stream]: 视频流和音频流（如果存在）
        """
        try:
            probe = ffmpeg.probe(input_path)
            video_stream = next((s for s in probe['streams'] if s['codec_type'] == 'video'), None)
            audio_stream = next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)
            if not video_stream:
                raise ValueError("未找到视频流")
            stream = ffmpeg.input(input_path)
            return stream.video, stream.audio if audio_stream else None
        except ffmpeg.Error as e:
            logging.error(f"分离音视频流失败: {e.stderr.decode()}")
            raise

    @staticmethod
    def get_video_properties(input_path: str) -> Tuple[int, int, float]:
        """
        获取视频的宽度、高度和帧率。

        参数:
            input_path: 输入视频文件路径

        返回:
            Tuple[int, int, float]: 宽度、高度和帧率
        """
        try:
            probe = ffmpeg.probe(input_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            return (int(video_info['width']), int(video_info['height']),
                    float(eval(video_info['r_frame_rate'])))
        except ffmpeg.Error as e:
            logging.error(f"获取视频属性失败: {e.stderr.decode()}")
            raise
