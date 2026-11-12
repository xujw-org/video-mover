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
注意：上传用的是有界面的 Chrome（DouYinVideo 内部 headless=False），
需要在有图形界面的 Windows 机器上跑；cookie 校验失败时本脚本直接退出，
不会在无人值守的调度里弹浏览器。
"""
import asyncio
import re
import sys
from pathlib import Path

# 脚本所在目录（Upload/）进 sys.path，保证 `import conf / uploader.*` 能找到。
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from conf import BASE_DIR

VIDEO_DIR = Path(BASE_DIR) / "videos"
COOKIES_DIR = Path(BASE_DIR) / "cookies"
MAX_TITLE_LEN = 30  # 抖音标题上限 30 字，DouYinVideo 内部也会截断，这里先截好方便打日志
MAX_TAGS = 10
_TAG_RE = re.compile(r"#([^\s#]+)")


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
        if path.is_dir() and path not in dirs:
            dirs.append(path)
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
    """按去重输出的文件名约定找 f2 的描述文件。

    去重输出沿用下载文件名 `<时间>_video.mp4`，描述文件在下载目录下
    `<时间>/<时间>_desc.txt`（与 Upload/vx_upload.py 同一约定）。
    """
    video_path = Path(video_path)
    stem = video_path.name
    if stem.endswith("_video.mp4"):
        video_time = stem[: -len("_video.mp4")]
    else:
        video_time = video_path.stem
    for download_dir in download_dirs:
        candidate = Path(download_dir) / video_time / f"{video_time}_desc.txt"
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
        print("请重新扫码登录：")
        print(f"  python Upload/cli_main.py douyin {account} login")
        return 1

    download_dirs = _resolve_download_dirs(section, repo_root)
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
