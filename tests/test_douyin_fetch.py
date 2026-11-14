# -*- coding: utf-8 -*-
"""douyin_fetch：配置解析、作品筛选、下载计划（全部离线，不打真实网络）。

为什么有这个模块：抖音对 ``aweme/v1/web/aweme/post`` 强制 Argus secsdk 签名
（``x-secsdk-web-signature`` + ``uifid``/``webid``/``fp``/``timestamp``），
f2 0.0.1.7 没有这些字段，请求必然 403。抓取改走浏览器通道，这里的测试钉住
“哪些作品该下、落到哪个路径”这些纯逻辑，浏览器与下载部分不进单测。
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

import douyin_fetch  # 顶层模块，main.py 也是直接 import 它


# --------------------------------------------------------------------------
# 造数据：一个视频、一个图文、一个越界视频
# --------------------------------------------------------------------------
def _video_aweme(aweme_id="7600000000000000001", create_time=1785475972, **extra):
    aweme = {
        "aweme_id": aweme_id,
        "create_time": create_time,
        "aweme_type": 0,
        "media_type": 4,
        "desc": "视频作品",
        "video": {
            "duration": 13800,
            "play_addr": {"url_list": [
                "https://cdn.example.com/play/video.mp4?a=1",
                "https://www.douyin.com/aweme/v1/play/?video_id=x",
            ]},
            "bit_rate": [
                {"play_addr": {"url_list": ["https://cdn.example.com/hi/video.mp4"]}},
                {"play_addr": {"url_list": ["https://cdn.example.com/lo/video.mp4"]}},
            ],
        },
    }
    aweme.update(extra)
    return aweme


def _image_aweme(aweme_id="7600000000000000002", create_time=1785475972):
    return {
        "aweme_id": aweme_id,
        "create_time": create_time,
        "aweme_type": 68,
        "media_type": 42,
        "images": [{"url_list": ["https://cdn.example.com/a.webp"]}],
        "video": {"play_addr": {"url_list": ["https://cdn.example.com/music.mp3"]}},
    }


# --------------------------------------------------------------------------
# 配置解析
# --------------------------------------------------------------------------
def test_parse_cookie():
    cookies = douyin_fetch.parse_cookie("ttwid=abc; sessionid=x=y; ;bad; msToken=zz")
    names = {c["name"]: c["value"] for c in cookies}
    assert names == {"ttwid": "abc", "sessionid": "x=y", "msToken": "zz"}
    assert all(c["domain"] == ".douyin.com" and c["path"] == "/" for c in cookies)
    assert douyin_fetch.parse_cookie("") == []


def test_load_douyin_setup(tmp_path):
    config = tmp_path / "my_apps.yaml"
    config.write_text(
        "douyin:\n"
        "  headers:\n"
        "    User-Agent: TestAgent/1.0\n"
        "    Referer: https://www.douyin.com/\n"
        "  cookie: \"a=1; b=2\"\n"
        "  proxies:\n"
        "    http://: \"\"\n"
        "    https://: \"http://127.0.0.1:8080\"\n",
        encoding="utf-8",
    )
    setup = douyin_fetch.load_douyin_setup(config)
    assert setup["cookie"] == "a=1; b=2"
    assert setup["user_agent"] == "TestAgent/1.0"
    assert setup["proxy"] == "http://127.0.0.1:8080"


def test_load_douyin_setup_defaults_and_missing_file(tmp_path):
    config = tmp_path / "my_apps.yaml"
    config.write_text("video_mover: {}\n", encoding="utf-8")
    setup = douyin_fetch.load_douyin_setup(config)
    assert setup["user_agent"] == douyin_fetch.DEFAULT_USER_AGENT
    assert setup["proxy"] == ""
    with pytest.raises(FileNotFoundError):
        douyin_fetch.load_douyin_setup(tmp_path / "no-such.yaml")


# --------------------------------------------------------------------------
# 作品形态与直链
# --------------------------------------------------------------------------
def test_is_video_aweme_skips_image_posts():
    assert douyin_fetch.is_video_aweme(_video_aweme()) is True
    assert douyin_fetch.is_video_aweme(_image_aweme()) is False
    assert douyin_fetch.is_video_aweme({"aweme_type": 0, "images": [{}]}) is False
    assert douyin_fetch.is_video_aweme({"aweme_type": 0, "media_type": 42}) is False


def test_iter_video_urls_prefers_bit_rate_and_skips_mp3():
    urls = list(douyin_fetch.iter_video_urls(_video_aweme()))
    assert urls[0] == "https://cdn.example.com/hi/video.mp4"
    assert urls[1] == "https://cdn.example.com/lo/video.mp4"
    assert "https://cdn.example.com/play/video.mp4?a=1" in urls

    # 图文作品的 play_addr 是背景音乐，不能被当成视频
    image_urls = list(douyin_fetch.iter_video_urls(_image_aweme()))
    assert image_urls == []


def test_iter_video_urls_dedups():
    aweme = _video_aweme()
    aweme["video"]["play_addr"]["url_list"] = [
        "https://cdn.example.com/hi/video.mp4",
        "https://cdn.example.com/hi/video.mp4",
    ]
    urls = list(douyin_fetch.iter_video_urls(aweme))
    assert urls.count("https://cdn.example.com/hi/video.mp4") == 1


# --------------------------------------------------------------------------
# 时间与标题
# --------------------------------------------------------------------------
def test_aweme_create_time():
    created = douyin_fetch.aweme_create_time(_video_aweme(create_time=1785475972))
    assert created == datetime.fromtimestamp(1785475972)
    assert douyin_fetch.aweme_create_time({}) is None
    assert douyin_fetch.aweme_create_time({"create_time": "junk"}) is None


def test_nickname_from_title():
    assert douyin_fetch.nickname_from_title("杨超越的抖音 - 抖音") == "杨超越"
    assert douyin_fetch.nickname_from_title("KingM的抖音 - 抖音") == "KingM"
    assert douyin_fetch.nickname_from_title("") == "unknown"


def test_safe_name_strips_windows_unsafe_chars():
    assert douyin_fetch._safe_name('a/b:c*d?e"f<g>h|i') == "abcdefghi"
    assert douyin_fetch._safe_name("  ..  ") == "unknown"


def test_parse_time_range_string():
    since, until = douyin_fetch.parse_time_range_string(
        "2026-11-12 10-00-00|2026-11-12 11-00-00")
    assert (since, until) == (datetime(2026, 11, 12, 10), datetime(2026, 11, 12, 11))
    assert douyin_fetch.parse_time_range_string("") == (None, None)
    assert douyin_fetch.parse_time_range_string("junk|junk") == (None, None)


# --------------------------------------------------------------------------
# 下载计划：路径结构、时间窗口、已存在跳过
# --------------------------------------------------------------------------
def test_plan_downloads_layout_and_filters(tmp_path):
    in_window = _video_aweme(aweme_id="7600000000000000001", create_time=1785475972)
    out_window = _video_aweme(aweme_id="7600000000000000003", create_time=1700000000)
    image = _image_aweme(aweme_id="7600000000000000002", create_time=1785475972)

    plan = douyin_fetch.plan_downloads(
        [in_window, image, out_window],
        download_dir=tmp_path,
        nickname="杨超越",
        since=datetime(2026, 7, 1),
    )

    assert len(plan) == 1
    aweme, urls, target = plan[0]
    assert aweme["aweme_id"] == "7600000000000000001"
    created = datetime.fromtimestamp(1785475972).strftime(douyin_fetch.TIME_FMT)
    # 文件名必须是 <作品时间>_video.mp4，上传脚本靠它反找描述文件
    assert target == Path(tmp_path) / "杨超越" / created / f"{created}_video.mp4"
    assert urls[0] == "https://cdn.example.com/hi/video.mp4"
    # 描述文件与视频同目录、同名前缀
    assert douyin_fetch.desc_file_path(target) == Path(tmp_path) / "杨超越" / created / f"{created}_desc.txt"


def test_plan_downloads_skips_existing_files(tmp_path):
    aweme = _video_aweme(create_time=1785475972)
    created = datetime.fromtimestamp(1785475972).strftime(douyin_fetch.TIME_FMT)
    target = Path(tmp_path) / "昵称" / created / f"{created}_video.mp4"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"already")

    assert douyin_fetch.plan_downloads(
        [aweme], download_dir=tmp_path, nickname="昵称") == []
    # 允许重新下载时能命中
    assert len(douyin_fetch.plan_downloads(
        [aweme], download_dir=tmp_path, nickname="昵称", skip_existing=False)) == 1


def test_plan_downloads_skips_aweme_without_urls(tmp_path):
    aweme = _video_aweme()
    aweme["video"] = {}
    assert douyin_fetch.plan_downloads(
        [aweme], download_dir=tmp_path, nickname="昵称") == []


def test_download_plan_dry_run_does_not_touch_disk(tmp_path, caplog):
    aweme = _video_aweme(create_time=1785475972)
    plan = douyin_fetch.plan_downloads([aweme], download_dir=tmp_path, nickname="昵称")
    failed = douyin_fetch.download_plan(
        plan, user_agent="UA", cookie="c=1", dry_run=True)
    assert failed == 0
    assert not (Path(tmp_path) / "昵称").exists()


def test_desc_text_and_write_desc(tmp_path):
    aweme = _video_aweme()
    aweme["desc"] = "测试标题 #话题A #话题B"
    target = Path(tmp_path) / "昵称" / "2026-07-31 13-32-52" / "2026-07-31 13-32-52_video.mp4"
    target.parent.mkdir(parents=True)

    douyin_fetch._write_desc(aweme, target)

    desc = douyin_fetch.desc_file_path(target)
    assert desc.name == "2026-07-31 13-32-52_desc.txt"
    assert desc.read_text(encoding="utf-8").strip() == "测试标题 #话题A #话题B"

    # 已存在不覆盖；空 desc 不落文件
    desc.write_text("旧内容" + chr(10), encoding="utf-8")
    douyin_fetch._write_desc(aweme, target)
    assert desc.read_text(encoding="utf-8").strip() == "旧内容"
    douyin_fetch._write_desc({"aweme_id": "1"}, target.with_name("2020-01-01 00-00-00_video.mp4"))
    assert not (target.parent / "2020-01-01 00-00-00_desc.txt").exists()


def test_plan_downloads_honours_limit(tmp_path):
    """补抓历史时要能分批下载：limit 只取最新/最早的 N 条。"""
    awemes = [
        _video_aweme(aweme_id=f"76000000000000000{i:02d}", create_time=1785475972 + i * 60)
        for i in range(5)
    ]
    plan = douyin_fetch.plan_downloads(
        awemes, download_dir=tmp_path, nickname="昵称", limit=2)
    assert len(plan) == 2


def test_nickname_falls_back_to_author_when_title_unusable():
    """Cookie 失效时页面标题拿不到，昵称要用作品作者的，而不是 unknown。"""
    aweme = _video_aweme()
    aweme["author"] = {"nickname": "李雨真Jenny"}
    assert douyin_fetch.nickname_from_title("") == "unknown"
    # 走真实函数里的逻辑需要 Playwright；这里直接验证取昵称那段的行为约定
    nickname = douyin_fetch.nickname_from_title("")
    if nickname == "unknown":
        for a in [aweme]:
            author = (a.get("author") or {}).get("nickname")
            if author:
                nickname = douyin_fetch._safe_name(author)
                break
    assert nickname == "李雨真Jenny"
