# -*- coding: utf-8 -*-
"""Video Mover 图形控制台（NiceGUI）。

启动方式：双击 ``gui.bat``（推荐）或 ``python gui.py``。
界面只监听 127.0.0.1，默认端口 8765；重复启动会打开已有窗口。
"""

from __future__ import annotations

import os
import socket
import sys
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

try:
    from nicegui import app as nicegui_app
    from nicegui import run as nicegui_run
    from nicegui import ui
except ImportError:
    print()
    print("[错误] 缺少 NiceGUI。请运行 gui.bat（会自动安装），或执行：")
    print("       python -m pip install -r requirements-gui.txt")
    print()
    raise SystemExit(1) from None

from vm_gui.checks import all_checks
from vm_gui.config import (
    TIMEZONE_CHOICES,
    ConfigError,
    ConfigStore,
    cookie_missing,
    default_draft,
    read_dotenv,
    write_dotenv_value,
)
from vm_gui.process import ProcessManager, tail_file

ROOT = Path(__file__).resolve().parent
STORE = ConfigStore(ROOT)
MANAGER = ProcessManager(ROOT)
store_created = False


def _port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex((host, port)) == 0


def _existing_gui(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1.5) as response:
            body = response.read(8192).decode("utf-8", errors="replace")
        return "Video Mover" in body
    except Exception:  # noqa: BLE001 - 端口不通就是没有
        return False


def _open_path(path: Path) -> None:
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            ui.notify(f"请手动打开：{path}", type="info")
    except OSError as exc:
        ui.notify(f"打不开 {path}：{exc}", type="negative")


