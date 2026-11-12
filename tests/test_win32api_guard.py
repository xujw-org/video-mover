# -*- coding: utf-8 -*-
"""回归测试：main.py 在 Windows 上没有 pywin32 时也能 import。

背景：CI 的 windows-smoke 曾在收集阶段失败，
`main.py:21: import win32api` 在没装 pywin32 的 Windows 上抛
`ModuleNotFoundError: No module named 'win32api'`，
导致 tests/test_appconfig.py 和 tests/test_filemanager.py
两个文件都无法收集（2 errors in 0.41s），Ubuntu 则因为
os.name != 'nt' 跳过这行而通过。

修复后：win32api 改为 try/except 导入，缺失时为 None；
SchedulerManager._register_signals 在 win32api 为 None 时
只打警告、不调用。这样 import main 不再硬性依赖 pywin32。
"""
from __future__ import annotations

import importlib
import os
import sys
from unittest import mock

import main as main_module


def test_main_imports_without_win32api_on_windows():
    """模拟 Windows 且未装 pywin32：reload main 不应抛错，win32api 为 None。"""
    assert "win32api" not in sys.modules or sys.modules.get("win32api") is None
    with mock.patch.object(os, "name", "nt"):
        with mock.patch.dict(sys.modules, {"win32api": None}):
            reloaded = importlib.reload(main_module)
            assert reloaded.win32api is None
    # 恢复：按当前平台重新加载一次，避免后续测试拿到被 patch 的状态。
    importlib.reload(main_module)


def test_register_signals_without_win32api_does_not_raise(caplog):
    """win32api 为 None 时，_register_signals 只警告、不崩。"""
    dummy = mock.Mock()
    dummy._windows_signal_handler = mock.Mock(return_value=True)
    with mock.patch.object(os, "name", "nt"):
        with mock.patch.object(main_module, "win32api", None):
            main_module.SchedulerManager._register_signals(dummy)
    dummy._windows_signal_handler.assert_not_called()
