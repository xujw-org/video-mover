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
    # 这个用例故意用“推导出的默认下载目录”，会落在仓库根目录的 Download/ 下。
    # 清理时只能删本次测试自己建的那两个空目录——以前是
    # shutil.rmtree(REPO_ROOT / "Download")，会把用户真实下载的视频一起删掉。
    derived_dirs = [
        REPO_ROOT / "Download" / "douyin" / "post" / "dance2026",
        REPO_ROOT / "Download" / "tiktok" / "post" / "catclips",
    ]
    preexisting = {path for path in derived_dirs if path.exists()}
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
        assert first["f2_command"] == ["f2", "dy", "-M", "post"]
        assert first["download_dir"] == REPO_ROOT / "Download" / "douyin" / "post" / "dance2026"
        assert first["main_command"][:2] == ["f2", "dy"]
        assert first["main_command"][-1] == "https://www.douyin.com/@dance2026"
        # 第二个源：显式写的值优先
        assert second["download_dir"] == dl2
        # 配置里写了 ["f2", "dy"]，缺 mode 也会被补上
        assert second["f2_command"] == ["f2", "dy", "-M", "post"]
        # 第三个 TikTok 源：同样按平台推导
        assert third["f2_command"] == ["f2", "tk", "-M", "post"]
        assert third["download_dir"] == REPO_ROOT / "Download" / "tiktok" / "post" / "catclips"
        # 兼容旧属性恒等于第一个源
        assert cfg.SOURCE_PLATFORM == "douyin"
        assert cfg.SOURCE_ACCOUNT == "@dance2026"
        assert cfg.SOURCE_URL == "https://www.douyin.com/@dance2026"
        assert cfg.F2_COMMAND == ["f2", "dy", "-M", "post"]
        assert cfg.MAIN_COMMAND == first["main_command"]
        assert cfg.DOWNLOAD_DIR == first["download_dir"]
        assert cfg.DOWNLOAD_DIRS == [s["download_dir"] for s in cfg.SOURCES]
    finally:
        for path in derived_dirs:
            if path in preexisting:
                continue
            shutil.rmtree(path, ignore_errors=True)
            for parent in (path.parent, path.parent.parent, path.parent.parent.parent):
                try:
                    parent.rmdir()  # 只删空目录，Download 里还有别的东西就留着
                except OSError:
                    break


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
    """两个 tiktok 源：走 f2 子进程那条分支（抖音现在走浏览器通道，见下面的用例）。"""
    sources = [
        {"platform": "tiktok", "account": "@a", "url": "https://www.tiktok.com/@a",
         "download_dir": str(tmp_path / "dl-a")},
        {"platform": "tiktok", "account": "@b", "url": "https://www.tiktok.com/@b",
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
    assert seen[0][:2] == ["f2", "tk"]
    assert seen[0][-4:] == ["-u", "https://www.tiktok.com/@a", "-i",
                            "2026-11-12 10-00-00|2026-11-12 11-00-00"]
    assert seen[1][-3] == "https://www.tiktok.com/@b"


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


# --------------------------------------------------------------------------
# f2 下载模式：不带 -M 时 f2 0.0.1.7 直接报错退出
# --------------------------------------------------------------------------
def test_ensure_mode_appends_default():
    import main as main_module

    assert main_module._ensure_mode(["f2", "dy"]) == ["f2", "dy", "-M", "post"]


@pytest.mark.parametrize(
    "command",
    [
        ["f2", "dy", "-M", "like"],
        ["f2", "dy", "--mode", "one"],
    ],
)
def test_ensure_mode_keeps_explicit_mode(command):
    import main as main_module

    assert main_module._ensure_mode(command) == command


def test_ensure_mode_does_not_mutate_input():
    import main as main_module

    original = ["f2", "dy"]
    main_module._ensure_mode(original)
    assert original == ["f2", "dy"]

def test_execute_main_command_routes_douyin_to_browser_fetcher(tmp_path, monkeypatch):
    """抖音源不走 f2（会被 Argus 签名挡成 403），走 douyin_fetch 的浏览器通道。"""
    from datetime import datetime

    sources = [
        {"platform": "douyin", "account": "@a", "url": "https://www.douyin.com/@a",
         "download_dir": str(tmp_path / "dl-a")},
        {"platform": "tiktok", "account": "@b", "url": "https://www.tiktok.com/@b",
         "download_dir": str(tmp_path / "dl-b")},
    ]
    cfg = AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))
    handler = main_module.MainCommandHandler(cfg)

    fetched = []
    f2_calls = []

    def fake_fetch(url, **kwargs):
        fetched.append((url, kwargs))
        return 3

    monkeypatch.setattr(main_module.douyin_fetch, "fetch_and_download", fake_fetch)
    monkeypatch.setattr(handler, "_run_command",
                        lambda command: (f2_calls.append(command), (True, False))[1])

    success, forbidden = handler.execute_main_command(
        "2026-11-12 10-00-00|2026-11-12 11-00-00")

    assert (success, forbidden) == (True, False)
    assert fetched == [(
        "https://www.douyin.com/@a",
        {
            "download_dir": cfg.SOURCES[0]["download_dir"],
            "config_path": cfg.CONFIG_FILE,
            "since": datetime(2026, 11, 12, 10, 0, 0),
            "until": datetime(2026, 11, 12, 11, 0, 0),
            "max_items": None,  # 未开补抓时不限量
        },
    )]
    # 抖音源不产生 f2 子进程，只有 tiktok 源会
    assert len(f2_calls) == 1
    assert f2_calls[0][:2] == ["f2", "tk"]


