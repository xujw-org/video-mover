# -*- coding: utf-8 -*-
"""apply_upstream_patches.py：替换原语、三个补丁的幂等性与 --check 模式。"""
from __future__ import annotations

import hashlib
import importlib.util
import sys
from pathlib import Path

import pytest

from tests.helpers import REPO_ROOT

SPEC = importlib.util.spec_from_file_location(
    "apply_upstream_patches", REPO_ROOT / "scripts" / "apply_upstream_patches.py"
)
patches = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patches)


# --- 假 f2 树：handler.py 含 5 处 cursor 取值，utils.py 含日期解析的 4 处原文 ---
HANDLER_SRC = """\
import datetime


class TikTokHandler:
    def list_a(self):
        cursor = self.kwargs.get("cursor", 0)
        cursor = self.kwargs.get("cursor", 0)
        return cursor

    def list_b(self):
            cursor = self.kwargs.get("cursor", 0)
        cursor = self.kwargs.get("cursor", 0)
        cursor = self.kwargs.get("cursor", 0)
        return cursor
"""

UTILS_SRC = """\
import datetime


def str_2_timestamp(date_str, format, unit="second"):
    date_obj = datetime.datetime.strptime(date_str, format)
    if unit == "milli":
        return date_obj


def interval_2_timestamp(interval, date_type):
    if True:
        if date_type == "start":
            date_str = f"{start_date} 00-00-00"
        elif date_type == "end":
            date_str = f"{end_date} 23-59-59"
        else:
            pass


def filter_by_date_interval(interval, date_str):
    if True:
        start_str, end_str = interval.split("|")
        start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d")
        end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d") + datetime.timedelta(
            days=1, seconds=-1
        )

        if end_date < start_date:
            return False


def check_create_time(date_str, start_date, end_date):
    if True:
        try:
            date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H-%M-%S")
        except ValueError:
            logger.warning(_("无法解析作品的创建时间：{0}").format(date_str))
            return False

        if date < start_date or date > end_date:
            return False
    return True
"""


@pytest.fixture
def fake_f2(tmp_path):
    root = tmp_path / "f2"
    (root / "apps" / "tiktok").mkdir(parents=True)
    (root / "utils").mkdir(parents=True)
    (root / "apps" / "tiktok" / "handler.py").write_text(HANDLER_SRC, encoding="utf-8")
    (root / "utils" / "utils.py").write_text(UTILS_SRC, encoding="utf-8")
    return root


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_apply_replacement_applied():
    new, status = patches.apply_replacement("aaa bbb", "bbb", "ccc", "x")
    assert new == "aaa ccc"
    assert status == "APPLIED"


def test_apply_replacement_already_applied():
    _, status = patches.apply_replacement("aaa ccc", "bbb", "ccc", "x")
    assert status == "ALREADY_APPLIED"


def test_apply_replacement_failed_when_old_missing():
    _, status = patches.apply_replacement("aaa", "bbb", "ccc", "x")
    assert status.startswith("FAILED")


def test_apply_replacement_failed_when_old_appears_twice():
    _, status = patches.apply_replacement("bbb bbb", "bbb", "ccc", "x")
    assert status.startswith("FAILED")


def test_patch_cursor_int_apply_and_idempotent(fake_f2):
    handler = fake_f2 / "apps" / "tiktok" / "handler.py"
    status = patches.patch_cursor_int(handler, check_only=False)
    assert status.startswith("APPLIED")
    text = handler.read_text(encoding="utf-8")
    assert text.count("int(self.kwargs.get(\"cursor\", 0) or 0)") == 5
    assert "cursor = self.kwargs.get(\"cursor\", 0)\n" not in text
    before = _sha(handler)
    status2 = patches.patch_cursor_int(handler, check_only=False)
    assert status2.startswith("ALREADY_APPLIED")
    assert _sha(handler) == before  # 第二次运行不改文件


def test_patch_cursor_int_check_only_does_not_write(fake_f2):
    handler = fake_f2 / "apps" / "tiktok" / "handler.py"
    before = _sha(handler)
    status = patches.patch_cursor_int(handler, check_only=True)
    assert "APPLIED" in status and "--check" in status
    assert _sha(handler) == before


def test_patch_cursor_int_failed_when_no_match(fake_f2):
    handler = fake_f2 / "apps" / "tiktok" / "handler.py"
    handler.write_text("nothing here\n", encoding="utf-8")
    assert patches.patch_cursor_int(handler, check_only=True).startswith("FAILED")


def test_patch_date_parsing_apply_and_idempotent(fake_f2):
    utils = fake_f2 / "utils" / "utils.py"
    status = patches.patch_date_parsing(utils, check_only=False)
    assert status == "APPLIED", status
    text = utils.read_text(encoding="utf-8")
    assert text.count("VIDEO-MOVER PATCH") == 4
    before = _sha(utils)
    assert patches.patch_date_parsing(utils, check_only=False) == "ALREADY_APPLIED"
    assert _sha(utils) == before


def test_patch_date_parsing_check_only_does_not_write(fake_f2):
    utils = fake_f2 / "utils" / "utils.py"
    before = _sha(utils)
    status = patches.patch_date_parsing(utils, check_only=True)
    assert status.startswith("APPLIED")
    assert _sha(utils) == before


def test_patch_tencent_timeout_already_applied_on_repo_file():
    # 本仓库自带的视频号上传代码早已是 timeout=10000，无需修改。
    tencent = REPO_ROOT / "Upload" / "uploader" / "tencent_uploader" / "main.py"
    assert patches.patch_tencent_timeout(tencent, check_only=True).startswith("ALREADY_APPLIED")


def test_main_check_mode(fake_f2, monkeypatch):
    handler = fake_f2 / "apps" / "tiktok" / "handler.py"
    utils = fake_f2 / "utils" / "utils.py"
    before = (_sha(handler), _sha(utils))
    monkeypatch.setattr(
        sys, "argv", ["apply_upstream_patches.py", "--check", "--f2-dir", str(fake_f2)]
    )
    assert patches.main() == 0
    assert (_sha(handler), _sha(utils)) == before  # --check 不写文件


def test_main_apply_then_check(fake_f2, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["apply_upstream_patches.py", "--f2-dir", str(fake_f2)]
    )
    assert patches.main() == 0
    handler = fake_f2 / "apps" / "tiktok" / "handler.py"
    assert "VIDEO-MOVER PATCH" in handler.read_text(encoding="utf-8")
    monkeypatch.setattr(
        sys, "argv", ["apply_upstream_patches.py", "--check", "--f2-dir", str(fake_f2)]
    )
    assert patches.main() == 0  # 打过补丁后 --check 也应通过


def test_main_missing_f2_dir_returns_2(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sys, "argv", ["apply_upstream_patches.py", "--f2-dir", str(tmp_path / "empty")]
    )
    assert patches.main() == 2


def test_find_f2_dir_rejects_invalid_dir(tmp_path):
    assert patches.find_f2_dir(str(tmp_path)) is None
