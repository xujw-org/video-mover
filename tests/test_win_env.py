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
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "win_env", REPO_ROOT / "scripts" / "win_env.py"
)
win_env = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(win_env)

EXE_NAME = "python.exe" if os.name == "nt" else "python"
BAT_FILES = ["setup.bat", "start.bat", "gui.bat", "update.bat"]


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


def test_gui_flags():
    args = win_env.build_parser().parse_args(["gui", "--env", "py312"])
    assert args.env == "py312"
    assert args.command == "gui"
    assert args.func is win_env.cmd_gui


def test_update_flags():
    args = win_env.build_parser().parse_args(["update", "--env", "py312"])
    assert args.env == "py312"
    assert args.command == "update"
    assert args.func is win_env.cmd_update


def test_update_pulls_then_runs_setup_and_assets(monkeypatch):
    calls = []
    monkeypatch.setattr(win_env, "ensure_interpreter", lambda env: Path("python"))
    monkeypatch.setattr(win_env, "run", lambda cmd: calls.append(list(cmd)) or 0)

    assert win_env.cmd_update(SimpleNamespace(env="dy")) == 0
    assert calls[0] == ["git", "pull", "--ff-only"]
    setup = [cmd for cmd in calls if any(str(part).endswith("win_env.py") for part in cmd)]
    assert setup and "setup" in setup[0] and "--env" in setup[0] and "dy" in setup[0]
    assert any("download_assets.py" in str(cmd) for cmd in calls)


def test_update_stops_when_git_pull_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(win_env, "ensure_interpreter", lambda env: Path("python"))
    monkeypatch.setattr(win_env, "run", lambda cmd: calls.append(list(cmd)) or 1)

    assert win_env.cmd_update(SimpleNamespace(env="dy")) == 1
    assert calls == [["git", "pull", "--ff-only"]]


# --------------------------------------------------------------------------
# PyTorch 构建选择（老机器没有显卡时不能拉 CUDA 版本）
# --------------------------------------------------------------------------
def test_resolve_torch_mode_auto_follows_gpu(monkeypatch):
    monkeypatch.setattr(win_env, "_has_nvidia_gpu", lambda: False)
    assert win_env.resolve_torch_mode("auto") == "cpu"
    monkeypatch.setattr(win_env, "_has_nvidia_gpu", lambda: True)
    assert win_env.resolve_torch_mode("auto") == "cuda"


def test_resolve_torch_mode_keeps_explicit_choice(monkeypatch):
    monkeypatch.setattr(win_env, "_has_nvidia_gpu", lambda: True)
    assert win_env.resolve_torch_mode("cpu") == "cpu"
    assert win_env.resolve_torch_mode("cuda") == "cuda"


def test_setup_accepts_torch_flag():
    args = win_env.build_parser().parse_args(["setup", "--torch", "cpu"])
    assert args.torch == "cpu"