def test_execute_main_command_douyin_failure_does_not_break_others(tmp_path, monkeypatch):
    sources = [
        {"platform": "douyin", "account": "@a", "url": "https://www.douyin.com/@a",
         "download_dir": str(tmp_path / "dl-a")},
        {"platform": "tiktok", "account": "@b", "url": "https://www.tiktok.com/@b",
         "download_dir": str(tmp_path / "dl-b")},
    ]
    cfg = AppConfig(config_path=str(_write_sources_yaml(tmp_path, sources)))
    handler = main_module.MainCommandHandler(cfg)

    def boom(url, **kwargs):
        raise RuntimeError("浏览器起不来")

    monkeypatch.setattr(main_module.douyin_fetch, "fetch_and_download", boom)
    monkeypatch.setattr(handler, "_run_command", lambda command: (True, False))

    # 抖音失败，tiktok 成功 -> 整体成功
    assert handler.execute_main_command("t0|t1") == (True, False)


# ------------------------------------------------------------------ 上传模式开关

def test_apply_upload_options_defaults_to_headless():
    mod = _load_douyin_upload()
    environ = {}
    opts = mod.apply_upload_options({}, environ)
    assert opts == {"headless": True, "dry_run": False}
    assert "DOUYIN_UPLOAD_HEADED" not in environ
    assert "DOUYIN_UPLOAD_DRY_RUN" not in environ


def test_apply_upload_options_reads_config():
    mod = _load_douyin_upload()
    environ = {}
    opts = mod.apply_upload_options({"headless": False, "dry_run": "yes"}, environ)
    assert opts == {"headless": False, "dry_run": True}
    assert environ["DOUYIN_UPLOAD_HEADED"] == "1"
    assert environ["DOUYIN_UPLOAD_DRY_RUN"] == "1"


def test_apply_upload_options_env_can_only_make_it_safer():
    mod = _load_douyin_upload()
    # 配置要无窗口，但调试时设了 HEADED -> 有界面
    opts = mod.apply_upload_options({"headless": True}, {"DOUYIN_UPLOAD_HEADED": "1"})
    assert opts["headless"] is False
    # 配置没开 dry_run，但一次性设了环境变量 -> 不发布
    opts = mod.apply_upload_options({}, {"DOUYIN_UPLOAD_DRY_RUN": "1"})
    assert opts["dry_run"] is True
    # 反过来：环境变量不能把 dry_run 关掉
    opts = mod.apply_upload_options({"dry_run": True}, {})
    assert opts["dry_run"] is True


