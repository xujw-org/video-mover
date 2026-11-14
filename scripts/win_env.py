"""Video Mover Windows 环境助手（setup.bat / start.bat 的实际执行体）。

为什么把逻辑放在这里而不是 .bat 里：

1. `.bat` 写中文会乱码。cmd 默认按系统代码页（简体中文 Windows 是 cp936）
   解释文件字节，UTF-8 编码的中文在 `echo` 里就是一堆乱码；
2. 加 `chcp 65001` 能解决显示问题，但会触发 cmd.exe 批处理解析器的一个
   已知缺陷：在 65001 代码页下，解析器按“字符数”当“字节数”回溯文件，
   遇到多字节中文会把某一行截断，把半行残片当命令执行（本机实测会出现
   `'ocal，否则' 不是内部或外部命令`）。控制台起始代码页是 65001 时更容易
   触发，属于概率性故障。

因此：两个 .bat 只保留 ASCII（不会乱码、也不会触发上述缺陷），所有中文
提示都由本文件输出。本文件是 UTF-8 源码，配合 .bat 里的 `chcp 65001`，
中文在控制台能正常显示（Python 侧还额外设置了 PYTHONUTF8=1）。

用法（一般由 .bat 调用，也可以手动执行）：

    python scripts/win_env.py setup  [--env NAME] [--with-assets]
    python scripts/win_env.py run    [--env NAME] [--dry-run]
    python scripts/win_env.py check  [--env NAME]

  setup  按 requirements 安装依赖、装 Playwright 浏览器、打上游补丁
  run    清理待上传目录并启动 main.py
  check  只检查不修改：解释器、依赖、ffmpeg、Playwright 浏览器、补丁、资产
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV = "dy"


# --------------------------------------------------------------------------
# 输出与进程工具
# --------------------------------------------------------------------------
def _force_utf8_stdio() -> None:
    """控制台已是 UTF-8（.bat 里执行过 chcp 65001）时，保证 Python 也按 UTF-8 输出。

    同时给子进程（本文件会调用 apply_upstream_patches.py 等）设好 UTF-8
    环境变量，否则子进程往管道里写中文会用 cp936，采集回来就是乱码。
    """
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(index: int, total: int, msg: str) -> None:
    say()
    say(f"[{index}/{total}] {msg}")


def run(cmd: list[str]) -> int:
    """执行命令并直接继承控制台（输出实时可见），返回进程退出码。"""
    try:
        return subprocess.run(cmd, cwd=str(ROOT)).returncode
    except FileNotFoundError:
        say(f"  [错误] 找不到可执行文件：{cmd[0]}")
        return 127


def run_captured(cmd: list[str]) -> tuple[int, str]:
    """执行命令并静默采集输出（用于探测环境、取版本号）。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return 127, ""
    return proc.returncode, proc.stdout or ""


def conda_base() -> Path | None:
    code, out = run_captured(["conda", "info", "--base"])
    if code != 0:
        return None
    for line in reversed(out.splitlines()):
        candidate = line.strip()
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


def resolve_interpreter(env_name: str) -> Path | None:
    """按 conda 环境名找到对应解释器。

    顺序：conda 默认 envs 目录 -> base 环境 -> conda run 兜底 -> 当前已激活环境。
    全部失败返回 None。
    """
    exe_name = "python.exe" if os.name == "nt" else "python"
    base = conda_base()
    if base is not None:
        if env_name == "base":
            candidate = base / exe_name
        else:
            candidate = base / "envs" / env_name / exe_name
        if candidate.is_file():
            return candidate

    code, out = run_captured(
        ["conda", "run", "-n", env_name, "python", "-c", "import sys;print(sys.executable)"]
    )
    if code == 0:
        for line in reversed(out.splitlines()):
            candidate = Path(line.strip())
            if candidate.is_file():
                return candidate

    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidate = Path(prefix) / exe_name
        if candidate.is_file() and (env_name == "base" or Path(prefix).name == env_name):
            return candidate
    return None


def require_interpreter(env_name: str) -> Path:
    interpreter = resolve_interpreter(env_name)
    if interpreter is None:
        say()
        say(f"[错误] 找不到 conda 环境 “{env_name}” 的 Python。")
        say("        先创建环境，再重新运行：")
        say(f"          conda create -y -n {env_name} python=3.12")
        say("        环境名不是 “%s” 时，用参数指定：setup.bat 环境名" % env_name)
        raise SystemExit(1)
    return interpreter


# --------------------------------------------------------------------------
# check：只读检查
# --------------------------------------------------------------------------
REQUIRED_IMPORTS = [
    ("psutil", "psutil"),
    ("apscheduler", "apscheduler"),
    ("watchdog", "watchdog"),
    ("yaml", "pyyaml"),
    ("PIL", "Pillow"),
    ("numpy", "numpy"),
    ("playwright", "playwright"),
    ("f2", "f2"),
]


