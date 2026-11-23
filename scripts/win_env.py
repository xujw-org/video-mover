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
    python scripts/win_env.py gui    [--env NAME]
    python scripts/win_env.py update [--env NAME]
    python scripts/win_env.py check  [--env NAME]

  setup  确认环境（缺失时自动创建 conda 环境或 .venv）→ 安装依赖、装 Playwright
         浏览器、打上游补丁；Python 解释器本身由 setup.bat 负责装
  run    清理待上传目录并启动 main.py
  gui    启动 NiceGUI 图形控制台（缺依赖时自动安装 requirements-gui.txt）
  update 拉取最新代码，然后检查/安装依赖、重打补丁、补下缺失素材
  check  只检查不修改：解释器、依赖、ffmpeg、Playwright 浏览器、补丁、资产
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
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


def run_captured(cmd: list[str], timeout: float | None = None) -> tuple[int, str]:
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
            timeout=timeout,
        )
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
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


def _conda_available() -> bool:
    return shutil.which("conda") is not None


def _existing_env_names() -> list[str]:
    """conda env list 里的环境名（探测失败返回空列表，不影响主流程）。"""
    code, out = run_captured(["conda", "env", "list"])
    if code != 0:
        return []
    names: list[str] = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) >= 2:
            names.append(fields[0].lstrip("*"))
    return names


def venv_python() -> Path:
    """项目内虚拟环境的解释器路径（与 start.bat / setup.bat 的查找顺序一致）。"""
    scripts = "Scripts" if os.name == "nt" else "bin"
    exe = "python.exe" if os.name == "nt" else "python"
    return ROOT / ".venv" / scripts / exe


def find_interpreter(env_name: str) -> Path | None:
    """运行期解析：conda 环境优先，没有 conda 时退回项目内 .venv。

    只在默认环境名上退回 .venv；显式指定别的环境名时不猜。
    """
    interpreter = resolve_interpreter(env_name)
    if interpreter is not None:
        return interpreter
    if env_name == DEFAULT_ENV and venv_python().is_file():
        return venv_python()
    return None


def explain_missing_env(env_name: str) -> None:
    """环境缺失时打印可执行的下一步，区分“conda 没装”和“环境没建”。"""
    say()
    say(f"[错误] 找不到环境 “{env_name}” 的 Python。")
    if _conda_available():
        existing = _existing_env_names()
        if existing:
            say(f"        当前已有的 conda 环境：{', '.join(existing)}")
            say("        用已有环境安装：setup.bat 环境名")
        say("        setup.bat 会自动创建缺失的 conda 环境。")
    else:
        say("        本机没有 conda：默认环境 dy 会使用项目内 .venv；")
        say("        连 Python 3.12+ 都没有时，会自动下载并安装 Python。")
        if env_name != DEFAULT_ENV:
            say(f"        自定义环境名 “{env_name}” 需要 conda，请先安装 Miniconda/Anaconda。")
    say(f"        手动创建 conda 环境：conda create -y -n {env_name} python=3.12")


def require_interpreter(env_name: str) -> Path:
    interpreter = find_interpreter(env_name)
    if interpreter is None:
        explain_missing_env(env_name)
        raise SystemExit(1)
    return interpreter


NEW_ENV_PYTHON = "3.12"


def _create_conda_env(env_name: str) -> Path:
    say()
    say(f"[环境] “{env_name}” 不存在，自动创建："
        f"conda create -y -n {env_name} python={NEW_ENV_PYTHON}")
    if run(["conda", "create", "-y", "-n", env_name, f"python={NEW_ENV_PYTHON}"]) != 0:
        say()
        say("[错误] 自动创建失败（网络 / 镜像 / conda 服务条款未接受等）。请手动执行：")
        say(f"          conda create -y -n {env_name} python={NEW_ENV_PYTHON}")
        raise SystemExit(1)

    interpreter = resolve_interpreter(env_name)
    if interpreter is None:
        explain_missing_env(env_name)
        raise SystemExit(1)
    say(f"[环境] 创建完成：{interpreter}")
    return interpreter