def test_truthy_values():
    mod = _load_douyin_upload()
    for value in (True, "1", "true", "YES", "on", " yes "):
        assert mod._truthy(value) is True, value
    for value in (False, "0", "false", "no", "off", "", None, "2"):
        assert mod._truthy(value) is False, value


def test_find_desc_file_supports_nested_nickname_dir(tmp_path):
    """抖音浏览器通道的落盘多一层昵称，描述文件也要能找到。"""
    mod = _load_douyin_upload()
    download_dir = tmp_path / "dl"
    nested = download_dir / "杨超越" / "2026-11-12 11-00-25"
    nested.mkdir(parents=True)
    desc = nested / "2026-11-12 11-00-25_desc.txt"
    desc.write_text("标题 #话题\n", encoding="utf-8")

    video = tmp_path / "videos" / "2026-11-12 11-00-25_video.mp4"
    video.parent.mkdir()
    video.write_bytes(b"x")

    assert mod.find_desc_file(video, [download_dir]) == desc
    # 本层直接命中也要支持（f2 老结构）
    flat = download_dir / "2026-11-12 11-00-25"
    flat.mkdir(parents=True, exist_ok=True)
    (flat / "2026-11-12 11-00-25_desc.txt").write_text("本层\n", encoding="utf-8")
    assert mod.find_desc_file(video, [download_dir]).parent == flat


def test_resolve_download_dirs_includes_parent_for_nickname_layout(tmp_path, monkeypatch):
    """配置目录不存在、只有上一层（抖音浏览器通道的默认参数抓法）时也要能搜到。"""
    mod = _load_douyin_upload()
    mode_dir = tmp_path / "Download" / "douyin" / "post"
    (mode_dir / "杨超越").mkdir(parents=True)
    section = {"sources": [{"platform": "douyin", "account": "@a"}]}
    dirs = mod._resolve_download_dirs(section, tmp_path)
    # 配置推导出的是 <mode>/a（不存在），实际搜到的是它的上一层 <mode>
    assert dirs == [mode_dir]


# ------------------------------------------------------------------ 补抓历史 / 队列模式

def _backfill_config(tmp_path, **backfill):
    sources = [{"platform": "douyin", "account": "@a",
                "url": "https://www.douyin.com/@a",
                "download_dir": str(tmp_path / "dl")}]
    path = _write_sources_yaml(tmp_path, sources)
    import yaml as _yaml

    data = _yaml.safe_load(path.read_text(encoding="utf-8"))
    data["video_mover"]["backfill"] = backfill
    path.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cfg = AppConfig(config_path=str(path))
    cfg.STATE_FILE = tmp_path / "state" / "processed.json"
    return cfg


def test_backfill_config_defaults_and_overrides(tmp_path):
    cfg = _backfill_config(tmp_path, days=30, max_per_source=5, max_per_run=2)
    assert cfg.BACKFILL_DAYS == 30
    assert cfg.BACKFILL_MAX_PER_SOURCE == 5
    assert cfg.BACKFILL_MAX_PER_RUN == 2

    # 不写 backfill 时默认关闭补抓
    plain = AppConfig(config_path=str(_write_sources_yaml(
        tmp_path, [{"platform": "douyin", "account": "@a",
                    "url": "https://www.douyin.com/@a",
                    "download_dir": str(tmp_path / "dl2")}])))
    assert plain.BACKFILL_DAYS == 0


def test_backfill_rejects_out_of_range_days(tmp_path):
    import pytest as _pytest

    with _pytest.raises(ValueError):
        _backfill_config(tmp_path, days=999)
    with _pytest.raises(ValueError):
        _backfill_config(tmp_path, days="junk")


