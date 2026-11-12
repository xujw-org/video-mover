# -*- coding: utf-8 -*-
"""字幕处理（SubtitleHandler）：Whisper 生成字幕与 SRT 时间格式。

拆分自 Dedup/dedup.py（第二批改进）。whisper / opencc 在模块级用
try/except 导入，缺失时为 None；只有真正生成字幕时才会用到它们。"""

from __future__ import annotations

import logging
import tempfile

try:
    import opencc
except ImportError:  # 未安装 opencc 时为 None，生成字幕时再报错
    opencc = None  # type: ignore[assignment]

try:
    import whisper
except ImportError:  # 未安装 openai-whisper 时为 None，生成字幕时再报错
    whisper = None  # type: ignore[assignment]


class SubtitleHandler:
    """字幕处理类，用于生成和添加字幕"""
    
    @staticmethod
    def generate_subtitles(input_path: str, model_name: str = 'base') -> str:
        """使用 Whisper 生成字幕文件，并将繁体中文转换为简体中文"""
        try:
            import warnings
            # 抑制 FP16 警告
            warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead")
            model = whisper.load_model(model_name)
            result = model.transcribe(input_path)
            srt_path = tempfile.NamedTemporaryFile(suffix='.srt', delete=False).name
            converter = opencc.OpenCC('t2s')  # 繁体转简体
            with open(srt_path, 'w', encoding='utf-8') as f:
                for i, segment in enumerate(result['segments']):
                    start = segment['start']
                    end = segment['end']
                    text = converter.convert(segment['text'].strip())  # 转换为简体中文
                    f.write(f"{i+1}\n")
                    f.write(f"{SubtitleHandler.format_time(start)} --> {SubtitleHandler.format_time(end)}\n")
                    f.write(f"{text}\n\n")
            logging.debug(f"字幕文件生成: {srt_path}")
            return srt_path
        except Exception as e:
            logging.error(f"字幕生成失败: {str(e)}")
            raise

    @staticmethod
    def format_time(seconds: float) -> str:
        """将秒数格式化为 SRT 时间格式"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours:02d}:{minutes:02d}:{secs:06.3f}".replace('.', ',')