def _create_venv() -> Path:
    target = ROOT / ".venv"
    say()
    say(f"[环境] 没有 conda，改用项目内虚拟环境：{target}")
    say(f"        基础解释器：{sys.executable}")
    if run([sys.executable, "-m", "venv", str(target)]) != 0:
        say()
        say("[错误] 创建 .venv 失败。请手动执行：python -m venv .venv")
        raise SystemExit(1)

    interpreter = venv_python()
    if not interpreter.is_file():
        say()
        say(f"[错误] .venv 已创建，但找不到解释器：{interpreter}")
        raise SystemExit(1)
    say(f"[环境] 创建完成：{interpreter}")
    return interpreter


def ensure_interpreter(env_name: str) -> Path:
    """setup 专用：环境不存在时自动补齐，而不是让用户手工建。

    顺序：conda 环境 -> 项目内 .venv -> 新建 conda 环境（有 conda 时）
          -> 新建 .venv（没有 conda，且用的是默认环境名）。
    """
    interpreter = find_interpreter(env_name)
    if interpreter is not None:
        return interpreter
    if env_name == "base":
        explain_missing_env(env_name)
        raise SystemExit(1)
    if _conda_available():
        return _create_conda_env(env_name)
    if env_name == DEFAULT_ENV:
        return _create_venv()
    explain_missing_env(env_name)
    raise SystemExit(1)


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
    say(f"环境      ：{args.env}")
    say(f"解释器    ：{interpreter}")

    code, out = run_captured([str(interpreter), "-c", "import sys;print(sys.version.split()[0])"])
    say(f"Python    ：{out.strip() or '未知'}")

    code, out = run_captured(
        [str(interpreter), "-c", "import torch;print(torch.__version__,'cuda=',torch.version.cuda)"]
    )
    say(f"PyTorch   ：{out.strip() or '未安装（whisper 生成字幕需要）'}")

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

    code, _ = run_captured([str(interpreter), "-c", "import nicegui"])
    say(f"  nicegui      {'OK' if code == 0 else '未安装（gui.bat 会自动安装）'}")

    say()
    say("外部工具：")
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        say(f"  {tool:<8} {path if path else '未找到（PATH 中没有）'}")
    bundled = bundled_ffmpeg_bin()
    say(f"  bundled {bundled if bundled else '无（运行 setup.bat 自动下载）'}")

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
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"


def _has_nvidia_gpu() -> bool:
    code, out = run_captured(["nvidia-smi", "-L"], timeout=20)
    return code == 0 and "GPU" in out


def resolve_torch_mode(requested: str) -> str:
    """auto：有 NVIDIA 显卡就用默认（CUDA）构建，否则用 CPU 构建。"""
    if requested != "auto":
        return requested
    return "cuda" if _has_nvidia_gpu() else "cpu"


def _torch_flavor(interpreter: Path) -> str | None:
    """已安装 torch 的构建类型：cpu / cuda；未安装返回 None。"""
    code, out = run_captured(
        [str(interpreter), "-c", "import torch; print(torch.version.cuda or 'cpu')"],
        timeout=120,
    )
    if code != 0:
        return None
    lines = [line.strip() for line in out.splitlines() if line.strip()]
    if not lines:
        return None
    return "cpu" if lines[-1].lower() == "cpu" else "cuda"


def ensure_torch(interpreter: Path, mode: str) -> bool:
    """Windows 默认 torch wheel 自带 CUDA，约 2~3 GB；无显卡的机器改用 CPU 构建。

    whisper 是唯一需要 torch 的依赖；CPU 构建同样满足 whisper 的依赖声明，
    后续 pip install -r requirements.txt 不会再下载 PyPI 的体重版。
    """
    flavor = _torch_flavor(interpreter)
    if mode == "cuda":
        if flavor is None:
            say("  PyTorch：未安装，交给 requirements 安装默认（CUDA）构建")
        else:
            say(f"  PyTorch：已安装（{flavor} 构建），保持不动")
        return True
    if flavor == "cpu":
        say("  PyTorch：已安装 CPU 构建，跳过")
        return True

    say("  PyTorch：未检测到 NVIDIA GPU，安装 CPU 构建（避免下载数 GB 的 CUDA 依赖）")
    code = run(
        [
            str(interpreter),
            "-m",
            "pip",
            "install",
            "torch",
            "--index-url",
            TORCH_CPU_INDEX,
        ]
    )
    if code != 0:
        say("  [警告] CPU 版 PyTorch 安装失败；继续装 requirements（可能回退到 PyPI 的 CUDA 构建）")
        return False
    return True


FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def _ffmpeg_exe_name() -> str:
    return "ffmpeg.exe" if os.name == "nt" else "ffmpeg"


def _ffmpeg_local_bin() -> Path:
    return ROOT / "tools" / "ffmpeg" / "bin"


def bundled_ffmpeg_bin() -> Path | None:
    """仓库自带（setup 自动下载）的 ffmpeg bin 目录。"""
    candidate = _ffmpeg_local_bin()
    return candidate if (candidate / _ffmpeg_exe_name()).is_file() else None


def ffmpeg_available() -> bool:
    if shutil.which("ffmpeg") and shutil.which("ffprobe"):
        return True
    return bundled_ffmpeg_bin() is not None


def _fetch_sha256(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url + ".sha256", timeout=20) as response:
            text = response.read().decode("ascii", "replace").strip()
    except Exception:
        return None
    token = (text.split()[0] if text else "").lower()
    return token if len(token) == 64 else None


def _download_verified(url: str, dest: Path, timeout: float = 60) -> bool:
    """下载并校验官方 sha256；取不到校验文件时只告警（来源 gyan.dev）。"""
    say(f"  下载 ffmpeg：{url}")
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response, dest.open("wb") as fh:
            final_url = response.geturl()
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                fh.write(chunk)
                digest.update(chunk)
                total += len(chunk)
    except Exception as exc:
        say(f"  [错误] 下载失败：{exc}")
        return False
    say(f"  下载完成：{total / 1024 / 1024:.1f} MB")

    expected = _fetch_sha256(final_url)
    if not expected:
        say("  [警告] 没取到官方 sha256，跳过校验")
        return True
    if digest.hexdigest() != expected:
        dest.unlink(missing_ok=True)
        say("  [错误] sha256 校验失败，已丢弃下载文件")
        return False
    say("  sha256 校验通过")
    return True


def _install_ffmpeg_from_zip() -> bool:
    """下载 gyan.dev essentials 构建，解压出 bin/ffmpeg.exe + ffprobe.exe。"""
    target = _ffmpeg_local_bin()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        zip_path = tmp_path / "ffmpeg.zip"
        if not _download_verified(FFMPEG_ZIP_URL, zip_path):
            return False

        extract_dir = tmp_path / "extract"
        try:
            with zipfile.ZipFile(zip_path) as archive:
                archive.extractall(extract_dir)
        except (zipfile.BadZipFile, OSError) as exc:
            say(f"  [错误] 解压失败：{exc}")
            return False

        candidate = next(
            (path for path in extract_dir.rglob(_ffmpeg_exe_name()) if path.parent.name == "bin"),
            None,
        )
        if candidate is None:
            say("  [错误] 压缩包里没找到 bin/ffmpeg.exe")
            return False
        src_bin = candidate.parent
        for name in ("ffmpeg.exe", "ffprobe.exe"):
            if not (src_bin / name).is_file():
                say(f"  [错误] 压缩包里缺少 {name}")
                return False

        if target.exists():
            shutil.rmtree(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_bin, target)
    say(f"  已安装到 {target}")
    return True


def ensure_ffmpeg() -> Path | None:
    """确保 ffmpeg / ffprobe 可用：PATH 优先，其次仓库自带，最后自动下载。"""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg and shutil.which("ffprobe"):
        say(f"  ffmpeg 已在 PATH：{Path(ffmpeg).parent}")
        return Path(ffmpeg).parent
    bundled = bundled_ffmpeg_bin()
    if bundled:
        say(f"  ffmpeg 使用仓库自带版本：{bundled}")
        return bundled
    if os.name != "nt":
        say("  [警告] 未找到 ffmpeg，请先安装（apt install ffmpeg / brew install ffmpeg）")
        return None
    say("  未找到 ffmpeg，下载官方 essentials 构建到 tools\\ffmpeg（约 90 MB）")
    if _install_ffmpeg_from_zip():
        return bundled_ffmpeg_bin()
    say("  [警告] 自动安装失败；手动下载 https://www.gyan.dev/ffmpeg/builds/ ，")
    say("         解压后把 bin 目录加入 PATH，或放到 tools\\ffmpeg\\bin。")
    return None


