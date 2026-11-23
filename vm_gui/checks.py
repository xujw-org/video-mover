# -*- coding: utf-8 -*-
"""界面上的“能不能开跑”检查：配置、cookie、资产、外部工具、依赖。

这里只做无副作用的探测，不安装、不修改任何文件；缺失项由界面按钮去修复。
"""

from __future__ import annotations

import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any

from vm_gui.config import (
    ConfigStore,
    cookie_missing,
    needs_douyin_cookie,
)

REQUIRED_MODULES = [
    ("psutil", "psutil"),
    ("apscheduler", "apscheduler"),
    ("watchdog", "watchdog"),
    ("yaml", "pyyaml"),
    ("playwright", "playwright"),
]

ASSET_FILES = [
    ("Dedup/assets/fonts/simkai.ttf", "中文字体"),
    ("Dedup/assets/bgm.mp3", "背景音乐"),
    ("Dedup/assets/watermark.png", "水印图"),
    ("Dedup/assets/hzh.mp4", "画中画素材"),
]

VIDEO_MOVER_ENV_PREFIX = "VIDEO_MOVER_"
GUI_ENV_PREFIX = "VIDEO_MOVER_GUI_"


def _is_config_env(key: str) -> bool:
    """main.py 会读取的 VIDEO_MOVER_* 才算覆盖；GUI 自己的变量不算。"""
    return key.startswith(VIDEO_MOVER_ENV_PREFIX) and not key.startswith(GUI_ENV_PREFIX)


def _item(ok: bool, title: str, detail: str, action: str = "") -> dict[str, Any]:
    return {"ok": ok, "title": title, "detail": detail, "action": action}


def _upload_cookie_path(root: Path, account: str) -> Path:
    return root / "Upload" / "cookies" / f"douyin_{account}.json"


def _format_mtime(path: Path) -> str:
    try:
        from datetime import datetime

        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "未知时间"


