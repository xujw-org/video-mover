# -*- coding: utf-8 -*-
"""配置读写层：把 my_apps.yaml 的 ``video_mover`` 小节和 f2 平台配置映射成
界面友好的扁平草稿（draft），保存时再写回原来的 YAML 文档。

设计约束：

* 用 ruamel.yaml round-trip 读写，尽量保留用户手工写的注释和其它小节
  （weibo / twitter / bark 等）原样不动；
* 保存前先做基础校验，再交给真正的 ``main.AppConfig`` 做一次权威校验
  （子进程，避免把 main.py 的日志 handler 带进界面进程）；
* 草稿里的字段都是 str / int / bool / None / list，方便 NiceGUI 直接绑定。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

CONFIG_NAME = "my_apps.yaml"
EXAMPLE_NAME = "my_apps.yaml.example"
BACKUP_SUFFIX = ".bak"

# GUI 目前只暴露内置过 f2 子命令的两个平台；其它平台需要手写 f2_command，
# 属于高级用法，继续用文本编辑器改 yaml。
KNOWN_PLATFORMS = ("douyin", "tiktok")

TIMEZONE_CHOICES = [
    "Asia/Shanghai",
    "Asia/Singapore",
    "Asia/Hong_Kong",
    "Asia/Tokyo",
    "Asia/Seoul",
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Los_Angeles",
]

COOKIE_PLACEHOLDERS = {
    "",
    "YOUR_DOYIN_COOKIE_HERE",
    "YOUR_TIKTOK_COOKIE_HERE",
    "YOUR_WEIBO_COOKIE_HERE",
    "YOUR_TWITTER_COOKIE_HERE",
}

DEFAULT_PATHS = {
    "dedup_dir": "Dedup",
    "upload_dir": "Upload",
    "flush_script": "flush_device_id.py",
    "dedup_script": "Dedup/dedup.py",
}


def default_draft() -> dict[str, Any]:
    """与 my_apps.yaml.example / main.DEFAULT_CONFIG 对齐的初始草稿。"""
    return {
        "sources": [
            {
                "platform": "douyin",
                "account": "@example",
                "url": "https://www.douyin.com/@example",
                "download_dir": "",
            }
        ],
        "upload": {
            "douyin_account": "default",
            "min_interval_minutes": 15,
            "hot_tags": 2,
            "headless": True,
            "dry_run": False,
        },
        "schedule": {"interval_minutes": 300, "timezone": "Asia/Singapore"},
        "backfill": {"days": 0, "max_per_source": 20, "max_per_run": 3},
        "runtime": {"max_workers": None, "config_file": CONFIG_NAME},
        "paths": {**DEFAULT_PATHS, "upload_scripts": ["Upload/douyin_upload.py"]},
        "f2": {
            "douyin_cookie": "",
            "douyin_http_proxy": "",
            "douyin_https_proxy": "",
            "tiktok_cookie": "",
            "tiktok_http_proxy": "",
            "tiktok_https_proxy": "",
        },
    }


class ConfigError(ValueError):
    """配置校验失败；message 直接展示给用户。"""


def _yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _int_or(value: Any, default: int | None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _bool_or(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def load_document(path: Path) -> CommentedMap:
    """读取完整 YAML 文档；文件不存在时返回空文档。"""
    if not path.is_file():
        return CommentedMap()
    try:
        with path.open(encoding="utf-8") as fh:
            data = _yaml().load(fh)
    except Exception as exc:  # noqa: BLE001 - 交给界面显示
        raise ConfigError(f"读取 {path.name} 失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name} 顶层不是键值结构，请检查文件内容")
    return data


def dump_document(document: dict[str, Any], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        _yaml().dump(document, fh)


def draft_from_document(document: dict[str, Any]) -> dict[str, Any]:
    """把完整 YAML 文档压成界面草稿（缺失字段用默认值补齐）。"""
    draft = default_draft()
    section = _as_dict(document.get("video_mover"))

    sources_raw = section.get("sources")
    if sources_raw is None:
        legacy = _as_dict(section.get("source"))
        sources_raw = [legacy] if legacy else []
    sources: list[dict[str, str]] = []
    if isinstance(sources_raw, list):
        for item in sources_raw:
            if not isinstance(item, dict):
                continue
            sources.append(
                {
                    "platform": _text(item.get("platform"), "douyin"),
                    "account": _text(item.get("account")),
                    "url": _text(item.get("url")),
                    "download_dir": _text(item.get("download_dir")),
                }
            )
    if sources:
        draft["sources"] = sources

    upload = _as_dict(section.get("upload"))
    if upload:
        draft["upload"].update(
            {
                "douyin_account": _text(upload.get("douyin_account"), "default"),
                "min_interval_minutes": _int_or(upload.get("min_interval_minutes"), 15),
                "hot_tags": _int_or(upload.get("hot_tags"), 2),
                "headless": _bool_or(upload.get("headless"), True),
                "dry_run": _bool_or(upload.get("dry_run"), False),
            }
        )

    schedule = _as_dict(section.get("schedule"))
    if schedule:
        draft["schedule"].update(
            {
                "interval_minutes": _int_or(schedule.get("interval_minutes"), 300),
                "timezone": _text(schedule.get("timezone"), "Asia/Singapore"),
            }
        )

    backfill = _as_dict(section.get("backfill"))
    if backfill:
        draft["backfill"].update(
            {
                "days": _int_or(backfill.get("days"), 0),
                "max_per_source": _int_or(backfill.get("max_per_source"), 20),
                "max_per_run": _int_or(backfill.get("max_per_run"), 3),
            }
        )

    runtime = _as_dict(section.get("runtime"))
    if runtime:
        draft["runtime"].update(
            {
                "max_workers": _int_or(runtime.get("max_workers"), None),
                "config_file": _text(runtime.get("config_file"), CONFIG_NAME),
            }
        )

    paths = _as_dict(section.get("paths"))
    if paths:
        for key in DEFAULT_PATHS:
            if paths.get(key) is not None:
                draft["paths"][key] = _text(paths.get(key))
        scripts = paths.get("upload_scripts")
        if scripts is None:
            legacy_script = paths.get("upload_script")
            scripts = [legacy_script] if legacy_script else None
        if isinstance(scripts, str):
            scripts = [scripts]
        if isinstance(scripts, list) and scripts:
            draft["paths"]["upload_scripts"] = [_text(item) for item in scripts if _text(item)]

    for platform in ("douyin", "tiktok"):
        conf = _as_dict(document.get(platform))
        if not conf:
            continue
        draft["f2"][f"{platform}_cookie"] = _text(conf.get("cookie"))
        proxies = _as_dict(conf.get("proxies"))
        draft["f2"][f"{platform}_http_proxy"] = _text(proxies.get("http://"))
        draft["f2"][f"{platform}_https_proxy"] = _text(proxies.get("https://"))

    return draft


def _sync_map(target: dict[str, Any], values: dict[str, Any]) -> None:
    """按键更新 CommentedMap，保留已有键的顺序和注释。"""
    for key, value in values.items():
        target[key] = value


def apply_draft(document: dict[str, Any], draft: dict[str, Any]) -> None:
    """把草稿写回完整 YAML 文档；不碰界面没有暴露的字段。"""
    section = document.get("video_mover")
    if not isinstance(section, dict):
        section = CommentedMap()
        document["video_mover"] = section

    # 视频源：按位置复用旧 CommentedMap，保留每项注释；多余项删掉。
    old_sources = section.get("sources")
    if not isinstance(old_sources, list):
        old_sources = []
    new_sources = CommentedSeq()
    for index, source in enumerate(draft["sources"]):
        if index < len(old_sources) and isinstance(old_sources[index], dict):
            item = old_sources[index]
        else:
            item = CommentedMap()
        item["platform"] = source["platform"]
        item["account"] = source["account"]
        item["url"] = source["url"]
        download_dir = str(source.get("download_dir") or "").strip()
        if download_dir:
            item["download_dir"] = download_dir
        else:
            item.pop("download_dir", None)
        new_sources.append(item)
    section["sources"] = new_sources
    # 旧版单个 source 与 sources 同时存在容易混淆，界面保存时移除。
    section.pop("source", None)

    upload = section.get("upload")
    if not isinstance(upload, dict):
        upload = CommentedMap()
        section["upload"] = upload
    _sync_map(
        upload,
        {
            "douyin_account": draft["upload"]["douyin_account"],
            "min_interval_minutes": draft["upload"]["min_interval_minutes"],
            "hot_tags": draft["upload"]["hot_tags"],
            "headless": draft["upload"]["headless"],
            "dry_run": draft["upload"]["dry_run"],
        },
    )

    schedule = section.get("schedule")
    if not isinstance(schedule, dict):
        schedule = CommentedMap()
        section["schedule"] = schedule
    _sync_map(
        schedule,
        {
            "interval_minutes": draft["schedule"]["interval_minutes"],
            "timezone": draft["schedule"]["timezone"],
        },
    )

    backfill = section.get("backfill")
    if not isinstance(backfill, dict):
        backfill = CommentedMap()
        section["backfill"] = backfill
    _sync_map(
        backfill,
        {
            "days": draft["backfill"]["days"],
            "max_per_source": draft["backfill"]["max_per_source"],
            "max_per_run": draft["backfill"]["max_per_run"],
        },
    )

    runtime = section.get("runtime")
    if not isinstance(runtime, dict):
        runtime = CommentedMap()
        section["runtime"] = runtime
    runtime["max_workers"] = draft["runtime"]["max_workers"]
    runtime.setdefault("config_file", draft["runtime"]["config_file"] or CONFIG_NAME)

    paths = section.get("paths")
    if not isinstance(paths, dict):
        paths = CommentedMap()
        section["paths"] = paths
    for key in DEFAULT_PATHS:
        paths[key] = draft["paths"][key]
    paths["upload_scripts"] = list(draft["paths"]["upload_scripts"])
    # 旧版单脚本键由 upload_scripts 取代，避免两份配置打架。
    paths.pop("upload_script", None)

    for platform in ("douyin", "tiktok"):
        conf = document.get(platform)
        if not isinstance(conf, dict):
            conf = CommentedMap()
            document[platform] = conf
        cookie = draft["f2"][f"{platform}_cookie"].strip()
        if cookie:
            conf["cookie"] = cookie
        proxies = conf.get("proxies")
        if not isinstance(proxies, dict):
            proxies = CommentedMap()
            conf["proxies"] = proxies
        proxies["http://"] = draft["f2"][f"{platform}_http_proxy"].strip()
        proxies["https://"] = draft["f2"][f"{platform}_https_proxy"].strip()


def validate_draft(draft: dict[str, Any]) -> list[str]:
    """界面层的基础校验；返回空列表表示通过。"""
    errors: list[str] = []
    sources = draft.get("sources") or []
    if not sources:
        errors.append("至少需要一个视频源（博主主页）。")
    for index, source in enumerate(sources, start=1):
        label = f"视频源 {index}"
        platform = str(source.get("platform") or "").strip()
        if not platform:
            errors.append(f"{label}：请选择平台。")
        elif platform not in KNOWN_PLATFORMS:
            supported = " / ".join(KNOWN_PLATFORMS)
            errors.append(
                f"{label}：界面只支持 {supported}，其它平台请直接编辑 my_apps.yaml。"
            )
        account = str(source.get("account") or "").strip()
        if not account:
            errors.append(f"{label}：请填写博主账号。")
        url = str(source.get("url") or "").strip()
        if not url:
            errors.append(f"{label}：请填写博主主页地址。")
        elif not url.lower().startswith(("http://", "https://")):
            errors.append(f"{label}：主页地址要以 http:// 或 https:// 开头。")

    schedule = draft.get("schedule") or {}
    interval = schedule.get("interval_minutes")
    try:
        interval_value = int(interval)
    except (TypeError, ValueError):
        errors.append("调度间隔必须是整数分钟。")
    else:
        if not 1 <= interval_value <= 1440:
            errors.append("调度间隔必须在 1-1440 分钟之间。")
    timezone = str(schedule.get("timezone") or "").strip()
    if not timezone:
        errors.append("请填写时区。")
    else:
        try:
            ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            errors.append(f"时区 {timezone!r} 无效，请填 IANA 名称，例如 Asia/Shanghai。")

    upload = draft.get("upload") or {}
    if not str(upload.get("douyin_account") or "").strip():
        errors.append("请填写抖音上传账号名。")
    for key, label in (("min_interval_minutes", "最小发布间隔"), ("hot_tags", "热门标签数")):
        try:
            value = int(upload.get(key))
        except (TypeError, ValueError):
            errors.append(f"{label}必须是整数。")
        else:
            if value < 0:
                errors.append(f"{label}不能为负数。")

    backfill = draft.get("backfill") or {}
    days = _int_or(backfill.get("days"), None)
    if days is None or not 0 <= days <= 365:
        errors.append("补抓天数必须是 0-365 的整数（0 = 关闭）。")
    for key, label in (("max_per_source", "每个源单次上限"), ("max_per_run", "每轮处理上限")):
        value = _int_or(backfill.get(key), None)
        if value is None or value < 1:
            errors.append(f"{label}必须是 >=1 的整数。")

    max_workers = draft.get("runtime", {}).get("max_workers")
    if max_workers not in (None, ""):
        value = _int_or(max_workers, None)
        if value is None or value < 1:
            errors.append("最大工作线程数必须是正整数，或留空使用 CPU 核心数。")

    scripts = (draft.get("paths") or {}).get("upload_scripts") or []
    if not scripts:
        errors.append("至少需要一个上传脚本。")
    else:
        for index, script in enumerate(scripts, start=1):
            if not str(script).strip():
                errors.append(f"上传脚本 {index} 为空。")

    for key, label in DEFAULT_PATHS.items():
        if not str((draft.get("paths") or {}).get(key) or "").strip():
            errors.append(f"{label} 路径不能为空。")

    return errors


def needs_douyin_cookie(draft: dict[str, Any]) -> bool:
    """是否依赖抖音 cookie：抖音源抓取或抖音上传。"""
    if any(str(s.get("platform")) == "douyin" for s in draft.get("sources") or []):
        return True
    scripts = (draft.get("paths") or {}).get("upload_scripts") or []
    return any("douyin" in str(script).lower() for script in scripts)


def cookie_missing(value: str) -> bool:
    return value.strip() in COOKIE_PLACEHOLDERS


def validate_with_main(config_path: Path, timeout: float = 60.0) -> None:
    """用 ``main.AppConfig`` 做权威校验（子进程，隔离日志与副作用）。"""
    code_root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(code_root)!r}); "
        "import main; "
        f"main.AppConfig(config_path={str(config_path)!r}); "
        "print('CONFIG_OK')"
    )
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with tempfile.TemporaryDirectory(prefix="vm-gui-validate-") as tmp:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", code],
                cwd=tmp,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ConfigError("配置校验超时，请检查配置里是否有死循环或网络阻塞。") from exc
        except OSError as exc:
            raise ConfigError(f"无法启动配置校验进程：{exc}") from exc
    output = (proc.stdout or "").strip()
    if proc.returncode != 0:
        tail = "\n".join(output.splitlines()[-12:]) or "（没有输出）"
        raise ConfigError(f"main.py 不接受这份配置：\n{tail}")
    if "CONFIG_OK" not in output:
        raise ConfigError(f"配置校验没有正常结束：\n{output[-1500:]}")


class ConfigStore:
    """仓库内 my_apps.yaml 的读写入口。"""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.path = self.root / CONFIG_NAME
        self.example = self.root / EXAMPLE_NAME

    def ensure_config(self) -> bool:
        """配置缺失时从模板复制一份；返回是否新建。"""
        if self.path.is_file():
            return False
        if not self.example.is_file():
            raise ConfigError(f"缺少 {EXAMPLE_NAME}，无法自动创建配置文件。")
        shutil.copyfile(self.example, self.path)
        return True

    def load(self) -> dict[str, Any]:
        return draft_from_document(load_document(self.path))

    def save(self, draft: dict[str, Any], *, validate: bool = True) -> None:
        errors = validate_draft(draft)
        if errors:
            raise ConfigError("\n".join(errors))
        if not self.path.is_file():
            self.ensure_config()
        document = load_document(self.path)
        apply_draft(document, draft)
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            dump_document(document, tmp)
            if validate:
                validate_with_main(tmp)
            if self.path.is_file():
                backup = self.path.with_name(self.path.name + BACKUP_SUFFIX)
                shutil.copyfile(self.path, backup)
            os.replace(tmp, self.path)
        finally:
            tmp.unlink(missing_ok=True)

    def summary(self, draft: dict[str, Any] | None = None) -> dict[str, Any]:
        data = draft or self.load()
        return {
            "sources": len(data.get("sources") or []),
            "interval": data.get("schedule", {}).get("interval_minutes"),
            "timezone": data.get("schedule", {}).get("timezone"),
            "account": data.get("upload", {}).get("douyin_account"),
            "headless": data.get("upload", {}).get("headless"),
            "dry_run": data.get("upload", {}).get("dry_run"),
            "backfill_days": data.get("backfill", {}).get("days"),
        }


# ---------------------------------------------------------------------------
# .env：只管理界面暴露的 DASHSCOPE_API_KEY，保留其它行与注释
# ---------------------------------------------------------------------------
def read_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _dotenv_value(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ConfigError("这项配置不能包含换行。")
    value = value.strip()
    if not value:
        return ""
    if any(ch in value for ch in ' \t#'):
        return '"' + value.replace('"', "'") + '"'
    return value


def write_dotenv_value(path: Path, key: str, value: str) -> None:
    """写入/更新一个键；保留其它行、注释和顺序。"""
    line = f"{key}={_dotenv_value(value)}"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    replaced = False
    for index, old in enumerate(lines):
        stripped = old.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        if stripped.split("=", 1)[0].strip() == key:
            lines[index] = line
            replaced = True
            break
    if not replaced:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(line)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