def test_ensure_torch_installs_cpu_build_when_missing(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(win_env, "_torch_flavor", lambda interpreter: None)
    monkeypatch.setattr(win_env, "run", lambda cmd: calls.append(cmd) or 0)

    assert win_env.ensure_torch(Path("py"), "cpu") is True
    assert calls == [
        [
            "py",
            "-m",
            "pip",
            "install",
            "torch",
            "--index-url",
            win_env.TORCH_CPU_INDEX,
        ]
    ]
    assert "CPU 构建" in capsys.readouterr().out


def test_ensure_torch_skips_when_cpu_build_installed(monkeypatch):
    monkeypatch.setattr(win_env, "_torch_flavor", lambda interpreter: "cpu")
    monkeypatch.setattr(win_env, "run", lambda cmd: pytest.fail("不应重复安装 torch"))
    assert win_env.ensure_torch(Path("py"), "cpu") is True


def test_ensure_torch_cuda_mode_leaves_torch_to_requirements(monkeypatch):
    monkeypatch.setattr(win_env, "_torch_flavor", lambda interpreter: None)
    monkeypatch.setattr(win_env, "run", lambda cmd: pytest.fail("cuda 模式不应预先安装"))
    assert win_env.ensure_torch(Path("py"), "cuda") is True


def test_ensure_torch_failure_does_not_abort_setup(monkeypatch, capsys):
    monkeypatch.setattr(win_env, "_torch_flavor", lambda interpreter: None)
    monkeypatch.setattr(win_env, "run", lambda cmd: 1)
    assert win_env.ensure_torch(Path("py"), "cpu") is False
    assert "警告" in capsys.readouterr().out


def test_run_captured_returns_124_on_timeout():
    code, _ = win_env.run_captured(
        [sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2
    )
    assert code == 124


# --------------------------------------------------------------------------
# ffmpeg 准备：PATH -> 仓库自带 -> 自动下载
# --------------------------------------------------------------------------
def test_ensure_ffmpeg_prefers_path(monkeypatch, capsys):
    monkeypatch.setattr(win_env.shutil, "which", lambda name: f"C:/bin/{name}.exe")
    monkeypatch.setattr(win_env, "_install_ffmpeg_from_zip", lambda: pytest.fail("不应下载"))
    assert win_env.ensure_ffmpeg() == Path("C:/bin")
    assert "已在 PATH" in capsys.readouterr().out


def test_ensure_ffmpeg_uses_bundled_copy(tmp_path, monkeypatch):
    bin_dir = tmp_path / "tools" / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / win_env._ffmpeg_exe_name()).write_bytes(b"")
    monkeypatch.setattr(win_env, "ROOT", tmp_path)
    monkeypatch.setattr(win_env.shutil, "which", lambda name: None)
    assert win_env.ensure_ffmpeg() == bin_dir


@pytest.mark.skipif(os.name != "nt", reason="自动下载只在 Windows 上启用")
def test_install_ffmpeg_extracts_only_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(win_env, "ROOT", tmp_path)
    monkeypatch.setattr(win_env, "_ffmpeg_exe_name", lambda: "ffmpeg.exe")
    monkeypatch.setattr(win_env.shutil, "which", lambda name: None)

    zip_src = tmp_path / "src.zip"
    with zipfile.ZipFile(zip_src, "w") as archive:
        archive.writestr("ffmpeg-9.1-essentials_build/bin/ffmpeg.exe", b"f")
        archive.writestr("ffmpeg-9.1-essentials_build/bin/ffprobe.exe", b"p")
        archive.writestr("ffmpeg-9.1-essentials_build/README.txt", b"r")

    def fake_download(url, dest, timeout=60):
        shutil.copyfile(zip_src, dest)
        return True

    monkeypatch.setattr(win_env, "_download_verified", fake_download)
    bin_dir = tmp_path / "tools" / "ffmpeg" / "bin"
    assert win_env.ensure_ffmpeg() == bin_dir
    assert (bin_dir / "ffmpeg.exe").read_bytes() == b"f"
    assert (bin_dir / "ffprobe.exe").read_bytes() == b"p"
    assert not (bin_dir / "README.txt").exists()


@pytest.mark.skipif(os.name != "nt", reason="自动下载只在 Windows 上启用")
def test_install_ffmpeg_reports_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(win_env, "ROOT", tmp_path)
    monkeypatch.setattr(win_env.shutil, "which", lambda name: None)
    monkeypatch.setattr(win_env, "_download_verified", lambda *args, **kwargs: False)
    assert win_env.ensure_ffmpeg() is None
    assert "自动安装失败" in capsys.readouterr().out


# --------------------------------------------------------------------------
# 子进程 PATH：venv / conda 未激活时也要能调到 f2
# --------------------------------------------------------------------------
def test_env_with_scripts_prepends_venv_dir(tmp_path, monkeypatch):
    interpreter = tmp_path / "Scripts" / "python.exe"
    monkeypatch.setenv("PATH", "C:\\Windows")
    env = win_env.env_with_scripts(interpreter)
    assert env["PATH"].split(os.pathsep)[0] == str(interpreter.parent)


def test_env_with_scripts_covers_conda_layout(tmp_path, monkeypatch):
    (tmp_path / "Scripts").mkdir()
    interpreter = tmp_path / "python.exe"
    monkeypatch.setenv("PATH", "C:\\Windows")
    entries = win_env.env_with_scripts(interpreter)["PATH"].split(os.pathsep)
    assert str(tmp_path) in entries[:2]
    assert str(tmp_path / "Scripts") in entries[:2]


def test_env_with_scripts_includes_bundled_ffmpeg(tmp_path, monkeypatch):
    bin_dir = tmp_path / "tools" / "ffmpeg" / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / win_env._ffmpeg_exe_name()).write_bytes(b"")
    monkeypatch.setattr(win_env, "ROOT", tmp_path)
    monkeypatch.setenv("PATH", "C:\\Windows")

    entries = win_env.env_with_scripts(Path("python"))["PATH"].split(os.pathsep)

    assert str(bin_dir) in entries


def test_env_with_scripts_does_not_duplicate_entries(tmp_path, monkeypatch):
    (tmp_path / "Scripts").mkdir()
    interpreter = tmp_path / "python.exe"
    existing = os.pathsep.join([str(tmp_path / "Scripts"), "C:\\Windows"])
    monkeypatch.setenv("PATH", existing)
    entries = win_env.env_with_scripts(interpreter)["PATH"].split(os.pathsep)
    assert entries.count(str(tmp_path / "Scripts")) == 1


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
    monkeypatch.setattr(win_env, "venv_python", lambda: Path("/nonexistent/python"))
    monkeypatch.setattr(win_env, "_conda_available", lambda: True)
    monkeypatch.setattr(win_env, "_existing_env_names", lambda: ["dy", "py312"])
    with pytest.raises(SystemExit) as excinfo:
        win_env.require_interpreter("dy")
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "conda create -y -n dy python=3.12" in out
    assert "setup.bat 环境名" in out


