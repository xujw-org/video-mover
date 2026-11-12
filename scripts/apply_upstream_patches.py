#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对上游依赖做可重复执行的兼容补丁。

背景：原仓库 README 要求手动改第三方库源码（f2 的两处、视频号上传的一处），
手动步骤容易丢、也无法验证。本脚本把这三处补丁变成可重复执行的自动化操作，
每次运行都会先校验目标代码是否存在，校验失败就报错退出，绝不静默跳过。

针对的上游版本：f2==0.0.1.7（见 requirements.txt 的版本锁定）。
补丁打在“已安装的 f2”上（即虚拟环境的 site-packages），因此每次重装或升级
依赖后都需要重新运行一次；setup.bat 已包含这一步。

用法：
    python scripts/apply_upstream_patches.py            # 应用全部补丁
    python scripts/apply_upstream_patches.py --check    # 只检查，不修改
    python scripts/apply_upstream_patches.py --f2-dir <f2 包所在目录>  # 指定 f2 位置（测试用）

退出码：0 = 全部补丁已应用或早已应用；1 = 有补丁校验失败，需要人工处理；
        2 = 未找到已安装的 f2（请先 pip install -r requirements.txt）。

详细说明见 PATCHES.md。
"""

import argparse
import importlib.util
import re
import sys
from pathlib import Path

# 补丁在 f2 0.0.1.7 源码中核对过（2026-11-12，官方 sdist）。
# 注意：README 原文写的行号（handler.py 约 389 行）与 0.0.1.7 实际代码对不上，
# 389 行是 `if cursor < min_cursor:`，并不存在 `params={"cursor": cursor, ...}`；
# 实际的修复点是 cursor 从 kwargs 取值处的类型转换，见 PATCHES.md。
F2_VERSION = "0.0.1.7"

PATCH_MARKER = "VIDEO-MOVER PATCH"


def log(msg: str) -> None:
    print(msg, flush=True)


def find_f2_dir(cli_dir: str | None) -> Path | None:
    """定位已安装的 f2 包目录。"""
    if cli_dir:
        p = Path(cli_dir)
        if (p / "apps" / "tiktok" / "handler.py").exists() and (p / "utils" / "utils.py").exists():
            return p
        log(f"[错误] --f2-dir 指定的目录不是有效的 f2 包目录: {cli_dir}")
        return None
    spec = importlib.util.find_spec("f2")
    if spec is None or not spec.submodule_search_locations:
        return None
    return Path(spec.submodule_search_locations[0])


def backup(path: Path) -> None:
    """首次修改前备份原文件为 .bak（已存在则不再覆盖）。"""
    bak = path.with_suffix(path.suffix + ".bak")
    if not bak.exists():
        bak.write_bytes(path.read_bytes())
        log(f"  已备份原文件 -> {bak.name}")


def apply_replacement(content: str, old: str, new: str, name: str) -> tuple[str, str]:
    """对一段文本应用一次替换，返回 (新文本, 状态)。

    状态：APPLIED（本次替换成功）、ALREADY_APPLIED（已是补丁后的样子）、
    FAILED（既找不到原文，也找不到补丁后的文本，需要人工检查）。

    注意：必须先判断 new 是否已存在再判断 old，因为补丁后的文本里可能仍包含
    old 的子串（例如缩进不同的同一行），先判 old 会导致重复打补丁、破坏代码。
    """
    if new in content:
        return content, "ALREADY_APPLIED"
    if old in content:
        if content.count(old) != 1:
            return content, f"FAILED（{name}：原文出现 {content.count(old)} 次，预期 1 次，不敢改）"
        return content.replace(old, new, 1), "APPLIED"
    return content, f"FAILED（{name}：找不到原文，上游代码可能已变，请看 PATCHES.md 人工处理）"


def patch_cursor_int(handler_path: Path, check_only: bool) -> str:
    """补丁 1：f2 tiktok handler 的 cursor 必须是 int。

    用行锚定正则匹配全部 `cursor = self.kwargs.get("cursor", 0)`（f2 0.0.1.7 里
    共有 5 处），而不是写死次数；已打过补丁的行不会被重复匹配。
    """
    old_re = re.compile(r'^( *)cursor = self\.kwargs\.get\("cursor", 0\) *$', re.M)
    new_line = f'cursor = int(self.kwargs.get("cursor", 0) or 0)  # {PATCH_MARKER}：cursor 可能是字符串，接口要求 int'
    marker = 'int(self.kwargs.get("cursor", 0) or 0)'
    content = handler_path.read_text(encoding="utf-8")
    unpatched = list(old_re.finditer(content))
    already = content.count(marker)
    if not unpatched and already > 0:
        return f"ALREADY_APPLIED（{already} 处已是补丁后的样子）"
    if not unpatched:
        return "FAILED（找不到原文，上游代码可能已变，请看 PATCHES.md 人工处理）"
    if check_only:
        return f"APPLIED（--check 模式，未实际写入；将替换 {len(unpatched)} 处）"
    backup(handler_path)
    new_content, n = old_re.subn(lambda m: f"{m.group(1)}{new_line}", content)
    handler_path.write_text(new_content, encoding="utf-8")
    verify = handler_path.read_text(encoding="utf-8")
    if not old_re.search(verify) and verify.count(marker) == already + n:
        return f"APPLIED（共替换 {n} 处）"
    return "FAILED（写入后校验失败，请检查文件）"


def patch_date_parsing(utils_path: Path, check_only: bool) -> str:
    """补丁 2：f2 日期解析兼容纯日期与带时间两种写法（共 4 处）。"""
    replacements = [
        (
            "str_2_timestamp 增加多格式回退",
            '    date_obj = datetime.datetime.strptime(date_str, format)\n'
            '    if unit == "milli":\n',
            '    try:\n'
            '        date_obj = datetime.datetime.strptime(date_str, format)\n'
            '    except ValueError:\n'
            f'        # {PATCH_MARKER}：再试几种常见格式，兼容纯日期与带时间的写法\n'
            '        for _fallback_format in ("%Y-%m-%d %H-%M-%S", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):\n'
            '            if _fallback_format == format:\n'
            '                continue\n'
            '            try:\n'
            '                date_obj = datetime.datetime.strptime(date_str, _fallback_format)\n'
            '                break\n'
            '            except ValueError:\n'
            '                continue\n'
            '        else:\n'
            '            raise\n'
            '    if unit == "milli":\n',
        ),
        (
            "interval_2_timestamp 不再对带时间的区间重复追加时间后缀",
            '        if date_type == "start":\n'
            '            date_str = f"{start_date} 00-00-00"\n'
            '        elif date_type == "end":\n'
            '            date_str = f"{end_date} 23-59-59"\n'
            '        else:\n',
            '        if date_type == "start":\n'
            f'            # {PATCH_MARKER}：带时间的区间不再重复追加时间后缀\n'
            '            date_str = start_date if " " in start_date else f"{start_date} 00-00-00"\n'
            '        elif date_type == "end":\n'
            '            date_str = end_date if " " in end_date else f"{end_date} 23-59-59"\n'
            '        else:\n',
        ),
        (
            "filter_by_date_interval 区间端点兼容带时间写法",
            '        start_str, end_str = interval.split("|")\n'
            '        start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d")\n'
            '        end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d") + datetime.timedelta(\n'
            '            days=1, seconds=-1\n'
            '        )\n'
            '\n'
            '        if end_date < start_date:\n',
            '        start_str, end_str = interval.split("|")\n'
            f'        # {PATCH_MARKER}：区间端点兼容带时间的写法\n'
            '        try:\n'
            '            start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d %H-%M-%S")\n'
            '        except ValueError:\n'
            '            start_date = datetime.datetime.strptime(start_str, "%Y-%m-%d")\n'
            '        try:\n'
            '            end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d %H-%M-%S")\n'
            '        except ValueError:\n'
            '            end_date = datetime.datetime.strptime(end_str, "%Y-%m-%d") + datetime.timedelta(\n'
            '                days=1, seconds=-1\n'
            '            )\n'
            '\n'
            '        if end_date < start_date:\n',
        ),
        (
            "filter_by_date_interval 作品创建时间兼容纯日期",
            '        try:\n'
            '            date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H-%M-%S")\n'
            '        except ValueError:\n'
            '            logger.warning(_("无法解析作品的创建时间：{0}").format(date_str))\n'
            '            return False\n'
            '\n'
            '        if date < start_date or date > end_date:\n',
            '        try:\n'
            '            date = datetime.datetime.strptime(date_str, "%Y-%m-%d %H-%M-%S")\n'
            '        except ValueError:\n'
            '            try:\n'
            f'                # {PATCH_MARKER}：兼容纯日期的创建时间\n'
            '                date = datetime.datetime.strptime(date_str, "%Y-%m-%d")\n'
            '            except ValueError:\n'
            '                logger.warning(_("无法解析作品的创建时间：{0}").format(date_str))\n'
            '                return False\n'
            '\n'
            '        if date < start_date or date > end_date:\n',
        ),
    ]
    content = utils_path.read_text(encoding="utf-8")
    statuses = []
    new_content = content
    for name, old, new in replacements:
        new_content, status = apply_replacement(new_content, old, new, name)
        statuses.append(f"{name}：{status}")
        if status.startswith("FAILED"):
            return "FAILED（" + "；".join(statuses) + "）"
    if all(s.endswith("ALREADY_APPLIED") for s in statuses):
        return "ALREADY_APPLIED"
    if check_only:
        return "APPLIED（--check 模式，未实际写入）"
    backup(utils_path)
    utils_path.write_text(new_content, encoding="utf-8")
    verify = utils_path.read_text(encoding="utf-8")
    if PATCH_MARKER in verify:
        return "APPLIED"
    return "FAILED（写入后校验失败，请检查文件）"


def patch_tencent_timeout(tencent_path: Path, check_only: bool) -> str:
    """补丁 3：视频号上传的页面跳转等待超时 1500ms -> 10000ms。

    核对结果（2026-11-12）：本仓库自带的 Upload/uploader/tencent_uploader/main.py
    共 267 行，全文没有 1500，click_publish 里已经是 timeout=10000，
    所以这处补丁在当前版本里早已满足，无需修改。
    """
    content = tencent_path.read_text(encoding="utf-8")
    if "timeout=1500" in content:
        if check_only:
            return "APPLIED（--check 模式，未实际写入）"
        backup(tencent_path)
        tencent_path.write_text(content.replace("timeout=1500", "timeout=10000"), encoding="utf-8")
        return "APPLIED"
    if "timeout=10000" in content:
        return "ALREADY_APPLIED（本仓库自带代码已是 10000ms，无需修改）"
    return "FAILED（既找不到 timeout=1500，也找不到 timeout=10000，请人工检查）"


def main() -> int:
    parser = argparse.ArgumentParser(description="应用 video-mover 的上游兼容补丁（f2==%s）" % F2_VERSION)
    parser.add_argument("--check", action="store_true", help="只检查，不修改任何文件")
    parser.add_argument("--f2-dir", default=None, help="指定 f2 包所在目录（测试用）")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    f2_dir = find_f2_dir(args.f2_dir)
    if f2_dir is None:
        log("[错误] 未找到已安装的 f2，请先执行：pip install -r requirements.txt")
        log("       （或用 --f2-dir 指定 f2 包所在目录）")
        return 2

    log(f"f2 位置：{f2_dir}")
    handler_path = f2_dir / "apps" / "tiktok" / "handler.py"
    utils_path = f2_dir / "utils" / "utils.py"
    tencent_path = repo_root / "Upload" / "uploader" / "tencent_uploader" / "main.py"
    for p in (handler_path, utils_path, tencent_path):
        if not p.exists():
            log(f"[错误] 找不到目标文件：{p}")
            return 1

    results = []
    log("\n[补丁 1] f2 tiktok handler：cursor 转 int")
    results.append(("补丁 1 cursor 转 int", patch_cursor_int(handler_path, args.check)))
    log(f"  -> {results[-1][1]}")

    log("\n[补丁 2] f2 utils：日期解析兼容纯日期与带时间")
    results.append(("补丁 2 日期解析兼容", patch_date_parsing(utils_path, args.check)))
    log(f"  -> {results[-1][1]}")

    log("\n[补丁 3] 视频号上传：页面跳转等待超时 1500ms -> 10000ms")
    results.append(("补丁 3 视频号超时", patch_tencent_timeout(tencent_path, args.check)))
    log(f"  -> {results[-1][1]}")

    log("\n--- 汇总 ---")
    failed = False
    for name, status in results:
        log(f"  {name}：{status}")
        if status.startswith("FAILED"):
            failed = True
    if failed:
        log("\n有补丁失败，请看 PATCHES.md 人工处理后再重试。")
        return 1
    log("\n全部补丁已应用（或早已应用）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
