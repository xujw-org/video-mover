import os
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
XHS_SERVER = "http://127.0.0.1:11901"


def _chrome_candidates() -> list[str | None]:
    return [
        os.environ.get("DOUYIN_CHROME_PATH"),
        os.environ.get("CHROME_PATH"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]


def resolve_chrome_path(candidates: list[str | None] | None = None) -> str | None:
    """本机 Chrome 的路径；找不到返回 None（交给 Playwright 自带的 Chromium）。

    以前这里写死 ``C:/Program Files/Google/Chrome/Application/chrome.exe``，
    没装 Chrome（或装在用户目录 / 其它盘）的机器上上传直接
    ``Failed to launch chromium because executable doesn't exist``。
    setup.bat 已经装了 Playwright 的 Chromium，找不到 Chrome 就用它。
    想指定路径：环境变量 ``DOUYIN_CHROME_PATH``（或 ``CHROME_PATH``）。
    """
    for candidate in _chrome_candidates() if candidates is None else candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return candidate
    return None


LOCAL_CHROME_PATH = resolve_chrome_path()
