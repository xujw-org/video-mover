# -*- coding: utf-8 -*-
"""pytest 共享配置：重依赖替身 + 隔离工作目录。

本仓库的运行依赖（opencv / ffmpeg-python / whisper / pydub / psutil /
apscheduler / watchdog）在 CI 与本机测试环境里都不安装，测试用这里的
替身模块代替。替身只实现测试真正用到的那部分行为（见各类的 docstring），
绝不是对真实库的完整模拟；凡是需要真实视频、真实模型或真实网络的
行为都不在测试范围内。

另外：main.py 在导入时会在当前目录建 app.log，测试不在 conftest 里
用 chdir 躲它——那样做会让 pytest 在决定 testpaths 之前就切走工作目录，
导致 `PytestConfigWarning: No files were found in testpaths`。
app.log 本来就在 .gitignore 里，测试跑完后由下面的
pytest_sessionfinish 把测试产生的那份删掉即可。
"""
from __future__ import annotations

import io
import os
import sys
import types
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_APP_LOG = REPO_ROOT / "app.log"
_APP_LOG_PREEXISTED = _APP_LOG.exists()


def pytest_sessionfinish(session, exitstatus):
    """删掉本次测试产生的 app.log（main.py 导入时在当前目录建的）。

    测试开始前就已存在的文件不动；它只是运行日志，本来也在 .gitignore 里。
    """
    if not _APP_LOG_PREEXISTED and _APP_LOG.exists():
        try:
            _APP_LOG.unlink()
        except OSError:
            pass


def _module(name: str, **attrs):
    if name in sys.modules:  # conftest 被重复导入时复用已装好的替身，不覆盖
        return sys.modules[name]
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    sys.modules[name] = mod
    return mod


# ---------------------------------------------------------------- cv2 替身
def _make_fake_cv2():
    import numpy as np

    cv2 = types.ModuleType("cv2")
    cv2.COLOR_BGR2RGB = 4
    cv2.COLOR_RGB2BGR = 5
    cv2.COLOR_BGR2HSV = 40
    cv2.COLOR_HSV2BGR = 55
    cv2.COLOR_RGB2HSV = 41
    cv2.COLOR_HSV2RGB = 56
    cv2.COLOR_GRAY2BGR = 8
    cv2.CAP_PROP_FRAME_COUNT = 1
    cv2.CAP_PROP_POS_FRAMES = 2
    cv2.CAP_PROP_FPS = 5
    cv2.INTER_AREA = 3
    cv2.INTER_LINEAR = 1

    def cvtColor(frame, code):  # BGR<->RGB 只换通道，其余转换原样返回
        if code in (cv2.COLOR_BGR2RGB, cv2.COLOR_RGB2BGR):
            return frame[:, :, ::-1].copy()
        return frame.copy()

    def flip(frame, code):
        return np.flip(frame, axis=1) if code == 1 else np.flip(frame, axis=0)

    def resize(frame, dsize, interpolation=None):
        w, h = dsize
        return np.resize(frame, (h, w) + frame.shape[2:])

    def GaussianBlur(frame, ksize, sigma):
        return frame.copy()

    def getRotationMatrix2D(center, angle, scale):
        return np.eye(2, 3)

    def warpAffine(frame, matrix, dsize):
        return frame.copy()

    def convertScaleAbs(frame, alpha=1.0, beta=0):
        return np.clip(frame.astype(float) * alpha + beta, 0, 255).astype(np.uint8)

    def split(frame):
        return [frame[:, :, i].copy() for i in range(frame.shape[2])]

    def merge(channels):
        return np.stack(channels, axis=-1)

    def addWeighted(src1, alpha, src2, beta, gamma):
        out = src1.astype(float) * alpha + src2.astype(float) * beta + gamma
        return np.clip(out, 0, 255).astype(np.uint8)

    def Canny(frame, t1, t2):
        return np.zeros(frame.shape[:2], dtype=np.uint8)

    # VideoCapture：测试用注册表，test 通过 set_capture_frames 注入帧。
    _CAPTURE_FRAMES: dict = {}

    class VideoCapture:
        def __init__(self, path):
            self._frames = list(_CAPTURE_FRAMES.get(os.fspath(path), []))
            self._idx = 0

        def isOpened(self):
            return True

        def get(self, prop):
            if prop == cv2.CAP_PROP_FRAME_COUNT:
                return len(self._frames)
            if prop == cv2.CAP_PROP_FPS:
                return 30.0
            return 0

        def set(self, prop, value):
            if prop == cv2.CAP_PROP_POS_FRAMES:
                self._idx = int(value)
            return True

        def read(self):
            if self._idx >= len(self._frames):
                return False, None
            frame = self._frames[self._idx]
            self._idx += 1
            return True, frame

        def release(self):
            return None

    cv2.cvtColor = cvtColor
    cv2.flip = flip
    cv2.resize = resize
    cv2.GaussianBlur = GaussianBlur
    cv2.getRotationMatrix2D = getRotationMatrix2D
    cv2.warpAffine = warpAffine
    cv2.convertScaleAbs = convertScaleAbs
    cv2.split = split
    cv2.merge = merge
    cv2.addWeighted = addWeighted
    cv2.Canny = Canny
    cv2.VideoCapture = VideoCapture
    cv2.ocl = SimpleNamespace(setUseOpenCL=lambda *a: None)
    cv2.set_capture_frames = lambda path, frames: _CAPTURE_FRAMES.__setitem__(
        os.fspath(path), list(frames)
    )
    cv2.clear_capture_frames = _CAPTURE_FRAMES.clear
    return cv2


