# -*- coding: utf-8 -*-
"""子进程管理：启动/停止 main.py，以及登录、导出 cookie、下载素材等一次性任务。

界面进程不直接运行业务代码，所有操作都走子进程，这样：

* 配置错误、依赖错误只会让子进程退出，不会把界面带崩；
* 停止流水线可以发 Ctrl+Break 让 main.py 自己走 shutdown，超时再杀进程树；
* 实时输出统一进 LogBuffer，界面按序号增量拉取。
"""

from __future__ import annotations

import ctypes
import os
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil

from scripts.win_env import env_with_scripts

IS_WINDOWS = os.name == "nt"
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
# 测试里的 psutil 替身没有 Error；真实 psutil 有。两者都能安全捕获。
PSUTIL_ERROR = getattr(psutil, "Error", Exception)


class LogBuffer:
    """线程安全的环形日志；`since(index)` 返回增量。"""

    def __init__(self, max_lines: int = 4000):
        self._lines: deque[str] = deque(maxlen=max_lines)
        self._count = 0
        self._lock = threading.Lock()

    def add(self, line: str) -> None:
        text = line.rstrip("\r\n")
        if not text:
            return
        with self._lock:
            self._lines.append(text)
            self._count += 1

    def since(self, index: int) -> list[str]:
        with self._lock:
            start = self._count - len(self._lines)
            offset = max(0, index - start)
            return list(self._lines)[offset:]

    @property
    def count(self) -> int:
        with self._lock:
            return self._count

    def clear(self) -> None:
        """清空缓冲并重置序号；界面据此判断进入了新的一轮。"""
        with self._lock:
            self._lines.clear()
            self._count = 0

    def snapshot(self, limit: int = 500) -> list[str]:
        with self._lock:
            return list(self._lines)[-limit:]


def _now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def clean_upload_dir(root: Path) -> int:
    """与 start.bat 一致：启动前删除 Upload/videos 里的历史 mp4，防止重复发布。"""
    target = root / "Upload" / "videos"
    if not target.is_dir():
        return 0
    removed = 0
    for video in target.glob("*.mp4"):
        try:
            video.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def tail_file(path: Path, max_lines: int = 500, max_bytes: int = 512 * 1024) -> list[str]:
    """读取日志文件末尾若干行；不存在返回空列表。"""
    if not path.is_file():
        return []
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - max_bytes))
            data = fh.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _create_job_object():
    """创建“GUI 退出就杀掉所有子进程”的 Windows Job Object。

    直接关闭 gui.bat 的控制台窗口时，Python 不一定会走 on_shutdown；但进程退出时
    Windows 会关闭 Job 句柄，带 KILL_ON_JOB_CLOSE 的 Job 会一起结束 main.py 和它的
    子进程，避免残留。
    """
    if not IS_WINDOWS:
        return None, None
    try:
        from ctypes import wintypes
    except Exception:  # pragma: no cover - 只可能在非 Windows
        return None, None

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BasicLimitInformation(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimitInformation(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimitInformation),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None, None
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    info = _ExtendedLimitInformation()
    info.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)
    ):
        kernel32.CloseHandle(job)
        return None, None
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    return kernel32, job