def cmd_setup(args: argparse.Namespace) -> int:
    interpreter = ensure_interpreter(args.env)
    say("=" * 62)
    say(f"目标环境：{args.env}")
    say(f"解释器  ：{interpreter}")
    say("=" * 62)

    total = 8
    step(1, total, "升级 pip")
    if run([str(interpreter), "-m", "pip", "install", "--upgrade", "pip"]) != 0:
        return _fail()

    torch_mode = resolve_torch_mode(args.torch)
    step(2, total, f"准备 PyTorch（构建选择：{torch_mode}）")
    ensure_torch(interpreter, torch_mode)

    step(3, total, "安装运行依赖 requirements.txt（opencv / whisper / playwright，首次较慢）")
    if run([str(interpreter), "-m", "pip", "install", "-r", "requirements.txt"]) != 0:
        return _fail()

    step(4, total, "安装测试依赖 requirements-dev.txt")
    if run([str(interpreter), "-m", "pip", "install", "-r", "requirements-dev.txt"]) != 0:
        return _fail()

    step(5, total, "安装图形界面依赖 requirements-gui.txt（NiceGUI，已与 f2 版本对齐）")
    if run([str(interpreter), "-m", "pip", "install", "-r", "requirements-gui.txt"]) != 0:
        return _fail()

    step(6, total, "安装 Playwright 浏览器（chromium / firefox）")
    if run([str(interpreter), "-m", "playwright", "install", "chromium", "firefox"]) != 0:
        return _fail()

    step(7, total, "应用上游兼容补丁（f2 等，详见 PATCHES.md）")
    if run([str(interpreter), str(ROOT / "scripts" / "apply_upstream_patches.py")]) != 0:
        return _fail()

    step(8, total, "准备 ffmpeg（PATH 中没有就自动下载到 tools\\ffmpeg）")
    if ensure_ffmpeg() is None:
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
    say("  2) 生成配置文件（缺失会自动从模板创建）：")
    say("       copy my_apps.yaml.example my_apps.yaml")
    say(f"  3) 打开图形界面：gui.bat {args.env}")
    say(f"     或命令行启动：start.bat {args.env}")
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


def env_with_scripts(interpreter: Path) -> dict[str, str]:
    """子进程环境：把解释器目录（以及 Windows 下 conda 的 Scripts）放到 PATH 最前面。

    直接调用 venv / conda 的 python（不 activate）时，该环境的 Scripts 目录不在
    PATH 里，main.py 里 `subprocess.Popen(["f2", ...])` 会 WinError 2。
    venv 的 python 本身就在 Scripts；conda 的 python 在环境根目录，脚本在 Scripts 下。
    """
    env = os.environ.copy()
    base = Path(interpreter).parent
    scripts = [str(base)]
    if os.name == "nt" and (base / "Scripts").is_dir():
        scripts.insert(0, str(base / "Scripts"))
    bundled_ffmpeg = bundled_ffmpeg_bin()
    if bundled_ffmpeg:
        scripts.append(str(bundled_ffmpeg))

    existing = env.get("PATH", "")
    entries = existing.split(os.pathsep) if existing else []
    lowered = {entry.lower() for entry in entries}
    missing = [path for path in reversed(scripts) if path.lower() not in lowered]
    if missing:
        env["PATH"] = os.pathsep.join(missing + ([existing] if existing else []))
    return env


def cmd_run(args: argparse.Namespace) -> int:
    interpreter = require_interpreter(args.env)

    code, _ = run_captured([str(interpreter), "-c", "import psutil, apscheduler, watchdog"])
    if code != 0:
        say()
        say(f"[错误] 环境 “{args.env}” 缺少依赖（psutil / apscheduler / watchdog）。")
        say(f"        请先运行：setup.bat {args.env}（环境缺失时它会自动创建）")
        return 1

    say(f"使用解释器：{interpreter}")
    if args.dry_run:
        say("（--dry-run：只检查环境，不清理目录、不启动 main.py）")
        return 0

    if not ffmpeg_available():
        say()
        say("[依赖] 未找到 ffmpeg / ffprobe，视频处理需要它们；尝试自动安装 ...")
        ensure_ffmpeg()

    _clean_upload_dir()
    say(f"启动 main.py（当前目录：{ROOT}）")
    say("-" * 62)
    try:
        return subprocess.run(
            [str(interpreter), str(ROOT / "main.py")],
            cwd=str(ROOT),
            env=env_with_scripts(interpreter),
        ).returncode
    except KeyboardInterrupt:
        say()
        say("已中断，正在退出。")
        return 130


