# -*- coding: utf-8 -*-
"""多博主抓取 + 抖音上传接入（2026-11-12）：
sources 列表解析、逐源抓取聚合、多上传脚本、抖音批量上传的纯函数。
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import main as main_module
from tests.helpers import REPO_ROOT
from tests.test_appconfig import ENV_NAMES, _write_yaml

AppConfig = main_module.AppConfig


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield


def _write_sources_yaml(tmp_path, sources, upload_scripts=None, interval=60,
                        timezone="Asia/Shanghai", max_workers=2):
    data = {
        "video_mover": {
            "sources": sources,
            "paths": {
                "dedup_dir": str(REPO_ROOT / "Dedup"),
                "upload_dir": str(REPO_ROOT / "Upload"),
                "flush_script": str(REPO_ROOT / "flush_device_id.py"),
                "dedup_script": str(REPO_ROOT / "Dedup" / "dedup.py"),
            },
            "schedule": {"interval_minutes": interval, "timezone": timezone},
            "runtime": {"max_workers": max_workers, "config_file": "my_apps.yaml"},
        }
    }
    if upload_scripts is not None:
        data["video_mover"]["paths"]["upload_scripts"] = upload_scripts
    else:
        data["video_mover"]["paths"]["upload_script"] = str(REPO_ROOT / "Upload" / "douyin_upload.py")
    path = tmp_path / "my_apps.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _load_douyin_upload():
    spec = importlib.util.spec_from_file_location(
        "douyin_upload", REPO_ROOT / "Upload" / "douyin_upload.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------ sources 解析

def test_sources_list_parsed_with_derived_values(tmp_path):
    dl2 = tmp_path / "dl2"
    sources = [
        {"platform": "douyin", "account": "@dance2026",
         "url": "https://www.douyin.com/@dance2026"},
        {"platform": "douyin", "account": "@travelvlog",
         "url": "https://www.douyin.com/@travelvlog",
         "f2_command": ["f2", "dy"], "download_dir": str(dl2)},
        {"platform": "tiktok", "account": "@catclips",
         "url": "https://www.tiktok.com/@catclips"},
    ]
    try:
        cfg = AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))
        assert len(cfg.SOURCES) == 3
        first, second, third = cfg.SOURCES
        # 第一个抖音源：f2_command 与下载目录都是按平台/账号推导的
        assert first["platform"] == "douyin"
        assert first["account"] == "@dance2026"
        assert first["f2_command"] == ["f2", "dy"]
        assert first["download_dir"] == REPO_ROOT / "Download" / "douyin" / "post" / "dance2026"
        assert first["main_command"][:2] == ["f2", "dy"]
        assert first["main_command"][-1] == "https://www.douyin.com/@dance2026"
        # 第二个源：显式写的值优先
        assert second["download_dir"] == dl2
        assert second["f2_command"] == ["f2", "dy"]
        # 第三个 TikTok 源：同样按平台推导
        assert third["f2_command"] == ["f2", "tk"]
        assert third["download_dir"] == REPO_ROOT / "Download" / "tiktok" / "post" / "catclips"
        # 兼容旧属性恒等于第一个源
        assert cfg.SOURCE_PLATFORM == "douyin"
        assert cfg.SOURCE_ACCOUNT == "@dance2026"
        assert cfg.SOURCE_URL == "https://www.douyin.com/@dance2026"
        assert cfg.F2_COMMAND == ["f2", "dy"]
        assert cfg.MAIN_COMMAND == first["main_command"]
        assert cfg.DOWNLOAD_DIR == first["download_dir"]
        assert cfg.DOWNLOAD_DIRS == [s["download_dir"] for s in cfg.SOURCES]
    finally:
        shutil.rmtree(REPO_ROOT / "Download", ignore_errors=True)


def test_legacy_single_source_builds_one_entry(tmp_path):
    cfg = AppConfig(config_path=str(_write_yaml(tmp_path)))
    assert len(cfg.SOURCES) == 1
    assert cfg.SOURCES[0]["platform"] == "tiktok"
    assert cfg.SOURCES[0]["account"] == "@tester"
    assert cfg.DOWNLOAD_DIRS == [cfg.DOWNLOAD_DIR]
    assert cfg.MAIN_COMMAND[:2] == ["f2", "tk"]


def test_empty_sources_raises(tmp_path):
    with pytest.raises(ValueError, match="sources"):
        AppConfig(config_path=str(_write_sources_yaml(tmp_path, [])))


def test_source_without_url_raises(tmp_path):
    sources = [{"platform": "douyin", "account": "@no_url"}]
    with pytest.raises(ValueError, match="缺少 url"):
        AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))


def test_unknown_platform_without_f2_command_raises(tmp_path):
    sources = [{"platform": "weibo", "account": "@wb",
                "url": "https://weibo.com/u/123"}]
    with pytest.raises(ValueError, match="f2_command"):
        AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))


# ------------------------------------------------------------------ 逐源抓取

class _FakePopen:
    instances = []

    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.returncode = 0
        _FakePopen.instances.append(self)

    def wait(self):
        return self.returncode


def _config_with_two_sources(tmp_path):
    sources = [
        {"platform": "douyin", "account": "@a", "url": "https://www.douyin.com/@a",
         "download_dir": str(tmp_path / "dl-a")},
        {"platform": "douyin", "account": "@b", "url": "https://www.douyin.com/@b",
         "download_dir": str(tmp_path / "dl-b")},
    ]
    return AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))


def test_execute_main_command_runs_each_source(tmp_path, monkeypatch):
    cfg = _config_with_two_sources(tmp_path)
    handler = main_module.MainCommandHandler(cfg)
    seen = []

    def fake_run(command):
        seen.append(command)
        return True, False

    monkeypatch.setattr(handler, "_run_command", fake_run)
    success, forbidden = handler.execute_main_command("2026-11-12 10-00-00|2026-11-12 11-00-00")
    assert (success, forbidden) == (True, False)
    assert len(seen) == 2
    assert seen[0][:2] == ["f2", "dy"]
    assert seen[0][-4:] == ["-u", "https://www.douyin.com/@a", "-i",
                            "2026-11-12 10-00-00|2026-11-12 11-00-00"]
    assert seen[1][-3] == "https://www.douyin.com/@b"


def test_execute_main_command_aggregates_results(tmp_path, monkeypatch):
    cfg = _config_with_two_sources(tmp_path)
    handler = main_module.MainCommandHandler(cfg)
    calls = {"n": 0}

    def fake_run(command):
        calls["n"] += 1
        # 第一个源失败且 403，第二个源成功：整体仍算成功，但要上报 forbidden
        return (False, True) if calls["n"] == 1 else (True, False)

    monkeypatch.setattr(handler, "_run_command", fake_run)
    success, forbidden = handler.execute_main_command("t0|t1")
    assert (success, forbidden) == (True, True)
    assert calls["n"] == 2  # 一个源失败不中断其余源


def test_execute_main_command_all_fail(tmp_path, monkeypatch):
    cfg = _config_with_two_sources(tmp_path)
    handler = main_module.MainCommandHandler(cfg)
    monkeypatch.setattr(handler, "_run_command", lambda command: (False, False))
    assert handler.execute_main_command("t0|t1") == (False, False)


class _FakeStdout:
    def __init__(self, lines):
        self._lines = iter(lines)

    def readline(self):
        return next(self._lines, "")


class _FakePopenWithOutput(_FakePopen):
    def __init__(self, args, **kwargs):
        super().__init__(args, **kwargs)
        self.stdout = _FakeStdout(["downloading...\n", "403 Forbidden\n"])
        self.returncode = 1

    def poll(self):
        return self.returncode


def test_run_command_detects_403(tmp_path, monkeypatch):
    cfg = _config_with_two_sources(tmp_path)
    handler = main_module.MainCommandHandler(cfg)
    monkeypatch.setattr(subprocess, "Popen", _FakePopenWithOutput)
    success, forbidden = handler._run_command(["f2", "dy"])
    assert (success, forbidden) == (False, True)


# ------------------------------------------------------------------ 多下载目录扫描

def test_filemanager_scans_all_download_dirs(tmp_path):
    sources = [
        {"platform": "douyin", "account": "@a", "url": "https://www.douyin.com/@a",
         "download_dir": str(tmp_path / "dl-a")},
        {"platform": "douyin", "account": "@b", "url": "https://www.douyin.com/@b",
         "download_dir": str(tmp_path / "dl-b")},
    ]
    cfg = AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))
    (tmp_path / "dl-a" / "2026-11-12 10-00-00").mkdir(parents=True)
    (tmp_path / "dl-b" / "2026-11-12 10-30-00").mkdir(parents=True)
    (tmp_path / "dl-a" / "2026-11-12 10-00-00" / "2026-11-12 10-00-00_video.mp4").write_bytes(b"x")
    (tmp_path / "dl-b" / "2026-11-12 10-30-00" / "2026-11-12 10-30-00_video.mp4").write_bytes(b"x")
    # 时间窗之外的不取
    (tmp_path / "dl-a" / "2026-11-11 10-00-00").mkdir(parents=True)
    (tmp_path / "dl-a" / "2026-11-11 10-00-00" / "2026-11-11 10-00-00_video.mp4").write_bytes(b"x")
    manager = main_module.FileManager(cfg)
    try:
        from datetime import datetime
        files = manager._get_video_files(datetime(2026, 11, 12, 9, 0, 0),
                                         datetime(2026, 11, 12, 11, 0, 0))
        assert sorted(p.name for p in files) == [
            "2026-11-12 10-00-00_video.mp4", "2026-11-12 10-30-00_video.mp4",
        ]
    finally:
        # conftest 里的 watchdog 替身没有 join（真实 Observer 有），只 stop 即可。
        manager.observer.stop()


# ------------------------------------------------------------------ 多上传脚本

def test_upload_handler_runs_all_scripts(tmp_path, monkeypatch):
    cfg = AppConfig(config_path=str(_write_sources_yaml(
        tmp_path,
        [{"platform": "douyin", "account": "@a", "url": "https://www.douyin.com/@a",
          "download_dir": str(tmp_path / "dl-a")}],
        upload_scripts=[str(REPO_ROOT / "Upload" / "douyin_upload.py"),
                        str(REPO_ROOT / "Upload" / "vx_upload.py")],
    )))
    assert [p.name for p in cfg.UPLOAD_SCRIPTS] == ["douyin_upload.py", "vx_upload.py"]
    assert cfg.UPLOAD_SCRIPT.name == "douyin_upload.py"
    _FakePopen.instances.clear()
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    handler = main_module.UploadHandler(cfg)
    assert handler.run() is True
    assert [p.args[1] for p in _FakePopen.instances] == [
        str(REPO_ROOT / "Upload" / "douyin_upload.py"),
        str(REPO_ROOT / "Upload" / "vx_upload.py"),
    ]
    assert all(p.args[0] == sys.executable for p in _FakePopen.instances)


def test_upload_handler_one_failure_fails_overall(tmp_path, monkeypatch):
    cfg = AppConfig(config_path=str(_write_sources_yaml(
        tmp_path,
        [{"platform": "douyin", "account": "@a", "url": "https://www.douyin.com/@a",
          "download_dir": str(tmp_path / "dl-a")}],
        upload_scripts=[str(REPO_ROOT / "Upload" / "douyin_upload.py"),
                        str(REPO_ROOT / "Upload" / "vx_upload.py")],
    )))

    class _FailSecond(_FakePopen):
        def __init__(self, args, **kwargs):
            super().__init__(args, **kwargs)
            if "vx_upload" in args[1]:
                self.returncode = 1

    monkeypatch.setattr(subprocess, "Popen", _FailSecond)
    handler = main_module.UploadHandler(cfg)
    assert handler.run() is False


# ------------------------------------------------------------------ 抖音批量上传纯函数

def test_parse_desc_text(tmp_path):
    mod = _load_douyin_upload()
    title, tags = mod.parse_desc_text("我的爆款标题\n#旅行 #美食 #旅行 #日常\n")
    assert title == "我的爆款标题"
    assert tags == ["旅行", "美食", "日常"]  # 去重、去 #


def test_parse_desc_text_truncates_long_title():
    mod = _load_douyin_upload()
    title, tags = mod.parse_desc_text("这是一个超过三十个字的超长标题这是一个超过三十个字的超长标题\n#标签\n")
    assert len(title) == 30


def test_parse_desc_text_empty():
    mod = _load_douyin_upload()
    assert mod.parse_desc_text("") == ("", [])


def test_find_desc_file_and_resolve_title_tags(tmp_path):
    mod = _load_douyin_upload()
    dl = tmp_path / "dl"
    folder = dl / "2026-11-12 10-00-00"
    folder.mkdir(parents=True)
    (folder / "2026-11-12 10-00-00_desc.txt").write_text(
        "原视频标题\n#舞蹈 #热门\n", encoding="utf-8")
    video = tmp_path / "2026-11-12 10-00-00_video.mp4"
    video.write_bytes(b"x")
    assert mod.find_desc_file(video, [dl]).name == "2026-11-12 10-00-00_desc.txt"
    assert mod.resolve_title_tags(video, [dl]) == ("原视频标题", ["舞蹈", "热门"])
    # 找不到描述文件时用文件名兜底
    other = tmp_path / "clip.mp4"
    other.write_bytes(b"x")
    assert mod.resolve_title_tags(other, [dl]) == ("clip", [])
    assert mod.find_desc_file(other, [dl]) is None


def test_collect_videos(tmp_path):
    mod = _load_douyin_upload()
    videos = tmp_path / "videos"
    videos.mkdir()
    (videos / "b.mp4").write_bytes(b"x")
    (videos / "a.mp4").write_bytes(b"x")
    (videos / "notes.txt").write_text("ignore", encoding="utf-8")
    assert [p.name for p in mod.collect_videos(videos)] == ["a.mp4", "b.mp4"]
    assert mod.collect_videos(tmp_path / "no-such-dir") == []


def test_resolve_download_dirs(tmp_path):
    mod = _load_douyin_upload()
    dl_a = tmp_path / "dl-a"
    dl_a.mkdir()
    section = {
        "sources": [
            {"platform": "douyin", "account": "@a", "download_dir": str(dl_a)},
            {"platform": "douyin", "account": "@missing"},  # 推导出的目录不存在，跳过
        ]
    }
    assert mod._resolve_download_dirs(section, tmp_path) == [dl_a]
    # 旧版单 source：回落到 paths.download_dir
    dl_old = tmp_path / "dl-old"
    dl_old.mkdir()
    assert mod._resolve_download_dirs(
        {"paths": {"download_dir": str(dl_old)}}, tmp_path) == [dl_old]


def test_load_video_mover_section_missing_file(tmp_path):
    mod = _load_douyin_upload()
    with pytest.raises(FileNotFoundError, match="找不到配置文件"):
        mod._load_video_mover_section(tmp_path / "no-such.yaml")