sys.modules.setdefault("cv2", _make_fake_cv2())


# ---------------------------------------------------------------- ffmpeg 替身
class _FakeFFmpegError(Exception):
    """带 .stderr（bytes）的 ffmpeg.Error 替身：原代码在 except 里调 e.stderr.decode()。"""

    def __init__(self, message=""):
        super().__init__(message)
        self.stderr = message.encode() if isinstance(message, str) else b""


class _FakeStdin:
    """BytesIO 的替身：close() 后仍能 getvalue()（真实代码会先 close 再 wait）。"""

    def __init__(self):
        self._buf = bytearray()
        self.closed = False

    def write(self, data):
        self._buf += data
        return len(data)

    def close(self):
        self.closed = True

    def getvalue(self):
        return bytes(self._buf)


class _FakeProcess:
    def __init__(self):
        self.stdin = _FakeStdin()
        self.waited = False

    def wait(self):
        self.waited = True
        return 0


class _FakeStream:
    """只记录调用，不做真实编解码。output/run/run_async 返回 self 或假进程。"""

    def __init__(self, ffmpeg_mod, name="stream"):
        self._mod = ffmpeg_mod
        self.name = name

    @property
    def video(self):
        return _FakeStream(self._mod, "video")

    @property
    def audio(self):
        return _FakeStream(self._mod, "audio")

    def output(self, *args, **kwargs):
        self._mod.calls.append(("output", args, kwargs))
        return self

    def filter(self, name, *args, **kwargs):
        # 与 ffmpeg-python 的 Stream.filter 同名：只记录，不做真实滤镜。
        self._mod.calls.append(("filter", (name,) + args, kwargs))
        return self

    def overwrite_output(self):
        self._mod.calls.append(("overwrite_output", (), {}))
        return self

    def run(self, **kwargs):
        self._mod.calls.append(("run", (), kwargs))
        return None

    def run_async(self, **kwargs):
        self._mod.calls.append(("run_async", (), kwargs))
        proc = _FakeProcess()
        self._mod.processes.append(proc)
        return proc


def _make_fake_ffmpeg():
    mod = types.ModuleType("ffmpeg")
    mod.Error = _FakeFFmpegError
    mod.calls = []
    mod.processes = []
    # 测试可改写：probe 返回的探测结果 / 要抛出的错误。
    mod.probe_result = {
        "streams": [
            {"codec_type": "video", "width": 64, "height": 48,
             "r_frame_rate": "30/1"},
        ],
        "format": {"duration": "1.0"},
    }
    mod.probe_error = None

    def probe(path):
        mod.calls.append(("probe", path))
        if mod.probe_error is not None:
            raise mod.probe_error
        return mod.probe_result

    def input(path, **kwargs):  # noqa: A002 - 与 ffmpeg-python 同名是故意的
        mod.calls.append(("input", path, kwargs))
        return _FakeStream(mod, "input")

    mod.probe = probe
    mod.input = input
    return mod


sys.modules.setdefault("ffmpeg", _make_fake_ffmpeg())


# ---------------------------------------------------------------- opencc / whisper 替身
class _FakeOpenCC:
    """只做测试用到的几个繁简字映射，其余原样返回。"""

    _MAP = {"國": "国", "語": "语", "體": "体", "學": "学"}

    def __init__(self, mode):
        self.mode = mode

    def convert(self, text):
        return "".join(self._MAP.get(ch, ch) for ch in text)


sys.modules.setdefault("opencc", _module("opencc", OpenCC=_FakeOpenCC))


