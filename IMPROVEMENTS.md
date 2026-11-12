# 改进版说明（IMPROVEMENTS.md）

本仓库是 [toki-plus/video-mover](https://github.com/toki-plus/video-mover)
（commit `294d6fd`，约 638 stars）的改进版，目标新仓库为
**xujw-org/video-mover**。本次只做了下面三组优先改进，没有重构业务逻辑，
没有改动视频处理与上传流程本身。

## CI Windows 修复（2026-11-12）

CI 首次运行：Ubuntu 的 test 任务全过，Windows 的 windows-smoke
在收集阶段失败，`main.py:21: import win32api` 在没装 pywin32 的
Windows 上抛 `ModuleNotFoundError: No module named 'win32api'`，
`tests/test_appconfig.py` 和 `tests/test_filemanager.py` 无法收集。

根因：`win32api` 只在 `SchedulerManager._register_signals`
（Windows 调度器运行时）真正用到，却在模块顶层无条件导入；
而 CI 的 windows-smoke 只装 `requirements-dev.txt`，里面原来
没有 pywin32。Ubuntu 因 `os.name != 'nt'` 跳过这行才通过。

修复（两处，缺一不可的思路是“导入不再硬依赖，CI 也装上真包”）：
- `main.py`：win32api 改为 try/except 导入，缺失时为 None；
  `_register_signals` 在为 None 时只打警告，不调用。
  这样 import main 不再硬性依赖 pywin32。
- `requirements-dev.txt`：加 `pywin32==312; sys_platform == "win32"`，
  Windows CI 会装上真包，覆盖真实导入路径；Linux/macOS 跳过。
- 新增回归测试 `tests/test_win32api_guard.py`（2 个）：
  模拟 Windows 且未装 pywin32 时 reload main 不抛错、
  `_register_signals` 不崩。测试总数 105 -> 107，全部通过。

## 第二批改进（2026-11-12）：测试、CI 与 Dedup 拆分

在第一批（依赖锁定、清理、配置抽离）基础上，本批做了三件事：

### 1. Dedup/dedup.py 拆分：1312 行单文件 -> 包

新旧映射（类体逐字节搬运，只改了模块头，见 `Dedup/README.md`）：

| 原 `Dedup/dedup.py` | 新位置 |
|---|---|
| `VideoConfig` | `Dedup/config.py` |
| `FFmpegHandler` | `Dedup/ffmpeg_utils.py` |
| `AudioHandler` | `Dedup/audio.py` |
| `SubtitleHandler` | `Dedup/subtitles.py` |
| `VideoEffects` | `Dedup/filters.py` |
| `VideoHandler` | `Dedup/pipeline.py` |
| CLI 入口（`-i` / `-o`） | `Dedup/dedup.py`（薄垫片，只 re-export + 保留 CLI） |

行为不变：ffmpeg 参数、单帧处理链顺序（见 `Dedup/README.md`）、
输出文件名规则、main.py 的 subprocess 调用方式（`python Dedup/dedup.py -i … -o …`，
cwd=Dedup）全部保留。唯一有意的差别：重依赖（cv2 / ffmpeg / whisper /
pydub 等）从“导入时必须装好”改成了“模块级 try/except，调用时才需要”，
所以 `import Dedup` 与 `python Dedup/dedup.py --help` 在没装重依赖的机器上
也能跑；缺依赖时错误从导入时的 ModuleNotFoundError 变成了调用时的
AttributeError。`process_video` 里的帧交换闭包（`get_original_idx` /
`swapped_frame_generator`）依赖局部状态，留在 `pipeline.py` 里没有硬拆。

### 2. 测试：tests/（pytest），105 个测试，全部可离线跑

```bash
pip install -r requirements-dev.txt   # 只装测试依赖：pytest + pyyaml + numpy + Pillow
pytest -q
```

测试不用 GPU、不用真实视频、不用网络：重依赖用 `tests/conftest.py` 的
替身模块代替（假 cv2 / ffmpeg / whisper / opencc / pydub / pysrt /
psutil / apscheduler / watchdog）。覆盖：

- AppConfig 加载（完整配置、缺失配置默认值 + 警告、非法 interval / 时区报错、
  环境变量覆盖、空环境变量回退）与 FileManager（时间范围、文件夹时间解析、
  去重子进程的调用约定）；
- 补丁脚本（替换原语、三个补丁的幂等性、--check 不写文件、main() 返回码）；
- 资产下载脚本（单文件下载校验、HTTP / 网络错误、--check 的缺失与齐全两种情况）；
- Dedup 新模块（VideoConfig 校验、滤镜纯逻辑与开关、SRT 时间格式、
  Whisper 生成字幕内容、静音去除与 BGM 混合、ffmpeg 流分离与属性、
  单帧处理链顺序、帧交换开 / 关的端到端流程、写帧的编码参数）；
- 垫片兼容（re-export 恒等、三种运行方式的 --help、缺失输入的失败行为）。

注意一个测试本身的坑（已修好，见 `tests/helpers.py` 开头）：pytest 会把
`tests/conftest.py` 以 `conftest` 和 `tests.conftest` 两个名字各导入一次，
共享辅助不能放 conftest 里，否则替身状态会被复制两份。

### 3. CI 与工程化

- 新增 `.github/workflows/ci.yml`：push / PR 到 main 时跑。ubuntu-latest
  主任务：装测试依赖 -> `py_compile` 全仓库 -> `pytest -q` ->
  装 f2 -> 打补丁 -> `--check`；另有 windows-latest 的 smoke 任务（编译 + 测试）。
  顺序有讲究：补丁脚本在没装 f2 时 `--check` 直接返回 2，刚装好的 f2 又是
  没打过补丁的，所以必须“先打补丁、再 --check”才能验证补丁脚本本身。
- 新增最小 `pyproject.toml`：只有 pytest 配置（`testpaths = ["tests"]`）
  与 ruff 配置，没有引入构建系统，不影响 `setup.bat`。
- `requirements-dev.txt` 改为只含测试依赖（pytest + pyyaml + numpy + Pillow，
  版本与 `requirements.txt` 一致），CI 不再全量装重依赖；本地完整运行仍是
  `pip install -r requirements.txt -r requirements-dev.txt`。
- README 顶部加了 CI badge。

### 第二批验证结果（2026-11-12，本机，Python 3.12.3 + pytest 9.2.0）

- `pytest -q`：105 个测试全部通过（0 失败）。
- `python -m py_compile`：全仓库通过。
- `from main import AppConfig` 与 `import Dedup.dedup` 正常；
  `python Dedup/dedup.py --help`、`python -m Dedup.dedup --help`、
  `cd Dedup && python dedup.py --help` 三种方式都通过（原来第一种在没装
  cv2 的机器上导入即失败）。
- 拆分校验：六个类的类体与原文逐字节一致；单帧处理链顺序与帧交换
  （开：[1, 0, 2]；关：[0, 1, 2]）均有测试锁定。
- 清理检查：无新增二进制、无 `__pycache__` / `*.pyc` 残留、待推送文件
  全部 UTF-8 文本。

## 第一批改进（2026-11-12）

以下为第一批的内容（依赖锁定、清理、配置抽离），保留原文。

### 1. 依赖版本锁定与上游补丁自动化

- `requirements.txt`：原来 25 个包全部没有版本号，现在全部加上 `==` 锁定，
  锁定日期 2026-11-12，版本来源是 PyPI JSON API 查询到的当时最新稳定版。
  其中 `pywin32` 只在 Windows 需要，加了 `sys_platform == "win32"` 标记，
  Linux / macOS 下 pip 会自动跳过（原来无条件依赖，在非 Windows 上装不上）。
- 新增 `requirements-dev.txt`：开发依赖最小集（目前只有 pytest 9.2.0）。
- 新增 `scripts/apply_upstream_patches.py` + `PATCHES.md`：原来 README 要求手动改
  第三方库源码的三处补丁，现在变成可重复执行的脚本，每次运行先校验目标代码，
  校验失败就报错退出，不静默跳过；`setup.bat` 已自动调用它。
  - 补丁 1：f2 的 TikTok 分页游标转 int。核对发现 README 写的行号与位置
    （handler.py 约 389 行 `params={"cursor": cursor}`）在 f2 0.0.1.7 的实际
    源码里并不存在，实际修复点是 5 处 `self.kwargs.get("cursor", 0)` 的取值处。
  - 补丁 2：f2 的日期解析兼容纯日期与带时间两种写法。已验证这是个真问题：
    未打补丁时，`main.py` 生成的 `2025-03-07 21-00-00|2025-03-07 22-00-00`
    这种区间会被解析成时间戳 0；打补丁后 7 组测试用例全部通过。
  - 补丁 3：视频号上传等待超时 1500ms → 10000ms。核对发现本仓库自带的代码
    早已是 `timeout=10000`，无需修改，脚本每次运行会复核。
- `setup.bat`：安装后自动运行补丁脚本。

### 2. `.gitignore` 与清理：仓库从约 34.4MB 瘦身到约 0.4MB

- 新增完整的 Python `.gitignore`：`__pycache__`、`*.pyc`、`.env`、
  `my_apps.yaml`（本机配置）、cookies、`Download/`、`app.log`、以及
  `*.mp4` / `*.mp3` / `*.png` / `*.ttf` / `*.exe` 等二进制资产。
- 删除了原仓库提交的 11 个大二进制文件（约 34MB）与 17 个 `.pyc` 文件，
  详见 [ASSETS.md](./ASSETS.md)。删除后工作目录只剩文本文件，共 61 个文件、
  约 441KB，其中待推送的 59 个文件约 437KB
  （`my_apps.yaml` 与 `accounts.ini` 为本机配置，不进仓库），
  全部为 UTF-8 / ASCII 文本，无二进制、无 `.pyc`。
- 新增 `scripts/download_assets.py` + `ASSETS.md`：第一次运行前执行
  `python scripts/download_assets.py`，从原仓库 raw 地址下载被移除的资产，
  下载后校验文件大小，失败会明确报错。已实测：11 个文件全部下载成功，
  大小与预期一致。
- 新增 `.env.example` 与 `my_apps.yaml.example`（脱敏模板，不含真实值）。
  `my_apps.yaml` 本身已加入 `.gitignore`，请从模板复制后填写。
- **安全提醒**：原仓库的 `my_apps.yaml` 里带有真实的 TikTok 会话 cookie
  与代理账号密码，改进版已全部清除为占位符。**这些密钥既然曾公开提交过，
  请务必轮换（改代理密码、重新登录拿新 cookie），只删文件是不够的。**
  同样，原 `Upload/vx_upload.py` 里写死的一串已打码的示例 API Key 也已移除，
  改为从 `DASHSCOPE_API_KEY` 环境变量读取（见 `.env.example`）。

### 3. 配置与硬编码分离

- `main.py` 的 `AppConfig` 原来把下载目录、TikTok 账号主页、时区、调度间隔
  等都写死在代码里，现在全部移到 `my_apps.yaml` 顶部的 `video_mover` 小节
  （`source` / `paths` / `schedule` / `runtime` 四组结构化字段），并支持
  `VIDEO_MOVER_` 前缀的环境变量覆盖（另可用 `.env` 文件，见 `.env.example`），
  优先级：环境变量 > `my_apps.yaml` > 内置默认值。
- 新 `AppConfig` 会校验：`interval_minutes` 必须是 1–1440 的整数，否则报错；
  时区必须是合法的 IANA 时区名，否则报错；`Dedup` / `Upload` 目录与三个脚本
  文件不存在时报明确的 `FileNotFoundError`；下载目录不存在时自动创建。
  配置键缺失时打警告并用默认值补齐，不直接崩。
- `Upload/vx_upload.py` 里原来写死的下载目录（带原账号名的路径）也改为从
  同一份 `my_apps.yaml` 读取，与 `main.py` 保持一致；缺失时报明确错误。
- `main.py` 里已无任何硬编码账号（全仓库 grep 验证无原账号名），也无硬编码
  绝对路径；`README.md` 的配置说明已同步更新，示例与代码字段一致。

## 首次使用

```bash
git clone https://github.com/xujw-org/video-mover.git
cd video-mover
cp my_apps.yaml.example my_apps.yaml   # 填入你自己的账号、cookie、代理
cp .env.example .env                   # 可选：用环境变量覆盖配置
python scripts/download_assets.py      # 下载已移出仓库的二进制资产
# Windows：
setup.bat
# 或手动：
pip install -r requirements.txt
python scripts/apply_upstream_patches.py
playwright install chromium firefox
python main.py
```

## 验证结果（2026-11-12，本机）

- `python -m py_compile`：仓库内全部 41 个 `.py` 文件通过。
- `AppConfig` 加载测试 19 项全部通过：用新 `my_apps.yaml` 正常加载；
  配置文件缺失时用默认值 + 警告，不崩；非法 interval（0 / 1441 / -5 / 非数字）
  与非法时区均正确报错；环境变量覆盖与 `.env` 加载均生效。
- 补丁脚本测试：用 f2 0.0.1.7 官方 sdist 的真实源码副本验证，首次运行三处补丁
  全部应用（cursor 5 处、日期解析 4 处、视频号超时早已满足），第二次运行全部
  报告 ALREADY_APPLIED（幂等），`--check` 模式正常；打补丁后的 f2 文件可正常编译；
  日期解析函数 7 组用例全部通过，未打补丁的原版在带时间区间上返回 0（复现了原问题）。
- 资产下载脚本测试：`--check` 正确报告 11 个缺失，完整下载 11 个文件大小全部
  与预期一致，再次运行全部跳过。
- 清理验证：无二进制文件、无 `__pycache__` / `*.pyc`、全部 UTF-8 文本。
  待推送内容 59 个文件、约 437KB；原仓库 77 个文件、
  36,096,320 字节（约 34.4MB）。

## 不确定的地方 / 已知遗留问题

- **依赖完整安装未在本机验证**：`pip install --dry-run -r requirements.txt`
  在本机沙箱里失败，原因是沙箱代理环境变量（`NO_PROXY` 里的 IPv6 写法）让
  pip 隔离构建环境里的 httpx 解析报错，与版本本身无关；逐个下载验证时 24/25
  个包可正常下载，`biliup==1.3.5`（仅提供 sdist）同样卡在沙箱代理问题上，
  `pywin32==312` 只有 Windows 包，在 Linux 下下载失败是预期的（有平台标记）。
  在目标 Windows 机器上首次安装时请先小规模验证。
- **两个大版本升级需验证**：`opencv-python` 5.0.0.93（相对常见的 4.x）与
  `openai` 3.49.0（相对常见的 1.x）都是大版本升级，只做了版本锁定，没有跑过
  实际视频处理与 AI 调用流程。
- **四个包在仓库代码里无直接引用**：`eventlet`、`schedule`、`cf_clearance`、
  `openai`（`main.py` 不直接用，`vx_upload.py` 用的是 `dashscope`）。
  本次仅做版本锁定、暂不删除，后续可评估是历史遗留还是上游传递依赖。
- **未做的事情（第二批之后还剩）**：没有改 `Upload/conf.py` 里写死的
  Windows 版 Chrome 绝对路径、`README_en.md` 未同步更新（仍是旧的手动补丁
  说明与旧仓库地址）。拆 `Dedup/dedup.py`、加测试与 CI 已在第二批做完，
  见上文。拆分时还发现两个原有小问题（未改行为，只记录）：`VideoConfig.validate()`
  对 font / bgm / 字幕文件是无条件校验存在（无论对应开关开没开），以及
  `AppConfig` 里 interval 传浮点数 1.5 会被 `int()` 静默截断成 1；
  帧交换索引映射是 `process_video` 里的嵌套闭包，只能间接测试。
- **`.git` 历史必须丢弃**：原仓库的 git 历史里仍有大二进制文件、`.pyc` 和
  真实密钥，推送时必须用全新仓库（`git init` 后只加当前工作目录的文件），
  不能把旧 `.git` 目录推过去，否则清理等于白做。
