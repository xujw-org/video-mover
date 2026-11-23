# Video Mover: 多平台内容分发自动化流水线

[![CI](https://github.com/xujw-org/video-mover/actions/workflows/ci.yml/badge.svg)](https://github.com/xujw-org/video-mover/actions/workflows/ci.yml)

[简体中文](./README.md) | [English](./README_en.md)

面向多平台内容运营场景的视频处理与发布工作流。

该项目将文件监听、视频标准化处理、文案生成、任务调度和多平台发布整合到一条可配置流水线中，用于探索如何减少内容团队在重复操作上的时间投入。流水线各阶段均为独立模块，可按业务需要组合、替换或关闭。

> 本项目仅应用于拥有合法使用权的内容与账号。使用者应遵守内容版权、平台规则和当地法律法规。

> **改进版说明**：本仓库是 [toki-plus/video-mover](https://github.com/toki-plus/video-mover)
> 的改进版，主要改动是依赖版本锁定、上游补丁自动化、`.gitignore` 与大文件清理、
> 配置与硬编码分离，详见 [IMPROVEMENTS.md](./IMPROVEMENTS.md)。
> 大二进制资产（字体 / 音乐 / 水印图等）已移出仓库，首次运行前请执行
> `python scripts/download_assets.py`，详见 [ASSETS.md](./ASSETS.md)。

## 项目背景

跨平台内容运营通常包含多个相互割裂的步骤：素材进入、格式处理、文案整理、发布时间安排和逐平台上传。重复的人工操作不仅耗时，也容易造成命名、参数和发布记录不一致。

Video Mover 将这些步骤抽象为可组合的任务模块，以便对流程进行自动化、监控和扩展。项目的目标不是替代创作环节，而是把"处理—文案—调度—发布"这类确定性的重复劳动交给流水线，让人保留在素材选择与内容终审环节。

## 特别鸣谢

<p align="center">
  <a href="https://www.ipwo.net/?ref=githubvideomover" target="_blank">
    <img src="images/IPWO.png" alt="IPWO" width="800">
  </a>
</p>

<p align="center">
  <b><a href="https://www.ipwo.net/?ref=githubvideomover" target="_blank">IPWO</a></b>
  住宅代理提供 195+ 地区动静态住宅代理，适用于 TikTok、社交媒体运营、多平台内容分发、浏览器自动化及数据获取等场景，为开发者和运营团队提供不同地区的网络环境选择。
  <br>
  包含 HTTP(S) / SOCKS5 多协议，充裕住宅流量供免费测试，优惠码：<code>0205</code>，
  <a href="https://www.ipwo.net/?ref=githubvideomover">访问入口</a>
</p>

## 主要能力

- **目录监听与任务触发**：基于 Watchdog 持续监听指定素材目录，新文件进入后自动触发处理任务，支持 7×24 小时无人值守运行。
- **内容差异化处理工具箱**：基于 FFmpeg / OpenCV 的可配置处理链，覆盖自动字幕、自定义标题、背景音乐（BGM）、画中画（PIP）、静音剪辑、镜像、旋转、裁剪、淡入淡出、画质调整，以及背景模糊、帧交换、颜色偏移、纹理噪声等数十种视觉处理项。所有功能独立可配、自由组合，服务于二次创作与素材规范化场景。
- **GPU 加速**：在兼容环境下调用 NVIDIA 显卡进行硬件编码加速，显著缩短批量处理时间。
- **AI 文案草稿生成**：接入阿里云百炼大模型，分析视频内容后生成标题与标签草稿，发布前由人工终审确认后使用。
- **任务队列与定时调度**：通过 APScheduler 配置任务队列与发布时间表，统一维护执行状态。
- **多平台发布适配**：基于 Playwright 的浏览器自动化，适配 TikTok、抖音、快手、哔哩哔哩、视频号和小红书等平台的上传流程，自动完成登录态复用与表单填写。
- **可扩展架构**：通过插件与 Handler 结构扩展处理步骤及上传适配器，新增平台或处理项无需改动主流程。
- **日志与状态记录**：完整记录任务日志与执行状态，便于失败定位与流程复盘。

## 📸 软件截图

> 截图文件已移出仓库，首次查看前请先运行 `python scripts/download_assets.py`，
> 详见 [ASSETS.md](./ASSETS.md)。

<p align="center">
  <a href="https://www.bilibili.com/video/BV1txQeYyEEz" target="_blank">
    <img src="./images/cover_demo.png" alt="软件界面演示" width="800"/>
  </a>
  <br>
  <em>软件界面（点击封面跳转 B 站观看演示视频）</em>
</p>

<p align="center">
  <img src="./images/cover_script.png" alt="脚本运行展示" width="800"/>
  <br>
  <em>脚本运行过程展示</em>
</p>

## 工作流

```text
Content input
    -> File watcher
    -> Video processing
    -> Metadata generation
    -> Scheduling
    -> Platform adapters
    -> Execution logs
```

## 技术设计

- `main.py`：任务编排、文件管理、调度与插件入口
- `Dedup/`：基于 FFmpeg、OpenCV 的视频处理模块（对应上方工具箱的各项处理）
- `Upload/`：各平台上传适配器与账号配置
- `my_apps.yaml`：应用与网络参数配置（视频源、路径、调度等），主程序配置在
  顶部的 `video_mover` 小节；f2 的平台配置在下方各小节

主要技术：Python、FFmpeg、OpenCV、Playwright、Watchdog、APScheduler、LLM API。

## 快速开始

### 环境要求

- Windows
- Python 3.12+（conda 可选；没有 conda 时脚本用项目内 `.venv`，没有 Python
  时 `setup.bat` 会自动安装）
- Node.js 22.x
- FFmpeg（PATH 里有就直接用；Windows 下 `setup.bat` 会自动下载到
  `tools\ffmpeg`）
- Chrome（可选；没装时用 `setup.bat` 安装的 Playwright Chromium，可用
  `DOUYIN_CHROME_PATH` 指定路径）

### 安装

1. 克隆仓库：

   ```bash
   git clone https://github.com/xujw-org/video-mover.git
   cd video-mover
   ```

2. 准备运行环境。不用手工做任何事，`setup.bat` 按顺序自动挑一个：

   - 已有的 conda 环境（默认名 `dy`；不存在时自动 `conda create -y -n dy
     python=3.12`）；
   - 本机没有 conda 时，用项目内 `.venv`（首次运行自动创建）；
   - 连 Python 3.12+ 都没有时，自动安装 Python 3.13（优先 `winget`，失败
     则下载 python.org 官方安装包，按用户安装并加入 `PATH`）。

   想固定用某个 conda 环境，先建好再指定名字：

   ```bash
   conda create -y -n dy python=3.12     # 可选
   setup.bat dy
   ```

3. 运行 `setup.bat`（默认环境名 `dy`，已有环境名不同时用第一个参数指定）。
   它会依次执行：确认/创建环境 → 升级 pip → 准备 PyTorch → 安装
   `requirements.txt` → 安装 `requirements-dev.txt` → 安装 Playwright 浏览器
   （chromium / firefox）→ 应用上游兼容补丁 → 准备 ffmpeg（`PATH` 里没有就
   自动下载到 `tools\ffmpeg`）。

   > **没有显卡的老机器**：`openai-whisper` 依赖的 torch 在 Windows 上默认自带
   > CUDA，安装包有 2~3 GB，很容易看起来“卡死”。`setup.bat` 检测不到 NVIDIA
   > 显卡时会先装 CPU 构建（`--index-url https://download.pytorch.org/whl/cpu`），
   > 之后的 requirements 不会再拉 CUDA 版。也可以显式指定：
   > `setup.bat --torch cpu`（强制 CPU）或 `setup.bat --torch cuda`（强制默认
   > CUDA 构建）。

   安装完成后想复查环境，执行：

   ```bash
   python scripts/win_env.py check --env dy
   ```

   > **关于 `.bat` 里的中文**：`setup.bat` / `start.bat` 刻意只用 ASCII 字符。
   > cmd.exe 默认按系统代码页（简体中文 Windows 是 cp936）解释批处理文件，
   > UTF-8 中文会乱码；加 `chcp 65001` 能修显示，却会触发 cmd 批处理解析器
   > 在多字节字符上的偏移错位，把半行内容当命令执行。所以两个 `.bat` 只做
   > 定位解释器和转交，所有中文提示都由 `scripts/win_env.py` 输出（UTF-8 源码
   > + `chcp 65001` 控制台，显示正常）。改动 `.bat` 时请保持纯 ASCII。

4. **依赖补丁（已自动化）**：为兼容目标平台接口，需要对已安装的 f2 等上游库做
   三处小改动，现已收进 `scripts/apply_upstream_patches.py`，`setup.bat` 会自动
   运行它；也可以手动执行 `python scripts/apply_upstream_patches.py`（只检查不
   改动：加 `--check`）。补丁针对 f2==0.0.1.7 核对过，详见 [PATCHES.md](./PATCHES.md)。
   每次重装或升级依赖后请重新运行一次。

5. **下载二进制资产**：字体、背景音乐、水印图、画中画视频、README 截图等大文件
   已移出仓库，首次运行前执行（`setup.bat --with-assets` 也会顺手做这一步）：

   ```bash
   python scripts/download_assets.py
   ```

   详见 [ASSETS.md](./ASSETS.md)。

### 图形界面（推荐）

不想手改 YAML、也不想记命令时，双击 `gui.bat`（或 `gui.bat 环境名`）。第一次启动会
自动安装 `requirements-gui.txt`（NiceGUI 2.x；版本特意与 f2 锁定的
`pydantic==2.9.*` / `websockets<13` 对齐），然后自动打开浏览器：
`http://127.0.0.1:8765/`。

界面里可以：

- 启动 / 停止流水线；停止时先发 Ctrl+Break 让 `main.py` 自己收尾，超时才杀进程树。
- 用表单改视频源、调度、上传账号、补抓、Cookie / 代理、路径和上传脚本。
- 保存前先让 `main.py` 校验配置，错误会直接显示原因，不会写坏 YAML。
- 一键导出 Cookie / 扫码登录 / 下载素材 / 修复环境。
- 看本次运行的实时输出和 `app.log`。
- 开跑前检查：配置、Cookie、上传登录态、ffmpeg、Playwright、素材。

注意事项：

- 界面只监听本机 `127.0.0.1`，默认端口 8765；重复双击 `gui.bat` 会直接打开已有页面。
- 配置保存后，正在跑的流水线不会热加载；用界面里的“保存并重启”。
- 启动前会清空 `Upload/videos` 里的历史 mp4（与 `start.bat` 一致，防止重复发布）。
- 关掉启动 `gui.bat` 的控制台窗口会停止流水线；想脱离窗口运行仍可用 `start.bat`。
- 命令行方式 `start.bat` / `python main.py` 仍然可用，读的是同一份 `my_apps.yaml`。

### 配置

1. 推荐直接双击 `gui.bat` 在界面里填写（缺失的 `my_apps.yaml` 会自动从模板创建）；
   也可以手动复制模板并编辑：

   ```bash
   cp my_apps.yaml.example my_apps.yaml
   ```

   在 `my_apps.yaml` 顶部的 `video_mover` 小节里配置视频源、路径、调度和运行参数：

   ```yaml
   video_mover:
     sources:  # 多个博主按顺序抓取；旧版单个 source 写法仍可用
       - platform: douyin
         account: "@example"
         url: "https://www.douyin.com/@example"
       - platform: douyin
         account: "@example2"
         url: "https://www.douyin.com/@example2"
     upload:
       douyin_account: "default"  # 抖音上传账号名，见下方登录步骤
     paths:
       dedup_dir: "Dedup"
       upload_dir: "Upload"
       flush_script: "flush_device_id.py"
       dedup_script: "Dedup/dedup.py"
       upload_scripts: ["Upload/douyin_upload.py"]  # 按顺序执行，可再加视频号等
     schedule:
       interval_minutes: 300   # 必须是 1-1440 的整数
       timezone: "Asia/Singapore"  # 必须是合法的 IANA 时区名
     runtime:
       max_workers: null       # null = CPU 核心数
       config_file: "my_apps.yaml"
   ```

   配置优先级：环境变量 `VIDEO_MOVER_*` > `my_apps.yaml` > 内置默认值。
   注意环境变量只覆盖旧版单个 `source`，写了 `sources` 列表后以列表为准。
   环境变量清单见 `.env.example`（复制为 `.env` 后填写；`.env` 不进仓库）。
   缺失的配置项会打警告并用默认值补齐；`interval_minutes` 超出 1-1440 或时区
   不合法时会直接报错退出。

   下载目录 `download_dir` 不写时按博主推导为
   `Download/<platform>/post/<account>`。f2 的真实落盘结构是
   `Download/<app>/<mode>/<昵称>/<作品时间>/`：配到 `<昵称>` 这层，或往上
   配到 `<mode>` 层（如 `Download/douyin/post`），去重扫描都能找到
   （见 `main.py` 的 `FileManager._iter_work_dirs`）。
   下方的 `douyin` / `tiktok` / `weibo` / `twitter` 小节是 f2 的平台配置，
   其中的 cookie 与代理请填你自己的真实值。
   抖音抓取用的就是 `douyin` 小节里的 cookie（下载也要登录态）。

2. 抖音上传 cookie（两种方式，**推荐第一种**）：

   ```bash
   # 方式一：把上面填的 douyin.cookie 直接转成上传器的 cookie 文件
   # （creator.douyin.com 与 www.douyin.com 共用 .douyin.com 作用域的 cookie，
   #   实测 headless 能直接进上传页，不需要扫码、不弹浏览器）
   python Upload/export_cookie.py

   # 方式二：传统扫码登录（cookie 失效又不想重新导网页 cookie 时用）
   python Upload/cli_main.py douyin <账号名> login
   ```

   cookie 保存在 `Upload/cookies/douyin_<账号名>.json`。`<账号名>` 要和
   `my_apps.yaml` 里 `video_mover.upload.douyin_account` 填的一致。

   上传默认**无窗口**（headless）运行，不会在桌面弹 Chrome。`video_mover.upload`
   里两个可选开关：

   ```yaml
   upload:
     headless: true   # false = 有界面，方便盯界面排查
     dry_run: false   # true = 只填到“发布”按钮前，不真正发布、不删文件
   ```

   cookie 失效时上传脚本直接退出并打印重导指引，不会在无人值守时弹浏览器。

2. 如启用 AI 文案功能，通过安全的本地配置方式提供 API Key，切勿提交到仓库。
3. 首次运行平台适配器时，根据提示完成账号登录与 Cookie 初始化。

### 更新

旧电脑已经 `git clone` 过时，双击 `update.bat`（环境名不是 `dy` 时用
`update.bat 环境名`）。它会依次：

1. `git pull --ff-only` 拉取最新代码；
2. 重跑 setup：检查/安装依赖、Playwright、上游补丁、ffmpeg；
3. 补下缺失的大二进制素材（已有的会跳过）。

如果 pull 因为本机有未提交修改、分支分叉或网络问题失败，脚本会立即停下并提示，
不会继续改依赖。更新完成后用 `gui.bat` 或 `start.bat` 启动。

注意：`my_apps.yaml`、`.env`、`Upload/cookies/` 都是本机文件，不会被 `git pull`
更新；不要把它们提交到仓库。

### 运行

双击 `gui.bat`（图形界面，推荐；见上文“图形界面”），或双击 `start.bat`
（或在命令行 `start.bat 环境名`），也可以直接执行：

```bash
python main.py
```

`start.bat` 使用与 `setup.bat` 相同的查找顺序（conda 环境 `dy` → 项目 `.venv`），
会先清空 `Upload\videos` 里的历史 mp4，再启动 `main.py`。只想确认环境是否装好、
不想真的启动时：`start.bat dy --dry-run`。

程序会自动打开浏览器并执行任务，按提示完成首次登录即可进入自动化流程。

### 补抓历史作品（队列模式）

默认每个调度周期只处理 `interval_minutes`（最长 24 小时）内的新作品。想分批把
博主的历史作品搬过来，在 `my_apps.yaml` 里打开 backfill：

```yaml
video_mover:
  backfill:
    days: 30           # 抓最近 30 天的作品；0 = 关闭
    max_per_source: 20 # 每个源单次最多下载多少条
    max_per_run: 3     # 每轮最多去重多少条（4K 一条约 1.5 分钟）
```

开启后：抓取阶段把时间窗放大到 `days` 天并把作品下载到 `Download/`；去重阶段
改看**未处理队列**（`state/processed.json` 记录已处理的文件），每轮只吃
`max_per_run` 条，跑完自动发布。想停就改回 `days: 0`。

> 4K 素材一条去重约 1.5 分钟、成品 20~30MB，补抓 30 天前建议先看磁盘余量。

### cookie 反复失效怎么排查

抖音会把“同一个 sessionid 从不同设备/浏览器使用”判成异常并强制登出。自动化这边
已经统一成真 Chrome 指纹（UA + Client Hints + 视口 + 语言 + 时区），所以正常情况
下 cookie 能撑到 `sid_guard` 的 60 天有效期。如果又失效，按下面顺序查：

1. 重新登录（会把 session 写到 `Upload/cookies/douyin_<账号>.json`，抓取和上传都用它）：

   ```bash
   python Upload/cli_main.py douyin default login
   ```

   登录成功后会自动保存（不再需要手动点 Inspector 的“继续”）。抓取侧会自动
   选用比 yaml 更新的这份登录状态，所以**不用再手抄网页 cookie**；
2. `sid_guard` 的签发时间（cookie 里第 2 段，形如 `sig|<签发时间戳>|5184000|...`）
   是不是很久以前 —— 那才是真过期，重新登录即可；
3. 是不是又用 `export_cookie.py` 把旧 yaml cookie 导回上传器（会作废旧 session，
   脚本现在会拦下来，需要 `--force` 才覆盖）；
4. 是不是同时开了多个自动发布（短时间连着发多条，容易被风控盯上）；
5. 环境变量 `DOUYIN_UPLOAD_UA` 有没有被设成奇怪的 UA。

### 封面与话题

发布时会自动：

- 从视频里挑一帧（最亮的）生成 **竖封面 3:4（1080×1440）** 并设进发布页；
  自己传图失败时退回使用平台的 **AI 推荐封面**（横封面不设，抖音只会提示缺横版）；
- 把描述里的 `#话题` 挂成**官方话题**（联想下拉里带播放量的那种），并按
  `upload.hot_tags`（默认 2）在同一关键词下再补几个官方热门话题。

```yaml
video_mover:
  upload:
    hot_tags: 2   # 每个话题额外补几个官方热门标签；0 = 不加
```

### 发布节奏与短信验证

`video_mover.upload.min_interval_minutes`（默认 15）限制两次发布的最小间隔，
状态写在 `Upload/.last_publish`，不够间隔就跳过本轮（视频留在 `Upload/videos`）。

抖音对“新设备上的第一次发布”常常要求**短信验证码**（为确保是本人操作）。
现在不需要手动切换模式：无窗口上传如果遇到验证码弹窗，脚本会关掉当前浏览器、
自动改用**有界面浏览器**重走一遍上传，把窗口留给你输入手机收到的验证码
（最多等 10 分钟，输入后自动继续发布）。日志里会看到：

```text
抖音要求短信验证码：自动切换到有界面浏览器，请在弹出的窗口里输入手机收到的验证码
```

想从一开始就用有界面模式盯流程：

```bash
set DOUYIN_UPLOAD_HEADED=1
python Upload/douyin_upload.py
```

### 临时文件位置

Dedup 的中间音频放在仓库的 `tmp/`（与项目同盘，默认 D 盘），不再落到
`C:\Users\<用户>\AppData\Local\Temp`；每次启动会清掉 24 小时前的残留。
抖音抓取用的 Chromium profile 也固定在 `tmp/chromium-profile`（可用环境变量
`VM_PLAYWRIGHT_PROFILE` 改），不会在 C 盘临时目录留一堆
`playwright_chromiumdev_profile-*`。

### 抖音抓取通道（2026-11-14 起）

抖音**不再走 f2**：抖音现在对 `/aweme/v1/web/aweme/post/` 强制 Argus secsdk
签名（`x-secsdk-web-signature` + `uifid`/`webid`/`fp`/`timestamp`），而 f2 0.0.1.7
的请求里没有这些字段，必然返回 403。改用 `douyin_fetch.py` 的**浏览器通道**：
用 Chromium 打开博主主页、直接读页面自己发出的接口响应（签名由页面 JS 完成），
再按视频直链下载，落盘结构与 f2 一致：

```text
Download/<平台>/post/<昵称>/<作品时间>/<aweme_id>.mp4
```

`main.py` 会按平台自动分流：`douyin` 源走浏览器通道，tiktok 等其它平台仍走 f2
子进程。图文（相册）作品不是视频，会跳过。

首次使用需要装好浏览器：`python -m playwright install chromium`（`setup.bat`
已经做了）。手动补抓历史（调度窗口只有 `interval_minutes`，最长 24 小时）：

```bash
python douyin_fetch.py --url "https://www.douyin.com/user/xxxx" --days 30
python douyin_fetch.py --url "..." --since "2026-11-01 00-00-00" --dry-run
```

想把抓取过程摊到 Burp / mitmproxy 里看：`--config` 指向一份把
`douyin.proxies` 设成代理地址的配置文件即可（会自动放行代理的自签证书）。

## 当前限制

- 平台页面和接口发生变化时，上传适配器可能需要同步更新。
- 依赖版本已在 `requirements.txt` 中锁定（2026-11-12），但 `opencv-python` 5.x
  与 `openai` 3.x 是大版本升级，首次安装后请先小规模验证，详见
  [IMPROVEMENTS.md](./IMPROVEMENTS.md)。
- 项目尚未建立完整的自动化测试与 CI，生产使用前应进行小规模验证。
- API Key、Cookie 和账号配置不应提交到 Git 仓库。`my_apps.yaml` 与 `.env`
  已加入 `.gitignore`，请从 `my_apps.yaml.example` / `.env.example` 复制后填写。
- 大二进制资产不在仓库里，首次运行前请执行 `python scripts/download_assets.py`。

## 项目价值

本项目重点验证的是跨工具、跨平台工作流的拆解与编排能力：如何把文件监听、媒体处理、LLM 调用、定时调度和浏览器自动化串成一条可观测、可恢复的流水线，包括任务边界设计、第三方系统适配、失败日志和后续扩展，而非单一的视频处理算法。其中"上游库需要打补丁才能兼容真实平台接口"这类工程细节，也正是自动化项目落地时最常见的隐性成本。

## 📂 更多项目

- [ai-highlight-clip](https://github.com/toki-plus/ai-highlight-clip) — 长视频智能初筛：Whisper 转写 + LLM 评分 + 人工终审，分钟级定位高光片段
- [ai-ttv-workflow](https://github.com/toki-plus/ai-ttv-workflow) — 文案到短视频的桌面工作流，关键节点保留人工确认
- [ai-video-workflow](https://github.com/toki-plus/ai-video-workflow) — 多模型 AIGC 视频生成流水线：文生图、图生视频、文生音乐的异步编排
- [ai-mixed-cut](https://github.com/toki-plus/ai-mixed-cut) — 素材库结构化与脚本重组的视频再创作工作流
- [ai-trader-for-mt4](https://github.com/toki-plus/ai-trader-for-mt4) — LLM×MT4 受控执行框架：工具约束、风控规则、状态管理与异步桥接
- [ai-trader-for-mt5](https://github.com/toki-plus/ai-trader-for-mt5) — 面向 MT5 的 AI 交易助手与 EA 工程化框架
- [auto-usps-tracker](https://github.com/toki-plus/auto-usps-tracker) — 跨境电商批量物流追踪与 Excel 报告自动化
- [AB-Video-Deduplicator](https://github.com/toki-plus/AB-Video-Deduplicator) — 基于高帧率抽帧混合的视频再创作实验工具
- [netease-downloader](https://github.com/toki-plus/netease-downloader) — 网易云音乐下载桌面应用：扫码登录、下载队列、ID3 元数据写入

## License

See [LICENSE](./LICENSE).