class ProcessManager:
    """同一时间只允许一个业务进程（流水线或一次性任务）。"""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.log = LogBuffer()
        self._lock = threading.Lock()
        self._proc: subprocess.Popen[str] | None = None
        self._kind: str = ""
        self._label: str = ""
        self._started_at: float | None = None
        self._exit_code: int | None = None
        self._task_env_name = os.environ.get("VIDEO_MOVER_GUI_ENV") or os.environ.get(
            "CONDA_DEFAULT_ENV", "dy"
        )
        self._external_cache: list[dict[str, Any]] = []
        self._external_cache_at = 0.0
        self._external_lock = threading.Lock()
        self._job_kernel32, self._job_handle = _create_job_object()
        self._job_warned = False

    # ------------------------------------------------------------------ 状态
    @property
    def kind(self) -> str:
        return self._kind

    @property
    def label(self) -> str:
        return self._label

    def proc_alive(self) -> bool:
        proc = self._proc
        return proc is not None and proc.poll() is None

    def main_running(self) -> bool:
        return self.proc_alive() and self._kind == "main"

    def task_running(self) -> bool:
        return self.proc_alive() and self._kind != "main"

    def busy(self) -> bool:
        return self.proc_alive()

    def status(self) -> dict[str, Any]:
        alive = self.proc_alive()
        elapsed = 0
        if alive and self._started_at is not None:
            elapsed = int(time.time() - self._started_at)
        return {
            "running": alive,
            "kind": self._kind,
            "label": self._label,
            "pid": self._proc.pid if alive and self._proc else None,
            "started_at": self._started_at,
            "elapsed": elapsed,
            "exit_code": self._exit_code,
            "env_name": self._task_env_name,
        }

    # ------------------------------------------------------------------ 启动
    def _environment(self) -> dict[str, str]:
        env = env_with_scripts(Path(sys.executable))
        env.setdefault("PYTHONUTF8", "1")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        return env

    def _assign_to_job(self, proc: subprocess.Popen[str]) -> None:
        if not self._job_handle:
            return
        try:
            handle = int(proc._handle)  # type: ignore[attr-defined]
            if not self._job_kernel32.AssignProcessToJobObject(self._job_handle, handle):
                raise OSError(f"AssignProcessToJobObject 错误码 {ctypes.get_last_error()}")
        except Exception as exc:  # noqa: BLE001 - Job 绑定失败不应阻止启动
            if not self._job_warned:
                self.log.add(
                    f"[{_now_text()}] 警告：无法把子进程绑定到 Job Object，"
                    f"关闭 GUI 时可能残留：{exc}"
                )
                self._job_warned = True

    def _spawn(self, kind: str, label: str, command: list[str], cwd: Path) -> bool:
        with self._lock:
            if self.proc_alive():
                self.log.add(f"[{_now_text()}] 已有任务在运行（{self._label}），请先停止。")
                return False
            self.log.add("")
            self.log.add(f"[{_now_text()}] ▶ 启动{label}：{command[0]} ...")
            try:
                proc = subprocess.Popen(
                    command,
                    cwd=str(cwd),
                    env=self._environment(),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    creationflags=CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0,
                )
            except OSError as exc:
                self.log.add(f"[{_now_text()}] ✖ 启动失败：{exc}")
                return False
            self._assign_to_job(proc)
            self._proc = proc
            self._kind = kind
            self._label = label
            self._started_at = time.time()
            self._exit_code = None
            threading.Thread(
                target=self._pump, args=(proc, label), daemon=True, name="vm-gui-pump"
            ).start()
            return True

    def _pump(self, proc: subprocess.Popen[str], label: str) -> None:
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    self.log.add(line)
        except (OSError, ValueError):
            pass
        code = proc.wait()
        end = time.time()
        duration = f"{int(end - (self._started_at or end))} 秒"
        with self._lock:
            if self._proc is proc:
                self._proc = None
                self._kind = ""
                self._label = ""
                self._started_at = None
                self._exit_code = code
        result = "正常结束" if code == 0 else f"退出码 {code}"
        self.log.add(f"[{_now_text()}] ■ {label}{result}（耗时 {duration}）")

    # ------------------------------------------------------------------ 流水线
    def reset_logs(self) -> None:
        """清空上一轮输出，并把旧 app.log 备份成 app.log.prev。"""
        self.log.clear()
        self._exit_code = None
        log_path = self.root / "app.log"
        backup = self.root / "app.log.prev"
        if log_path.is_file():
            try:
                log_path.replace(backup)
                self.log.add(f"[{_now_text()}] 已清空上一轮日志（旧 app.log 备份为 app.log.prev）")
            except OSError as exc:
                self.log.add(f"[{_now_text()}] 清理旧日志失败：{exc}")
        else:
            self.log.add(f"[{_now_text()}] 已清空上一轮日志")

    def start_main(
        self, clean_upload: bool = True, reset_logs: bool = True
    ) -> tuple[bool, str]:
        if self.busy():
            return False, f"已有任务在运行（{self._label}），请先停止。"
        external = self.find_external_main(max_age=0)
        if external:
            pids = "、".join(str(item["pid"]) for item in external)
            return (
                False,
                f"检测到外部已在运行 main.py（PID {pids}）。"
                "请先在命令行窗口按 Ctrl+C 停止它。",
            )
        if not (self.root / "my_apps.yaml").is_file():
            return False, "缺少 my_apps.yaml，请先在“配置”页保存。"
        if reset_logs:
            self.reset_logs()
        if clean_upload:
            removed = clean_upload_dir(self.root)
            if removed:
                self.log.add(
                    f"[{_now_text()}] 已清理 Upload/videos 里 {removed} 个历史 mp4"
                    "（与 start.bat 一致）"
                )
        ok = self._spawn("main", "流水线", [sys.executable, str(self.root / "main.py")], self.root)
        if ok:
            return True, "已启动流水线，首轮任务会立即执行。"
        return False, "启动失败，请看日志。"

    # ------------------------------------------------------------------ 一次性任务
    def run_task(
        self, kind: str, label: str, command: list[str], cwd: Path | None = None
    ) -> tuple[bool, str]:
        if self.main_running():
            return False, "流水线正在运行，请先停止再执行这个操作。"
        if self.busy():
            return False, f"已有任务在运行（{self._label}），请等它结束。"
        ok = self._spawn(kind, label, command, cwd or self.root)
        return (True, f"已开始：{label}") if ok else (False, "启动失败，请看日志。")

    def export_cookie(self, account: str) -> tuple[bool, str]:
        return self.run_task(
            "export",
            "导出抖音 Cookie",
            [sys.executable, str(self.root / "Upload" / "export_cookie.py")],
            self.root,
        )

    def login_douyin(self, account: str) -> tuple[bool, str]:
        return self.run_task(
            "login",
            f"抖音扫码登录（{account}）",
            [
                sys.executable,
                str(self.root / "Upload" / "cli_main.py"),
                "douyin",
                account,
                "login",
            ],
            self.root / "Upload",
        )

    def download_assets(self) -> tuple[bool, str]:
        return self.run_task(
            "assets",
            "下载视频处理素材",
            [sys.executable, str(self.root / "scripts" / "download_assets.py")],
            self.root,
        )

    def setup_environment(self) -> tuple[bool, str]:
        return self.run_task(
            "setup",
            f"修复环境（{self._task_env_name}）",
            [
                sys.executable,
                str(self.root / "scripts" / "win_env.py"),
                "setup",
                "--env",
                self._task_env_name,
            ],
            self.root,
        )

    # ------------------------------------------------------------------ 停止
    def stop(self, timeout: float = 12.0) -> tuple[bool, str]:
        with self._lock:
            proc = self._proc
            label = self._label or "任务"
        if proc is None or proc.poll() is not None:
            return False, "当前没有正在运行的任务。"
        self.log.add(f"[{_now_text()}] 正在停止{label} ...")
        try:
            if IS_WINDOWS:
                os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
        except (OSError, ValueError) as exc:
            self.log.add(f"[{_now_text()}] 发送停止信号失败（{exc}），稍后强制结束。")
        try:
            proc.wait(timeout=timeout)
            return True, f"{label}已停止。"
        except subprocess.TimeoutExpired:
            self.log.add(f"[{_now_text()}] {label}未在 {timeout:g} 秒内退出，强制结束进程树。")
            self._kill_tree(proc)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return True, f"{label}已强制结束。"

    def _kill_tree(self, proc: subprocess.Popen[str]) -> None:
        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            return
        for child in children:
            try:
                child.terminate()
            except PSUTIL_ERROR:
                pass
        try:
            parent.terminate()
        except PSUTIL_ERROR:
            pass
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)
        for item in alive:
            try:
                item.kill()
            except PSUTIL_ERROR:
                pass

    # ------------------------------------------------------------------ 外部进程
    def find_external_main(self, max_age: float = 5.0) -> list[dict[str, Any]]:
        """找不是本界面启动的 main.py（例如用户又双击了 start.bat）。

        只检查进程名含 python 的进程，再取 cmdline；先取所有进程的 cmdline
        在 Windows 上会碰到受保护进程，psutil 内部会反复重试，足以拖慢界面。
        结果缓存 max_age 秒，多个页面/定时器共享，避免重复扫描。
        """
        now = time.time()
        if max_age > 0 and now - self._external_cache_at < max_age:
            return list(self._external_cache)
        if max_age > 0:
            if not self._external_lock.acquire(blocking=False):
                return list(self._external_cache)
        else:
            if not self._external_lock.acquire(timeout=5.0):
                return list(self._external_cache)
        try:
            return self._find_external_main_locked()
        finally:
            self._external_lock.release()

    def _find_external_main_locked(self) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        own_pid = os.getpid()
        own_child = self._proc.pid if self._proc else None
        own_children: set[int] = set()
        try:
            own_children = {
                child.pid for child in psutil.Process(own_pid).children(recursive=False)
            }
        except PSUTIL_ERROR:
            pass
        target = self.root / "main.py"
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                pid = int(proc.info.get("pid") or 0)
                if pid in (own_pid, own_child) or pid in own_children:
                    continue
                name = str(proc.info.get("name") or "").lower()
                if "python" not in name:
                    continue
                cmdline = proc.cmdline()
                if not any(Path(str(part)).name == "main.py" for part in cmdline):
                    continue
                try:
                    cwd = proc.cwd()
                except PSUTIL_ERROR:
                    cwd = None
                absolute = any(
                    Path(str(part)).resolve() == target
                    for part in cmdline
                    if str(part).endswith("main.py")
                )
                if absolute or (cwd and Path(str(cwd)).resolve() == self.root):
                    hits.append({"pid": pid, "cwd": cwd})
            except (PSUTIL_ERROR, OSError, ValueError):
                continue
        self._external_cache = hits
        self._external_cache_at = time.time()
        return list(hits)

    def kill_external_main(self) -> tuple[bool, str]:
        """强制结束检测到的外部 main.py 及其子进程（不留收尾机会）。"""
        hits = self.find_external_main(max_age=0)
        if not hits:
            return False, "没有检测到外部的 main.py。"
        stopped: list[str] = []
        for item in hits:
            pid = int(item["pid"])
            try:
                parent = psutil.Process(pid)
                children = parent.children(recursive=True)
            except psutil.NoSuchProcess:
                stopped.append(f"{pid}（已退出）")
                continue
            except PSUTIL_ERROR as exc:
                stopped.append(f"{pid}（失败：{exc}）")
                continue
            for child in children:
                try:
                    child.terminate()
                except PSUTIL_ERROR:
                    pass
            try:
                parent.terminate()
            except PSUTIL_ERROR:
                pass
            _gone, alive = psutil.wait_procs(children + [parent], timeout=5)
            for proc in alive:
                try:
                    proc.kill()
                except PSUTIL_ERROR:
                    pass
            stopped.append(str(pid))
        self._external_cache = []
        self._external_cache_at = 0.0
        message = f"已强制结束外部 main.py（PID {'、'.join(stopped)}）。"
        self.log.add(f"[{_now_text()}] {message}")
        return True, message
