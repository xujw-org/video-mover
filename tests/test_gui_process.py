# -*- coding: utf-8 -*-
"""GUI 后端的小工具：日志缓冲、日志尾读、上传目录清理、进程状态。"""
from __future__ import annotations

from pathlib import Path

from vm_gui.process import LogBuffer, ProcessManager, clean_upload_dir, tail_file


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


def test_tail_file_reads_last_lines(tmp_path: Path):
    path = tmp_path / "app.log"
    path.write_text("a\nb\nc\n", encoding="utf-8")
    assert tail_file(path, max_lines=2) == ["b", "c"]
    assert tail_file(tmp_path / "missing.log") == []


def test_clean_upload_dir_only_removes_mp4(tmp_path: Path):
    videos = tmp_path / "Upload" / "videos"
    videos.mkdir(parents=True)
    (videos / "a.mp4").write_bytes(b"video")
    (videos / "keep.txt").write_text("keep", encoding="utf-8")
    assert clean_upload_dir(tmp_path) == 1
    assert not (videos / "a.mp4").exists()
    assert (videos / "keep.txt").is_file()


def test_process_manager_initial_status(tmp_path: Path):
    manager = ProcessManager(tmp_path)
    status = manager.status()
    assert status["running"] is False
    assert status["exit_code"] is None
    assert status["pid"] is None
    assert manager.busy() is False
