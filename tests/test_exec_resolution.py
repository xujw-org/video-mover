# -*- coding: utf-8 -*-
"""main.py 的可执行文件解析。

背景：`start.bat` 直接用 venv / conda 的 python 启动 main.py，不 activate 环境，
PATH 里没有该环境的 Scripts 目录。main.py 里 `subprocess.Popen(["f2", ...])`
因此抛 WinError 2（用户实测的“任务执行失败: [WinError 2]”）。这里钉住回退逻辑。
"""
from __future__ import annotations

import os
from pathlib import Path

import main as main_module


def _make_exe(dir_path: Path, name: str) -> Path:
    dir_path.mkdir(parents=True, exist_ok=True)
    target = dir_path / name
    target.write_bytes(b"")
    return target


def test_keeps_command_when_on_path(monkeypatch):
    monkeypatch.setattr(main_module.shutil, "which", lambda name: r"C:\bin\f2.exe")
    command = ["f2", "tk", "-M", "post"]
    assert main_module._resolve_executable_command(command) is command


def test_keeps_absolute_command():
    command = [str(Path(r"D:\tools\f2.exe").resolve()), "tk"]
    assert main_module._resolve_executable_command(command) == command


def test_resolves_console_script_next_to_interpreter(tmp_path, monkeypatch):
    exe_dir = tmp_path / "Scripts"
    python = _make_exe(exe_dir, "python.exe" if os.name == "nt" else "python")
    script = _make_exe(exe_dir, "f2.exe" if os.name == "nt" else "f2")
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(main_module.sys, "executable", str(python))

    result = main_module._resolve_executable_command(["f2", "tk", "-M", "post"])
    assert result == [str(script), "tk", "-M", "post"]


def test_resolves_conda_script_in_scripts_subdir(tmp_path, monkeypatch):
    """conda 的 python 在环境根目录，console script 在 Scripts 子目录。"""
    env_root = tmp_path / "envs" / "dy"
    python = _make_exe(env_root, "python.exe" if os.name == "nt" else "python")
    script = _make_exe(env_root / "Scripts", "f2.exe")
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(main_module.sys, "executable", str(python))

    result = main_module._resolve_executable_command(["f2", "tk"])
    assert result == [str(script), "tk"]


def test_returns_original_when_nothing_found(tmp_path, monkeypatch):
    python = _make_exe(tmp_path, "python")
    monkeypatch.setattr(main_module.shutil, "which", lambda name: None)
    monkeypatch.setattr(main_module.sys, "executable", str(python))
    command = ["f2", "tk"]
    assert main_module._resolve_executable_command(command) == command


def test_prepend_bundled_tools_adds_ffmpeg_bin(tmp_path, monkeypatch):
    bundled = tmp_path / "tools" / "ffmpeg" / "bin"
    bundled.mkdir(parents=True)
    (bundled / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")).write_bytes(b"")
    monkeypatch.setattr(main_module, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("PATH", "C:\\Windows")

    main_module._prepend_bundled_tools()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(bundled)


def test_prepend_bundled_tools_is_noop_without_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(main_module, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("PATH", "C:\\Windows")

    main_module._prepend_bundled_tools()

    assert os.environ["PATH"] == "C:\\Windows"
