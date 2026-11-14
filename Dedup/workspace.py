# -*- coding: utf-8 -*-
r"""Dedup 的临时文件位置：放仓库里的 tmp/，不要落在系统临时目录。

为什么：默认 `tempfile.mktemp()` 落在 C:\Users\<用户>\AppData\Local\Temp，
而 4K 素材的中间音频（原声 wav + 混音 float wav）是一条几十兆级别的开销；
如果进程被强杀（Ctrl+C、timeout、崩溃），finally 里的清理不会执行，
这些文件就留在 C 盘上越攒越多。项目本身在 D 盘，临时文件跟着放 D 盘，
并且每次启动顺手清掉一天前的残留。

用法::

    from .workspace import temp_wav, clean_stale

    path = temp_wav()          # -> <repo>/tmp/tmpXXXXXXXX.wav
    clean_stale()              # 启动时调用一次，删掉 1 天前的残留
"""

from __future__ import annotations

import logging
import tempfile
import time
from pathlib import Path

MAX_AGE_SECONDS = 24 * 3600

TMP_DIR = Path(__file__).resolve().parent.parent / "tmp"


def ensure_tmp_dir() -> Path:
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    return TMP_DIR


def temp_wav(suffix: str = ".wav") -> str:
    """在 <repo>/tmp 里建一个临时 wav 路径（与 tempfile.mktemp 行为一致，不创建文件）。"""
    path = Path(tempfile.mktemp(suffix=suffix, dir=str(ensure_tmp_dir())))
    return str(path)


def clean_stale(max_age_seconds: int = MAX_AGE_SECONDS) -> int:
    """删掉 tmp/ 里超过 max_age_seconds 的残留文件，返回删除个数。"""
    if not TMP_DIR.is_dir():
        return 0
    now = time.time()
    removed = 0
    for entry in TMP_DIR.iterdir():
        try:
            if not entry.is_file():
                continue
            if now - entry.stat().st_mtime < max_age_seconds:
                continue
            entry.unlink()
            removed += 1
        except OSError:
            continue
    if removed:
        logging.info(f"清理了 {removed} 个上次遗留的临时文件（{TMP_DIR}）")
    return removed
