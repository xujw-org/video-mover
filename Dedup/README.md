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
  -> _write_frames：ffmpeg pipe rawvideo -> libx264 + aac，preset fast，crf 走
     config.output_crf（默认 18）；输出帧率 = 原帧率 × playback_speed（第 2 步），
     帧数不变，时长随之变化
```

单帧处理链顺序（`_process_single_frame`，不要轻易调换）：

1. BGR -> RGB
2. 水平镜像（`flip_horizontal`）
3. `apply_geometry`：旋转 + 裁剪 + 缩放 + zoom 合并成**一次** `warpAffine`
   （镜像补边；放大 >1.15× 时用 CUBIC）。原链路是 rotate → 裁剪 → resize →
   zoom，最多 3 次插值，裁剪大时明显发软。
4. `adjust_sbc` 饱和度 / 亮度 / 对比度（LUT 饱和截断）
5. `apply_hue_shift` 色相偏移（第 2 步新增）
6. `add_watermark` 水印（`include_watermark`）
7. `add_subtitles` 字幕（`include_subtitles` 且字幕已加载）
8. `add_titles` 顶部 / 底部标题（`include_titles`）
9. `add_hzh_effect` 画中画（默认关闭：整幅半透明叠加会显得发虚）
10. `color_shift` 颜色偏移（整片固定 `color_shift_value`，不再逐帧随机）
11. `blur_background` 背景模糊
12. `scramble_phase` 频域扰乱（默认关；开启时混合比例 0.15）
13. `add_texture_noise` 纹理噪声（默认关）
14. `apply_edge_blur` 边缘模糊（默认关）
15. `apply_gaussian_blur` 高斯模糊（按帧步长）
16. `apply_fade_effect` 淡入淡出
17. RGB -> BGR 返回

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
从安全范围里抽一套参数——旋转 ±6°、裁剪 4–12%、饱和度/对比度 0.90–1.15、
亮度 −0.10–0.15、帧交换间隔 5/8/10/12/15/20、水印透明度、背景音乐音量等，
25% 概率镜像、10% 概率开轻频域扰乱（0.05–0.15）。同一文件名重跑得到
同一套参数（可复现），不同视频参数组合不同。`--seed N` 指定种子，
`--no-randomize` 恢复原来的固定默认值。

画质修复（2026-11-16）：纹理噪声与边缘模糊不再默认/随机开启（前者是逐帧
高频白噪声，肉眼几乎看不出颗粒感却让编码器多花码率；后者把 Canny 边缘再
高斯模糊后按 10% 叠加，等于给整片蒙灰）；颜色偏移改为每视频固定一个值，
不再逐帧随机（消除颜色闪烁）；频域扰乱概率 20%→10%、混合 0.35→0.15；
旋转/裁剪/缩放/zoom 合并成一次 `apply_geometry` 重采样（此前每帧最多采 3
次，裁剪 20% 时还要放大 1.7×），放大用 CUBIC，裁剪范围收窄到 4–12%；
画中画默认关闭（整幅半透明叠加会显得发虚）；水印默认固定在**左下角**
（`watermark_direction='bottom_left'`，边距为短边 3%；也支持四角 / 8 向移动 /
random 整片固定一点，原来 random 是每帧随机、观感是“有东西在画面里乱跳”）；
水印图没有透明通道时用亮度当 alpha（深色背景透明、亮色 logo 保留），否则整块
方形背景会以低透明度糊在画面上；编码 CRF 从写死的 23 改为
`config.output_crf`（默认 18）。去重侧的几何/色相/帧交换/速度/水印扰动全部保留。

第 2 步（2026-11-12）：在随机参数里加了播放速度 0.95–1.05、色相偏移
±10°、缩放 1.02–1.08。速度只改输出帧率与音频 tempo，时长随之变化，
音画同步不变（见上）；色相和缩放都是肉眼几乎看不出、但逐像素指纹会变的量。

第 3 步（2026-11-12）：音频也按视频随机：主音频音量 0.90–1.10、
音调 0.98–1.02（asetrate+aresample 变调，atempo 把时长补回与速度一致；
拿不到采样率时跳过变调）。BGM 音量已在第 1 步里随机（0.05–0.15）。

注意：`VideoConfig` 的默认值要求水印图、画中画视频等资产存在，
先执行 `python scripts/download_assets.py`，或把对应开关关掉。
