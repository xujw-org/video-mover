# -*- coding: utf-8 -*-
"""GUI 配置层回归测试：模板复制、round-trip、校验、.env 写入。"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT
from vm_gui.checks import config_checks
from vm_gui.config import (
    ConfigError,
    ConfigStore,
    default_draft,
    read_dotenv,
    validate_draft,
    write_dotenv_value,
)


def _store(tmp_path: Path) -> ConfigStore:
    shutil.copyfile(REPO_ROOT / "my_apps.yaml.example", tmp_path / "my_apps.yaml.example")
    return ConfigStore(tmp_path)


def test_ensure_config_copies_template(tmp_path):
    store = _store(tmp_path)
    assert store.ensure_config() is True
    assert store.path.is_file()
    assert store.ensure_config() is False


def test_roundtrip_keeps_other_sections_and_comments(tmp_path):
    store = _store(tmp_path)
    store.ensure_config()
    store.path.write_text(
        store.path.read_text(encoding="utf-8") + "\ncustom_section:\n  keep: me\n",
        encoding="utf-8",
    )
    draft = store.load()
    draft["sources"][0]["account"] = "@new"
    draft["sources"][0]["url"] = "https://www.douyin.com/@new"
    draft["upload"]["headless"] = False
    draft["f2"]["douyin_cookie"] = "a=b; c=d"
    store.save(draft, validate=False)

    reloaded = store.load()
    assert reloaded["sources"][0]["account"] == "@new"
    assert reloaded["upload"]["headless"] is False
    assert reloaded["f2"]["douyin_cookie"] == "a=b; c=d"
    text = store.path.read_text(encoding="utf-8")
    assert "custom_section:" in text
    assert "视频源支持多个博主" in text  # 模板注释没有被 round-trip 吃掉


def test_legacy_source_is_upgraded_to_sources(tmp_path):
    store = ConfigStore(tmp_path)
    store.path.write_text(
        """
video_mover:
  source:
    platform: tiktok
    account: "@legacy"
    url: "https://www.tiktok.com/@legacy"
  paths:
    dedup_dir: "Dedup"
    upload_dir: "Upload"
    flush_script: "flush_device_id.py"
    dedup_script: "Dedup/dedup.py"
    upload_script: "Upload/douyin_upload.py"
  schedule:
    interval_minutes: 60
    timezone: "Asia/Shanghai"
""",
        encoding="utf-8",
    )
    draft = store.load()
    assert draft["sources"][0]["account"] == "@legacy"
    assert draft["paths"]["upload_scripts"] == ["Upload/douyin_upload.py"]
    store.save(draft, validate=False)
    text = store.path.read_text(encoding="utf-8")
    assert "sources:" in text
    assert "\n  source:" not in text


def test_validate_draft_reports_actionable_errors():
    draft = default_draft()
    draft["sources"] = []
    draft["schedule"]["interval_minutes"] = 0
    draft["schedule"]["timezone"] = "Mars/Olympus"
    draft["paths"]["upload_scripts"] = []
    errors = validate_draft(draft)
    assert any("至少需要一个视频源" in item for item in errors)
    assert any("1-1440" in item for item in errors)
    assert any("时区" in item for item in errors)
    assert any("上传脚本" in item for item in errors)


def test_save_rejects_invalid_draft_without_touching_file(tmp_path):
    store = _store(tmp_path)
    store.ensure_config()
    original = store.path.read_bytes()
    draft = store.load()
    draft["schedule"]["interval_minutes"] = 9999
    with pytest.raises(ConfigError, match="1-1440"):
        store.save(draft)
    assert store.path.read_bytes() == original


def test_save_uses_real_appconfig_for_validation(tmp_path):
    """保存流程会真的启动 main.AppConfig；用绝对路径避免污染仓库。"""
    dedup = tmp_path / "Dedup"
    upload = tmp_path / "Upload"
    download = tmp_path / "Download"
    for folder in (dedup, upload, download):
        folder.mkdir()
    store = ConfigStore(tmp_path)
    shutil.copyfile(REPO_ROOT / "my_apps.yaml.example", tmp_path / "my_apps.yaml.example")
    draft = default_draft()
    draft["sources"] = [
        {
            "platform": "douyin",
            "account": "@tester",
            "url": "https://www.douyin.com/@tester",
            "download_dir": str(download),
        }
    ]
    draft["schedule"] = {"interval_minutes": 30, "timezone": "Asia/Shanghai"}
    draft["paths"] = {
        "dedup_dir": str(dedup),
        "upload_dir": str(upload),
        "flush_script": str(REPO_ROOT / "flush_device_id.py"),
        "dedup_script": str(REPO_ROOT / "Dedup" / "dedup.py"),
        "upload_scripts": [str(REPO_ROOT / "Upload" / "douyin_upload.py")],
    }
    store.save(draft)
    assert store.path.is_file()
    assert "sources:" in store.path.read_text(encoding="utf-8")


def test_dotenv_roundtrip_preserves_other_lines(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# comment\nDASHSCOPE_API_KEY=old\nVIDEO_MOVER_INTERVAL_MINUTES=60\n",
        encoding="utf-8",
    )
    write_dotenv_value(path, "DASHSCOPE_API_KEY", "new key")
    values = read_dotenv(path)
    assert values["DASHSCOPE_API_KEY"] == "new key"
    assert values["VIDEO_MOVER_INTERVAL_MINUTES"] == "60"
    assert "# comment" in path.read_text(encoding="utf-8")
    assert path.read_text(encoding="utf-8").count("DASHSCOPE_API_KEY") == 1


def test_config_checks_flags_placeholder_cookie(tmp_path):
    store = _store(tmp_path)
    store.ensure_config()
    draft = store.load()
    draft["f2"]["douyin_cookie"] = "YOUR_DOYIN_COOKIE_HERE"
    draft["upload"]["douyin_account"] = "default"
    items = config_checks(store, draft)
    cookie = next(item for item in items if item["title"] == "抖音 Cookie")
    assert cookie["ok"] is False
    login = next(item for item in items if item["title"] == "上传登录态")
    assert login["ok"] is False
