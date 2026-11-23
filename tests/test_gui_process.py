# -*- coding: utf-8 -*-
"""GUI 后端的小工具：日志缓冲、日志尾读、上传目录清理、进程状态。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import vm_gui.process as win_process
from vm_gui.process import LogBuffer, ProcessManager, tail_file


def test_log_buffer_is_incremental_and_bounded():
    buffer = LogBuffer(max_lines=3)
    for line in ("a", "b", "c", "d"):
        buffer.add(line)
    assert buffer.snapshot() == ["b", "c", "d"]
    assert buffer.since(0) == ["b", "c", "d"]
    assert buffer.since(buffer.count - 1) == ["d"]
    assert buffer.since(buffer.count) == []


def test_log_buffer_ignores_blank_lines():
    buffer = LogBuffer()
    buffer.add("")
    buffer.add("\n")
    buffer.add("x")
    assert buffer.snapshot() == ["x"]


def test_log_buffer_clear_resets_index():
    buffer = LogBuffer()
    buffer.add("old")
    buffer.clear()
    assert buffer.count == 0
    assert buffer.snapshot() == []
    assert buffer.since(0) == []


def test_reset_logs_rotates_app_log(tmp_path: Path):
    log_path = tmp_path / "app.log"
    log_path.write_text("old run\n", encoding="utf-8")
    manager = ProcessManager(tmp_path)
    manager.log.add("old line")
    manager.reset_logs()
    assert not log_path.exists()
    assert (tmp_path / "app.log.prev").read_text(encoding="utf-8") == "old run\n"
    lines = manager.log.snapshot()
    assert any("已清空上一轮日志" in line for line in lines)
    assert all("old line" not in line for line in lines)


def test_reset_logs_without_old_file(tmp_path: Path):
    manager = ProcessManager(tmp_path)
    manager.log.add("old line")
    manager.reset_logs()
    assert not (tmp_path / "app.log.prev").exists()
    assert manager.log.count == 1
    assert "已清空上一轮日志" in manager.log.snapshot()[0]


def test_tail_file_reads_last_lines(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    assert tail_file(path, max_lines=2) == ["b", "c"]
    assert tail_file(tmp_path / "missing.log") == []


def test_process_manager_initial_status(tmp_path: Path):
    manager = ProcessManager(tmp_path)
    status = manager.status()
    assert status["running"] is False
    assert status["exit_code"] is None
    assert status["pid"] is None
    assert manager.busy() is False


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object only")
def test_process_manager_creates_kill_on_close_job(tmp_path: Path):
    manager = ProcessManager(tmp_path)
    assert manager._job_handle


def test_kill_external_main_terminates_process_tree(tmp_path: Path, monkeypatch):
    events = []

    class FakeProc:
        def __init__(self, pid: int):
            self.pid = pid

        def children(self, recursive: bool = True):
            return []

        def terminate(self):
            events.append(f"terminate {self.pid}")

    manager = ProcessManager(tmp_path)
    monkeypatch.setattr(
        manager, "find_external_main", lambda max_age=0: [{"pid": 4242}]
    )
    monkeypatch.setattr(win_process.psutil, "Process", lambda pid: FakeProc(pid))
    monkeypatch.setattr(
        win_process.psutil, "wait_procs", lambda procs, timeout: (procs, []), raising=False
    )
    ok, message = manager.kill_external_main()
    assert ok
    assert "4242" in message
    assert events == ["terminate 4242"]


def test_kill_external_main_never_kills_its_own_process(tmp_path: Path, monkeypatch):
    manager = ProcessManager(tmp_path)
    monkeypatch.setattr(
        manager, "find_external_main", lambda max_age=0: [{"pid": os.getpid()}]
    )
    ok, message = manager.kill_external_main()
    assert ok is False
    assert "自己启动" in message
    assert "已忽略" in message
