# -*- coding: utf-8 -*-
"""批量上传 Upload/videos 里的处理后视频到抖音。

由 main.py 的 UploadHandler 按配置调用（paths.upload_scripts），也可以单独跑：

    python Upload/douyin_upload.py

流程：读 my_apps.yaml 的 video_mover.upload.douyin_account 找到登录 cookie，
校验有效后，把 Upload/videos 下的每个 mp4 依次传到抖音创作者中心（立即发布），
传成功的从 Upload/videos 里删除，失败的保留、最后返回非零退出码。

标题与话题：优先用 f2 下载时写下的描述文件（`<时间>/<时间>_desc.txt`，
与 Upload/vx_upload.py 同一约定），第一行当标题、全文里的 #话题 当标签；
找不到描述文件时用文件名当标题、不带话题。

首次使用前必须在 Windows 上扫码登录一次生成 cookie：

    python Upload/cli_main.py douyin <账号名> login

cookie 保存在 Upload/cookies/douyin_<账号名>.json，过期后重新扫码即可。
上传默认**无窗口**（headless）跑：不需要盯着浏览器，也不会在桌面弹窗。
`video_mover.upload` 里两个可选开关：

    upload:
      headless: true    # false 时回到有界面，方便跟界面排查问题
      dry_run: false    # true 时只把表单填到“发布”前，不真的发布（不删文件）
"""
import asyncio
import os
import re
import sys
from pathlib import Path

# 标题往往带 emoji（抖音作品 desc 原样带过来），Windows 控制台默认 cp936，
# 直接 print 会抛 UnicodeEncodeError 把整个上传打断。跟 main.py 一样把
# stdout/stderr 改成 UTF-8（errors=replace）；在 start.bat 的 chcp 65001 下
# 显示正常，在旧控制台里至少不会崩。
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 脚本所在目录（Upload/）进 sys.path，保证 `import conf / uploader.*` 能找到。
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from conf import BASE_DIR

VIDEO_DIR = Path(BASE_DIR) / "videos"
COOKIES_DIR = Path(BASE_DIR) / "cookies"
MAX_TITLE_LEN = 30  # 抖音标题上限 30 字，DouYinVideo 内部也会截断，这里先截好方便打日志
MAX_TAGS = 10
_TAG_RE = re.compile(r"#([^\s#]+)")


