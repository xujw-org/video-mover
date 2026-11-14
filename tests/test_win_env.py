# -*- coding: utf-8 -*-
"""Windows 启动/安装脚本：.bat 编码约束 + scripts/win_env.py 的核心逻辑。

背景（为什么要这些测试）：

- `.bat` 里写中文在 cmd 默认代码页（简体中文 Windows 是 cp936）下会乱码；
- 加 `chcp 65001` 能修正显示，但会触发 cmd.exe 批处理解析器在多字节
  字符上的偏移错位，把半行内容当命令执行（本机实测过）。所以两个 .bat
  被约束为“纯 ASCII + CRLF”，中文提示全部交给 win_env.py 输出。
  这个约束很容易在以后编辑时被破坏，用测试钉住。
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

import pytest

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "win_env", REPO_ROOT / "scripts" / "win_env.py"
)
win_env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(win_env)

EXE_NAME = "python.exe" if os.name == "nt" else "python"
BAT_FILES = ["setup.bat", "start.bat"]


# --------------------------------------------------------------------------
# .bat 编码约束
# --------------------------------------------------------------------------
@pytest.mark.parametrize("name", BAT_FILES)
def test_bat_is_ascii_only(name):
    """非 ASCII 字节 = 潜在的乱码 / 解析器错位，必须为 0。"""
    data = (REPO_ROOT / name).read_bytes()
    offenders = [(i, b) for i, b in enumerate(data) if b >= 0x80]
    assert not offenders, f"{name} 含非 ASCII 字节（首个位置 {offenders[0]}）"


@pytest.mark.parametrize("name", BAT_FILES)
def test_bat_uses_crlf_and_switches_codepage(name):
    data = (REPO_ROOT / name).read_bytes()
    assert b"\n" not in data.replace(b"\r\n", b""), f"{name} 含裸 LF 换行"
    assert data.endswith(b"\r\n"), f"{name} 未以 CRLF 结尾"
    text = data.decode("ascii")
    assert "chcp 65001" in text, f"{name} 需要 chcp 65001 才能让 Python 的 UTF-8 输出正常显示"


@pytest.mark.parametrize("name", BAT_FILES)
def test_bat_has_no_call_statement(name):
    """call 第二个 .bat 会放大解析器错位风险，所以逻辑统一走 win_env.py。"""
    text = (REPO_ROOT / name).read_bytes().decode("ascii").lower()
    statements = [line.strip() for line in text.splitlines()]
    assert not any(line.startswith(("call ", "call\t")) for line in statements), (
        f"{name} 不应再 call 其它批处理"
    )
    assert "win_env.py" in text


# --------------------------------------------------------------------------
# 参数解析
# --------------------------------------------------------------------------
def test_default_env_is_dy():
    args = win_env.build_parser().parse_args(["check"])
    assert args.env == "dy"
    assert args.command == "check"


def test_setup_flags():
    args = win_env.build_parser().parse_args(["setup", "--env", "py312", "--with-assets"])
    assert args.env == "py312"
    assert args.with_assets is True


def test_run_flags():
    args = win_env.build_parser().parse_args(["run", "--dry-run"])
    assert args.dry_run is True


# --------------------------------------------------------------------------
# 解释器解析
# --------------------------------------------------------------------------
def _make_env(base, env_name):
    target = base / "envs" / env_name / EXE_NAME
    target.parent.mkdir(parents=True)
    target.write_bytes(b"")
    return target


def test_resolve_interpreter_from_envs_dir(tmp_path, monkeypatch):
    expected = _make_env(tmp_path, "dy")
    monkeypatch.setattr(win_env, "conda_base", lambda: tmp_path)
    assert win_env.resolve_interpreter("dy") == expected


def test_resolve_interpreter_base_env(tmp_path, monkeypatch):
    expected = tmp_path / EXE_NAME
    expected.write_bytes(b"")
    monkeypatch.setattr(win_env, "conda_base", lambda: tmp_path)
    assert win_env.resolve_interpreter("base") == expected


def test_resolve_interpreter_falls_back_to_conda_run(tmp_path, monkeypatch):
    expected = _make_env(tmp_path, "custom")  # 不在 <base>/envs 下的场景
    monkeypatch.setattr(win_env, "conda_base", lambda: None)
    monkeypatch.setattr(
        win_env, "run_captured", lambda cmd: (0, f"noise\n{expected}\n")
    )
    assert win_env.resolve_interpreter("custom") == expected


def test_resolve_interpreter_returns_none_when_absent(monkeypatch):
    monkeypatch.setattr(win_env, "conda_base", lambda: None)
    monkeypatch.setattr(win_env, "run_captured", lambda cmd: (1, ""))
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    assert win_env.resolve_interpreter("nope") is None


def test_require_interpreter_exits_with_hint(monkeypatch, capsys):
    monkeypatch.setattr(win_env, "resolve_interpreter", lambda env: None)
    with pytest.raises(SystemExit) as excinfo:
        win_env.require_interpreter("dy")
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "conda create -y -n dy python=3.12" in out


# --------------------------------------------------------------------------
# 启动前的目录清理
# --------------------------------------------------------------------------
def test_clean_upload_dir_only_removes_mp4(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(win_env, "ROOT", tmp_path)
    videos = tmp_path / "Upload" / "videos"
    videos.mkdir(parents=True)
    (videos / "a.mp4").write_bytes(b"x")
    (videos / "b.mp4").write_bytes(b"x")
    keep = videos / "keep.txt"
    keep.write_bytes(b"x")

    win_env._clean_upload_dir()

    assert sorted(p.name for p in videos.iterdir()) == ["keep.txt"]
    assert "删除 2 个历史 mp4" in capsys.readouterr().out


def test_clean_upload_dir_is_quiet_when_empty(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(win_env, "ROOT", tmp_path)
    win_env._clean_upload_dir()  # 目录不存在
    assert capsys.readouterr().out == ""
    (tmp_path / "Upload" / "videos").mkdir(parents=True)
    win_env._clean_upload_dir()  # 目录存在但没有 mp4
    assert capsys.readouterr().out == ""


# --------------------------------------------------------------------------
# 脚本自身可执行（帮助信息）
# --------------------------------------------------------------------------
def test_help_runs():
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "win_env.py"), "--help"],
        capture_output=True,
    )
    assert proc.returncode == 0
    out = (proc.stdout + proc.stderr).decode("utf-8", "replace")
    assert "setup" in out and "run" in out and "check" in out