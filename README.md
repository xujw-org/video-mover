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
- Python 3.12+
- Node.js 22.x
- FFmpeg（需加入 `PATH`）
- Chrome

### 安装

1. 克隆仓库：

   ```bash
   git clone https://github.com/xujw-org/video-mover.git
   cd video-mover
   ```

2. 运行 `setup.bat`，自动安装 Python、Node.js、Playwright 与相关依赖，并自动运行
   上游兼容补丁脚本。建议在独立虚拟环境中运行。

3. **依赖补丁（已自动化）**：为兼容目标平台接口，需要对已安装的 f2 等上游库做
   三处小改动，现已收进 `scripts/apply_upstream_patches.py`，`setup.bat` 会自动
   运行它；也可以手动执行 `python scripts/apply_upstream_patches.py`（只检查不
   改动：加 `--check`）。补丁针对 f2==0.0.1.7 核对过，详见 [PATCHES.md](./PATCHES.md)。
   每次重装或升级依赖后请重新运行一次。

4. **下载二进制资产**：字体、背景音乐、水印图、画中画视频、README 截图等大文件
   已移出仓库，首次运行前执行：

   ```bash
   python scripts/download_assets.py
   ```

   详见 [ASSETS.md](./ASSETS.md)。

### 配置

1. 复制配置模板并填入你自己的值：

   ```bash
   cp my_apps.yaml.example my_apps.yaml
   ```

   在 `my_apps.yaml` 顶部的 `video_mover` 小节里配置视频源、路径、调度和运行参数：

   ```yaml
   video_mover:
     source:
       platform: tiktok
       account: "@example"     # 改成你自己的账号
       url: "https://www.tiktok.com/@example"
       f2_command: ["f2", "tk"]
     paths:
       download_dir: "Download/tiktok/post/example"  # 不存在时自动创建
       dedup_dir: "Dedup"
       upload_dir: "Upload"
       flush_script: "flush_device_id.py"
       dedup_script: "Dedup/dedup.py"
       upload_script: "Upload/vx_upload.py"
     schedule:
       interval_minutes: 300   # 必须是 1-1440 的整数
       timezone: "Asia/Singapore"  # 必须是合法的 IANA 时区名
     runtime:
       max_workers: null       # null = CPU 核心数
       config_file: "my_apps.yaml"
   ```

   配置优先级：环境变量 `VIDEO_MOVER_*` > `my_apps.yaml` > 内置默认值。
   环境变量清单见 `.env.example`（复制为 `.env` 后填写；`.env` 不进仓库）。
   缺失的配置项会打警告并用默认值补齐；`interval_minutes` 超出 1-1440 或时区
   不合法时会直接报错退出。
   下方的 `douyin` / `tiktok` / `weibo` / `twitter` 小节是 f2 的平台配置，
   其中的 cookie 与代理请填你自己的真实值。

2. 如启用 AI 文案功能，通过安全的本地配置方式提供 API Key，切勿提交到仓库。
3. 首次运行平台适配器时，根据提示完成账号登录与 Cookie 初始化。

### 运行

双击 `start.bat`，或执行：

```bash
python main.py
```

程序会自动打开浏览器并执行任务，按提示完成首次登录即可进入自动化流程。

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
