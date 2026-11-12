# 大二进制资产说明（ASSETS.md）

改进版仓库**不再提交**以下大二进制文件。原因：仓库原来 35MB 里有 34MB 以上是
二进制文件，git 对二进制文件不友好（每次改动都会让仓库永久变大、clone 变慢），
而且字体、音乐、可执行文件这类资产本身就不适合放进源码仓库。

第一次运行前，请执行：

```bash
python scripts/download_assets.py
```

脚本会从原仓库的 raw 地址下载这些文件到本地对应位置，下载后校验文件大小，
失败会明确报错，不会静默跳过。已下载过的文件再次运行会跳过。
也可以用 `python scripts/download_assets.py --check` 只检查缺失情况。

## 被移除的文件清单

| 文件 | 大小 | 用途 | 替代来源 |
| --- | --- | --- | --- |
| `Upload/uploader/bilibili_uploader/biliup.exe` | 约 14.3MB | B 站上传的命令行工具 | 本脚本下载；或 `pip install biliup` 用 Python 包（`Upload/uploader/bilibili_uploader/main.py` 用的就是 biliup 包，不是这个 exe） |
| `Dedup/assets/fonts/simkai.ttf` | 约 11.8MB | 字幕 / 水印的中文字体（楷体），`Dedup/dedup.py` 默认 `font_file` | 本脚本下载；Windows 系统字体目录里一般自带楷体，也可自行替换 |
| `Dedup/assets/fonts/arial.ttf` | 约 1.0MB | 英文字体 | 本脚本下载；代码里目前没有引用它，仅作备用字体保留 |
| `Dedup/assets/watermark.png` | 约 1.0MB | 默认图片水印，`Dedup/dedup.py` 默认 `watermark_image_path` | 本脚本下载；也可换成你自己的水印图 |
| `Dedup/assets/hzh.mp4` | 约 0.8MB | 默认画中画视频，`Dedup/dedup.py` 默认 `hzh_video_file` | 本脚本下载；也可换成你自己的视频 |
| `Dedup/assets/bgm.mp3` | 约 0.5MB | 默认背景音乐，`Dedup/dedup.py` 默认 `background_music_file` | 本脚本下载；也可换成你自己的音乐（注意版权） |
| `images/IPWO.png` | 约 2.6MB | README 里的赞助商横幅 | 本脚本下载；不影响运行，只影响 README 显示 |
| `images/cover_demo.png` | 约 2.4MB | README 软件截图 | 本脚本下载；不影响运行 |
| `images/cover_script.png` | 约 0.7MB | README 脚本运行截图 | 本脚本下载；不影响运行 |
| `images/gzh.png` | 约 0.1MB | 公众号二维码宣传图 | 本脚本下载；代码和文档里都没有引用它，不影响运行 |
| `images/wechat.png` | 约 0.1MB | 微信二维码宣传图 | 本脚本下载；代码和文档里都没有引用它，不影响运行 |

合计约 34MB。移除后仓库待推送内容只剩文本文件，约 0.3MB。

## 注意事项

- `Dedup/dedup.py` 的默认值要求水印图、画中画视频等资产存在（不存在会报
  `FileNotFoundError`），所以第一次跑去重之前请先运行下载脚本，或者把
  `watermark_type` / `include_hzh` 等选项改成不需要这些文件的配置。
- 字体、音乐这类资产可能涉及版权与许可，请确认你有权使用再分发。
  仓库里不放它们，也是在避免把这类文件扩散到每个 clone 里。
- `Upload/utils/stealth.min.js` 是纯文本的 JavaScript 文件，仍保留在仓库里。
- 如果原仓库的 raw 地址将来失效，脚本会明确报错；届时按上表“替代来源”一栏
  获取，或从你自己的备份里恢复。