def test_pending_files_skips_processed_and_respects_limit(tmp_path):
    cfg = _backfill_config(tmp_path, days=30, max_per_run=2)
    dl = cfg.DOWNLOAD_DIRS[0]
    made = []
    for day, hour in ((10, 10), (11, 11), (12, 12)):
        folder = dl / f"2026-11-{day} {hour}-00-00"
        folder.mkdir(parents=True, exist_ok=True)
        video = folder / f"2026-11-{day} {hour}-00-00_video.mp4"
        video.write_bytes(b"x")
        made.append(video)

    manager = main_module.FileManager(cfg)
    try:
        pending = manager._get_pending_files(limit=10)
        # 先空队列里的全部文件，按作品时间从旧到新
        assert pending == made

        # 记一条已处理，队列里就不该再出现
        manager._record_processed(made[0])
        assert manager._get_pending_files(limit=10) == made[1:]

        # 每轮上限：只剩两条待办，limit=1 只取最旧的那条
        assert manager._get_pending_files(limit=1) == made[1:2]
    finally:
        manager.observer.stop()


def test_dedup_videos_in_backfill_mode_consumes_queue_and_records_state(tmp_path, monkeypatch):
    cfg = _backfill_config(tmp_path, days=30, max_per_run=1)
    dl = cfg.DOWNLOAD_DIRS[0]
    old_folder = dl / "2026-11-10 10-00-00"     # 远早于当前时间窗
    old_folder.mkdir(parents=True)
    old_video = old_folder / "2026-11-10 10-00-00_video.mp4"
    old_video.write_bytes(b"x")

    manager = main_module.FileManager(cfg)
    processed = []
    monkeypatch.setattr(manager, "_process_video",
                        lambda f: (processed.append(f), True)[1])
    try:
        count = manager.dedup_videos("2026-11-14 00-00-00|2026-11-14 05-00-00")
        assert count == 1
        assert processed == [old_video]          # 时间窗外的历史作品也被处理了
        # 处理成功要记进 state，第二轮不会重复处理
        assert old_video.name in "".join(manager._load_processed())
        assert manager.dedup_videos("2026-11-14 00-00-00|2026-11-14 05-00-00") == 0
    finally:
        manager.observer.stop()


def test_dedup_videos_without_backfill_still_uses_time_window(tmp_path, monkeypatch):
    cfg = _backfill_config(tmp_path, days=0)
    dl = cfg.DOWNLOAD_DIRS[0]
    (dl / "2026-11-10 10-00-00").mkdir(parents=True)
    (dl / "2026-11-10 10-00-00" / "2026-11-10 10-00-00_video.mp4").write_bytes(b"x")

    manager = main_module.FileManager(cfg)
    monkeypatch.setattr(manager, "_process_video", lambda f: True)
    try:
        # 时间窗内没有作品 -> 0（窗口外的历史作品不会被碰）
        assert manager.dedup_videos("2026-11-14 00-00-00|2026-11-14 05-00-00") == 0
    finally:
        manager.observer.stop()


def test_execute_main_command_backfill_widens_window(tmp_path, monkeypatch):
    from datetime import datetime as _dt, timedelta as _td

    cfg = _backfill_config(tmp_path, days=30, max_per_source=7)
    handler = main_module.MainCommandHandler(cfg)
    calls = []
    monkeypatch.setattr(main_module.douyin_fetch, "fetch_and_download",
                        lambda url, **kw: (calls.append((url, kw)), 0)[1])
    monkeypatch.setattr(handler, "_run_command", lambda command: (True, False))

    handler.execute_main_command("2026-11-14 00-00-00|2026-11-14 05-00-00")
    assert len(calls) == 1
    _, kwargs = calls[0]
    span = kwargs["until"] - kwargs["since"]
    assert abs(span - _td(days=30)) < _td(minutes=1)   # 窗口被放大到 30 天
    assert kwargs["max_items"] == 7
