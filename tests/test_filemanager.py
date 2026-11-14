# -*- coding: utf-8 -*-
"""FileManager：时间范围、文件夹时间解析、去重子进程调用约定。"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

import main as main_module
from tests.test_appconfig import _write_yaml


@pytest.fixture
def file_manager(tmp_path):
    # upload_dir 指到 tmp，避免 _process_video 在仓库里建 Upload/videos；
    # AppConfig 要求上传目录已存在（create=False），先建好。
    (tmp_path / "up").mkdir()
    cfg = main_module.AppConfig(
        config_path=str(_write_yaml(tmp_path, upload_dir=tmp_path / "up"))
    )
    manager = main_module.FileManager(cfg)
    return manager, cfg


def test_generate_time_range_format_and_span(file_manager):
    manager, _ = file_manager
    result = manager.generate_time_range(60)
    assert re.match(
        r"^\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}\|\d{4}-\d{2}-\d{2} \d{2}-\d{2}-\d{2}$",
        result,
    )
    start, end = result.split("|")
    delta = datetime.strptime(end, "%Y-%m-%d %H-%M-%S") - datetime.strptime(
        start, "%Y-%m-%d %H-%M-%S"
    )
    assert delta.total_seconds() == 60 * 60


def test_parse_folder_time(file_manager):
    manager, _ = file_manager
    assert manager._parse_folder_time("2025-03-07 21-00-00") == datetime(2025, 3, 7, 21, 0, 0)
    assert manager._parse_folder_time("junk") is None


def test_dedup_videos_bad_range_returns_zero(file_manager):
    manager, _ = file_manager
    assert manager.dedup_videos("not-a-range") == 0


class _FakePopen:
    instances = []

    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.returncode = 0
        _FakePopen.instances.append(self)

    def wait(self):
        return self.returncode


def test_process_video_calls_dedup_cli(file_manager, tmp_path, monkeypatch):
    manager, cfg = file_manager
    _FakePopen.instances.clear()
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"fake")
    assert manager._process_video(input_file) is True
    proc = _FakePopen.instances[-1]
    assert proc.args[0] == sys.executable
    assert proc.args[1] == str(cfg.DEDUP_SCRIPT)
    assert proc.args[2:] == ["-i", str(input_file), "-o", str(cfg.UPLOAD_DIR / "videos" / "clip.mp4")]
    assert proc.kwargs.get("cwd") == cfg.DEDUP_DIR
    assert (cfg.UPLOAD_DIR / "videos").is_dir()


def test_process_video_nonzero_exit_returns_false(file_manager, tmp_path, monkeypatch):
    manager, _ = file_manager

    class _FailPopen(_FakePopen):
        def __init__(self, args, **kwargs):
            super().__init__(args, **kwargs)
            self.returncode = 1

    monkeypatch.setattr(subprocess, "Popen", _FailPopen)
    input_file = tmp_path / "clip.mp4"
    input_file.write_bytes(b"fake")
    assert manager._process_video(input_file) is False


def test_get_video_files_supports_f2_nested_layout(file_manager, tmp_path):
    """f2 落盘是 <download_dir>/<昵称>/<作品时间>/*.mp4，也要能扫到。"""
    manager, cfg = file_manager
    download_dir = cfg.DOWNLOAD_DIR
    download_dir.mkdir(parents=True, exist_ok=True)

    # 结构一：download_dir 直接是 <作品时间>
    flat = download_dir / "2025-03-07 21-00-00"
    flat.mkdir()
    (flat / "flat.mp4").write_bytes(b"x")

    # 结构二：download_dir 是 <昵称>，作品时间在下一层
    nested = download_dir / "nickname" / "2025-03-07 21-30-00"
    nested.mkdir(parents=True)
    (nested / "nested.mp4").write_bytes(b"x")

    # 不在时间范围内的作品不取
    other = download_dir / "nickname" / "2025-03-07 23-00-00"
    other.mkdir(parents=True)
    (other / "late.mp4").write_bytes(b"x")

    start = datetime(2025, 3, 7, 20, 45, 0)
    end = datetime(2025, 3, 7, 21, 45, 0)
    found = {p.name for p in manager._get_video_files(start, end)}
    assert found == {"flat.mp4", "nested.mp4"}
