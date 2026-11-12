# 上游兼容补丁说明（PATCHES.md）

原仓库 README 要求手动改第三方库源码（f2 的两处、视频号上传的一处），手动步骤
容易丢、也无法验证。改进版把这三处补丁收进 `scripts/apply_upstream_patches.py`，
每次运行都会先校验目标代码是否存在，校验失败就报错退出，绝不静默跳过。

针对的上游版本：**f2==0.0.1.7**（见 `requirements.txt` 的版本锁定）。
补丁打在“已安装的 f2”上（虚拟环境的 site-packages），因此每次重装或升级依赖后
都需要重新运行一次；`setup.bat` 已包含这一步。

用法：

```bash
python scripts/apply_upstream_patches.py            # 应用全部补丁
python scripts/apply_upstream_patches.py --check    # 只检查，不修改
```

## 补丁 1：f2 的 TikTok 分页游标必须是 int

- 位置：已安装 f2 包内的 `f2/apps/tiktok/handler.py`
- 原因：cursor 从命令行参数 / 配置里取出来可能是字符串，而 TikTok 接口要求 int，
  不转换会在翻页时出错。
- 做法：把五处 `cursor = self.kwargs.get("cursor", 0)`（第 292 / 425 / 545 / 663 / 877 行，
  分别在 `fetch_one_video`、`fetch_user_post_videos`、`fetch_user_like_videos`、
  `fetch_user_collect_videos`、`fetch_user_mix_videos` 里）改为
  `cursor = int(self.kwargs.get("cursor", 0) or 0)`。
- **核对说明**：README 原文写的是 handler.py 约 389 行
  `params={"cursor": cursor, ...}` 改为 `int(cursor)`，但在 f2 0.0.1.7 的官方源码里
  389 行是 `if cursor < min_cursor:`，全文件根本不存在 `params={"cursor": cursor}` 这种
  写法（cursor 是通过 `UserPost` / `UserLike` / `UserCollect` 等模型传参的）。
  脚本按 0.0.1.7 的实际代码做了等价修复，意图与原文一致，行号以实际源码为准。
  核对时间：2026-11-12，来源：PyPI 官方 sdist `f2-0.0.1.7.tar.gz`。

## 补丁 2：f2 的日期解析要同时兼容纯日期与带时间的写法

- 位置：已安装 f2 包内的 `f2/utils/utils.py`
- 原因：本项目 `main.py` 生成的时间区间是带时间的格式，例如
  `2025-03-07 21-00-00|2025-03-07 22-00-00`，而 f2 0.0.1.7 的日期解析只认
  单一格式，混用就会解析失败返回 0，导致抓取不到正确时间范围的作品。
- 做法（共 4 处，均先校验原文、找不到就报错）：
  1. `str_2_timestamp`：先按传入的格式解析，失败后再依次尝试
     `%Y-%m-%d %H-%M-%S`、`%Y-%m-%d`、`%Y-%m-%d %H:%M:%S`。
  2. `interval_2_timestamp`：区间端点如果本身已带时间，就不再追加
     ` 00-00-00` / ` 23-59-59` 后缀（原来无条件追加会拼出
     `2025-03-07 21-00-00 00-00-00` 这种非法字符串）。
  3. `filter_by_date_interval` 的区间端点解析：先试带时间的格式，再试纯日期格式；
     纯日期的结束端点仍按原来的“当天 23:59:59”处理。
  4. `filter_by_date_interval` 里作品 `create_time` 的解析：先试带时间的格式，
     再试纯日期格式，都失败才记警告并跳过。
- 核对说明：位置与原文描述的“约 200 / 690 行”基本吻合（`interval_2_timestamp`
  在 173 行附近，`filter_by_date_interval` 在 643 行附近），以实际源码为准。

## 补丁 3：视频号上传的页面跳转等待超时 1500ms → 10000ms

- 位置：本仓库自带的 `Upload/uploader/tencent_uploader/main.py`（`click_publish`）
- 核对结果：**本仓库自带的代码已经是 `timeout=10000`，全文没有 `1500`，无需修改。**
  该文件共 267 行，README 原文写的“约 191 行”已过时。
  脚本每次运行都会复核：如果发现 `timeout=1500` 就改掉，如果已是 `10000` 就
  直接报告“早已应用”，如果两种都找不到就报错请人工检查。
- 原因：慢网络下页面跳转超过 1500ms 会被误判为发布失败。

## 注意事项

- 补丁只针对锁定的 f2==0.0.1.7 做过核对。升级 f2 后请先用
  `python scripts/apply_upstream_patches.py --check` 检查，校验失败时不要强行
  安装，先看本文件更新补丁位置。
- 脚本首次修改文件前会备份原文件为 `.bak`（已存在则不再覆盖）。
- 如果某天上游 f2 修好了这些问题，脚本会报告 ALREADY_APPLIED 或 FAILED，
  请按提示处理，不要手动改完又忘记录。