def cmd_check(args: argparse.Namespace) -> int:
    interpreter = require_interpreter(args.env)
    say("=" * 62)
    say(f"conda 环境：{args.env}")
    say(f"解释器    ：{interpreter}")

    code, out = run_captured([str(interpreter), "-c", "import sys;print(sys.version.split()[0])"])
    say(f"Python    ：{out.strip() or '未知'}")

    say()
    say("依赖：")
    missing = []
    for module, package in REQUIRED_IMPORTS:
        code, _ = run_captured([str(interpreter), "-c", f"import {module}"])
        state = "OK" if code == 0 else "缺失"
        if code != 0:
            missing.append(package)
        say(f"  {module:<12} {state}")
    if missing:
        say(f"  缺失的包：{', '.join(missing)}（运行 setup.bat 安装）")

    say()
    say("外部工具：")
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        say(f"  {tool:<8} {path if path else '未找到（需加入 PATH）'}")

    browsers = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    if browsers.is_dir():
        names = sorted(
            p.name for p in browsers.iterdir() if p.is_dir() and not p.name.startswith("_")
        )
        say(f"  playwright {browsers} -> {', '.join(names) if names else '空'}")
    else:
        say("  playwright 浏览器目录不存在（运行 setup.bat 安装）")

    say()
    say("上游补丁（apply_upstream_patches.py --check）：")
    patches = ROOT / "scripts" / "apply_upstream_patches.py"
    code, out = run_captured([str(interpreter), str(patches), "--check"])
    for line in out.strip().splitlines()[-6:]:
        say(f"  {line}")
    say(f"  退出码 {code}（0 表示全部已应用）")

    say()
    say("大二进制资产（download_assets.py --check）：")
    assets = ROOT / "scripts" / "download_assets.py"
    code, out = run_captured([str(interpreter), str(assets), "--check"])
    for line in out.strip().splitlines()[-8:]:
        say(f"  {line}")
    say("=" * 62)
    return 0


# --------------------------------------------------------------------------
# setup：安装
# --------------------------------------------------------------------------
def cmd_setup(args: argparse.Namespace) -> int:
    interpreter = require_interpreter(args.env)
    say("=" * 62)
    say(f"目标环境：conda {args.env}")
    say(f"解释器  ：{interpreter}")
    say("=" * 62)

    total = 6
    step(1, total, "升级 pip")
    if run([str(interpreter), "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        return _fail()

    step(2, total, "安装运行依赖 requirements.txt（opencv / whisper / playwright，首次较慢）")
    if run([str(interpreter), "-m", "pip", "install", "-r", "requirements.txt"]) != 0:
        return _fail()

    step(3, total, "安装测试依赖 requirements-dev.txt")
    if run([str(interpreter), "-m", "pip", "install", "-r", "requirements-dev.txt"]) != 0:
        return _fail()

    step(4, total, "安装 Playwright 浏览器（chromium / firefox）")
    if run([str(interpreter), "-m", "playwright", "install", "chromium", "firefox"]) != 0:
        return _fail()

    step(5, total, "应用上游兼容补丁（f2 等，详见 PATCHES.md）")
    if run([str(interpreter), str(ROOT / "scripts" / "apply_upstream_patches.py")]) != 0:
        return _fail()

    step(6, total, "检查外部工具（ffmpeg 需在 PATH 中）")
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        say(f"  {tool:<8} {path if path else '未找到 —— 请安装 ffmpeg 并加入 PATH'}")
    if not shutil.which("ffmpeg"):
        say("  （后续视频处理步骤会失败；本步不算安装失败）")

    if args.with_assets:
        say()
        say("附加步骤：下载大二进制资产（字体 / 音乐 / 水印 / 画中画）")
        if run([str(interpreter), str(ROOT / "scripts" / "download_assets.py")]) != 0:
            return _fail()

    say()
    say("=" * 62)
    say("安装完成。接下来：")
    if not args.with_assets:
        say("  1) 首次运行前下载大二进制资产：")
        say(f'       "{interpreter}" scripts\\download_assets.py')
    say("  2) 生成配置文件（缺失会打警告并用默认值）：")
    say("       copy my_apps.yaml.example my_apps.yaml")
    say(f"  3) 启动：start.bat {args.env}")
    say("=" * 62)
    return 0


def _fail() -> int:
    say()
    say("[错误] 上一步失败，请查看上面的报错信息。")
    return 1


# --------------------------------------------------------------------------
# run：启动主程序
# --------------------------------------------------------------------------
def _clean_upload_dir() -> None:
    """与原 start.bat 行为一致：启动前清空 Upload/videos 里的历史视频。"""
    target = ROOT / "Upload" / "videos"
    if not target.is_dir():
        return
    videos = list(target.glob("*.mp4"))
    if not videos:
        return
    say(f"清理待上传目录：删除 {len(videos)} 个历史 mp4（{target}）")
    for video in videos:
        try:
            video.unlink()
        except OSError as exc:
            say(f"  [警告] 删除失败 {video.name}：{exc}")


def cmd_run(args: argparse.Namespace) -> int:
    interpreter = require_interpreter(args.env)

    code, _ = run_captured([str(interpreter), "-c", "import psutil, apscheduler, watchdog"])
    if code != 0:
        say()
        say(f"[错误] 环境 “{args.env}” 缺少依赖（psutil / apscheduler / watchdog）。")
        say(f"        请先运行：setup.bat {args.env}")
        return 1

    say(f"使用解释器：{interpreter}")
    if args.dry_run:
        say("（--dry-run：只检查环境，不清理目录、不启动 main.py）")
        return 0

    _clean_upload_dir()
    say(f"启动 main.py（当前目录：{ROOT}）")
    say("-" * 62)
    try:
        return subprocess.run([str(interpreter), str(ROOT / "main.py")], cwd=str(ROOT)).returncode
    except KeyboardInterrupt:
        say()
        say("已中断，正在退出。")
        return 130


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Video Mover Windows 环境助手（setup.bat / start.bat 的执行体）"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_setup = sub.add_parser("setup", help="安装依赖、Playwright 浏览器并应用上游补丁")
    p_setup.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_setup.add_argument("--with-assets", action="store_true", help="同时下载大二进制资产")
    p_setup.set_defaults(func=cmd_setup)

    p_run = sub.add_parser("run", help="清理待上传目录并启动 main.py")
    p_run.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_run.add_argument("--dry-run", action="store_true", help="只检查环境，不启动")
    p_run.set_defaults(func=cmd_run)

    p_check = sub.add_parser("check", help="只检查不修改")
    p_check.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())