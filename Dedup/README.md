# Dedup：视频去重处理

本目录是视频去重（二次创作差异化处理）的实现。第二批改进（2026-11-12）
把原来 1312 行的单文件 `dedup.py` 拆成了包，类体代码逐字节搬运，
没有改任何 ffmpeg 参数、处理顺序与输出文件名规则。

## 模块结构

```
Dedup/
├── __init__.py        # 包入口：re-export 六个公开类
├── dedup.py           # 向后兼容垫片 + 原 CLI 入口（-i/-o），本身不含处理逻辑
├── config.py          # VideoConfig：全部处理选项 + validate()
├── ffmpeg_utils.py    # FFmpegHandler：分离音视频流、读视频属性
├── audio.py           # AudioHandler：静音去除、背景音乐混合
├── subtitles.py       # SubtitleHandler：Whisper 生成字幕、SRT 时间格式
├── filters.py         # VideoEffects：逐帧视觉特效（水印、字幕、标题、模糊…）
├── pipeline.py        # VideoHandler：编排全流程（见下）
└── assets/            # 资产占位：字幕样例、字体目录（真实大文件用 scripts/download_assets.py 下载）
```

## 新旧映射表

| 原 `Dedup/dedup.py`（1312 行） | 新位置 | 行数 |
|---|---|---|
| `VideoConfig`（`__init__` + `validate` + `is_valid_color`） | `Dedup/config.py` | 约 288 行类体 |
| `FFmpegHandler`（`split_av_streams`、`get_video_properties`） | `Dedup/ffmpeg_utils.py` | 约 46 行类体 |
| `AudioHandler`（`remove_silence`、`mix_bgm`） | `Dedup/audio.py` | 约 67 行类体 |
| `SubtitleHandler`（`generate_subtitles`、`format_time`） | `Dedup/subtitles.py` | 约 35 行类体 |
| `VideoEffects`（水印、字幕、标题、高斯模糊、旋转、SBC、背景模糊、淡入淡出、颜色偏移、画中画、频域扰乱、纹理噪声、边缘模糊） | `Dedup/filters.py` | 约 555 行类体 |
| `VideoHandler`（`process_video` 与帧生成 / 分批 / 单帧 / 写帧） | `Dedup/pipeline.py` | 约 279 行类体 |
| `if __name__ == "__main__"`（argparse `-i` / `-o`） | `Dedup/dedup.py` 的 `main()` | 不变 |

拆分时唯一动过的代码是模块头（导入部分）；类体经校验与原文逐字节一致。
有一个函数没有单独拆成模块：`process_video` 里的帧交换索引映射
`get_original_idx` / `swapped_frame_generator` 是闭包，依赖
`process_video` 的局部状态（`enable_frame_swap`、`frame_swap_interval`），
硬拆会改调用方式，所以留在 `pipeline.py` 里。

## 处理流程（`VideoHandler.process_video`）

```
输入视频
  -> FFmpegHandler.split_av_streams：分离音视频流
  -> FFmpegHandler.get_video_properties：宽 / 高 / 帧率
  -> 字幕：时长 > subtitles_duration 且 include_subtitles 时，
     use_whisper 则 Whisper 生成，否则读 subtitles_file；pysrt 加载
  -> 音频：ffmpeg 抽 wav -> remove_silence（可选）-> mix_bgm（可选）
     -> 音频多样化（第 3 步）：volume 音量、asetrate 变调、atempo 变速
  -> 帧：enable_frame_swap 时用 swapped_frame_generator（交换相邻帧），
     否则用 _frame_generator；分批（batch_size）+ ThreadPoolExecutor(4) 并行
  -> _process_single_frame（单帧处理链，顺序固定，见下）
  -> _write_frames：ffmpeg pipe rawvideo -> libx264 + aac，preset fast，crf 23，b:v 2M；
     输出帧率 = 原帧率 × playback_speed（第 2 步），帧数不变，时长随之变化
```

单帧处理链顺序（`_process_single_frame`，不要轻易调换）：

1. BGR -> RGB
2. 水平镜像（`flip_horizontal`）
3. `rotate_frame` 旋转
4. 按 `crop_percentage` 裁剪，再缩放回原始尺寸
5. `apply_zoom` 轻微缩放：先放大再居中裁回原尺寸（第 2 步新增）
6. `adjust_sbc` 饱和度 / 亮度 / 对比度
7. `apply_hue_shift` 色相偏移（第 2 步新增）
8. `add_watermark` 水印（`include_watermark`）
9. `add_subtitles` 字幕（`include_subtitles` 且字幕已加载）
10. `add_titles` 顶部 / 底部标题（`include_titles`）
11. `add_hzh_effect` 画中画
12. `color_shift` 颜色偏移
13. `blur_background` 背景模糊
14. `scramble_phase` 频域扰乱
15. `add_texture_noise` 纹理噪声
16. `apply_edge_blur` 边缘模糊
17. `apply_gaussian_blur` 高斯模糊（按帧步长）
18. `apply_fade_effect` 淡入淡出
19. RGB -> BGR 返回

