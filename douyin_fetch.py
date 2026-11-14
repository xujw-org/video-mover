# -*- coding: utf-8 -*-
"""抖音博主主页作品抓取（浏览器通道）。

为什么不用 f2：抖音现在对 ``/aweme/v1/web/aweme/post/`` 强制 Argus secsdk
签名。Burp 抓到的最新真实请求里除 ``a_bogus`` 之外还必须有
``x-secsdk-web-signature``，以及 ``uifid`` / ``webid`` / ``fp`` / ``timestamp``
这些风控参数。逐项删参数重放的实测结果：

    浏览器原样 URL                  -> 200（返回 aweme_list）
    去掉 x-secsdk-web-signature     -> 403 Blocked by ArgusSecurityPlugin Signature Not Found
    去掉 fp/webid/uifid/timestamp   -> 403 Blocked by ArgusSecurityPlugin Uifid Not Found

f2 0.0.1.7（PyPI 上的最新版）根本没有 secsdk 签名逻辑，所以它的请求必然 403。
签名由页面里的 secsdk JS 计算，因此这里的做法是**让 Chromium 自己发请求**：
打开博主主页 -> 直接读取页面自己发出的 ``aweme/post`` 响应 -> 按需滚动翻页
-> 用 httpx 按直链下载视频。落盘结构与 f2 一致，FileManager 的去重扫描不用改::

    <download_dir>/<昵称>/<作品时间>/<aweme_id>.mp4

图文（aweme_type=68 / media_type=42，带 images）不是视频，跳过；它们的
``video.play_addr`` 指向的是背景音乐 mp3，直接下载会得到音频文件。

单独使用（调试 / 补抓历史）::

    python douyin_fetch.py --url https://www.douyin.com/user/xxxx --days 30
    python douyin_fetch.py --url ... --since "2026-11-14 10:00:00" --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36"
)
TIME_FMT = "%Y-%m-%d %H-%M-%S"
PROFILE_API_MARK = "/aweme/v1/web/aweme/post/"

# 图文作品的 aweme_type：68 = 图集；media_type 42 = 图集，4 = 视频。
_IMAGE_AWEME_TYPE = 68
_VIDEO_MEDIA_TYPE = 4


# --------------------------------------------------------------------------
# 纯函数：配置解析、作品筛选、下载计划（便于单测）
# --------------------------------------------------------------------------
def parse_cookie(cookie_str: str) -> list[dict]:
    """把 ``k=v; k2=v2`` 解析成 Playwright 需要的 cookie 列表。"""
    cookies = []
    for item in (cookie_str or "").split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append({"name": name, "value": value, "domain": ".douyin.com", "path": "/"})
    return cookies


def load_douyin_setup(config_path: str | Path) -> dict:
    """从 my_apps.yaml 读 douyin 小节的 cookie / UA / 代理。"""
    path = Path(config_path)
    if not path.is_file():
        raise FileNotFoundError(f"找不到配置文件: {path}")
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyyaml 是运行依赖
        raise RuntimeError("需要 pyyaml 才能读取 my_apps.yaml") from exc

    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    section = data.get("douyin") or {}
    headers = {str(k).lower(): str(v) for k, v in (section.get("headers") or {}).items()}
    proxies = section.get("proxies") or {}
    proxy = ""
    for key in ("http://", "https://"):
        value = str(proxies.get(key) or "").strip()
        if value:
            proxy = value
            break
    return {
        "cookie": str(section.get("cookie") or "").strip(),
        "user_agent": headers.get("user-agent") or DEFAULT_USER_AGENT,
        "referer": headers.get("referer") or "https://www.douyin.com/",
        "proxy": proxy,
    }


def is_video_aweme(aweme: dict) -> bool:
    """是否是视频作品（跳过图文）。"""
    if int(aweme.get("aweme_type") or 0) == _IMAGE_AWEME_TYPE:
        return False
    if aweme.get("images"):
        return False
    if aweme.get("media_type") is not None and int(aweme["media_type"]) != _VIDEO_MEDIA_TYPE:
        return False
    return True


def aweme_create_time(aweme: dict) -> Optional[datetime]:
    raw = aweme.get("create_time")
    if not raw:
        return None
    try:
        return datetime.fromtimestamp(int(raw))
    except (TypeError, ValueError, OSError):
        return None


def iter_video_urls(aweme: dict) -> Iterator[str]:
    """按优先级给出可尝试的视频地址。

    优先 ``bit_rate``（按码率从高到低），再退回 ``play_addr``；去重并跳过
    ``.mp3``（图文作品的 play_addr 就是背景音乐）。
    """
    video = aweme.get("video") or {}
    seen = set()
    candidates: list[str] = []
    for rate in video.get("bit_rate") or []:
        for url in ((rate.get("play_addr") or {}).get("url_list") or []):
            candidates.append(str(url))
    for key in ("play_addr", "play_addr_h265", "download_addr"):
        for url in ((video.get(key) or {}).get("url_list") or []):
            candidates.append(str(url))
    for url in candidates:
        if not url or url in seen:
            continue
        seen.add(url)
        if ".mp3" in url.lower():
            continue
        yield url


def desc_file_path(video_target) -> Path:
    """作品描述文件路径。

    与 f2 / ``Upload/douyin_upload.py`` 的约定一致：同一作品目录里的
    ``<时间>/<时间>_desc.txt``，上传时拿第一行当标题、全文里的 #话题 当标签。
    """
    folder = Path(video_target).parent
    return folder / f"{folder.name}_desc.txt"


def desc_text(aweme: dict) -> str:
    """作品描述原文（抖音的 desc 里通常就带 #话题，原样保留即可）。"""
    return str(aweme.get("desc") or "").strip()


