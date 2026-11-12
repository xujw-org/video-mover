# -*- coding: utf-8 -*-
"""回归测试：时区数据（tzdata）与 Windows 控制台编码。

背景：CI 第二次运行在 windows-smoke 上 13 failed、89 passed、5 errors。
主因是 Windows 的 Python 3.12 自身不带 IANA 时区数据库，
AppConfig 用 ZoneInfo('Asia/Shanghai') 校验时抛
ZoneInfoNotFoundError / ModuleNotFoundError: No module named 'tzdata'，
导致大量用 Asia/Shanghai / Europe/London 的测试连带失败；
Ubuntu 因系统自带时区库而通过。

次因是 main.py 日志里有 ✅（U+2705），Windows 控制台默认编码是
cp936（charmap），直接输出它会抛 UnicodeEncodeError。修复后日志
里不再有这类符号，main.py 启动时还会把 stdout/stderr 重设为
UTF-8（errors='replace'），失败时静默跳过。
"""
from __future__ import annotations

import re
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_zoneinfo_asia_shanghai_and_london():
    """tzdata / 系统时区库可用时，测试里用的三个时区都能解析。"""
    for name in ("Asia/Shanghai", "Asia/Singapore", "Europe/London"):
        assert ZoneInfo(name) is not None


def test_tzdata_is_pinned_in_both_requirements():
    """tzdata 必须同时锁在运行依赖和测试依赖里（CI 只装后者）。"""
    for filename in ("requirements.txt", "requirements-dev.txt"):
        text = (REPO_ROOT / filename).read_text(encoding="utf-8")
        assert re.search(r"^tzdata==\S+$", text, flags=re.MULTILINE), filename


def test_invalid_timezone_error_mentions_tzdata():
    """时区找不到时，报错要提示 Windows 用户装 tzdata，而不是只说名字非法。"""
    text = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert "tzdata" in text
    assert "ZoneInfoNotFoundError" in text


def test_no_emoji_in_runtime_code():
    """运行时代码（main / Dedup / Upload / scripts）里不能有 ✅ 这类
    Windows charmap 编码不了的符号；日志只用中文和 ASCII。"""
    emoji = {"✅", "❌", "⚠️", "🎉", "📦", "🔧"}
    offenders = []
    for path in list((REPO_ROOT / "main.py").parent.glob("*.py")) + list(
        (REPO_ROOT / "Dedup").rglob("*.py")
    ) + list((REPO_ROOT / "Upload").rglob("*.py")) + list(
        (REPO_ROOT / "scripts").rglob("*.py")
    ):
        text = path.read_text(encoding="utf-8")
        found = emoji & set(text)
        if found:
            offenders.append(f"{path.relative_to(REPO_ROOT)}: {sorted(found)}")
    assert offenders == []


def test_main_stdout_is_reconfigured_to_utf8():
    """main.py 启动时把 stdout/stderr 重设为 UTF-8（errors='replace'）。"""
    text = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    assert 'sys.stdout.reconfigure(encoding="utf-8"' in text
    assert 'sys.stderr.reconfigure(encoding="utf-8"' in text