def _truthy(value) -> bool:
    """配置里的开关可能是 bool，也可能是 "true"/"1"/"yes"/"on" 字串。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def apply_upload_options(upload_cfg, environ=None):
    """把 video_mover.upload 的 headless / dry_run 落到环境变量上。

    浏览器是在 uploader/douyin_uploader 里深层创建的，用环境变量传最省事：
    - ``DOUYIN_UPLOAD_HEADED=1``  → 有界面（默认无窗口）
    - ``DOUYIN_UPLOAD_DRY_RUN=1`` → 只填到“发布”前，不真正发布

    返回实际生效的 ``{"headless": bool, "dry_run": bool}``，方便打日志和测试。
    """
    environ = os.environ if environ is None else environ
    upload_cfg = upload_cfg or {}
    # 配置是主来源；环境变量只能往“更安全/更好调试”的方向覆盖：
    # DOUYIN_UPLOAD_HEADED=1 强制有界面，DOUYIN_UPLOAD_DRY_RUN=1 强制不发布。
    headless = _truthy(upload_cfg.get("headless", True)) and not _truthy(
        environ.get("DOUYIN_UPLOAD_HEADED")
    )
    dry_run = _truthy(upload_cfg.get("dry_run", False)) or _truthy(
        environ.get("DOUYIN_UPLOAD_DRY_RUN")
    )
    if headless:
        environ.pop("DOUYIN_UPLOAD_HEADED", None)
    else:
        environ["DOUYIN_UPLOAD_HEADED"] = "1"
    if dry_run:
        environ["DOUYIN_UPLOAD_DRY_RUN"] = "1"
    else:
        environ.pop("DOUYIN_UPLOAD_DRY_RUN", None)
    return {"headless": headless, "dry_run": dry_run}


def _load_video_mover_section(config_path):
    """读取 my_apps.yaml 的 video_mover 小节（只读配置，不读密钥以外的字段）。"""
    try:
        import yaml
    except ImportError as e:
        raise RuntimeError("读取配置需要 PyYAML，请先 pip install -r requirements.txt") from e
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"找不到配置文件 {config_path}，请先从 my_apps.yaml.example 复制一份并填写"
        )
    with open(config_path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    section = data.get("video_mover", {}) or {}
    if not isinstance(section, dict):
        raise ValueError("my_apps.yaml 里 video_mover 小节不是键值结构")
    return section


def _resolve_download_dirs(section, repo_root):
    """返回全部视频源的下载目录（用于找 f2 写下的描述文件）。

    与 main.py.AppConfig 的推导保持一致：sources 里没写 download_dir 的，
    默认是 Download/<platform>/post/<account>；不存在的目录跳过。
    """
    raw_dirs = []
    sources = section.get("sources")
    if isinstance(sources, list):
        for item in sources:
            if not isinstance(item, dict):
                continue
            raw = item.get("download_dir")
            if raw is None:
                platform = str(item.get("platform") or "tiktok")
                account = str(item.get("account") or "@example").lstrip("@")
                raw = f"Download/{platform}/post/{account}"
            raw_dirs.append(raw)
    if not raw_dirs:
        legacy = (section.get("paths", {}) or {}).get("download_dir")
        if legacy:
            raw_dirs.append(legacy)
    dirs = []
    for raw in raw_dirs:
        path = Path(str(raw))
        path = path if path.is_absolute() else Path(repo_root) / path
        # 优先配置里的下载目录本身（抖音浏览器通道会把作品放在
        # <配置目录>/<昵称>/<时间>/）；配置目录不存在时退一层——手动用
        # douyin_fetch.py 默认参数抓的历史作品落在 Download/douyin/post/<昵称>/<时间>/，
        # 正好是配置目录的上一层。
        if path.is_dir():
            candidate = path
        elif path.parent.is_dir():
            candidate = path.parent
        else:
            continue
        if candidate not in dirs:
            dirs.append(candidate)
    return dirs


def parse_desc_text(text):
    """从 f2 的描述文件解析标题与话题。

    第一行非空行当标题（超长截断到 30 字）；全文里的 #话题 依次去重，最多 MAX_TAGS 个。
    """
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    title = lines[0][:MAX_TITLE_LEN] if lines else ""
    tags = []
    for tag in _TAG_RE.findall(text or ""):
        tag = tag.strip()
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return title, tags


def find_desc_file(video_path, download_dirs):
    """按去重输出的文件名约定找描述文件。

    去重输出沿用下载文件名 `<时间>_video.mp4`，描述文件在下载目录下的
    `<时间>/<时间>_desc.txt`（与 Upload/vx_upload.py 同一约定）。

    抖音走浏览器通道后，下载目录还会多一层昵称（`Download/.../post/<账号>/<昵称>/<时间>/`），
    所以这里先看下载目录本层，再往下一层找一次。
    """
    video_path = Path(video_path)
    stem = video_path.name
    if stem.endswith("_video.mp4"):
        video_time = stem[: -len("_video.mp4")]
    else:
        video_time = video_path.stem
    rel = Path(video_time) / f"{video_time}_desc.txt"
    for download_dir in download_dirs:
        download_dir = Path(download_dir)
        candidate = download_dir / rel
        if candidate.is_file():
            return candidate
        for nested in sorted(download_dir.glob("*")):
            if not nested.is_dir():
                continue
            candidate = nested / rel
            if candidate.is_file():
                return candidate
    return None


def resolve_title_tags(video_path, download_dirs):
    """决定一个视频的标题与话题：优先用 f2 描述文件，找不到则用文件名兜底。"""
    video_path = Path(video_path)
    desc_file = find_desc_file(video_path, download_dirs)
    if desc_file is not None:
        try:
            title, tags = parse_desc_text(desc_file.read_text(encoding="utf-8", errors="replace"))
        except OSError as e:
            print(f"读取描述文件失败 {desc_file}: {e}，改用文件名作标题")
            title, tags = "", []
        if title:
            return title, tags
    stem = video_path.name
    if stem.endswith("_video.mp4"):
        stem = stem[: -len("_video.mp4")]
    else:
        stem = video_path.stem
    return stem, []


def collect_videos(video_dir=VIDEO_DIR):
    """按文件名排序，返回待上传的 mp4 列表。"""
    video_dir = Path(video_dir)
    if not video_dir.is_dir():
        return []
    return sorted(video_dir.glob("*.mp4"))


async def upload_one(video_path, title, tags, account_file):
    """上传单个视频；DouYinVideo 内部已处理上传失败重试，抛异常才算失败。"""
    # 延迟导入：本脚本的纯函数（标题解析等）被测试导入时不需要 playwright。
    from uploader.douyin_uploader.main import DouYinVideo

    app = DouYinVideo(
        title=title, file_path=video_path, tags=tags, publish_date=0, account_file=account_file
    )
    await app.main()


async def run(video_dir=VIDEO_DIR, config_path=None, repo_root=None):
    """批量上传入口，返回进程退出码（0=全部成功，1=有失败或缺配置）。"""
    repo_root = Path(repo_root) if repo_root else Path(BASE_DIR).parent
    config_path = Path(config_path) if config_path else repo_root / "my_apps.yaml"
    section = _load_video_mover_section(config_path)
    upload_cfg = section.get("upload", {}) or {}
    account = str(upload_cfg.get("douyin_account") or "default")
    account_file = COOKIES_DIR / f"douyin_{account}.json"

    videos = collect_videos(video_dir)
    if not videos:
        print("没有需要上传的视频文件")
        return 0

    if not account_file.is_file():
        print(f"找不到抖音登录 cookie：{account_file}")
        print("请先在 Windows 上扫码登录一次生成 cookie：")
        print(f"  python Upload/cli_main.py douyin {account} login")
        return 1

    # 延迟导入：同 upload_one，测试纯函数时不需要 playwright。
    from uploader.douyin_uploader.main import douyin_setup

    if not await douyin_setup(str(account_file), handle=False):
        print(f"抖音 cookie 已失效：{account_file}")
        print("先把浏览器里最新的抖音 cookie 更新到 my_apps.yaml 的 douyin.cookie，然后：")
        print("  python Upload/export_cookie.py      # 网页 cookie -> 上传器 cookie")
        print("（不想用网页 cookie 时，也可以扫码：")
        print(f"  python Upload/cli_main.py douyin {account} login ）")
        return 1

    download_dirs = _resolve_download_dirs(section, repo_root)
    options = apply_upload_options(upload_cfg)
    print(f"上传模式：{'无窗口' if options['headless'] else '有界面'}"
          + ("（dry_run：不真正发布）" if options["dry_run"] else ""))
    failed, succeeded = [], []
    for video_path in videos:
        title, tags = resolve_title_tags(video_path, download_dirs)
        print(f"上传: {video_path.name} 标题: {title} 话题: {tags}")
        try:
            await upload_one(video_path, title, tags, account_file)
        except Exception as e:
            print(f"上传失败 {video_path.name}: {e}")
            failed.append(video_path)
            continue
        succeeded.append(video_path)

    if options["dry_run"]:
        # dry_run 下没真的发布，文件不能删
        print(f"dry_run 完成：{len(succeeded)} 个视频走到发布前，未发布也未删除")
        return 0 if not failed else 1

    for video_path in succeeded:
        try:
            video_path.unlink()
        except OSError as e:
            print(f"删除已上传视频失败 {video_path}: {e}")

    if failed:
        print(f"上传完成：成功 {len(succeeded)} 个，失败 {len(failed)} 个（失败文件已保留在 {video_dir}）")
        return 1
    print(f"全部上传成功：{len(succeeded)} 个视频")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