@ui.page("/")
def index() -> None:
    ui.page_title("Video Mover 控制台")
    ui.add_css(".q-btn { text-transform: none; }")

    try:
        draft = STORE.load()
        load_error = ""
    except ConfigError as exc:
        draft = default_draft()
        load_error = str(exc)

    scripts_holder = {"text": "\n".join(draft["paths"]["upload_scripts"])}
    api_key_holder = {"value": read_dotenv(ROOT / ".env").get("DASHSCOPE_API_KEY", "")}
    page_state: dict[str, Any] = {
        "log_index": MANAGER.log.count,
        "applog_size": None,
        "external": [],
        "was_busy": MANAGER.busy(),
    }
    widgets: dict[str, Any] = {}
    client = ui.context.client

    def connected() -> bool:
        """浏览器连接还在时才允许更新 UI。

        NiceGUI 的定时器在标签页关闭后可能还会跑一拍；此时 push/set_text 会触发
        “Client has been deleted but is still being used”（#3028）。所有异步回调
        在更新界面前都先看这个。
        """
        return client.has_socket_connection

    # ------------------------------------------------------------------ 工具函数
    def as_int(value, empty=None):
        if value is None or value == "":
            return empty
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return value

    def sync_draft() -> None:
        for source in draft.get("sources") or []:
            for key in ("platform", "account", "url", "download_dir"):
                source[key] = str(source.get(key) or "").strip()
        schedule = draft["schedule"]
        schedule["interval_minutes"] = as_int(schedule.get("interval_minutes"))
        schedule["timezone"] = str(schedule.get("timezone") or "").strip()
        upload = draft["upload"]
        upload["douyin_account"] = str(upload.get("douyin_account") or "").strip()
        upload["min_interval_minutes"] = as_int(upload.get("min_interval_minutes"))
        upload["hot_tags"] = as_int(upload.get("hot_tags"))
        upload["headless"] = bool(upload.get("headless"))
        upload["dry_run"] = bool(upload.get("dry_run"))
        backfill = draft["backfill"]
        backfill["days"] = as_int(backfill.get("days"))
        backfill["max_per_source"] = as_int(backfill.get("max_per_source"))
        backfill["max_per_run"] = as_int(backfill.get("max_per_run"))
        max_workers = draft["runtime"].get("max_workers")
        draft["runtime"]["max_workers"] = (
            None if max_workers in (None, "") else as_int(max_workers)
        )
        for key in ("dedup_dir", "upload_dir", "flush_script", "dedup_script"):
            draft["paths"][key] = str(draft["paths"].get(key) or "").strip()
        draft["paths"]["upload_scripts"] = [
            line.strip() for line in scripts_holder["text"].splitlines() if line.strip()
        ]
        for key in list(draft["f2"]):
            draft["f2"][key] = str(draft["f2"].get(key) or "").strip()

    def show_error(title: str, message: str) -> None:
        if not connected():
            return
        widgets["error_title"].set_text(title)  # type: ignore[union-attr]
        widgets["error_body"].set_text(message)  # type: ignore[union-attr]
        widgets["error_dialog"].open()  # type: ignore[union-attr]

    def refresh_summary() -> None:
        try:
            summary = STORE.summary(draft)
        except Exception as exc:  # noqa: BLE001
            widgets["summary"].set_text(f"配置摘要不可用：{exc}")  # type: ignore[union-attr]
            return
        mode = "无窗口上传" if summary["headless"] else "有界面上传"
        dry = " · 演练模式（不真正发布）" if summary["dry_run"] else ""
        backfill = f" · 补抓 {summary['backfill_days']} 天" if summary["backfill_days"] else ""
        widgets["summary"].set_text(  # type: ignore[union-attr]
            f"视频源 {summary['sources']} 个 · 每 {summary['interval']} 分钟 · "
            f"时区 {summary['timezone']}\n"
            f"上传账号 {summary['account']} · {mode}{dry}{backfill}"
        )

    def refresh_checks() -> None:
        container = widgets.get("checks")
        if container is None:
            return
        container.clear()
        with container:
            for item in all_checks(STORE, draft):
                color = "text-green-600" if item["ok"] else "text-red-600"
                icon = "check_circle" if item["ok"] else "error"
                with ui.row().classes("w-full items-start gap-2 flex-nowrap"):
                    ui.icon(icon).classes(f"text-lg {color}")
                    with ui.column().classes("gap-0"):
                        ui.label(item["title"]).classes("font-medium text-sm")
                        ui.label(item["detail"]).classes(
                            "text-xs text-gray-500 whitespace-pre-wrap"
                        )

    def refresh_status() -> None:
        if not connected():
            return
        status = MANAGER.status()
        if status["running"]:
            widgets["badge"].set_text(f"运行中 · {status['label']}")  # type: ignore[union-attr]
            widgets["badge"].props("color=positive")  # type: ignore[union-attr]
            widgets["status_detail"].set_text(  # type: ignore[union-attr]
                f"PID {status['pid']} · 已运行 {status['elapsed']} 秒 · "
                "点“停止”会让 main.py 正常收尾"
            )
        else:
            widgets["badge"].set_text("已停止")  # type: ignore[union-attr]
            widgets["badge"].props("color=grey-6")  # type: ignore[union-attr]
            last = (
                f"上次退出码 {status['exit_code']}"
                if status["exit_code"] is not None
                else "还没有启动过"
            )
            widgets["status_detail"].set_text(last)  # type: ignore[union-attr]

        external = page_state["external"]
        external_label = widgets.get("external")
        if external_label is not None:
            if external:
                pids = "、".join(str(item["pid"]) for item in external)
                external_label.set_text(
                    f"检测到外部也在运行 main.py（PID {pids}）。请先到那个命令行窗口按 Ctrl+C，"
                    "否则两边会同时抓取/上传。"
                )
                external_label.set_visibility(True)
            else:
                external_label.set_visibility(False)

        if page_state["was_busy"] and not status["running"]:
            refresh_checks()
            refresh_summary()
        page_state["was_busy"] = status["running"]

        start_btn = widgets.get("start_btn")
        stop_btn = widgets.get("stop_btn")
        if start_btn is not None:
            start_btn.set_enabled(not status["running"])
        if stop_btn is not None:
            stop_btn.set_enabled(status["running"])
        badge = widgets.get("badge")
        if badge is not None and external and not status["running"]:
            badge.set_text("外部进程运行中")
            badge.props("color=warning")

    async def refresh_external() -> None:
        if not connected():
            return
        try:
            page_state["external"] = await nicegui_run.io_bound(
                MANAGER.find_external_main, 0
            )
        except Exception:  # noqa: BLE001 - 探测失败不应影响界面
            page_state["external"] = []
        if connected():
            refresh_status()

    async def on_refresh() -> None:
        if not connected():
            return
        await refresh_external()
        if connected():
            refresh_checks()

    async def save_config(show_ok: bool = True) -> bool:
        sync_draft()
        try:
            await nicegui_run.io_bound(STORE.save, draft)
        except ConfigError as exc:
            show_error("配置没有保存", str(exc))
            return False
        except Exception as exc:  # noqa: BLE001
            show_error("配置保存失败", f"{type(exc).__name__}: {exc}")
            return False
        if not connected():
            return True
        if show_ok:
            ui.notify("配置已保存", type="positive")
        widgets["created_banner"].set_visibility(False)  # type: ignore[union-attr]
        widgets["load_error_card"].set_visibility(False)  # type: ignore[union-attr]
        refresh_summary()
        refresh_checks()
        return True

    async def on_save() -> None:
        if not await save_config(True) or not connected():
            return
        if MANAGER.busy():
            ui.notify("流水线正在使用旧配置，点“保存并重启”才会生效", type="info")

    async def on_save_restart() -> None:
        if not await save_config(show_ok=False) or not connected():
            return
        if MANAGER.busy():
            await nicegui_run.io_bound(MANAGER.stop, 12.0)
            if not connected():
                return
        ok, message = await nicegui_run.io_bound(MANAGER.start_main, True)
        if not connected():
            return
        ui.notify(message, type="positive" if ok else "negative")
        refresh_status()
        if ok:
            await refresh_external()
            widgets["tabs"].set_value("日志")  # type: ignore[union-attr]

    async def on_start() -> None:
        if MANAGER.busy():
            ui.notify(f"已有任务在运行（{MANAGER.label}）", type="warning")
            return
        # 启动前把界面上的最新改动写盘，避免“改了没保存，启动的却是旧配置”。
        if not await save_config(show_ok=False) or not connected():
            return
        ok, message = await nicegui_run.io_bound(MANAGER.start_main, True)
        if not connected():
            return
        ui.notify(message, type="positive" if ok else "negative")
        refresh_status()
        if ok:
            await refresh_external()
            widgets["tabs"].set_value("日志")  # type: ignore[union-attr]

    async def on_stop() -> None:
        ok, message = await nicegui_run.io_bound(MANAGER.stop, 12.0)
        if not connected():
            return
        ui.notify(message, type="positive" if ok else "warning")
        await refresh_external()

    async def on_check_config() -> None:
        if await save_config(show_ok=False) and connected():
            ui.notify("配置已保存，main.py 能正确解析这份配置", type="positive")

    async def on_export() -> None:
        if MANAGER.main_running():
            ui.notify("流水线正在运行，请先停止再导出 Cookie", type="warning")
            return
        if cookie_missing(str(draft.get("f2", {}).get("douyin_cookie", ""))):
            ui.notify(
                "请先在“配置 → 高级：f2 Cookie 与代理”里粘贴抖音 Cookie 再导出；"
                "如果已经扫码登录成功，则不需要再导出。",
                type="warning",
            )
            widgets["tabs"].set_value("配置")  # type: ignore[union-attr]
            return
        if not await save_config(show_ok=False):
            return
        if not connected():
            return
        account = str(draft["upload"].get("douyin_account") or "default")
        ok, message = MANAGER.export_cookie(account)
        if not connected():
            return
        ui.notify(message, type="positive" if ok else "negative")
        if ok:
            widgets["tabs"].set_value("日志")  # type: ignore[union-attr]

    async def on_login() -> None:
        if MANAGER.main_running():
            ui.notify("流水线正在运行，请先停止再登录", type="warning")
            return
        account = str(draft["upload"].get("douyin_account") or "default").strip() or "default"
        ok, message = MANAGER.login_douyin(account)
        if not connected():
            return
        ui.notify(message, type="positive" if ok else "negative")
        if ok:
            widgets["tabs"].set_value("日志")  # type: ignore[union-attr]

    async def on_assets() -> None:
        ok, message = MANAGER.download_assets()
        if not connected():
            return
        ui.notify(message, type="positive" if ok else "negative")
        if ok:
            widgets["tabs"].set_value("日志")  # type: ignore[union-attr]

    async def on_setup() -> None:
        ok, message = MANAGER.setup_environment()
        if not connected():
            return
        if ok:
            ui.notify(
                "开始修复环境：会重装依赖，可能需要几分钟。完成后请关闭本窗口，重新双击 gui.bat。",
                type="warning",
                multi_line=True,
            )
            widgets["tabs"].set_value("日志")  # type: ignore[union-attr]
        else:
            ui.notify(message, type="negative")

    async def on_save_api() -> None:
        try:
            await nicegui_run.io_bound(
                write_dotenv_value,
                ROOT / ".env",
                "DASHSCOPE_API_KEY",
                api_key_holder["value"],
            )
        except ConfigError as exc:
            show_error("API Key 没有保存", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            show_error("API Key 保存失败", f"{type(exc).__name__}: {exc}")
            return
        if not connected():
            return
        ui.notify("已写入 .env（重启流水线后生效）", type="positive")
        refresh_checks()

    def add_source() -> None:
        if not connected():
            return
        draft["sources"].append(
            {"platform": "douyin", "account": "", "url": "", "download_dir": ""}
        )
        widgets["sources"].refresh()  # type: ignore[union-attr]

    def remove_source(index: int) -> None:
        if not connected():
            return
        if len(draft["sources"]) <= 1:
            ui.notify("至少保留一个视频源", type="warning")
            return
        draft["sources"].pop(index)
        widgets["sources"].refresh()  # type: ignore[union-attr]

    def pull_logs() -> None:
        if not connected():
            return
        new_lines = MANAGER.log.since(page_state["log_index"])
        if not new_lines:
            return
        live_log = widgets.get("live_log")
        if live_log is None:
            page_state["log_index"] = MANAGER.log.count
            return
        for line in new_lines:
            if not connected():
                return
            live_log.push(line)  # type: ignore[union-attr]
        page_state["log_index"] = MANAGER.log.count

    def refresh_applog() -> None:
        if not connected():
            return
        log_path = ROOT / "app.log"
        applog = widgets.get("applog")
        if applog is None:
            return
        try:
            size = log_path.stat().st_size
        except OSError:
            if not page_state.get("applog_missing") and connected():
                applog.clear()  # type: ignore[union-attr]
                applog.push("（还没有 app.log；启动流水线后会生成）")  # type: ignore[union-attr]
                page_state["applog_missing"] = True
                page_state["applog_size"] = None
            return
        page_state["applog_missing"] = False
        if not connected():
            return
        previous = page_state.get("applog_size")
        if previous is None or size < previous:
            applog.clear()  # type: ignore[union-attr]
            for line in tail_file(log_path, 400):
                if not connected():
                    return
                applog.push(line)  # type: ignore[union-attr]
        elif size > previous:
            try:
                with log_path.open("rb") as fh:
                    fh.seek(previous)
                    chunk = fh.read(size - previous)
            except OSError:
                return
            for line in chunk.decode("utf-8", errors="replace").splitlines():
                if not connected():
                    return
                applog.push(line)  # type: ignore[union-attr]
        page_state["applog_size"] = size

    def timer_status() -> None:
        if connected():
            refresh_status()

    def timer_logs() -> None:
        if connected():
            pull_logs()

    def timer_applog() -> None:
        if connected():
            refresh_applog()

    # ------------------------------------------------------------------ 页头
    with ui.row().classes("w-full max-w-6xl mx-auto items-center justify-between pt-6 px-4"):
        with ui.column().classes("gap-0"):
            ui.label("Video Mover 控制台").classes("text-2xl font-bold")
            ui.label("抓取 → 去重 → 上传，填好配置点启动即可").classes("text-sm text-gray-500")
        with ui.row().classes("items-center gap-2"):
            widgets["badge"] = ui.badge("检查中", color="grey")
            widgets["start_btn"] = ui.button(
                "启动流水线", icon="play_arrow", on_click=on_start, color="positive"
            )
            widgets["stop_btn"] = ui.button(
                "停止", icon="stop", on_click=on_stop, color="negative"
            ).props("outline")

    with ui.dialog() as error_dialog, ui.card().classes("w-[760px] max-w-[95vw]"):
        widgets["error_dialog"] = error_dialog
        widgets["error_title"] = ui.label().classes("text-lg font-bold text-red-700")
        widgets["error_body"] = ui.label().classes(
            "whitespace-pre-wrap text-sm font-mono max-h-[60vh] overflow-auto"
        )
        with ui.row().classes("w-full justify-end"):
            ui.button("关闭", on_click=error_dialog.close).props("flat")

    # ------------------------------------------------------------------ 标签页
    with ui.tabs().classes("w-full max-w-6xl mx-auto px-4") as tabs:
        overview_tab = ui.tab("总览", icon="dashboard")
        config_tab = ui.tab("配置", icon="settings")
        log_tab = ui.tab("日志", icon="article")
        help_tab = ui.tab("帮助", icon="help")
    widgets["tabs"] = tabs

    with ui.tab_panels(tabs, value=overview_tab).classes("w-full max-w-6xl mx-auto px-4 pb-8"):
        # -------------------------------------------------------------- 总览
        with ui.tab_panel(overview_tab):
            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("运行状态").classes("text-lg font-bold")
                    ui.button(
                        "刷新",
                        icon="refresh",
                        on_click=on_refresh,
                    ).props("flat dense")
                widgets["status_detail"] = ui.label("检查中…").classes("text-sm")
                widgets["external"] = ui.label().classes(
                    "text-sm text-orange-600 whitespace-pre-wrap"
                )
                widgets["external"].set_visibility(False)
                ui.separator()
                ui.label(
                    "启动前会清空 Upload/videos 里的历史 mp4（与 start.bat 一致，防止重复发布）。"
                ).classes("text-xs text-gray-500")

            with ui.card().classes("w-full"):
                ui.label("当前配置").classes("text-lg font-bold")
                widgets["summary"] = ui.label("…").classes(
                    "text-sm text-gray-700 whitespace-pre-line"
                )

            with ui.card().classes("w-full"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("开跑前检查").classes("text-lg font-bold")
                    ui.button("重新检查", icon="refresh", on_click=refresh_checks).props(
                        "flat dense"
                    )
                widgets["checks"] = ui.column().classes("w-full gap-3")

            with ui.card().classes("w-full"):
                ui.label("快捷操作").classes("text-lg font-bold")
                with ui.row().classes("gap-2 flex-wrap"):
                    ui.button("检查配置", icon="checklist", on_click=on_check_config).props(
                        "outline"
                    )
                    ui.button("导出 Cookie", icon="key", on_click=on_export).props("outline")
                    ui.button(
                        "扫码登录抖音", icon="qr_code_scanner", on_click=on_login
                    ).props("outline")
                    ui.button("下载素材", icon="download", on_click=on_assets).props("outline")
                    ui.button("修复环境", icon="build", on_click=on_setup).props(
                        "outline color=warning"
                    )
                with ui.row().classes("gap-2 flex-wrap"):
                    ui.button(
                        "打开配置文件",
                        icon="description",
                        on_click=lambda: _open_path(STORE.path),
                    ).props("flat")
                    ui.button(
                        "打开 app.log",
                        icon="article",
                        on_click=lambda: _open_path(ROOT / "app.log"),
                    ).props("flat")
                    ui.button(
                        "打开仓库目录",
                        icon="folder",
                        on_click=lambda: _open_path(ROOT),
                    ).props("flat")

            with ui.card().classes("w-full bg-blue-50"):
                ui.label("使用顺序").classes("font-bold")
                ui.label(
                    "1) 在“配置”里填视频源和抖音 Cookie → 2) 保存配置 → "
                    "3) 导出 Cookie 或扫码登录 → 4) 下载素材 → 5) 启动流水线。\n"
                    "“修复环境”只在缺少依赖/ffmpeg/Playwright 时用，跑完要重新打开界面。"
                ).classes("text-sm whitespace-pre-wrap")

        # -------------------------------------------------------------- 配置
        with ui.tab_panel(config_tab):
            with ui.row().classes("w-full items-center justify-between pt-2"):
                ui.label("配置").classes("text-xl font-bold")
                with ui.row().classes("gap-2"):
                    ui.button("保存配置", icon="save", on_click=on_save)
                    ui.button("保存并重启", icon="restart_alt", on_click=on_save_restart).props(
                        "outline"
                    )

            widgets["created_banner"] = ui.card().classes(
                "w-full bg-blue-50"
            )
            with widgets["created_banner"]:
                ui.label("首次使用：已从 my_apps.yaml.example 复制出 my_apps.yaml。").classes(
                    "font-bold"
                )
                ui.label("请按下面的表单填写，保存后生效。").classes("text-sm")
            widgets["created_banner"].set_visibility(store_created)

            widgets["load_error_card"] = ui.card().classes("w-full bg-red-50")
            with widgets["load_error_card"]:
                ui.label("配置文件读取失败，下面用的是默认值；保存会用当前表单覆盖。").classes(
                    "font-bold text-red-700"
                )
                ui.label(load_error).classes("text-sm whitespace-pre-wrap font-mono")
            widgets["load_error_card"].set_visibility(bool(load_error))

            with ui.card().classes("w-full"):
                ui.label("视频源").classes("text-lg font-bold")
                ui.label(
                    "每个源就是一位博主的主页。抖音走浏览器通道，TikTok 走 f2。"
                ).classes("text-xs text-gray-500")

                @ui.refreshable
                def sources_ui() -> None:
                    for index, source in enumerate(draft["sources"]):
                        with ui.card().classes("w-full bg-gray-50"):
                            with ui.row().classes("w-full items-center gap-2 flex-wrap"):
                                ui.select(
                                    ["douyin", "tiktok"],
                                    label="平台",
                                    value=source.get("platform") or "douyin",
                                ).bind_value(source, "platform").classes("w-36")
                                ui.input(
                                    "博主账号", placeholder="@example"
                                ).bind_value(source, "account").classes("flex-1 min-w-[180px]")
                                ui.button(
                                    icon="delete",
                                    on_click=lambda _event=None, i=index: remove_source(i),
                                ).props("flat round color=negative")
                            ui.input(
                                "主页地址",
                                placeholder="https://www.douyin.com/@example",
                            ).bind_value(source, "url").classes("w-full")
                            ui.input(
                                "下载目录（可留空）",
                                placeholder="留空自动用 Download/<平台>/post/<账号>",
                            ).bind_value(source, "download_dir").classes("w-full")
                    ui.button("添加视频源", icon="add", on_click=add_source).props("outline")
                    widgets["sources"] = sources_ui

                sources_ui()

            with ui.card().classes("w-full"):
                ui.label("调度").classes("text-lg font-bold")
                with ui.row().classes("w-full gap-4 items-start"):
                    ui.number(
                        "调度间隔（分钟）",
                        min=1,
                        max=1440,
                        precision=0,
                        value=draft["schedule"].get("interval_minutes"),
                    ).bind_value(draft["schedule"], "interval_minutes").classes("w-56")
                    timezone = str(draft["schedule"].get("timezone") or "")
                    options = (
                        TIMEZONE_CHOICES
                        if timezone in TIMEZONE_CHOICES
                        else [timezone] + TIMEZONE_CHOICES
                    )
                    ui.select(
                        options,
                        label="时区",
                        value=timezone,
                        with_input=True,
                        new_value_mode="add-unique",
                    ).bind_value(draft["schedule"], "timezone").classes("w-72")

            with ui.card().classes("w-full"):
                ui.label("上传").classes("text-lg font-bold")
                ui.input("抖音上传账号名", placeholder="default").bind_value(
                    draft["upload"], "douyin_account"
                ).classes("w-72")
                with ui.row().classes("w-full gap-4 items-start"):
                    ui.number(
                        "最小发布间隔（分钟）",
                        min=0,
                        precision=0,
                        value=draft["upload"].get("min_interval_minutes"),
                    ).bind_value(draft["upload"], "min_interval_minutes").classes("w-56")
                    ui.number(
                        "每个话题补充热门标签数",
                        min=0,
                        precision=0,
                        value=draft["upload"].get("hot_tags"),
                    ).bind_value(draft["upload"], "hot_tags").classes("w-56")
                ui.switch(
                    "无窗口上传（推荐；抖音要短信验证时会自动切到有界面）"
                ).bind_value(draft["upload"], "headless")
                ui.switch(
                    "演练模式：只把表单填到“发布”前，不真正发布，也不删视频"
                ).bind_value(draft["upload"], "dry_run")

            with ui.card().classes("w-full"):
                ui.label("补抓历史（队列模式）").classes("text-lg font-bold")
                ui.label(
                    "days = 0 时只处理最近一个调度周期的新作品；大于 0 时把时间窗放大到这么多天，"
                    "并按未处理队列每轮只吃 max_per_run 条。"
                ).classes("text-xs text-gray-500")
                with ui.row().classes("w-full gap-4 items-start"):
                    ui.number(
                        "补抓最近多少天（0 = 关闭）",
                        min=0,
                        max=365,
                        precision=0,
                        value=draft["backfill"].get("days"),
                    ).bind_value(draft["backfill"], "days").classes("w-56")
                    ui.number(
                        "每个源单次下载上限",
                        min=1,
                        precision=0,
                        value=draft["backfill"].get("max_per_source"),
                    ).bind_value(draft["backfill"], "max_per_source").classes("w-56")
                    ui.number(
                        "每轮最多处理条数",
                        min=1,
                        precision=0,
                        value=draft["backfill"].get("max_per_run"),
                    ).bind_value(draft["backfill"], "max_per_run").classes("w-56")

            with ui.expansion("高级：路径、上传脚本与线程数", icon="folder_open").classes("w-full"):
                with ui.card().classes("w-full"):
                    with ui.row().classes("w-full gap-4 items-start"):
                        ui.input("去重目录").bind_value(draft["paths"], "dedup_dir").classes(
                            "w-56"
                        )
                        ui.input("上传目录").bind_value(draft["paths"], "upload_dir").classes(
                            "w-56"
                        )
                    with ui.row().classes("w-full gap-4 items-start"):
                        ui.input("刷新脚本").bind_value(draft["paths"], "flush_script").classes(
                            "w-72"
                        )
                        ui.input("去重脚本").bind_value(draft["paths"], "dedup_script").classes(
                            "w-72"
                        )
                    ui.textarea(
                        "上传脚本（每行一个，按顺序执行）",
                        value=scripts_holder["text"],
                    ).bind_value(scripts_holder, "text").props("autogrow").classes(
                        "w-full font-mono text-xs"
                    )
                    ui.number(
                        "最大工作线程数（留空 = CPU 核心数）",
                        min=1,
                        precision=0,
                        value=draft["runtime"].get("max_workers"),
                    ).bind_value(draft["runtime"], "max_workers").classes("w-72")

            with ui.expansion("高级：f2 Cookie 与代理", icon="cookie").classes("w-full"):
                with ui.card().classes("w-full"):
                    ui.label(
                        "抖音 Cookie 同时供抓取和上传使用。从浏览器开发者工具复制完整 Cookie "
                        "（形如 k=v; k2=v2）粘进来即可。"
                    ).classes("text-xs text-gray-500")
                    ui.textarea(
                        "douyin.cookie",
                        value=draft["f2"].get("douyin_cookie", ""),
                    ).bind_value(draft["f2"], "douyin_cookie").props("autogrow").classes(
                        "w-full font-mono text-xs"
                    )
                    with ui.row().classes("w-full gap-4 items-start"):
                        ui.input("抖音 HTTP 代理").bind_value(
                            draft["f2"], "douyin_http_proxy"
                        ).classes("w-72")
                        ui.input("抖音 HTTPS 代理").bind_value(
                            draft["f2"], "douyin_https_proxy"
                        ).classes("w-72")
                    ui.separator()
                    ui.label("只有 TikTok 源需要填 tiktok.cookie；没有 TikTok 源可留空。").classes(
                        "text-xs text-gray-500"
                    )
                    ui.textarea(
                        "tiktok.cookie",
                        value=draft["f2"].get("tiktok_cookie", ""),
                    ).bind_value(draft["f2"], "tiktok_cookie").props("autogrow").classes(
                        "w-full font-mono text-xs"
                    )
                    with ui.row().classes("w-full gap-4 items-start"):
                        ui.input("TikTok HTTP 代理").bind_value(
                            draft["f2"], "tiktok_http_proxy"
                        ).classes("w-72")
                        ui.input("TikTok HTTPS 代理").bind_value(
                            draft["f2"], "tiktok_https_proxy"
                        ).classes("w-72")

            with ui.card().classes("w-full"):
                ui.label("百炼 API Key（可选）").classes("text-lg font-bold")
                ui.label(
                    "只有上传脚本里包含视频号（Upload/vx_upload.py）时才需要。"
                    "保存到 .env，不进仓库。"
                ).classes("text-xs text-gray-500")
                with ui.row().classes("w-full items-start gap-2"):
                    ui.input(
                        "DASHSCOPE_API_KEY",
                        password=True,
                        password_toggle_button=True,
                    ).bind_value(api_key_holder, "value").classes("flex-1")
                    ui.button("写入 .env", icon="save", on_click=on_save_api).props("outline")

            with ui.row().classes("w-full justify-end pt-2"):
                ui.button("保存配置", icon="save", on_click=on_save)
                ui.button("保存并重启", icon="restart_alt", on_click=on_save_restart).props(
                    "outline"
                )

        # -------------------------------------------------------------- 日志
        with ui.tab_panel(log_tab):
            with ui.row().classes("w-full items-center justify-between pt-2"):
                ui.label("本次运行输出").classes("text-xl font-bold")
                with ui.row().classes("gap-2"):
                    ui.button(
                        "清空显示",
                        icon="clear_all",
                        on_click=lambda: (
                            widgets["live_log"].clear(),  # type: ignore[union-attr]
                            page_state.update(log_index=MANAGER.log.count),
                        ),
                    ).props("flat dense")
                    ui.button(
                        "打开 app.log",
                        icon="open_in_new",
                        on_click=lambda: _open_path(ROOT / "app.log"),
                    ).props("flat dense")
            widgets["live_log"] = ui.log(max_lines=2000).classes(
                "w-full h-72 font-mono text-xs bg-slate-950 text-slate-100 rounded p-3"
            )
            for line in MANAGER.log.snapshot(400):
                widgets["live_log"].push(line)  # type: ignore[union-attr]

            ui.label("app.log（历史）").classes("text-xl font-bold mt-4")
            ui.label("最多显示最近 400 行；main.py 的日志同时写在仓库根目录的 app.log。").classes(
                "text-xs text-gray-500"
            )
            widgets["applog"] = ui.log(max_lines=600).classes(
                "w-full h-72 font-mono text-xs bg-slate-950 text-slate-100 rounded p-3"
            )

        # -------------------------------------------------------------- 帮助
        with ui.tab_panel(help_tab):
            ui.markdown(
                """
### 第一次使用

1. **配置**：填视频源（博主主页）和抖音 Cookie。视频源可以加多个。
2. **保存配置**：点“保存配置”。保存前会先让 `main.py` 做一次完整校验，
   不合格会直接把原因显示出来，不会写坏文件。
3. **登录**：
   - 已从浏览器复制了 Cookie：点“导出 Cookie”（推荐，不用扫码）。
   - Cookie 过期/没有：点“扫码登录抖音”，在弹出的浏览器里扫码。
4. **下载素材**：首次运行前点“下载素材”（字体 / BGM / 水印 / 画中画）。
5. **启动流水线**：启动后会立即执行一轮，之后按调度间隔循环。

### 常用开关

- **无窗口上传**：默认开启。抖音要求短信验证时，上传器会自动改用有界面浏览器，
  窗口会留着让你输入验证码。
- **演练模式**：只填到发布按钮前，不真正发布、不删视频，适合先看流程。
- **补抓历史**：`补抓最近多少天` 大于 0 后，会按未处理队列分批处理老作品。

### 注意

- 启动前会删除 `Upload/videos` 里的历史 mp4（与 `start.bat` 一致），防止重复发布。
- 配置保存后，正在跑的流水线不会热加载；用“保存并重启”。
- 界面只监听 `127.0.0.1`，默认端口 `8765`；重复双击 `gui.bat` 会直接打开已有页面。
- 如果又双击了 `start.bat`，界面会检测到外部 `main.py` 并阻止重复启动。
"""
            )

    # ------------------------------------------------------------------ 刷新与定时器
    refresh_status()
    refresh_summary()
    refresh_checks()
    refresh_applog()
    ui.timer(1.0, timer_status)
    ui.timer(1.0, timer_logs)
    ui.timer(2.0, timer_applog)
    ui.timer(0.1, refresh_external, once=True)


def _show_browser() -> bool:
    flag = os.environ.get("VIDEO_MOVER_GUI_NO_BROWSER", "").strip().lower()
    return flag not in {"1", "true", "yes", "on"}


def _choose_port() -> int | None:
    base = int(os.environ.get("VIDEO_MOVER_GUI_PORT", "8765"))
    if _existing_gui(base):
        if _show_browser():
            webbrowser.open(f"http://127.0.0.1:{base}/")
            print(f"控制台已经在 http://127.0.0.1:{base}/ 运行，已打开浏览器。")
        else:
            print(f"控制台已经在 http://127.0.0.1:{base}/ 运行。")
        return None
    for port in range(base, base + 20):
        if not _port_open(port):
            return port
    print(f"[错误] {base}-{base + 19} 端口都被占用，请设置 VIDEO_MOVER_GUI_PORT 换一个端口。")
    return None


def main() -> int:
    global store_created
    try:
        store_created = STORE.ensure_config()
    except ConfigError as exc:
        print(f"[警告] {exc}")

    port = _choose_port()
    if port is None:
        return 0
    if store_created:
        print("首次使用：已从 my_apps.yaml.example 创建 my_apps.yaml，请在界面里填写。")
    print(f"Video Mover 控制台：http://127.0.0.1:{port}/")
    print("关闭这个窗口会同时停止正在运行的流水线。")
    nicegui_app.on_shutdown(lambda: MANAGER.stop(timeout=5.0))
    ui.run(
        host="127.0.0.1",
        port=port,
        title="Video Mover 控制台",
        favicon="🎬",
        language="zh-CN",
        reload=False,
        show=_show_browser(),
        dark=None,
        uvicorn_logging_level="warning",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