def plan_downloads(
    awemes: Iterable[dict],
    *,
    download_dir: Path,
    nickname: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    skip_existing: bool = True,
) -> list[tuple[dict, list[str], Path]]:
    """把作品列表变成下载计划：[(aweme, 候选直链, 目标文件), ...]。

    落盘结构与 f2 一致::

        <download_dir>/<昵称>/<作品时间>/<作品时间>_video.mp4
        <download_dir>/<昵称>/<作品时间>/<作品时间>_desc.txt

    视频文件名用 ``<作品时间>_video.mp4``（不是 aweme_id）：
    ``Upload/douyin_upload.py`` 靠文件名里的时间去反找 ``_desc.txt``，
    换成 aweme_id 就只能拿一串数字当标题。
    """
    base = Path(download_dir) / _safe_name(nickname)
    plan: list[tuple[dict, list[str], Path]] = []
    for aweme in awemes:
        if not is_video_aweme(aweme):
            continue
        created = aweme_create_time(aweme)
        if created is None:
            continue
        if since and created < since:
            continue
        if until and created > until:
            continue
        urls = list(iter_video_urls(aweme))
        if not urls:
            continue
        aweme_id = str(aweme.get("aweme_id") or "").strip()
        if not aweme_id:
            continue
        folder_name = created.strftime(TIME_FMT)
        target = base / folder_name / f"{folder_name}_video.mp4"
        if skip_existing and target.exists() and target.stat().st_size > 0:
            continue
        plan.append((aweme, urls, target))
    return plan


def _safe_name(name: str, fallback: str = "unknown") -> str:
    """昵称直接当目录名，去掉 Windows 不允许的字符与首尾空白/点。"""
    cleaned = "".join(ch for ch in str(name or "") if ch not in '\\/:*?"<>|').strip().rstrip(".")
    return cleaned or fallback


def nickname_from_title(title: str) -> str:
    """页面标题形如 ``杨超越的抖音 - 抖音``，取其昵称部分。"""
    text = (title or "").replace(" - 抖音", "").strip()
    if text.endswith("的抖音"):
        text = text[: -len("的抖音")]
    return _safe_name(text)


