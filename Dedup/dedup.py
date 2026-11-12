#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""向后兼容垫片：Dedup/dedup.py 已拆分（第二批改进，2026-11-12）。

原 1312 行单文件已拆为 Dedup 包内的模块（映射表见 Dedup/README.md），
本文件只做两件事：

1. 从新模块 re-export 原有公开名字（VideoConfig / FFmpegHandler /
   AudioHandler / SubtitleHandler / VideoEffects / VideoHandler），
   旧的 `import Dedup.dedup` 与 `from Dedup.dedup import VideoHandler`
   写法继续能用；
2. 保留原命令行入口 `python Dedup/dedup.py -i input.mp4 -o output.mp4`，
   main.py 仍通过 subprocess 用这条命令调去重
   （见 main.py FileManager._process_video）。

请新代码直接用新模块，例如 `from Dedup.pipeline import VideoHandler`。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys

# GitHub Windows runner 是美区系统，stdio 默认编码是 cp1252（charmap），
# 根本编不了中文；argparse 的 --help 里有“输入视频文件路径”这类中文，
# 直接打印会抛 UnicodeEncodeError（CI 第三次运行的 3 个 --help 测试
# 就是这么挂的）。启动时尽量把 stdout/stderr 重设为 UTF-8
#（errors='replace'，失败时静默跳过），与 main.py 的做法一致。
# 注意：这必须在 argparse 打印帮助之前执行，所以放在模块顶层。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 让本文件无论以哪种方式运行都能找到 Dedup 包：
# - python Dedup/dedup.py（sys.path[0] 是 Dedup 目录）
# - python -m Dedup.dedup（包方式）
# - main.py 的 subprocess：cwd=Dedup，脚本用绝对路径传入
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from Dedup.audio import AudioHandler
    from Dedup.config import VideoConfig
    from Dedup.ffmpeg_utils import FFmpegHandler
    from Dedup.filters import VideoEffects
    from Dedup.pipeline import VideoHandler
    from Dedup.subtitles import SubtitleHandler
except ImportError:  # 直接以顶层模块导入 dedup.py 时的回退路径
    from audio import AudioHandler
    from config import VideoConfig
    from ffmpeg_utils import FFmpegHandler
    from filters import VideoEffects
    from pipeline import VideoHandler
    from subtitles import SubtitleHandler

__all__ = [
    "VideoConfig",
    "FFmpegHandler",
    "AudioHandler",
    "SubtitleHandler",
    "VideoEffects",
    "VideoHandler",
    "main",
]

# 与原 dedup.py 一致：导入即配置根日志（新模块本身不再做这件事）。
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main(argv=None) -> None:
    """原命令行入口：python dedup.py -i input.mp4 -o output.mp4"""
    parser = argparse.ArgumentParser(description="python dedup.py -i input.mp4 -o output.mp4")
    parser.add_argument("-i", "--input", required=True, help="输入视频文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出视频文件路径")
    args = parser.parse_args(argv)
    config = VideoConfig()
    processor = VideoHandler(config)
    processor.process_video(args.input, args.output)


if __name__ == "__main__":
    main()