def config_checks(store: ConfigStore, draft: dict[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    if store.path.is_file():
        items.append(_item(True, "配置文件", str(store.path)))
    else:
        items.append(
            _item(
                False,
                "配置文件",
                "缺少 my_apps.yaml；保存配置或点击“从模板创建”会自动生成。",
                "create",
            )
        )

    try:
        loaded = store.load()
    except Exception as exc:  # noqa: BLE001
        items.append(_item(False, "YAML 可读", str(exc), "config"))
    else:
        loaded_sources = loaded.get("sources") or []
        if loaded_sources:
            names = "、".join(
                f"{s.get('platform')} {s.get('account')}" for s in loaded_sources
            )
            items.append(_item(True, "视频源", names))
        else:
            items.append(_item(False, "视频源", "还没有视频源，请在“配置”里添加博主。", "config"))

    douyin_cookie = draft.get("f2", {}).get("douyin_cookie", "")
    if needs_douyin_cookie(draft):
        if cookie_missing(douyin_cookie):
            items.append(
                _item(
                    False,
                    "抖音 Cookie",
                    "my_apps.yaml 的 douyin.cookie 还是空的/模板占位符；抖音抓取和上传都需要它。",
                    "config",
                )
            )
        else:
            items.append(_item(True, "抖音 Cookie", "已填写（my_apps.yaml → douyin.cookie）"))
    else:
        items.append(_item(True, "抖音 Cookie", "当前配置没用到抖音，可留空"))

    account = str(draft.get("upload", {}).get("douyin_account") or "default")
    cookie_path = _upload_cookie_path(store.root, account)
    if cookie_path.is_file():
        items.append(
            _item(
                True,
                "上传登录态",
                f"{cookie_path.relative_to(store.root)}（更新于 {_format_mtime(cookie_path)}）",
            )
        )
    else:
        items.append(
            _item(
                False,
                "上传登录态",
                f"缺少 {cookie_path.relative_to(store.root)}；"
                "填好抖音 Cookie 后点“导出 Cookie”，或“扫码登录”。",
                "login",
            )
        )

    env_file = store.root / ".env"
    from vm_gui.config import read_dotenv

    dotenv = read_dotenv(env_file)
    overrides = sorted(
        key
        for key in dotenv
        if _is_config_env(key) and dotenv[key] != ""
    )
    process_overrides = sorted(
        key for key in os.environ if _is_config_env(key) and os.environ[key] != ""
    )
    if overrides or process_overrides:
        names = "、".join(sorted(set(overrides) | set(process_overrides)))
        items.append(
            _item(
                False,
                "环境变量覆盖",
                f"{names} 会覆盖 my_apps.yaml 里的同名配置；"
                "如果界面保存后行为不一致，先检查 .env。",
                "config",
            )
        )
    else:
        items.append(_item(True, "环境变量覆盖", "没有 VIDEO_MOVER_* 覆盖，界面配置就是实际配置"))

    return items


def environment_checks(root: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    missing = [
        package
        for module, package in REQUIRED_MODULES
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        items.append(
            _item(
                False,
                "Python 依赖",
                f"缺少：{', '.join(missing)}；运行 setup.bat 或点“修复环境”。",
                "setup",
            )
        )
    else:
        items.append(
            _item(
                True,
                "Python 依赖",
                "psutil / apscheduler / watchdog / pyyaml / playwright 都在",
            )
        )

    ffmpeg = shutil.which("ffmpeg")
    bundled = root / "tools" / "ffmpeg" / "bin" / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if ffmpeg:
        items.append(_item(True, "FFmpeg", ffmpeg))
    elif bundled.is_file():
        items.append(_item(True, "FFmpeg", f"使用仓库内 {bundled.relative_to(root)}"))
    else:
        items.append(
            _item(
                False,
                "FFmpeg",
                "PATH 和 tools/ffmpeg 都没找到；运行 setup.bat 自动下载。",
                "setup",
            )
        )

    browsers = Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"
    chromium = []
    if browsers.is_dir():
        chromium = sorted(
            p.name for p in browsers.iterdir() if p.is_dir() and p.name.startswith("chromium")
        )
    if chromium:
        items.append(_item(True, "Playwright 浏览器", "、".join(chromium)))
    else:
        items.append(
            _item(
                False,
                "Playwright 浏览器",
                "没有安装 Chromium；运行 setup.bat 或点“修复环境”。",
                "setup",
            )
        )

    missing_assets = [
        f"{label}（{relative}）"
        for relative, label in ASSET_FILES
        if not (root / relative).is_file()
    ]
    if missing_assets:
        items.append(
            _item(
                False,
                "视频处理素材",
                "缺少：" + "、".join(missing_assets) + "；点“下载素材”自动获取。",
                "assets",
            )
        )
    else:
        items.append(_item(True, "视频处理素材", "字体 / 背景音乐 / 水印 / 画中画都在"))

    from vm_gui.config import read_dotenv

    dashscope = read_dotenv(root / ".env").get("DASHSCOPE_API_KEY") or os.environ.get(
        "DASHSCOPE_API_KEY", ""
    )
    uses_vx = False
    try:
        draft = ConfigStore(root).load()
        scripts = draft.get("paths", {}).get("upload_scripts", [])
        uses_vx = any("vx_upload" in str(script) for script in scripts)
    except Exception:  # noqa: BLE001
        pass
    if uses_vx:
        if dashscope.strip():
            items.append(_item(True, "百炼 API Key", "已配置（视频号文案用）"))
        else:
            items.append(
                _item(
                    False,
                    "百炼 API Key",
                    "上传脚本含 vx_upload，但 .env 没有 DASHSCOPE_API_KEY。",
                    "config",
                )
            )
    else:
        items.append(_item(True, "百炼 API Key", "当前没启用视频号文案，可不填"))

    return items


def all_checks(store: ConfigStore, draft: dict[str, Any]) -> list[dict[str, Any]]:
    return config_checks(store, draft) + environment_checks(store.root)