def cmd_gui(args: argparse.Namespace) -> int:
    """启动 NiceGUI 控制台；缺依赖时自动安装 requirements-gui.txt。"""
    interpreter = require_interpreter(args.env)
    say(f"使用解释器：{interpreter}")

    code, out = run_captured(
        [
            str(interpreter),
            "-c",
            "import nicegui, pydantic, websockets;"
            "print(nicegui.__version__, pydantic.__version__, websockets.__version__)",
        ]
    )
    versions = out.split() if code == 0 else []
    compatible = (
        len(versions) == 3
        and versions[0] == "2.24.2"
        and versions[1].startswith("2.9.")
        and int(versions[2].split(".")[0]) < 13
    )
    if not compatible:
        say()
        say("操作界面依赖缺失或版本与 f2 冲突，正在安装 requirements-gui.txt ...")
        say("（这组版本特意与 f2 锁定的 pydantic 2.9 / websockets<13 保持兼容）")
        if run([str(interpreter), "-m", "pip", "install", "-r", "requirements-gui.txt"]) != 0:
            return _fail()

    env = env_with_scripts(interpreter)
    env["VIDEO_MOVER_GUI_ENV"] = args.env
    say(f"启动操作界面（环境：{args.env}）")
    say("-" * 62)
    try:
        return subprocess.run(
            [str(interpreter), str(ROOT / "gui.py")],
            cwd=str(ROOT),
            env=env,
        ).returncode
    except KeyboardInterrupt:
        say()
        say("已中断，正在退出。")
        return 130


def cmd_update(args: argparse.Namespace) -> int:
    """拉取最新代码，再走一遍 setup（依赖/补丁/ffmpeg），最后补素材。"""
    interpreter = require_interpreter(args.env)
    say("=" * 62)
    say(f"更新代码：{ROOT}")
    say("=" * 62)
    if run(["git", "pull", "--ff-only"]) != 0:
        say()
        say("[错误] git pull 失败，未继续更新依赖。常见原因：")
        say("  - 本机还有未提交的修改：先 git status 查看并处理；")
        say("  - 本地分支和远端分叉：需要先合并或变基；")
        say("  - 网络或账号凭据问题。")
        return 1

    say()
    say("代码已更新，开始检查依赖、Playwright、上游补丁和 ffmpeg ...")
    setup_args = argparse.Namespace(env=args.env, torch="auto", with_assets=False)
    if cmd_setup(setup_args) != 0:
        return 1

    say()
    say("补下缺失的大二进制资产（已有的会跳过）...")
    if run([str(interpreter), str(ROOT / "scripts" / "download_assets.py")]) != 0:
        say("[警告] 资产下载失败；可以稍后在图形界面点“下载素材”重试。")

    say()
    say("=" * 62)
    say(f"更新完成。启动图形界面：gui.bat {args.env}")
    say("=" * 62)
    return 0


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
    p_setup.add_argument(
        "--torch",
        choices=("auto", "cpu", "cuda"),
        default="auto",
        help="PyTorch 构建：auto 按是否有 NVIDIA 显卡决定（无显卡装 CPU 版），默认 auto",
    )
    p_setup.add_argument("--with-assets", action="store_true", help="同时下载大二进制资产")
    p_setup.set_defaults(func=cmd_setup)

    p_run = sub.add_parser("run", help="清理待上传目录并启动 main.py")
    p_run.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_run.add_argument("--dry-run", action="store_true", help="只检查环境，不启动")
    p_run.set_defaults(func=cmd_run)

    p_check = sub.add_parser("check", help="只检查不修改")
    p_check.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_check.set_defaults(func=cmd_check)

    p_gui = sub.add_parser("gui", help="启动图形操作界面（NiceGUI，浏览器打开）")
    p_gui.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_gui.set_defaults(func=cmd_gui)

    p_update = sub.add_parser("update", help="拉取最新代码并更新依赖、补丁和素材")
    p_update.add_argument("--env", default=DEFAULT_ENV, help="conda 环境名，默认 dy")
    p_update.set_defaults(func=cmd_update)
    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())