播放速度与音画同步（第 2、3 步）：`playback_speed` 只改输出帧率
（`_write_frames` 用 `原帧率 × 速度`），字幕仍按原时间查
（`_process_frames` 拿原帧率），否则字幕会整体漂移；音频用
`atempo` 同步变速，时长与视频新时长一致。变调时先用
`asetrate(sr×pitch) + aresample(sr)` 改音调，再用
`atempo(speed/pitch)` 把时长补回与速度一致；拿不到采样率时
跳过变调、只变速。以上音频处理集中在
`VideoHandler._apply_audio_effects()`，无音频流时返回 None。

## main.py 是怎么调它的

`main.py` 不 import 它，而是用 subprocess 调 CLI（`FileManager._process_video`）：

```python
[subprocess.Popen([sys.executable, str(DEDUP_SCRIPT), "-i", str(input_file),
                   "-o", str(output_file)], cwd=DEDUP_DIR, ...)]
```

其中 `DEDUP_SCRIPT` 默认是 `Dedup/dedup.py`，`cwd` 是 `Dedup` 目录。
所以垫片必须在三种运行方式下都能工作：仓库根目录 `python Dedup/dedup.py`、
`python -m Dedup.dedup`、以及 `cd Dedup && python dedup.py`——垫片开头会
把仓库根目录插进 `sys.path`，再按 `Dedup.xxx` 导入，失败时回退到同目录模块。
这三种方式都有测试覆盖（见 `tests/test_shim.py`）。

## 重依赖是懒加载的吗

不是完全懒加载，是“导入时不报错，调用时才需要”：各模块在顶层用
try/except 导入 cv2 / ffmpeg / pysrt / numpy / Pillow / pydub /
whisper / opencc，缺失时置为 None。好处是 `import Dedup` 和
`python Dedup/dedup.py --help` 在没装重依赖的机器上也能跑，CI 因此可以
只装测试依赖；代价是缺重依赖时，错误从原来的“导入时 ModuleNotFoundError”
变成了“调用处理方法时 AttributeError”。缺依赖时的报错信息以后可以再
收敛成明确的 RuntimeError，目前先保持类体原样不动。

## 单独使用

```bash
# 命令行（与原来完全一样）
python Dedup/dedup.py -i input.mp4 -o output.mp4

# 代码里用新模块
from Dedup.config import VideoConfig
from Dedup.pipeline import VideoHandler

config = VideoConfig()
config.include_subtitles = False
VideoHandler(config).process_video("input.mp4", "output.mp4")
```

## 每视频随机参数（2026-11-12）

默认不再用固定参数：CLI 每次按输入文件名派生种子（`VideoConfig.randomized_for()`），
从安全范围里抽一套参数——旋转 ±6°、裁剪 5–20%、饱和度/对比度 0.90–1.15、
亮度 −0.10–0.15、帧交换间隔 5/8/10/12/15/20、水印透明度、背景音乐音量等，
25% 概率镜像、30% 概率开纹理噪声、20% 概率开轻频域扰乱。同一文件名重跑得到
同一套参数（可复现），不同视频参数组合不同。`--seed N` 指定种子，
`--no-randomize` 恢复原来的固定默认值。`VideoConfig()` 的默认值本身没变。

第 2 步（2026-11-12）：在随机参数里加了播放速度 0.95–1.05、色相偏移
±10°、缩放 1.02–1.08。速度只改输出帧率与音频 tempo，时长随之变化，
音画同步不变（见上）；色相和缩放都是肉眼几乎看不出、但逐像素指纹会变的量。

第 3 步（2026-11-12）：音频也按视频随机：主音频音量 0.90–1.10、
音调 0.98–1.02（asetrate+aresample 变调，atempo 把时长补回与速度一致；
拿不到采样率时跳过变调）。BGM 音量已在第 1 步里随机（0.05–0.15）。

注意：`VideoConfig` 的默认值要求水印图、画中画视频等资产存在，
先执行 `python scripts/download_assets.py`，或把对应开关关掉。
