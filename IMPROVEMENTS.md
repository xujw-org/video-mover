# 改进版说明（IMPROVEMENTS.md）

本仓库是 [toki-plus/video-mover](https://github.com/toki-plus/video-mover)
（commit `294d6fd`，约 638 stars）的改进版，目标新仓库为
**xujw-org/video-mover**。本次只做了下面三组优先改进，没有重构业务逻辑，
没有改动视频处理与上传流程本身。

## Windows 批处理中文乱码 + conda 环境一键配置（2026-11-14，未推送）

目标机器：Windows 11（22631）+ Anaconda，使用已有的 conda 环境 `dy`
（Python 3.13.18）。本批只修脚本与依赖清单，不动业务逻辑。

### 1. `.bat` 中文乱码：根因与修复

根因有两层，第二层是本批真正花时间去查的：

1. **编码层**：cmd.exe 默认按系统代码页解释批处理文件的字节。简体中文
   Windows 是 cp936，UTF-8 编码的中文（`rem` 注释 / `echo` 文本）直接变成
   乱码，因为原来两个 `.bat` 既没有 `chcp 65001`，也没有声明编码。
2. **解析器层（实测确认）**：加上 `chcp 65001` 后显示修好了，但 cmd.exe
   的批处理解析器在 65001 代码页下用“字符数”当“字节数”回溯文件位置，
   遇到多字节中文会把某一行截断，把半行残片当命令执行。本机复现到的现象
   是偶发地多出两条报错：
   `'ocal，否则' 不是内部或外部命令`、`'已执行' 不是内部或外部命令`，
   位置正好落在文件第 512 字节边界附近。对照实验：控制台**起始**代码页
   65001 时 1/6 概率触发；起始为 936（双击运行时的默认值）时 6/6 干净。
   也就是说，把“切换代码页”写在文件里本身就带着概率性故障。

修复思路：**`.bat` 只保留纯 ASCII**（没有多字节，就不会乱码，也不会踩解析器
偏移错位），中文提示一律交给 Python 脚本输出。新增 `scripts/win_env.py`：

- `setup.bat [环境名]`（默认 `dy`）→ `python scripts\win_env.py setup --env …`：
  升级 pip → 装 `requirements.txt` → 装 `requirements-dev.txt` → 装 Playwright
  浏览器（chromium / firefox）→ 打上游补丁 → 检查 `ffmpeg` / `ffprobe`。
  加 `--with-assets` 会顺手跑 `download_assets.py`。
- `start.bat [环境名] [额外参数]` → `python scripts\win_env.py run --env …`：
  检查依赖 → 清空 `Upload\videos\*.mp4`（沿用原脚本行为）→ 启动 `main.py`
  并透传退出码；`--dry-run` 只检查环境不启动。
- `python scripts/win_env.py check`：只读体检报告（解释器、依赖导入、ffmpeg、
  Playwright 浏览器目录、补丁状态、资产状态）。

两个 `.bat` 现在只做三件事：`cd /d` 到仓库根目录、`chcp 65001`（让 Python
的 UTF-8 输出正常显示）、按 conda 环境名定位 `python.exe`，然后转交
`win_env.py`。刻意不再 `call` 另一个 `.bat`（`call` 会放大解析器出错的
影响面）。定位失败时的提示仍用英文 + ASCII，因为那时还没有 Python 可用。

### 2. `requirements` 的锁定组合原本装不上

在 dy 里实测 `pip install -r requirements.txt` 直接 `ResolutionImpossible`，
两个独立问题：

- **f2==0.0.1.7 硬钉了三个包的精确版本**（元数据里就是 `==`）：`pyyaml==6.0.2`、
  `qrcode==8.0`、`pytest==8.3.4`。本仓库原先锁的是 `pyyaml==6.0.3`、
  `qrcode==8.2`，于是冲突；`requirements-dev.txt` 里的 `pytest==9.2.0` 也让
  “同时装运行依赖 + 测试依赖”这条路走不通。
  → 三个版本改为跟随 f2：`qrcode==8.0`、`pyyaml==6.0.2`（两个文件都改）、
  `pytest==8.3.4`（dev），并在文件里写明原因。
- **`biliup==1.3.5` 在 Windows 上没有 wheel**：PyPI 上 1.3.x 只有 sdist，
  装它要 Rust + MSVC（本机实测 `maturin` 构建失败：`link.exe` 报错 / 缺
  C++ build tools）。1.2.9 有现成的 `cp39-abi3-win_amd64` wheel，且
  `Upload/uploader/bilibili_uploader/main.py` 用到的
  `biliup.plugins.bili_webup.{BiliBili,Data}` 在 1.2.9 里都在。
  → 锁到 `biliup==1.2.9` 并注明原因。

### 3. 真跑起来时暴露的两个阻塞问题

第一次 `start.bat` 跑通后 f2 一个文件也没下，日志里只有一行
`ERROR DouYin CLI 缺乏必要参数：mode`。顺着这条线查出两个必改项：

- **f2 命令缺 `-M/--mode`**：f2 0.0.1.7 的 `apps/douyin/cli.py` 和
  `apps/tiktok/cli.py` 把 `--mode/-M` 的 `default` 注释掉了，而
  `f2/conf/app.yaml` 的 douyin 小节里也没有 `mode`，于是不传就直接报错退出
  （`mode_function_map[mode]` 根本走不到）。修复：`_F2_COMMAND_BY_PLATFORM`
  改成带 `-M post`；新增 `_ensure_mode()`，用户自定义的 `f2_command` 里
  缺 `-M/--mode` 时也补默认 `post` 并打一条日志（有 `-M` / `--mode` 就尊重
  原值）。
- **落盘结构与去重扫描对不上**：f2 的真实结构是
  `<path>/<app>/<mode>/<昵称>/<作品时间>/<id>.mp4`
  （`apps/douyin/utils.py::create_user_folder`），而 `_get_video_files`
  原来只在 `<download_dir>/<作品时间>/` 一层里找；另外 douyin 小节默认
  没有 `folderize`，不开它 f2 会把作品平铺在 `Download` 下，按“作品时间
  文件夹”扫描永远为空。修复两处：
  1. `my_apps.yaml.example` 的 douyin 小节补上 `folderize: yes`、
     `mode: post`、`naming: '{create}'`（tiktok 小节本来就有；`{create}`
     正好是 `2026-11-14 15-17-57` 这种能被 `_parse_folder_time` 解析的名字）；
  2. `FileManager` 新增 `_iter_work_dirs()`：先找本层的时间戳目录，
     再往下找一层，所以 `download_dir` 配到 `<昵称>` 或往上到 `<mode>` 层
     都能扫到。

修完再跑：f2 日志变成 `模式：post`，请求真的发出去了；因为
`my_apps.yaml` 里还是模板占位账号（`https://www.douyin.com/@example`），
f2 报 `未在响应的地址中找到sec_user_id，检查链接是否为用户主页类名`，
两个源都失败，调度器按既有逻辑跳过后续去重 / 上传。也就是代码侧已无阻塞，
剩下只差真实博主主页地址 + 抖音 cookie。

### 4. f2 在抖音上彻底失效：Argus secsdk 签名（Burp 抓包定位）

环境、cookie、流水线代码都没问题，真正卡住的是新版风控签名。定位过程全在
Burp 里做（用户浏览器走 Burp 代理，同时把我们的抓取器也挂到代理上对照）：

- Burp 里最新一条 `/aweme/v1/web/aweme/detail/` 请求的参数除了 `a_bogus`
  之外，还带了 `x-secsdk-web-signature`、`uifid`、`webid`、`fp`/`verifyFp`、
  `timestamp`、`update_version_code` 等。
- 拿浏览器自己发的那条 **200** 的 `aweme/post` URL，逐项删参数重放：

  | 重放内容 | 结果 |
  | --- | --- |
  | 浏览器原样 URL | 200，返回 `aweme_list` |
  | 删 `x-secsdk-web-signature` | 403 `ArgusSecurityPlugin Signature Not Found` |
  | 删 `fp`/`webid`/`uifid`/`timestamp` | 403 `ArgusSecurityPlugin Uifid Not Found` |

  签名由页面里的 secsdk JS（`lf-security.bytegoofy.com` 的 runtime bundle）
  计算，f2 0.0.1.7 没有任何 secsdk 逻辑，PyPI 上 f2 最新就是 0.0.1.7，
  升级无路 → 只能在请求层绕开它。

修复：新增 `douyin_fetch.py`（抖音走**浏览器通道**）：

1. Chromium（Playwright）用 yaml 里的 cookie 打开博主主页；
2. 直接读页面**自己发出**的 `aweme/post` 响应（签名由页面 JS 完成），
   按需滚动翻页，直到掌到时间窗口下界 / 不再有新响应；
3. 用 httpx 按直链下载视频，落盘结构与 f2 一致：
   `<download_dir>/<昵称>/<作品时间>/<aweme_id>.mp4`，去重扫描不用改；
4. 图文作品（`aweme_type=68` / `media_type=42`）跳过：它们的
   `video.play_addr` 指向的是背景音乐 mp3，直接下会得到音频（已实测）。

`main.py` 的 `execute_main_command` 按平台分流：`douyin` →
`_fetch_douyin_source()`（浏览器通道），tiktok 等其它平台继续走 f2 子进程，
所以 f2 和现有配置对其它平台仍然有效。

验证结果（同样在 Burp 里可以看到）：

- 抓取器的 3 条 `aweme/post`（Burp 历史 index 1541/1635/1649）全部 **200**，
  响应 1.4MB / 1.07MB / 1.3MB，带完整 `x-secsdk-web-signature`；
- 真实下载：`7707114477661894106.mp4` 3.4MB，HEVC 2160x3840；
- 真实处理：`Dedup/dedup.py` 跑完这个 4K 视频（4m14s）→ h264 2160x3840 +
  aac，24MB，流水线链路通了；
- `pytest`：**190 passed**（新增 `tests/test_douyin_fetch.py` 14 个，
  以及 `main.py` 平台分流、图文跳过、落盘结构等回归用例）。

顺带修的两个环境问题：

- **`tests/test_multi_source.py` 会删掉真实的 `Download/`**：
  `test_sources_list_parsed_with_derived_values` 的 `finally` 里写着
  `shutil.rmtree(REPO_ROOT / "Download")`（因为该用例故意用推导出的默认下载
  目录），也就是说每跑一次测试就会把用户已经下载的素材一起删光（本机实测
  删过两次）。已改为只删本用例自己创建的两个空目录，并只清理变空的父目录。
- **Python 3.13 缺 `audioop`**：pydub 0.25.1 会退到 `import pyaudioop`，
  结果是 `AudioSegment` 为 `None`，Dedup 混 BGM 时报
  `'NoneType' object has no attribute 'from_file'`。已在 requirements 里补
  `audioop-lts==0.2.2; python_version >= "3.13"`。
- `f2` 在仓库根目录生成的 `douyin_users.db` 已加入 `.gitignore`。

遗留：抖音抓取依赖浏览器（比 f2 慢），需要 `python -m playwright install
chromium`；调度窗口仍是 `interval_minutes`（1-1440）滚动窗口，超过 24h 的
旧作品不会被自动处理，需要手动补抓：
`python douyin_fetch.py --url <主页> --days 30`，再对目标文件单独跑
`Dedup/dedup.py`。

### 5. 上传也能无窗口 + 不用扫码（2026-11-14）

用户问“能不能不用浏览器直接下载上传”，逐项确认的结果：

| 环节 | 是否需要浏览器 | 现状 |
| --- | --- | --- |
| 视频文件下载 | 不需要 | httpx 直链下载（本来就是） |
| 主页作品列表 | 需要（只需一个无窗口 Chromium 当“签名器”） | headless 跑，不弹窗口 |
| 抖音上传 | 需要（模拟创作者中心页面） | 已改成 **headless**，不弹窗口 |

要做底去掉浏览器，得把抖音的 secsdk 签名（215KB 混淆 runtime，见
`lf-security.bytegoofy.com`）逆出来；实测签名是页面 webpack 侧调用产出的
产物，短期不可行，因此下载列表保留 headless 浏览器。

上传部分的两处改动：

1. **cookie 不用扫码**：`sessionid`/`sid_guard`/`ttwid` 这些 cookie 的作用域是
   `.douyin.com`，`creator.douyin.com` 与 `www.douyin.com` 共用。新增
   `Upload/export_cookie.py`，把 `my_apps.yaml` 的 `douyin.cookie` 转成上传器要的
   Playwright `storage_state`（`Upload/cookies/douyin_<账号>.json`）。实测
   headless 直接进了 `creator-micro/content/upload`（页面已登录，无登录弹窗）。
2. **无窗口 + 可演练**：`DouYinVideo` 原来硬写 `headless=False`，现改为读
   `upload.headless`（默认 **true**，无窗口）；新增 `upload.dry_run`（默认 false）：
   把标题/话题/封面/地点都填好，停在“发布”按钮前，不真正发布也不删文件。
   环境变量只能往“更安全”的方向覆盖：`DOUYIN_UPLOAD_HEADED=1` 强制有界面，
   `DOUYIN_UPLOAD_DRY_RUN=1` 强制不发布（方便一次性演练）。

实测（无窗口、不发布）：

```text
上传模式：无窗口(dry_run：不真正发布)
[-] 正在打开页面...  -> [+] 成功进入version_2发布页面!
[-] 正在上传视频中... -> [-] 视频上传完毕
[-] dry_run：表单已就绪，停在“发布”按钮前，不真正发布
[-] cookie 更新完毕！
dry_run 完成：1 个视频走到发布前，未发布也未删除
```

新增测试：`tests/test_export_cookie.py`（4 个）、`test_multi_source.py` 里的上传
开关用例（4 个）。注：抖音创作者中心目前时不时会弹一个“发布前内容检测”引导层，
会挡住部分点击元素，演练时偶尔需要重跑一次（本次第一次就撞上了）。

### 6. 第一次真正发布：被引导浮层和过期 cookie 挡住（已修）

第一次真跑发布（`Upload/douyin_upload.py`，headless）时暴露两个问题：

1. **引导气泡挡住“发布”按钮**：创作者中心会弹一个「视频预览功能」气泡，
   带一个“我知道了”按钮，正好盖在底部操作区上。旧代码是
   `while True: 点发布 -> wait_for_url(manage**) -> 失败就再点`，于是
   在没挡住的状态下疯狂重试了 10 几分钟（截图确认点了几十次）。
   已修：
   - 新增 `_dismiss_guides()`，点之前先关掉“我知道了 / 知道了”这类浮层，
     并补一个 Escape；
   - 新增 `publish_video()`：最多试 3 次，成功只认跳转到
     `creator-micro/content/manage`，**失败直接抛错**，不再是死循环。
   - 事后核查：作品数仍是 3 条（最新 2025-08-15），**没有被误发布**。
2. **cookie 失效检测太旧**：原判断只找页面是否含“手机号登录”，新版扫码/
   手机号表单里这些字不在 innerText（placeholder 不算正文），于是“cookie 有效”
   误报，直到 `set_input_files` 撞上 3 个手机号输入框才炸（strict mode
   violation）。已修：用元素检测（`input[name="normal-input"]` /
   `web-login-area-code-input` + “扫码登录”等文字），失效时直接打印
   “把最新 cookie 更新到 my_apps.yaml → `python Upload/export_cookie.py`”的指引。
3. 顺带：抖音 desc 里带 emoji，Windows 控制台 cp936 下 `print` 会抛
   `UnicodeEncodeError` 把上传打断。`Upload/douyin_upload.py` 开头已把
   stdout/stderr 重设为 UTF-8（errors=replace）。

另外这一轮把下载→上传的“描述文件”链条补齐了：`douyin_fetch.py` 现在按 f2 约定
落盘 `<昵称>/<作品时间>/<作品时间>_video.mp4` 并写 `<作品时间>_desc.txt`，
`Upload/douyin_upload.py` 会拿它当标题 + 话题（实测标题
“🐱🐶🌧️ 因为太可爱了，所以放大看看👀” + 话题 `今天是太阳雨`）。
`_resolve_download_dirs` 也补了“配置目录不存在时退一层找”的逻辑，
`find_desc_file` 支持多一层昵称目录。

### 7. Dedup 处理 4K 视频：10 分钟 + 成品“后半段一帧卡死”（已修）

用户反馈：一段 8 秒的抖音 4K 视频，去重跑了 10 分钟，而且成品只有前几秒正常，
后面整段是同一帧。实测定位到三个独立问题：

1. **成品被截断到 100 帧（= 一个批大小）**：帧交换用的是“对每个输出帧
   `cap.set(CAP_PROP_POS_FRAMES)` 再读一帧”的 seek 写法。HEVC 4K 上逐帧定位
   极慢（单是 250 次 seek 就要 170 秒），而且 seek 一旦失败就 `break`，
   于是生成器在第 101 次 seek 失败后直接结束 —— 正好停在 batch_size=100 上，
   输出只有 3.5 秒画面。改成**顺序读帧 + 每块内交换前两帧**（内存只多 1 帧，
   语义与原来的 `get_original_idx` 一致），不再 seek，也不会提前结束。
2. **编码成了 yuv444p**：`_write_frames` 把 bgr24 直接塞给 libx264，没指定
   `pix_fmt`，x264 选了 `High 4:4:4 Predictive`。手机/抖音/多数播放器解不了
   4:4:4，表现就是“前几秒正常、后面卡住”，同时码率飙到 29Mbps
   （3.5 秒 12.8MB）。现在显式 `pix_fmt='yuv420p'`。
3. **容器时长跟音频走**：音频（变调 + BGM 混音后）比视频流长 0.7 秒，
   容器时长取最大值，播放器把最后一帧定住 → 又一处“卡住”。加了 `-shortest`。

另外 **10 分钟的耗时** 主因是频域扰乱 `scramble_phase`：4K 帧做全分辨率
2D FFT（3 通道正 + 逆）每帧 5.4 秒，250 帧光这一项就 20+ 分钟。现在大尺寸帧
先缩到 720 长边再 FFT、升采样回原尺寸与原帧按 0.35 混合（视觉几乎无差别，
实测与原帧 RMS 差异 1.9），单帧 5.4s → 0.17s。顺带把批大小按像素预算限到
256MB（4K 下 100 帧要 2.5GB 常驻）。

修复前后（同一段 4K HEVC 源，`Upload/videos` 里的成品）：

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| 处理耗时 | 10 分 02 秒 | 1 分 30 秒 |
| 视频帧数 | 100 / 250（截断） | 250 / 250 |
| 逐帧哈希唯一数 | — | 250 / 250（无重复帧） |
| 像素格式 | yuv444p（4:4:4） | **yuv420p** |
| 输出时长 | 视频 3.48s / 容器 9.1s（末帧冻结） | 视频 8.708s / 音频 8.707s |
| 文件大小 | 12.8MB（3.5 秒） | 27MB（8.7 秒，27Mbps 的 4K 正常量级） |
| 进度日志 | 无 | 每 25 帧打一次“平均 N 帧/秒” |

新增回归测试：编码参数（`pix_fmt='yuv420p'` 与 `-shortest` 必须在 kwargs 里）、
大帧 scramble 必须走缩小路径（monkeypatch 检查传给 `_scramble_fft` 的尺寸）。
另外给 `Dedup/filters.py` 补了 `TYPE_CHECKING` 导入，顺手消掉 15 个 F821。

### 8. 第一次真发布成功（2026-11-14 17:29）

用户更新 cookie 后 `python Upload/export_cookie.py`（74 条 cookie）→ 创作者中心
headless 直接进上传页 → `python Upload/douyin_upload.py`：

```text
[+] cookie 有效
[+]正在上传-------🐱🐶🌧️ 因为太可爱了，所以放大看看👀 #今天是太阳雨.mp4
[-] 正在填充标题和话题... 总共添加1个话题
[-]视频上传完毕
[-] 关掉引导浮层：我知道了          <- 之前“点发布没反应”的真凶
[-]视频发布成功                     <- 跳转到 content/manage
[-]cookie更新完毕！ 全部上传成功：1 个视频
```

退出码 0；`Upload/videos` 里的成品被正常删除；创作者中心作品数 3 → **4**，
新作品状态“审核中”。**整条链路（抓取 → 下载 → 去重 → 发布）第一次全自动跑通，
全程无窗口。**

### 9. 验证结果（2026-11-14，本机 dy）

- `setup.bat` 全流程 0 退出码：pip / 依赖 / Playwright（chromium-1254、
  firefox-1572）/ 补丁（3 个 APPLIED 或 ALREADY_APPLIED）/ ffmpeg 8.1.2 全 OK。
- `scripts/download_assets.py`：11 个资产全部下载并校验大小通过。
- `pytest -q`：**203 passed**（原 152 + 17 个 win_env 测试 + 5 个
  `-M`/落盘结构回归 + 14 个 douyin_fetch 测试 + 2 个平台分流测试）。
- `setup.bat` / `start.bat` 在起始代码页 936 与 65001 两种情况下各连跑 5 次，
  均无解析器报错，中文显示正常。
- 新增 `tests/test_win_env.py`（17 个）：钉住“.bat 纯 ASCII / CRLF / 必须
  `chcp 65001` / 不许再 `call` 批处理”这几条约束，以及解释器解析、
  `Upload\videos` 清理只删 mp4、`--help` 可跑。

## 多博主抓取 + 抖音上传接入流水线（2026-11-12，未推送）

Moon 要求把抖音搬抖音接进自动流水线，并支持多个博主抓取。

做法：
- `main.py` 的 `AppConfig` 新增 `video_mover.sources` 列表：每项一个
  博主（platform/account/url，可另写 f2_command/download_dir）。
  `f2_command` 与 `download_dir` 不写时按平台/账号推导（douyin →
  `["f2", "dy"]`、tiktok → `["f2", "tk"]`，下载目录默认
  `Download/<platform>/post/<account>`，与 f2 的默认落盘布局一致）；
  其它平台没有内置推导，必须显式写 f2_command。旧版单个 `source`
  写法仍可用（此时环境变量 `VIDEO_MOVER_SOURCE_*` 仍可覆盖）；
  一旦写了 `sources`，环境变量的 SOURCE_* 不再生效。
  兼容旧属性（`SOURCE_*` / `DOWNLOAD_DIR` / `MAIN_COMMAND`）恒等于
  第一个源；新增 `SOURCES` 与 `DOWNLOAD_DIRS`。
- `MainCommandHandler.execute_main_command` 改为逐个跑每个源的 f2 命令
  （`f2 <cmd> -c my_apps.yaml -u <url> -i <时间范围>`），一个源失败
  不中断其余源；返回“至少一个源成功”与“任一源命中 403”。命中 403 时
  调度器仍按老逻辑跑刷新脚本后整体重试一次（f2 会跳过已下载过的文件）。
- `FileManager` 的去重扫描与文件监听改为覆盖全部 `DOWNLOAD_DIRS`。
- `UploadHandler` 支持 `paths.upload_scripts` 列表（按顺序执行，全部
  成功才算成功）；旧版单个 `upload_script` 仍可用。默认上传脚本改为
  `Upload/douyin_upload.py`。
- 新增 `Upload/douyin_upload.py`：批量上传 `Upload/videos` 里的处理后
  视频到抖音（立即发布）。标题与话题优先用 f2 的描述文件
  （`<时间>/<时间>_desc.txt`，第一行当标题、全文 `#话题` 当标签，
  标题截断 30 字、话题最多 10 个），找不到则用文件名当标题、不带话题。
  上传账号来自 `video_mover.upload.douyin_account`，cookie 在
  `Upload/cookies/douyin_<账号名>.json`；cookie 缺失或失效时直接退出
  并打印扫码登录命令，不会在无人值守的调度里弹浏览器。传成功的从
  `Upload/videos` 里删除，失败的保留、下次继续传，最后返回非零退出码。
  上传本身复用已有的 `DouYinVideo`（Playwright + 有界面 Chrome）。
- 配置与文档：`my_apps.yaml.example` 改为 sources 示例（两个抖音博主）
  与 `upload_scripts`，`README.md` 与 `.env.example` 同步更新。
- 测试：新增 `tests/test_multi_source.py`（19 个）：sources 解析与推导、
  旧版兼容、空列表/缺 url/未知平台缺 f2_command 报错、逐源抓取的命令
  与聚合语义、403 检测、多下载目录扫描、多上传脚本执行与失败聚合、
  抖音上传纯函数（描述解析/标题兜底/下载目录推导）。本地 133 → 152
  个测试全过。

Moon 在自己机器上还需手动做的事（本机做不了）：
- `my_apps.yaml` 改成 sources 列表（要抓的博主主页地址）、
  `upload.douyin_account` 与 `upload_scripts: ["Upload/douyin_upload.py"]`；
  抖音抓取用的 cookie 填在文件下方 `douyin` 小节。
- 抖音上传首次登录一次：`python Upload/cli_main.py douyin <账号名> login`，
  扫码生成 `Upload/cookies/douyin_<账号名>.json`。

已知限制：两个博主在同一秒发视频且文件名都叫 `<时间>_video.mp4` 时，
去重输出到同一个 `Upload/videos` 会撞名（概率极小，未处理）；
`DouYinVideo` 发布失败时内部会一直重试直到进作品管理页，极端情况下
可能卡住单次调度；抖音页面结构变化可能导致上传器的选择器失效，需实测。

## CI 警告修复：Node 20 与 ubuntu-latest（2026-11-12，需手动更新）

`bd3ba1f` 推送后 CI 是绿的，但两个任务都报了警告：
- Node.js 20 已弃用：`actions/checkout@v4` 与 `actions/setup-python@v5`
  目标是 Node 20，被强制跑在 Node 24 上。已查官方 release：
  checkout 从 v6.0.0、setup-python 从 v6.0.0 开始支持 Node 24，
  最新分别是 v7.0.1 与 v7.1.0；v7 的破坏性变更只涉及
  `pull_request_target` / fork PR 与 ESM 迁移，本仓库的用法
  （默认 checkout、setup-python 的 python-version/cache）不受影响。
  所以两处统一升到 `@v7`。
- `ubuntu-latest` 将于 2026-10-19 起迁移到 Ubuntu 26：把 `test`
  任务的 `runs-on` 从 `ubuntu-latest` 固定为 `ubuntu-24.04`，
  保持当前已验证过的环境；`windows-latest` 没报警告，不动。
- 注意：和当初一样，workflow 文件推不上去（GitHub App 403），
  本地文件已改好，需 Moon 在网页上编辑
  `.github/workflows/ci.yml` 同步这 5 处改动，保存即会触发一次 CI。

## 每视频随机参数：固定参数易判重（2026-11-12，已推送 bd3ba1f）

Moon 提出视频处理可以更多样，否则容易被判重复。根因：CLI 每次都用
`VideoConfig()` 的固定默认值（旋转固定 −6°、裁剪固定 10%、饱和度/对比度
固定 1.05、帧交换固定每 15 帧、BGM 音量固定 0.1），真正随机的只有水印位置
和逐帧颜色偏移，感知哈希/帧指纹结构基本不变。

做法（低风险的第一步，也是后两步的基础）：
- `Dedup/config.py` 新增 `VideoConfig.randomized(seed)` 与
  `randomized_for(input_path)`：按输入文件名 SHA-256 派生种子，从安全范围
  里抽一套参数——旋转 ±6°、裁剪 5–20%、饱和度/对比度 0.90–1.15、亮度
  −0.10–0.15、帧交换间隔 5/8/10/12/15/20、高斯模糊间隔/核/面积、水印透明度
  0.04–0.10、BGM 音量 0.05–0.15、淡入淡出帧数、颜色偏移范围 2–5、画中画
  透明度/缩放、边缘模糊百分比；25% 概率镜像、30% 概率纹理噪声、20% 概率
  轻频域扰乱（0.05–0.20）。全部落在 `validate()` 允许范围内。
- `Dedup/dedup.py` 的 CLI 默认改用 `randomized_for(args.input)`，并按同一
  种子播种全局 `random` / `np.random`（水印位置、颜色偏移等逐帧随机也随
  种子走）；新增 `--seed N`（指定种子可复现）与 `--no-randomize`（恢复
  固定默认值）。`VideoConfig()` 默认值本身没变，`main.py` 的 subprocess
  调用方式不变。
- 新增 `tests/test_randomized_config.py`（7 个）：同一种子参数相同、不同
  种子参数不同、`randomized_for` 只认文件名、50 粒种子取值不越界、套用
  随机参数后 `validate()` 仍通过、默认值不变、`--help` 列出新参数。
  本地 113 → 120 个测试全过。

注意：可复现的保证只到“参数组合”一层——pipeline 用线程池并行处理帧，
逐帧随机调用的先后顺序可能变化，不保证逐帧比特级相同。镜像会翻转画面内
原有文字（只 25% 概率开）；频域扰乱处理时间较长（只 20% 概率开）。

### 第 2 步：新效果——速度、色相、缩放（2026-11-12，已推送 bd3ba1f）

- `Dedup/config.py` 新增 `playback_speed`（默认 1.0，随机 0.95–1.05）、
  `hue_shift`（默认 0，随机 ±10°）、`zoom_factor`（默认 1.0，随机
  1.02–1.08），并补了 `validate()` 范围校验（速度 0.5–2.0、色相
  ±30°、缩放 1.0–1.5）。
- `Dedup/filters.py` 新增 `apply_hue_shift`（HSV 的 H 通道整体平移，
  OpenCV 里 1° = 0.5 个单位）与 `apply_zoom`（先放大再居中裁回原尺寸，
  输出尺寸不变）；处理链顺序：缩放放在裁剪/回缩之后、色相放在 SBC 之后。
- `Dedup/pipeline.py`：输出帧率 = 原帧率 × 速度，帧数不变；字幕仍按
  原时间查（`_process_frames` 拿原 fps），只有写帧用新帧率，否则字幕
  会整体漂移。已用真实 cv2 验证：色相 +10° 确实改像素、缩放 1.08
  保持尺寸且改内容。
- 200 粒种子实测分布：速度 0.95–1.049、色相 −10–10、缩放 1.02–1.08。

### 第 3 步：音频多样化——音量、变调、变速（2026-11-12，已推送 bd3ba1f）

- `Dedup/config.py` 新增 `audio_volume`（默认 1.0，随机 0.90–1.10）与
  `pitch_shift`（默认 1.0，随机 0.98–1.02），并补了 `validate()` 范围校验。
- `Dedup/pipeline.py` 新增 `VideoHandler._apply_audio_effects()`，集中在
  最终音频流上加 ffmpeg 滤镜：`volume` 调音量；
  `asetrate(sr×pitch) + aresample(sr)` 变调；
  `atempo(speed/pitch)` 把时长补到与视频新时长一致（音调不受 atempo
  影响）。pitch 为 1.0 时跳过变调，atempo 因子就是速度；拿不到采样率
  时跳过变调、只变速；无音频流时返回 None；全是默认值时不加任何滤镜。
  采样率从 `ffmpeg.probe` 的音频流里取。
- 测试：新增 `tests/test_dedup_speed_audio.py`（9 个），覆盖音量/变速/
  变调/变调+变速组合/无采样率跳过/无音频流/处理与写帧的帧率分工；
  `tests/test_dedup_filters.py` 加色相/缩放 4 个测试；
  `tests/test_dedup_pipeline.py` 的处理链顺序断言更新为 19 步；
  `tests/test_randomized_config.py` 的随机字段与范围断言覆盖 5 个新参数。
  本地 120 → 133 个测试全过。

仍待 Moon 拿真实视频验证：画质（速度/色相/缩放是否可接受）、音画同步
（速度与变调叠加时）、以及频域扰乱叠加时的处理时间。BGM 轮换没做——
目前只有一个 bgm.mp3 资产，没有可轮换的曲库。

## CI Windows 修复之三：美区 runner 的 cp1252 编码（2026-11-12）

第三次 CI 运行：Ubuntu 全过，windows-smoke 5 failed、107 passed。
这次不是 tzdata（已修好），而是编码：

- 3 个 `--help` 测试失败：`UnicodeEncodeError: 'charmap' codec
  can't encode characters in position 207-214`。根因是 GitHub
  Windows runner 是美区系统，stdio 默认编码是 cp1252（charmap），
  根本编不了中文；而 argparse 的 `--help` 里有“输入视频文件路径”/
  “输出视频文件路径”这类中文（位置 207-214 正好是这 8 个字），
  直接打印就炸。本机用 `PYTHONIOENCODING=cp1252` 复现过，同一报错。
- 1 个缺失输入测试失败：子进程 stderr 的错误处理是
  backslashreplace，中文被写成 `\uXXXX` 转义，`"不存在"` 断言
  找不到原文。
- 1 个 win32api 测试失败：它断言“当前 sys.modules 里没有
  win32api”，但 CI 现在会装 pywin32（上次修复加的），所以
  win32api 已经作为真实模块存在，前置断言本身就是错的。

修复：
- `Dedup/dedup.py`：启动时把 stdout/stderr 重设为 UTF-8
 （errors='replace'，失败时静默跳过），与 main.py 同款做法，
  且放在 argparse 打印帮助之前。真实用户在美区 Windows 上
  直接跑 `python Dedup/dedup.py --help` 也不崩。
- `tests/test_shim.py`：子进程统一用 `encoding="utf-8"`、
  `errors="replace"` 捕获，并传 `PYTHONUTF8=1` /
  `PYTHONIOENCODING=utf-8`，不再依赖 runner 的默认编码。
- `tests/test_win32api_guard.py`：删掉错误的前置断言，只验证
  “把 win32api 从 sys.modules 拿掉后 reload main 仍成功”。
- 顺手修了同类隐患：`main.py` 的 `MainCommandHandler` 用
  `text=True` 读子进程输出时没写 encoding，美区 Windows 上
  会按 cp1252 解码中文输出而失败；已补 `encoding='utf-8'`、
  `errors='replace'`（`_build_subprocess_args` 里本来就有）。
- 新增回归测试 `test_cli_help_with_charmap_stdio`：用
  `PYTHONUTF8=0` + `PYTHONIOENCODING=cp1252` 模拟美区
  Windows 跑 `--help`，验证修复后能正常退出且帮助里有中文。
  测试总数 112 -> 113，全部通过。

## CI Windows 修复之二：tzdata 与控制台编码（2026-11-12）

第二次 CI 运行：Ubuntu 全过，windows-smoke 在测试阶段失败，
13 failed、89 passed、5 errors。主因是 Windows 的 Python 3.12
自身不带 IANA 时区数据库，`AppConfig` 用 `ZoneInfo('Asia/Shanghai')`
校验时抛 `ZoneInfoNotFoundError`（随后是 `ModuleNotFoundError:
No module named 'tzdata'`），大量用 Asia/Shanghai / Europe/London
的测试连带失败；Ubuntu 因系统自带时区库而通过。

修复：
- `requirements.txt` 和 `requirements-dev.txt` 都加了 `tzdata==2026.6`
 （CI 只装后者，所以两边都要加）。Linux/macOS 自带系统时区库，
  装上也无害。
- 时区校验的报错分开了：找不到时区数据时提示 Windows 用户先
  `pip install tzdata`，而不是只说名字非法。
- 次因是 `main.py` 日志里有 ✅（U+2705），Windows 控制台默认编码是
  cp936（charmap），输出它会抛 `UnicodeEncodeError`。已把两处 ✅
  从日志里去掉，并在启动时把 stdout/stderr 重设为 UTF-8
 （errors='replace'，失败时静默跳过）。
- 新增回归测试 `tests/test_tzdata_and_encoding.py`（5 个），测试总数
  107 -> 112，全部通过。

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

- **依赖完整安装（已在本机 Windows 验证，2026-11-14）**：早期写的“未验证”
  现在有结论了：原锁定组合确实装不上，原因是 f2 硬钉 `pyyaml==6.0.2` /
  `qrcode==8.0` / `pytest==8.3.4`，以及 `biliup==1.3.5` 在 Windows 上只有
  sdist 需要 Rust + MSVC。已按上文“Windows 批处理中文乱码 + conda 环境一键
  配置”一节改三处版本，`setup.bat` 在 conda 环境 `dy`（Python 3.13.18）里
  跑通，`pytest` 169 个全过。仍存的差异：目标 Python 是 3.13 而锁定说明按
  3.12 写的；`biliup` 用 1.2.9（上游锁 1.3.5），B 站上传流程**没有**真实跑过。
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