def parse_time_range_string(value: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """解析 f2 风格的时间区间 ``YYYY-MM-DD HH-MM-SS|YYYY-MM-DD HH-MM-SS``。"""
    if not value:
        return None, None
    parts = str(value).split("|")
    parsed = []
    for part in parts[:2]:
        part = part.strip()
        try:
            parsed.append(datetime.strptime(part, TIME_FMT))
        except ValueError:
            parsed.append(None)
    while len(parsed) < 2:
        parsed.append(None)
    return parsed[0], parsed[1]


# --------------------------------------------------------------------------
# 浏览器通道：抓取作品列表
# --------------------------------------------------------------------------
@dataclass
class FetchResult:
    nickname: str
    awemes: list[dict]
    pages: int


def fetch_profile_awemes(
    url: str,
    *,
    cookie: str,
    user_agent: str = DEFAULT_USER_AGENT,
    proxy: str = "",
    headless: bool = True,
    since: Optional[datetime] = None,
    max_pages: int = 20,
    max_scrolls: int = 25,
    total_timeout: float = 180.0,
    ignore_https_errors: bool = False,
) -> FetchResult:
    """打开博主主页，读取页面自己发出的 ``aweme/post`` 响应。

    签名（a_bogus + x-secsdk-web-signature）由页面 JS 计算，所以这里只管
    读响应、滚动翻页。滚动会在“已到时间窗口下界 / 没有新响应 / 滚动次数
    用尽”时停止。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - playwright 是运行依赖
        raise RuntimeError(
            "需要 playwright 才能抓取抖音：pip install playwright && "
            "python -m playwright install chromium"
        ) from exc

    cookies = parse_cookie(cookie)
    if not cookies:
        raise ValueError("my_apps.yaml 里 douyin.cookie 为空，无法抓取")

    payloads: list[dict] = []
    seen_ids: set[str] = set()
    deadline = time.monotonic() + total_timeout

    def collect(text: Optional[str]) -> None:
        if not text:
            return
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return
        added = 0
        for aweme in data.get("aweme_list") or []:
            aweme_id = str(aweme.get("aweme_id") or "")
            if aweme_id and aweme_id not in seen_ids:
                seen_ids.add(aweme_id)
                payloads.append(aweme)
                added += 1
        if added:
            logging.debug("aweme/post 新增 %s 条作品（累计 %s）", added, len(payloads))

    with sync_playwright() as pw:
        launch_kwargs = {
            "headless": headless,
            "args": ["--disable-blink-features=AutomationControlled"],
        }
        if proxy:
            launch_kwargs["proxy"] = {"server": proxy}
        browser = pw.chromium.launch(**launch_kwargs)
        context = browser.new_context(
            user_agent=user_agent,
            locale="zh-CN",
            viewport={"width": 1400, "height": 900},
            # 走 Burp 之类的拦截代理时，HTTPS 证书是代理自签的，必须放行才能
            # 看到明文（只在调试代理时才需要开）。
            ignore_https_errors=ignore_https_errors,
        )
        context.add_cookies(cookies)
        page = context.new_page()

        def on_response(response) -> None:
            if PROFILE_API_MARK not in response.url:
                return
            try:
                # 响应体必须在页面关闭前读掉，否则 TargetClosedError
                collect(response.text())
            except Exception as exc:  # pragma: no cover - 网络抖动
                logging.debug("读取 aweme/post 响应失败: %s", exc)

        page.on("response", on_response)
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3500)
        title = page.title()

        stalls = 0
        last_count = len(payloads)
        for _ in range(max_scrolls):
            if time.monotonic() > deadline:
                logging.warning("抓取超时，停止翻页（已收集 %s 条）", len(payloads))
                break
            oldest = min(
                (t for t in (aweme_create_time(a) for a in payloads) if t), default=None
            )
            if since and oldest and oldest <= since:
                break
            page.mouse.wheel(0, 2400)
            page.wait_for_timeout(2200)
            if len(payloads) == last_count:
                stalls += 1
                if stalls >= 3:
                    break
            else:
                stalls = 0
                last_count = len(payloads)
            if last_count and len({id(a) for a in payloads}) and len(payloads) >= max_pages * 20:
                break

        browser.close()

    nickname = nickname_from_title(title)
    if not payloads:
        nickname = nickname or _safe_name(Path(url).name)
    return FetchResult(nickname=nickname, awemes=payloads, pages=len(payloads))


# --------------------------------------------------------------------------
# 下载
# --------------------------------------------------------------------------
def http_client(*, user_agent: str, cookie: str, referer: str, proxy: str = ""):
    import httpx

    headers = {
        "User-Agent": user_agent,
        "Referer": referer,
        "Cookie": cookie,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    kwargs = {"headers": headers, "timeout": 60, "follow_redirects": True}
    if proxy:
        kwargs["proxy"] = proxy
        kwargs["verify"] = False  # 与浏览器同样的理由：调试代理用的是自签证书
    return httpx.Client(**kwargs)


def _write_desc(aweme: dict, target: Path) -> None:
    """写 ``<时间>_desc.txt``（上传时用作标题 + 话题）。已存在就不覆盖。"""
    text = desc_text(aweme)
    if not text:
        return
    path = desc_file_path(target)
    try:
        if not path.exists():
            path.write_text(text + "\n", encoding="utf-8")
    except OSError as exc:
        logging.warning("写描述文件失败 %s: %s", path, exc)


def download_plan(
    plan: list[tuple[dict, list[str], Path]],
    *,
    user_agent: str,
    cookie: str,
    referer: str = "https://www.douyin.com/",
    proxy: str = "",
    dry_run: bool = False,
) -> int:
    """按计划下载（并写描述文件），返回失败条数。第一个能用的直链就够。"""
    if dry_run:
        for aweme, urls, target in plan:
            logging.info("[dry-run] %s <- %s", target, urls[0][:80])
        return 0

    failed = 0
    with http_client(user_agent=user_agent, cookie=cookie, referer=referer, proxy=proxy) as client:
        for aweme, urls, target in plan:
            target.parent.mkdir(parents=True, exist_ok=True)
            _write_desc(aweme, target)
            ok = False
            for url in urls:
                tmp = target.with_suffix(".part")
                try:
                    with client.stream("GET", url) as resp:
                        if resp.status_code not in (200, 206):
                            logging.debug("直链返回 %s：%s", resp.status_code, url[:80])
                            continue
                        content_type = (resp.headers.get("content-type") or "").lower()
                        if content_type.startswith(("text/", "application/json")):
                            logging.debug("直链不是视频（%s）：%s", content_type, url[:80])
                            continue
                        size = 0
                        with tmp.open("wb") as fh:
                            for chunk in resp.iter_bytes(1 << 16):
                                fh.write(chunk)
                                size += len(chunk)
                    if size <= 0:
                        tmp.unlink(missing_ok=True)
                        continue
                    tmp.replace(target)
                    logging.info("已下载: %s（%.1f MB）", target.name, size / 1024 / 1024)
                    ok = True
                    break
                except Exception as exc:
                    logging.warning("下载失败 %s: %s", url[:80], exc)
                    tmp.unlink(missing_ok=True)
            if not ok:
                failed += 1
                logging.error("作品 %s 全部直链下载失败", aweme.get("aweme_id"))
    return failed


def fetch_and_download(
    url: str,
    *,
    download_dir: str | Path,
    config_path: str | Path = "my_apps.yaml",
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    headless: bool = True,
    dry_run: bool = False,
    max_scrolls: int = 25,
    ignore_https_errors: bool = False,
) -> int:
    """供 main.py 调用：抓取 + 下载，返回下载（或命中）的视频数量。"""
    setup = load_douyin_setup(config_path)
    if setup["proxy"]:
        # 配置了代理就要放行代理证书，否则 https 直接被拦在证书校验上
        ignore_https_errors = True
    result = fetch_profile_awemes(
        url,
        cookie=setup["cookie"],
        user_agent=setup["user_agent"],
        proxy=setup["proxy"],
        headless=headless,
        since=since,
        max_scrolls=max_scrolls,
        ignore_https_errors=ignore_https_errors,
    )
    logging.info(
        "抖音主页抓取完成: %s，作品 %s 条，昵称「%s」",
        url,
        len(result.awemes),
        result.nickname,
    )
    plan = plan_downloads(
        result.awemes, download_dir=Path(download_dir), nickname=result.nickname,
        since=since, until=until,
    )
    logging.info("命中时间窗口的视频 %s 条（图文与已存在的不算）", len(plan))
    if not plan:
        return 0
    failed = download_plan(
        plan,
        user_agent=setup["user_agent"],
        cookie=setup["cookie"],
        referer=setup["referer"],
        proxy=setup["proxy"],
        dry_run=dry_run,
    )
    return len(plan) - failed


# --------------------------------------------------------------------------
# 命令行（调试用）
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")

    parser = argparse.ArgumentParser(description="抖音博主主页视频抓取（浏览器通道）")
    parser.add_argument("--url", required=True, help="博主主页 URL")
    parser.add_argument("--config", default="my_apps.yaml",
                        help="配置文件（读 douyin 小节的 cookie）")
    parser.add_argument("--download-dir", default="Download/douyin/post", help="下载根目录")
    parser.add_argument("--days", type=float, help="抓最近 N 天（与 --since 互斥）")
    parser.add_argument("--since", help="起始时间 YYYY-MM-DD HH-MM-SS")
    parser.add_argument("--until", help="结束时间 YYYY-MM-DD HH-MM-SS")
    parser.add_argument("--headful", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--dry-run", action="store_true", help="只列计划不下载")
    parser.add_argument("--max-scrolls", type=int, default=25, help="最多滚动次数")
    parser.add_argument("--ignore-https-errors", action="store_true",
                        help="放行自签证书（走 Burp/mitmproxy 调试时需要）")
    args = parser.parse_args(argv)

    since = until = None
    if args.days:
        since = datetime.now() - timedelta(days=args.days)
    if args.since:
        since = datetime.strptime(args.since, TIME_FMT)
    if args.until:
        until = datetime.strptime(args.until, TIME_FMT)

    count = fetch_and_download(
        args.url,
        download_dir=args.download_dir,
        config_path=args.config,
        since=since,
        until=until,
        headless=not args.headful,
        dry_run=args.dry_run,
        max_scrolls=args.max_scrolls,
        ignore_https_errors=args.ignore_https_errors,
    )
    logging.info("完成，处理 %s 条视频", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())