class _FakeWhisperModel:
    def __init__(self, mod):
        self._mod = mod

    def transcribe(self, path):
        if self._mod.transcribe_error is not None:
            raise self._mod.transcribe_error
        return self._mod.transcribe_result


def _make_fake_whisper():
    mod = types.ModuleType("whisper")
    mod.transcribe_result = {"segments": [
        {"start": 0.0, "end": 1.5, "text": "你好世界"},
        {"start": 1.5, "end": 3.0, "text": "中國語"},
    ]}
    mod.transcribe_error = None
    mod.load_model = lambda name="base": _FakeWhisperModel(mod)
    return mod


sys.modules.setdefault("whisper", _make_fake_whisper())


# ---------------------------------------------------------------- pydub 替身
class _FakeAudioSegment:
    def __init__(self, duration_ms=1000):
        self.duration_ms = duration_ms
        self.ops = []

    @classmethod
    def from_file(cls, path):
        return cls()

    @classmethod
    def silent(cls, duration=0):
        return cls(duration_ms=duration)

    def export(self, path, format=None):  # noqa: A002 - 与 pydub 同名是故意的
        Path(path).write_bytes(b"FAKEWAV")
        return self

    def overlay(self, other, loop=False):
        seg = _FakeAudioSegment()
        seg.ops.append(("overlay", loop))
        return seg

    def __len__(self):
        # 与 pydub 一致：len(AudioSegment) 返回毫秒数
        return self.duration_ms

    def __add__(self, other):
        seg = _FakeAudioSegment()
        seg.ops.append(("add", other))
        seg.duration_ms = self.duration_ms + getattr(other, "duration_ms", 0)
        return seg

    def __sub__(self, other):
        seg = _FakeAudioSegment()
        seg.ops.append(("sub", other))
        return seg


def _make_fake_pydub():
    mod = types.ModuleType("pydub")
    mod.AudioSegment = _FakeAudioSegment
    silence = types.ModuleType("pydub.silence")
    # 测试可改写：split_on_silence 返回的片段列表。
    silence.split_result = [_FakeAudioSegment(), _FakeAudioSegment()]
    silence.split_on_silence = lambda audio, min_silence_len, silence_thresh: \
        list(silence.split_result)
    mod.silence = silence
    sys.modules.setdefault("pydub.silence", silence)
    return mod


sys.modules.setdefault("pydub", _make_fake_pydub())


# ---------------------------------------------------------------- pysrt 替身
def _make_fake_pysrt():
    mod = types.ModuleType("pysrt")
    mod.open_result = []
    mod.open = lambda path: list(mod.open_result)  # noqa: A002
    mod.SubRipFile = list
    return mod


sys.modules.setdefault("pysrt", _make_fake_pysrt())


# ---------------------------------------------------------------- main.py 的重依赖替身
class _FakeNoSuchProcess(Exception):
    pass


class _FakeTimeoutExpired(Exception):
    pass


sys.modules.setdefault(
    "psutil",
    _module(
        "psutil",
        cpu_percent=lambda: 0.0,
        virtual_memory=lambda: SimpleNamespace(used=0),
        Process=lambda pid: SimpleNamespace(pid=pid),
        NoSuchProcess=_FakeNoSuchProcess,
        TimeoutExpired=_FakeTimeoutExpired,
    ),
)

_apscheduler = _module("apscheduler")
_schedulers = _module("apscheduler.schedulers")
_blocking = _module(
    "apscheduler.schedulers.blocking",
    BlockingScheduler=type("BlockingScheduler", (), {"__init__": lambda self, *a, **k: None}),
)
_apscheduler.schedulers = _schedulers
_schedulers.blocking = _blocking

_watchdog = _module("watchdog")
_observers = _module(
    "watchdog.observers",
    Observer=type(
        "Observer",
        (),
        {
            "__init__": lambda self, *a, **k: None,
            "schedule": lambda self, *a, **k: None,
            "start": lambda self: None,
            "stop": lambda self: None,
        },
    ),
)
_events = _module(
    "watchdog.events",
    FileSystemEventHandler=type("FileSystemEventHandler", (), {}),
)
_watchdog.observers = _observers
_watchdog.events = _events


# ---------------------------------------------------------------- 备注
# 共享辅助函数（_passing_video_config、REPO_ROOT）在 tests/helpers.py 里，
# 不要放这里：conftest 会被 pytest 以 `conftest` 和 `tests.conftest`
# 两个名字各导入一次，放在这里的辅助一旦被测试文件 import，就会跑两遍
# 并复制替身状态（见 tests/helpers.py 开头的说明）。
