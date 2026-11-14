# -*- coding: utf-8 -*-
"""AppConfig：加载、默认值、校验与环境变量覆盖（main.py 第一批改进的回归测试）。"""
from __future__ import annotations

import logging

import pytest
import yaml

import main as main_module
from tests.helpers import REPO_ROOT

AppConfig = main_module.AppConfig

ENV_NAMES = [
    "VIDEO_MOVER_CONFIG_FILE",
    "VIDEO_MOVER_SOURCE_PLATFORM", "VIDEO_MOVER_SOURCE_ACCOUNT",
    "VIDEO_MOVER_SOURCE_URL", "VIDEO_MOVER_F2_COMMAND",
    "VIDEO_MOVER_DOWNLOAD_DIR", "VIDEO_MOVER_DEDUP_DIR", "VIDEO_MOVER_UPLOAD_DIR",
    "VIDEO_MOVER_FLUSH_SCRIPT", "VIDEO_MOVER_DEDUP_SCRIPT", "VIDEO_MOVER_UPLOAD_SCRIPT",
    "VIDEO_MOVER_INTERVAL_MINUTES", "VIDEO_MOVER_TIMEZONE",
    "VIDEO_MOVER_MAX_WORKERS",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    yield


def _write_yaml(tmp_path, *, interval=60, timezone="Asia/Shanghai", account="@tester",
                download_dir=None, upload_dir=None, max_workers=2):
    data = {
        "video_mover": {
            "source": {
                "platform": "tiktok",
                "account": account,
                "url": f"https://www.tiktok.com/{account}",
                "f2_command": ["f2", "tk"],
            },
            "paths": {
                "download_dir": str(download_dir or (tmp_path / "dl")),
                "dedup_dir": str(REPO_ROOT / "Dedup"),
                "upload_dir": str(upload_dir or (REPO_ROOT / "Upload")),
                "flush_script": str(REPO_ROOT / "flush_device_id.py"),
                "dedup_script": str(REPO_ROOT / "Dedup" / "dedup.py"),
                "upload_script": str(REPO_ROOT / "Upload" / "vx_upload.py"),
            },
            "schedule": {"interval_minutes": interval, "timezone": timezone},
            "runtime": {"max_workers": max_workers, "config_file": "my_apps.yaml"},
        }
    }
    path = tmp_path / "my_apps.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_load_full_config(tmp_path):
    cfg = AppConfig(config_path=str(_write_yaml(tmp_path)))
    assert cfg.SOURCE_PLATFORM == "tiktok"
    assert cfg.SOURCE_ACCOUNT == "@tester"
    assert cfg.SOURCE_URL == "https://www.tiktok.com/@tester"
    # f2 0.0.1.7 的 douyin/tiktok CLI 不带 -M 会直接报错退出，
    # 所以缺省时自动补 "-M post"（见 main._ensure_mode）。
    assert cfg.F2_COMMAND == ["f2", "tk", "-M", "post"]
    assert cfg.SCHEDULE_INTERVAL == 60
    assert cfg.TIMEZONE == "Asia/Shanghai"
    assert cfg.MAX_WORKERS == 2
    assert cfg.MAIN_COMMAND[:2] == ["f2", "tk"]
    assert cfg.MAIN_COMMAND[-1] == "https://www.tiktok.com/@tester"
    assert cfg.DOWNLOAD_DIR.is_dir()


def test_interval_as_string_is_accepted(tmp_path):
    cfg = AppConfig(config_path=str(_write_yaml(tmp_path, interval="45")))
    assert cfg.SCHEDULE_INTERVAL == 45


@pytest.mark.parametrize("bad", [0, 1441, -5, "abc"])
def test_illegal_interval_raises(tmp_path, bad):
    with pytest.raises(ValueError, match="interval_minutes"):
        AppConfig(config_path=str(_write_yaml(tmp_path, interval=bad)))


def test_illegal_timezone_raises(tmp_path):
    with pytest.raises(ValueError, match="无效时区"):
        AppConfig(config_path=str(_write_yaml(tmp_path, timezone="Mars/Olympus")))


def test_missing_config_file_uses_defaults_with_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("VIDEO_MOVER_DOWNLOAD_DIR", str(tmp_path / "dl"))
    with caplog.at_level(logging.WARNING):
        cfg = AppConfig(config_path=str(tmp_path / "no-such.yaml"))
    assert cfg.SOURCE_ACCOUNT == "@example"
    assert cfg.SCHEDULE_INTERVAL == 300
    assert cfg.TIMEZONE == "Asia/Singapore"
    assert any("配置文件不存在" in r.message for r in caplog.records)


def test_missing_keys_use_defaults_with_warning(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv("VIDEO_MOVER_DOWNLOAD_DIR", str(tmp_path / "dl"))
    path = tmp_path / "thin.yaml"
    path.write_text("video_mover:\n  source:\n    account: '@thin'\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        cfg = AppConfig(config_path=str(path))
    assert cfg.SOURCE_ACCOUNT == "@thin"
    assert cfg.SCHEDULE_INTERVAL == 300  # schedule 小节缺失，用默认值
    assert cfg.TIMEZONE == "Asia/Singapore"
    assert any("配置缺失" in r.message for r in caplog.records)


def test_env_overrides_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_MOVER_INTERVAL_MINUTES", "45")
    monkeypatch.setenv("VIDEO_MOVER_TIMEZONE", "Europe/London")
    monkeypatch.setenv("VIDEO_MOVER_SOURCE_ACCOUNT", "@envuser")
    cfg = AppConfig(config_path=str(_write_yaml(tmp_path)))
    assert cfg.SCHEDULE_INTERVAL == 45
    assert cfg.TIMEZONE == "Europe/London"
    assert cfg.SOURCE_ACCOUNT == "@envuser"


def test_empty_env_value_falls_back_to_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_MOVER_SOURCE_ACCOUNT", "")
    cfg = AppConfig(config_path=str(_write_yaml(tmp_path)))
    assert cfg.SOURCE_ACCOUNT == "@tester"


def test_max_workers_null_means_cpu_count(tmp_path):
    path = _write_yaml(tmp_path, max_workers=None)
    cfg = AppConfig(config_path=str(path))
    assert cfg.MAX_WORKERS >= 1


def test_max_workers_zero_raises(tmp_path):
    with pytest.raises(ValueError, match="max_workers"):
        AppConfig(config_path=str(_write_yaml(tmp_path, max_workers=0)))


def test_missing_dedup_script_raises(tmp_path):
    path = _write_yaml(tmp_path)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["video_mover"]["paths"]["dedup_script"] = str(tmp_path / "no-such.py")
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="去重脚本"):
        AppConfig(config_path=str(path))
