# -*- coding: utf-8 -*-
"""音频处理（AudioHandler）：静音去除与背景音乐混合。

拆分为 Dedup/audio.py（第二批改进）。静音去除用 pydub；**背景音乐混音已改成直接跑
ffmpeg**，因为 pydub 混音会先把原音转成 BGM 的采样率，而它底下的
audioop.ratecv 是线性插值重采样，实测会把 1kHz 正弦的满量程峰值外的杂散从
-93dB 抬到 -65dB（听感就是“滋滋”的噪音）。ffmpeg 的 swr/soxr 能做到 -94dB 左右。
"""

from __future__ import annotations

import logging
import math
import os
import subprocess
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

try:  # 既支持作为包导入，也支持 Dedup/dedup.py 的回退路径（顶层模块）
    from .workspace import temp_wav
except ImportError:
    from workspace import temp_wav


def _ffmpeg_exe() -> str:
    """取 ffmpeg 可执行文件（与本项目其它地方一致：靠 PATH）。"""
    return os.environ.get("FFMPEG_BIN") or "ffmpeg"


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
            # 拼掉静音后音频会变短，但视频并没有同步剪，长度不一致会音画错位；
            # 而且最后混流用 -shortest，视频会被音频截短。用静音补齐回原长度。
            target_ms = len(audio)
            if len(processed_audio) < target_ms:
                shorten = target_ms - len(processed_audio)
                processed_audio += AudioSegment.silent(duration=shorten)
                logging.info(
                    f"静音处理把音频剪短了 {shorten}ms，已用静音补回，保持音画同步"
                )
            output_path = temp_wav()
            processed_audio.export(output_path, format='wav')
            logging.info(f"静音处理完成，输出到 {output_path}")
            return output_path
        except Exception as e:
            logging.error(f"静音处理失败: {str(e)}")
            raise

    @staticmethod
    def mix_bgm(original_audio_path: str, bgm_path: str, background_music_volume: float = 0.5) -> str:
        """把原始音频和背景音乐混在一起（用 ffmpeg，不用 pydub）。

        为什么不用 pydub：`AudioSegment.overlay` 需要两段采样率一致，于是先把
        原音转成 BGM 的 48k（44.1k 素材），用的 audioop.ratecv 是线性插值重采样，
        实测会把 1kHz 正弦的杂散从 -93dB 抬到 -65dB —— 听感上就是一层“滋滋”声。
        这里用 ffmpeg 的滤镜图：BGM 先按分贝衰减再 `amix`（`normalize=0`，否则
        ffmpeg 默认会把两路都按输入数减半，原声莫名变小），时长跟原音走。

        参数:
            original_audio_path: 原始音频文件路径
            bgm_path: 背景音乐文件路径
            background_music_volume: 背景音乐音量，0-1（0 视为静音）

        返回:
            str: 混合后的音频文件路径；BGM 无效时原样返回原路径
        """
        if not bgm_path or not os.path.exists(bgm_path):
            logging.warning("背景音乐路径无效，返回原始音频")
            return original_audio_path
        try:
            if background_music_volume > 0:
                gain_db = 20 * math.log10(background_music_volume)
            else:
                gain_db = -60.0  # 0 时分贝对数无定义，用 -60dB 当静音
            mixed_path = temp_wav()
            filter_graph = (
                f"[1:a]volume={gain_db:.2f}dB[bgm];"
                "[0:a][bgm]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mix]"
            )
            cmd = [
                _ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                "-i", original_audio_path,
                "-stream_loop", "-1", "-i", bgm_path,
                "-filter_complex", filter_graph,
                # 中间结果用浮点 wav：原声已经 0dBFS，叠加 BGM 会短暂超过满量程，
                # 用整型写盘就会被削顶（硬切）→ 听感是“糊/毛刺”。浮点不削顶，
                # 交给最后的 alimiter 统一压回 -1dBFS。
                "-map", "[mix]", "-c:a", "pcm_f32le",
                mixed_path,
            ]
            completed = subprocess.run(cmd, capture_output=True, text=True)
            if completed.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg 混音失败（返回码 {completed.returncode}）: "
                    f"{(completed.stderr or '').strip()[:500]}"
                )
            logging.info(
                f"背景音乐混合完成（BGM 增益 {gain_db:.1f}dB，ffmpeg amix），输出到 {mixed_path}"
            )
            return mixed_path
        except Exception as e:
            logging.error(f"背景音乐混合失败: {str(e)}")
            raise