def test_find_interpreter_falls_back_to_venv(tmp_path, monkeypatch):
    fake = tmp_path / ".venv" / "Scripts" / EXE_NAME
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"")
    monkeypatch.setattr(win_env, "resolve_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "venv_python", lambda: fake)
    assert win_env.find_interpreter("dy") == fake


def test_find_interpreter_ignores_venv_for_custom_env(tmp_path, monkeypatch):
    fake = tmp_path / ".venv" / "Scripts" / EXE_NAME
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"")
    monkeypatch.setattr(win_env, "resolve_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "venv_python", lambda: fake)
    assert win_env.find_interpreter("py312") is None


def test_ensure_interpreter_creates_missing_conda_env(monkeypatch, capsys):
    """机器上有 conda 但没有 dy 时，setup 直接 conda create。"""
    interpreter = REPO_ROOT / ".nonexistent" / EXE_NAME
    recorded = []
    monkeypatch.setattr(win_env, "find_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "resolve_interpreter", lambda env: interpreter)
    monkeypatch.setattr(win_env, "_conda_available", lambda: True)
    monkeypatch.setattr(win_env, "run", lambda cmd: recorded.append(cmd) or 0)

    assert win_env.ensure_interpreter("dy") == interpreter
    assert recorded == [["conda", "create", "-y", "-n", "dy", "python=3.12"]]
    out = capsys.readouterr().out
    assert "自动创建" in out and "创建完成" in out


def test_ensure_interpreter_creates_venv_without_conda(tmp_path, monkeypatch, capsys):
    """没有 conda 时改用项目 .venv，不再要求用户先安装 conda。"""
    venv = tmp_path / ".venv" / "Scripts" / EXE_NAME
    venv.parent.mkdir(parents=True)
    venv.write_bytes(b"")
    recorded = []
    monkeypatch.setattr(win_env, "find_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "_conda_available", lambda: False)
    monkeypatch.setattr(win_env, "venv_python", lambda: venv)
    monkeypatch.setattr(win_env, "run", lambda cmd: recorded.append(cmd) or 0)
    monkeypatch.setattr(win_env, "ROOT", tmp_path)

    assert win_env.ensure_interpreter("dy") == venv
    assert recorded == [[sys.executable, "-m", "venv", str(tmp_path / ".venv")]]
    out = capsys.readouterr().out
    assert "没有 conda" in out and "创建完成" in out


def test_ensure_interpreter_requires_conda_for_custom_env(monkeypatch, capsys):
    monkeypatch.setattr(win_env, "find_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "_conda_available", lambda: False)
    monkeypatch.setattr(win_env, "run", lambda cmd: pytest.fail("不应创建任何环境"))

    with pytest.raises(SystemExit) as excinfo:
        win_env.ensure_interpreter("py312")
    assert excinfo.value.code == 1
    assert "需要 conda" in capsys.readouterr().out


def test_ensure_interpreter_skips_creation_when_env_exists(monkeypatch):
    interpreter = REPO_ROOT / ".nonexistent" / EXE_NAME
    calls = []
    monkeypatch.setattr(win_env, "find_interpreter", lambda env: interpreter)
    monkeypatch.setattr(win_env, "run", lambda cmd: calls.append(cmd) or 0)

    assert win_env.ensure_interpreter("dy") == interpreter
    assert calls == []


def test_ensure_interpreter_reports_create_failure(monkeypatch, capsys):
    monkeypatch.setattr(win_env, "find_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "_conda_available", lambda: True)
    monkeypatch.setattr(win_env, "run", lambda cmd: 1)

    with pytest.raises(SystemExit) as excinfo:
        win_env.ensure_interpreter("dy")
    assert excinfo.value.code == 1
    out = capsys.readouterr().out
    assert "自动创建失败" in out
    assert "conda create -y -n dy python=3.12" in out


def test_ensure_interpreter_never_creates_base(monkeypatch):
    monkeypatch.setattr(win_env, "find_interpreter", lambda env: None)
    monkeypatch.setattr(win_env, "_conda_available", lambda: True)
    monkeypatch.setattr(win_env, "_existing_env_names", lambda: ["base"])
    calls = []
    monkeypatch.setattr(win_env, "run", lambda cmd: calls.append(cmd) or 0)

    with pytest.raises(SystemExit):
        win_env.ensure_interpreter("base")
    assert calls == []


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
    assert "setup" in out and "run" in out and "check" in out and "gui" in out and "update" in out