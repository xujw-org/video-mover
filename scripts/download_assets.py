#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从原仓库下载本仓库已移除的大二进制资产。

背景：改进版仓库不再提交大二进制文件（字体 / 音乐 / 视频 / 图片 / 可执行文件），
第一次运行前需要用本脚本把它们下载回本地对应位置。详见 ASSETS.md。

来源：原仓库 https://github.com/toki-plus/video-mover 的 main 分支 raw 地址。
用法：
    python scripts/download_assets.py            # 下载全部缺失的资产
    python scripts/download_assets.py --check    # 只检查缺失情况，不下载
    python scripts/download_assets.py --force    # 已存在的文件也重新下载

行为：
- 已存在且大小与预期一致的文件会跳过（可重复执行）；
- 每次下载后校验文件大小，大小不对视为下载失败；
- 任何一个文件下载或校验失败都会明确报错并以非零退出码结束，绝不静默跳过；
- 如果原仓库地址失效，会提示你按 ASSETS.md 里的替代来源获取。
"""

import argparse
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE_URL = "https://raw.githubusercontent.com/toki-plus/video-mover/main"

# （仓库内相对路径，预期字节数）
# 字节数取自原仓库 2026-11-12 的 clone 结果，用于下载后校验。
ASSETS = [
    ("Upload/uploader/bilibili_uploader/biliup.exe", 14321152),
    ("Dedup/assets/fonts/simkai.ttf", 11789376),
    ("Dedup/assets/fonts/arial.ttf", 1047208),
    ("Dedup/assets/watermark.png", 1043939),
    ("Dedup/assets/hzh.mp4", 798754),
    ("Dedup/assets/bgm.mp3", 513024),
    ("images/IPWO.png", 2644345),
    ("images/cover_demo.png", 2428553),
    ("images/cover_script.png", 744526),
    ("images/gzh.png", 143839),
    ("images/wechat.png", 137371),
]


def download_one(url: str, dest: Path, expected_size: int) -> tuple[bool, str]:
    """下载单个文件并校验大小，返回 (是否成功, 说明)。"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "video-mover-asset-downloader"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}（地址可能已失效）"
    except urllib.error.URLError as e:
        return False, f"网络错误：{e.reason}"
    except Exception as e:  # 超时等
        return False, f"下载失败：{e}"
    if len(data) != expected_size:
        return False, f"大小校验失败：下载到 {len(data)} 字节，预期 {expected_size} 字节"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return True, f"已下载（{len(data)} 字节）"


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 video-mover 已移除的二进制资产")
    parser.add_argument("--check", action="store_true", help="只检查缺失情况，不下载")
    parser.add_argument("--force", action="store_true", help="已存在的文件也重新下载")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    missing = []
    failed = []
    for rel, size in ASSETS:
        dest = repo_root / rel
        if dest.exists() and dest.stat().st_size == size and not args.force:
            print(f"[跳过] {rel}（已存在，大小正确）")
            continue
        if dest.exists() and dest.stat().st_size != size and not args.force:
            print(f"[注意] {rel} 已存在但大小不对（{dest.stat().st_size} 字节，预期 {size} 字节），将重新下载")
        if args.check:
            missing.append(rel)
            print(f"[缺失] {rel}（{size} 字节）")
            continue
        ok, msg = download_one(f"{BASE_URL}/{rel}", dest, size)
        print(f"[{'成功' if ok else '失败'}] {rel}：{msg}")
        if not ok:
            failed.append(rel)

    if args.check:
        if missing:
            print(f"\n共缺失 {len(missing)} 个资产文件，请运行 python scripts/download_assets.py 下载。")
            return 1
        print("\n资产齐全，无需下载。")
        return 0
    if failed:
        print(f"\n{len(failed)} 个文件下载失败：{', '.join(failed)}")
        print("请检查网络后重试；如果原仓库地址已失效，请按 ASSETS.md 里的替代来源获取。")
        return 1
    print("\n全部资产就绪。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
