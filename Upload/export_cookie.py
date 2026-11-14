# -*- coding: utf-8 -*-
"""把 my_apps.yaml 里的抖音网页 cookie 转成上传器要的 storage_state 文件。

为什么需要它：上传器（Upload/uploader/douyin_uploader）用 Playwright 的
``storage_state`` 登录，传统做法是运行
``python Upload/cli_main.py douyin <账号> login`` 扫码一次。但 ``sessionid`` /
``sid_guard`` / ``ttwid`` 这些 cookie 的作用域是 ``.douyin.com``，
``creator.douyin.com`` 与 ``www.douyin.com`` 共用，直接转过来就能用——实测
headless 打开创作者中心能正常进上传页，不需要扫码、不需要弹浏览器。

用法::

    python Upload/export_cookie.py                  # 账号名取自 my_apps.yaml
    python Upload/export_cookie.py --account other  # 指定账号名

生成 ``Upload/cookies/douyin_<账号>.json``（已在 .gitignore 里，不会进仓库）。
cookie 过期后重新从浏览器导一次 my_apps.yaml 的 ``douyin.cookie`` 再跑本脚本。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

UPLOAD_DIR = Path(__file__).resolve().parent
REPO_ROOT = UPLOAD_DIR.parent


def load_web_cookie(config_path: Path) -> str:
    """从 my_apps.yaml 的 douyin.cookie 取网页登录 cookie。"""
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pyyaml 是运行依赖
        raise RuntimeError("需要 pyyaml 才能读取 my_apps.yaml") from exc
    if not config_path.is_file():
        raise FileNotFoundError(f"找不到配置文件: {config_path}")
    with config_path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    cookie = str((data.get("douyin") or {}).get("cookie") or "").strip()
    if not cookie:
        raise ValueError(f"{config_path} 里的 douyin.cookie 是空的")
    return cookie


def to_storage_state(cookie_str: str) -> dict:
    """把 ``k=v; k2=v2`` 转成 Playwright storage_state 结构。

    只产出 ``.douyin.com`` 作用域的 cookie（creator/www 共用）。
    """
    cookies = []
    for item in cookie_str.split(";"):
        if "=" not in item:
            continue
        name, value = item.split("=", 1)
        name = name.strip()
        if not name:
            continue
        cookies.append({
            "name": name,
            "value": value,
            "domain": ".douyin.com",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        })
    if not cookies:
        raise ValueError("cookie 解析后为空，检查是不是粘贴成了空串或换行")
    return {"cookies": cookies, "origins": []}


def sid_issued_at(cookies: dict) -> int:
    """从 sid_guard 里取“签发时间”（字段 2），拿不到就返回 0。

    sid_guard 形如 ``<hash>|<签发时间戳>|<有效期秒>|<到期日期>``，
    抖音每次登录/续期都会重新签一个。
    """
    raw = cookies.get("sid_guard") or ""
    try:
        fields = raw.replace("%7C", "|").split("|")
        return int(fields[1]) if len(fields) >= 2 else 0
    except (ValueError, IndexError):
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把网页 cookie 转成上传器 storage_state")
    parser.add_argument("--config", default=str(REPO_ROOT / "my_apps.yaml"),
                        help="配置文件路径")
    parser.add_argument("--account", default=None,
                        help="账号名，默认取 video_mover.upload.douyin_account")
    parser.add_argument("--output", default=None,
                        help="输出文件，默认 Upload/cookies/douyin_<账号>.json")
    parser.add_argument("--force", action="store_true",
                        help="即使输出文件里的 sid_guard 更新也照样覆盖")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    cookie = load_web_cookie(config_path)

    account = args.account
    if not account:
        try:
            import yaml

            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
            account = str(((data.get("video_mover") or {}).get("upload") or {})
                          .get("douyin_account") or "default")
        except Exception:
            account = "default"

    output = Path(args.output) if args.output else UPLOAD_DIR / "cookies" / f"douyin_{account}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    state = to_storage_state(cookie)

    # 别用旧的 yaml cookie 覆盖上传器刚续期出来的新 cookie：
    # 抖音每次登录/发布都会重签 sid_guard，覆盖回去等于把新 session 作废，
    # 下一次自动化就会用旧 session 被踢下线。
    if output.is_file() and not args.force:
        try:
            old_state = json.loads(io.open(output, encoding="utf-8").read())
            old_cookies = {c["name"]: c["value"] for c in old_state.get("cookies", [])}
            new_cookies = {c["name"]: c["value"] for c in state["cookies"]}
            old_at, new_at = sid_issued_at(old_cookies), sid_issued_at(new_cookies)
            if old_at and new_at and new_at < old_at:
                print(
                    f"跳过：{output.name} 里的 sid_guard 更新（{old_at} > yaml 的 {new_at}），"
                    "用旧 cookie 覆盖会把新 session 作废。确定要覆盖就加 --force。"
                    "（建议改成从浏览器重新导出最新 cookie 到 my_apps.yaml）"
                )
                return 1
        except (OSError, ValueError, KeyError) as exc:
            print(f"（检查已有文件失败，继续覆盖: {exc}）")

    io.open(output, "w", encoding="utf-8").write(json.dumps(state, ensure_ascii=False))
    print(f"已生成 {output}（{len(state['cookies'])} 条 cookie，账号 {account}）")
    print("接下来可以验证登录态：python Upload/douyin_upload.py（或直接跑 start.bat）")
    return 0


if __name__ == "__main__":
    sys.exit(main())