# -*- coding: utf-8 -*-
"""视频处理配置（VideoConfig 及其校验）。

拆分自 Dedup/dedup.py（第二批改进，2026-11-12）。本模块只依赖标准库，
可独立导入、独立测试；不依赖 cv2 / ffmpeg / whisper 等重依赖。"""

from __future__ import annotations

import hashlib
import os
import random
import re


class VideoConfig:
    """
    视频配置类，用于管理音频、视频特效、字幕等参数。
    """
    def __init__(self):
        # 随机化种子：None 表示使用固定默认值；randomized() / randomized_for()
        # 会填入一个整数种子，同一输入重跑得到同一套参数，不同输入得到不同参数。
        self.random_seed = None

        # GPU加速
        self.enable_gpu: bool = False  # 是否启用 GPU 加速

        # 字幕参数
        self.include_subtitles: bool = False                # 是否添加字幕
        self.subtitles_opacity: float = 0.10                # 字幕透明度，范围0-1，默认1.0
        self.use_whisper: bool = True                       # 是否使用 Whisper 自动生成字幕
        self.whisper_model_name: str = 'base'               # 默认使用 'base' 模型
        self.subtitles_file: str = 'assets/subtitles.srt'   # 字幕文件路径
        self.subtitles_color: str = 'yellow'                # 字幕字体颜色
        self.subtitles_duration: int = 5                    # 字幕持续时间（秒），视频时长超过此值时添加字幕。

        # 标题参数
        self.include_titles: bool = False                   # 是否添加标题
        self.titles_opacity: float = 0.10                   # 标题透明度，范围0-1
        self.top_title: str = 'YANQU'                       # 顶部标题文本
        self.top_title_margin: int = 5                      # 顶部标题与顶部的间隙百分比，范围 0-100。
        self.bottom_title: str = 'YANQU'                    # 底部标题文本
        self.bottom_title_margin: int = 5                   # 底部标题与底部的间隙百分比，范围 0-100。
        self.titles_color: str = 'red'                      # 标题颜色，支持颜色名称或 HEX 码。

        # 水印参数
        self.include_watermark: bool = True                         # 是否添加水印
        self.watermark_opacity: float = 0.06                        # 水印透明度，范围0-1，文字0.10，图片视频0.05
        self.watermark_direction: str = 'random'                    # 水印移动方向
        self.watermark_color: str = 'white'                         # 水印颜色，支持颜色名称或 HEX 码。
        self.watermark_text: str = 'YANQU'                          # 水印文本内容
        self.watermark_type: str = 'image'                          # 水印类型，根据类型设置对应路径，text、image、video。
        self.watermark_image_path: str = 'assets/watermark.png'     # 图片水印文件路径，当 watermark_type 为 'image' 时使用。
        self.watermark_video_path: str = ''                         # 视频水印文件路径，当 watermark_type 为 'video' 时使用。

        # 字体
        self.custom_font_enabled: bool = True               # 是否使用自定义字体
        self.font_file: str = 'assets/fonts/simkai.ttf'     # 字体文件路径

        # 文字外边框
        self.text_border_size: int = 1                      # 文字外边框像素大小

        # 静音消除
        self.enable_silence_check: bool = False     # 是否启用静音检测
        self.silence_retention_ratio: float = 0.5   # 保留的静音比例，范围 0-0.5，0.5 表示保留 50% 的静音片段。
        self.silence_threshold: int = -50           # 静音检测阈值（分贝），绝对值越大保留的声音越多。
        self.silent_duration: int = 500             # 静音持续时间（毫秒），超过此时间触发静音处理。建议不低于 300ms，过小可能导致音频频繁中断。

        # 背景音乐
        self.include_background_music: bool = True          # 是否添加背景音乐
        self.background_music_file: str = 'assets/bgm.mp3'  # 背景音乐文件路径
        self.background_music_volume: float = 0.1           # 背景音乐音量，范围0-1。

        # 视频镜像与旋转
        self.flip_horizontal: bool = False                  # 是否启用水平镜像
        self.rotation_angle: int = -6                       # 旋转角度（度），建议值 -3 到 3。

        # 视频裁剪
        self.crop_percentage: float = 0.1                   # 裁剪百分比，范围 0-0.5，例如 0.1 表示裁剪每边 10% 的区域。

        # 淡入淡出
        self.fade_in_frames: int = 5                        # 淡入效果持续的帧数，建议 10-30 帧。
        self.fade_out_frames: int = 20                      # 淡出效果持续的帧数，建议 10-30 帧。

        # 画中画
        self.include_hzh: bool = True        # 是否启用画中画
        self.hzh_opacity: float = 0.1        # 画中画透明度
        self.hzh_scale: float = 1.0          # 画中画大小因子
        self.hzh_video_file: str = 'assets/hzh.mp4'  # 画中画视频文件路径

        # 颜色调整
        self.enable_sbc: bool = True         # 是否启用饱和度、亮度、对比度调整
        self.saturation: float = 1.05        # 饱和度调整因子，建议 0.8-1.2。值越小颜色越淡，值越大颜色越鲜艳。
        self.brightness: float = 0.05        # 亮度调整因子，建议 -0.3 到 0.3。负值降低亮度，正值增加亮度。
        self.contrast: float = 1.05          # 对比度调整因子，建议 0.8-1.2。值越小对比度越低，值越大对比度越高。

        # 播放速度与色相、缩放（第 2 步新增，2026-11-12）
        self.playback_speed: float = 1.0     # 播放速度倍率，1.0 表示原速；输出帧率 = 原帧率 × 该值，
                                             # 音频用 atempo 同步变速，音画同步不变；建议 0.95-1.05。
        self.hue_shift: int = 0              # 色相偏移（度），范围 -30 到 30；0 表示不偏移。
        self.zoom_factor: float = 1.0        # 轻微缩放因子，1.0 表示不缩放；>1 时先放大再居中裁回原尺寸。

        # 音频多样化（第 3 步新增，2026-11-12）
        self.audio_volume: float = 1.0       # 主音频音量倍率，1.0 表示原音量；建议 0.9-1.1。
        self.pitch_shift: float = 1.0        # 音调偏移倍率，1.0 表示原调；用 asetrate+aresample 实现，
                                             # 再用 atempo 把时长补回与速度一致；建议 0.98-1.02。

        # 背景模糊
        self.blur_background_enabled: bool = True           # 是否启用背景模糊
        self.top_blur_percentage: int = 3                   # 顶部模糊区域百分比，范围 0-100。
        self.bottom_blur_percentage: int = 3                # 底部模糊区域百分比，范围 0-100。
        self.side_blur_percentage: int = 3                  # 侧边模糊区域百分比，范围 0-100。

        # 高斯模糊
        self.gaussian_blur_interval: int = 15               # 高斯模糊帧步长，0 表示禁用。
        self.gaussian_blur_kernel_size: int = 3             # 高斯模糊核大小，必须为正奇数（如 1, 3, 5）。
        self.gaussian_blur_area_percentage: int = 15        # 高斯模糊区域大小百分比，范围 0-100。

        # 帧交换
        self.enable_frame_swap: bool = True                 # 是否启用帧交换
        self.frame_swap_interval: int = 15                  # 帧交换步长。建议值 5-20，每隔指定步长交换帧，增加动态效果。

        # 颜色偏移
        self.enable_color_shift: bool = True                # 是否启用颜色偏移
        self.color_shift_range: int = 3                     # 颜色偏移区间，3代表[-3,3]，该值越大颜色差距越明显

        # 高级效果
        self.scramble_frequency: float = 0.0                # 频域扰乱参数，0.0表示禁用，范围0.0-1.0，开启后处理时间较长。
        self.enable_texture_noise: bool = False             # 是否启用纹理噪声
        self.texture_noise_strength: float = 0.5            # 纹理噪声强度，范围 0-1，默认 0.5
        self.enable_blur_edge: bool = True                  # 是否启用边缘模糊

    # 每视频随机参数的取值范围（2026-11-12，针对“固定参数易判重”）。
    # 全部落在 validate() 允许的范围内，且不超出各参数注释里的建议区间，
    # 画质风险可控：旋转 ±6°、裁剪 5–20%、饱和度/对比度 ±15%、亮度 ±0.15。
    # 镜像（flip_horizontal）和频域扰乱（scramble_frequency）只按概率开启，
    # 前者会左右翻转画面内文字，后者处理时间较长，见 randomized() 的注释。
    @classmethod
    def randomized(cls, seed=None):
        """返回一套按种子随机抽取的参数。

        同一种子 → 同一套参数（可复现）；不同种子 → 参数组合不同。
        不传 seed 时用系统熵，每次运行都不同。默认值 VideoConfig() 不变，
        仍是固定参数，供 --no-randomize 与旧调用方式使用。
        """
        rng = random.Random(seed)
        config = cls()
        config.random_seed = seed
        config.rotation_angle = rng.randint(-6, 6)
        config.crop_percentage = round(rng.uniform(0.05, 0.20), 3)
        config.saturation = round(rng.uniform(0.90, 1.15), 3)
        config.brightness = round(rng.uniform(-0.10, 0.15), 3)
        config.contrast = round(rng.uniform(0.90, 1.15), 3)
        config.frame_swap_interval = rng.choice([5, 8, 10, 12, 15, 20])
        config.gaussian_blur_interval = rng.choice([0, 10, 15, 20])
        config.gaussian_blur_kernel_size = rng.choice([3, 5])
        config.gaussian_blur_area_percentage = rng.randint(10, 20)
        config.watermark_opacity = round(rng.uniform(0.04, 0.10), 3)
        config.background_music_volume = round(rng.uniform(0.05, 0.15), 3)
        # 25% 概率镜像：对指纹扰动大，但会翻转画面内原有文字，默认不开满。
        config.flip_horizontal = rng.random() < 0.25
        config.fade_in_frames = rng.randint(5, 15)
        config.fade_out_frames = rng.randint(10, 30)
        config.color_shift_range = rng.randint(2, 5)
        config.enable_texture_noise = rng.random() < 0.30
        config.texture_noise_strength = round(rng.uniform(0.3, 0.7), 2)
        # 20% 概率开频域扰乱：0.05–0.20 的轻扰动，处理时间明显变长。
        config.scramble_frequency = (
            round(rng.uniform(0.05, 0.20), 2) if rng.random() < 0.20 else 0.0
        )
        config.hzh_opacity = round(rng.uniform(0.05, 0.15), 3)
        config.hzh_scale = round(rng.uniform(0.8, 1.0), 2)
        config.top_blur_percentage = rng.randint(2, 5)
        config.bottom_blur_percentage = rng.randint(2, 5)
        config.side_blur_percentage = rng.randint(2, 5)
        # 第 2 步：播放速度、色相、缩放。速度只在 ±5% 内浮动，避免可感知的
        # 快慢与口型错位；色相 ±10°、缩放 1.02–1.08，都是肉眼几乎看不出、
        # 但逐像素指纹会变的量。
        config.playback_speed = round(rng.uniform(0.95, 1.05), 3)
        config.hue_shift = rng.randint(-10, 10)
        config.zoom_factor = round(rng.uniform(1.02, 1.08), 3)
        # 第 3 步：主音频音量 ±10%、音调 ±2%。音调很敏感，只敢小幅浮动。
        config.audio_volume = round(rng.uniform(0.90, 1.10), 3)
        config.pitch_shift = round(rng.uniform(0.98, 1.02), 3)
        return config

    @classmethod
    def randomized_for(cls, input_path: str):
        """按输入视频文件名派生种子，再随机抽取一套参数。

        只用文件名（basename）做种子：同一视频重跑、改名后重跑结果不同，
        但同一文件名在不同目录下得到同一套参数，便于复现与排障。
        """
        digest = hashlib.sha256(
            os.path.basename(input_path).encode("utf-8")
        ).digest()
        seed = int.from_bytes(digest[:8], "big")
        return cls.randomized(seed)

    def validate(self):
        """
        验证配置参数的有效性，确保所有参数和文件路径合法。
        """
        # GPU 加速
        if not isinstance(self.enable_gpu, bool):
            raise ValueError("enable_gpu 必须是布尔值")

        # 字幕参数
        if not isinstance(self.include_subtitles, bool):
            raise ValueError("include_subtitles 必须是布尔值")
        if not 0 <= self.subtitles_opacity <= 1:
            raise ValueError("subtitles_opacity 必须在 0 到 1 之间")
        if not isinstance(self.use_whisper, bool):
            raise ValueError("use_whisper 必须是布尔值")
        if not isinstance(self.whisper_model_name, str):
            raise ValueError("whisper_model_name 必须是字符串")
        if not isinstance(self.subtitles_file, str):
            raise ValueError("subtitles_file 必须是字符串")
        if not isinstance(self.subtitles_duration, (int, float)) or self.subtitles_duration < 0:
            raise ValueError("subtitles_duration 必须是非负数")
        if not self.is_valid_color(self.subtitles_color):
            raise ValueError("subtitles_color 必须是有效的颜色")

        # 标题参数
        if not isinstance(self.include_titles, bool):
            raise ValueError("include_titles 必须是布尔值")
        if not 0 <= self.titles_opacity <= 1:
            raise ValueError("titles_opacity 必须在 0 到 1 之间")
        if not isinstance(self.top_title, str):
            raise ValueError("top_title 必须是字符串")
        if not 0 <= self.top_title_margin <= 100:
            raise ValueError("top_title_margin 必须在 0 到 100 之间")
        if not isinstance(self.bottom_title, str):
            raise ValueError("bottom_title 必须是字符串")
        if not 0 <= self.bottom_title_margin <= 100:
            raise ValueError("bottom_title_margin 必须在 0 到 100 之间")
        if not self.is_valid_color(self.titles_color):
            raise ValueError("titles_color 必须是有效的颜色")

        # 水印参数
        if not isinstance(self.include_watermark, bool):
            raise ValueError("include_watermark 必须是布尔值")
        if not 0 <= self.watermark_opacity <= 1:
            raise ValueError("watermark_opacity 必须在 0 到 1 之间")
        if self.watermark_type not in ['text', 'image', 'video']:
            raise ValueError("watermark_type 必须是 'text', 'image' 或 'video'")
        if not self.is_valid_color(self.watermark_color):
            raise ValueError("watermark_color 必须是有效的颜色")
        if self.watermark_type == 'image' and not os.path.exists(self.watermark_image_path):
            raise FileNotFoundError(f"图片水印文件 {self.watermark_image_path} 不存在")
        if self.watermark_type == 'video' and not os.path.exists(self.watermark_video_path):
            raise FileNotFoundError(f"视频水印文件 {self.watermark_video_path} 不存在")

        # 字体
        if not isinstance(self.custom_font_enabled, bool):
            raise ValueError("custom_font_enabled 必须是布尔值")
        if self.custom_font_enabled and not os.path.exists(self.font_file):
            raise FileNotFoundError(f"字体文件 {self.font_file} 不存在")

        # 文字外边框
        if not isinstance(self.text_border_size, int) or self.text_border_size < 0:
            raise ValueError("text_border_size 必须是非负整数")

        # 音频参数
        if not isinstance(self.enable_silence_check, bool):
            raise ValueError("enable_silence_check 必须是布尔值")
        if not isinstance(self.silence_threshold, (int, float)):
            raise ValueError("silence_threshold 必须是数字")
        if not 0 <= self.silence_retention_ratio <= 1:
            raise ValueError("silence_retention_ratio 必须在 0 到 1 之间")
        if not isinstance(self.silent_duration, int) or self.silent_duration < 0:
            raise ValueError("silent_duration 必须是非负整数")

        # 背景音乐
        if not isinstance(self.include_background_music, bool):
            raise ValueError("include_background_music 必须是布尔值")
        if self.include_background_music and not os.path.exists(self.background_music_file):
            raise FileNotFoundError(f"背景音乐文件 {self.background_music_file} 不存在")
        if not 0 <= self.background_music_volume <= 1:
            raise ValueError("background_music_volume 必须在 0 到 1 之间")

        # 视频镜像与旋转
        if not isinstance(self.flip_horizontal, bool):
            raise ValueError("flip_horizontal 必须是布尔值")
        if not isinstance(self.rotation_angle, (int, float)):
            raise ValueError("rotation_angle 必须是数字")

        # 视频裁剪
        if not 0 <= self.crop_percentage <= 0.5:
            raise ValueError("crop_percentage 必须在 0 到 0.5 之间")

        # 淡入淡出
        if not isinstance(self.fade_in_frames, int) or self.fade_in_frames < 0:
            raise ValueError("fade_in_frames 必须是非负整数")
        if not isinstance(self.fade_out_frames, int) or self.fade_out_frames < 0:
            raise ValueError("fade_out_frames 必须是非负整数")

        # 画中画
        if not isinstance(self.include_hzh, bool):
            raise ValueError("include_hzh 必须是布尔值")
        if not 0 <= self.hzh_opacity <= 1:
            raise ValueError("hzh_opacity 必须在 0 到 1 之间")
        if not 0 < self.hzh_scale <= 1:
            raise ValueError("hzh_scale 必须在 0 到 1 之间")
        if self.include_hzh and not os.path.exists(self.hzh_video_file):
            raise FileNotFoundError(f"画中画视频文件 {self.hzh_video_file} 不存在")

        # 颜色调整
        if not isinstance(self.enable_sbc, bool):
            raise ValueError("enable_sbc 必须是布尔值")
        if self.saturation < 0:
            raise ValueError("saturation 必须是非负数")
        if self.brightness < -1 or self.brightness > 1:
            raise ValueError("brightness 必须在 -1 到 1 之间")
        if self.contrast < 0:
            raise ValueError("contrast 必须是非负数")

        # 播放速度与色相、缩放（第 2 步新增）
        if not isinstance(self.playback_speed, (int, float)) or not 0.5 <= self.playback_speed <= 2.0:
            raise ValueError("playback_speed 必须在 0.5 到 2.0 之间")
        if not isinstance(self.hue_shift, (int, float)) or not -30 <= self.hue_shift <= 30:
            raise ValueError("hue_shift 必须在 -30 到 30 之间")
        if not isinstance(self.zoom_factor, (int, float)) or not 1.0 <= self.zoom_factor <= 1.5:
            raise ValueError("zoom_factor 必须在 1.0 到 1.5 之间")

        # 音频多样化（第 3 步新增）
        if not isinstance(self.audio_volume, (int, float)) or not 0 <= self.audio_volume <= 2.0:
            raise ValueError("audio_volume 必须在 0 到 2.0 之间")
        if not isinstance(self.pitch_shift, (int, float)) or not 0.5 <= self.pitch_shift <= 2.0:
            raise ValueError("pitch_shift 必须在 0.5 到 2.0 之间")

        # 背景模糊
        if not isinstance(self.blur_background_enabled, bool):
            raise ValueError("blur_background_enabled 必须是布尔值")
        if not 0 <= self.top_blur_percentage <= 100:
            raise ValueError("top_blur_percentage 必须在 0 到 100 之间")
        if not 0 <= self.bottom_blur_percentage <= 100:
            raise ValueError("bottom_blur_percentage 必须在 0 到 100 之间")
        if not 0 <= self.side_blur_percentage <= 100:
            raise ValueError("side_blur_percentage 必须在 0 到 100 之间")

        # 高斯模糊
        if not isinstance(self.gaussian_blur_interval, int) or self.gaussian_blur_interval < 0:
            raise ValueError("gaussian_blur_interval 必须是非负整数")
        if self.gaussian_blur_kernel_size < 1 or self.gaussian_blur_kernel_size % 2 == 0:
            raise ValueError("gaussian_blur_kernel_size 必须是正奇数")
        if not 0 <= self.gaussian_blur_area_percentage <= 100:
            raise ValueError("gaussian_blur_area_percentage 必须在 0 到 100 之间")

        # 帧交换
        if not isinstance(self.enable_frame_swap, bool):
            raise ValueError("enable_frame_swap 必须是布尔值")
        if not isinstance(self.frame_swap_interval, int) or self.frame_swap_interval < 1:
            raise ValueError("frame_swap_interval 必须是正整数")

        # 颜色偏移
        if not isinstance(self.enable_color_shift, bool):
            raise ValueError("enable_color_shift 必须是布尔值")
        if not isinstance(self.color_shift_range, int) or self.color_shift_range < 0:
            raise ValueError("color_shift_range 必须是非负整数")

        # 高级效果
        if not 0 <= self.scramble_frequency <= 1:
            raise ValueError("scramble_frequency 必须在 0 到 1 之间")
        if not isinstance(self.enable_texture_noise, bool):
            raise ValueError("enable_texture_noise 必须是布尔值")
        if not 0 <= self.texture_noise_strength <= 1:
            raise ValueError("texture_noise_strength 必须在 0 到 1 之间")
        if not isinstance(self.enable_blur_edge, bool):
            raise ValueError("enable_blur_edge 必须是布尔值")

        # 验证文件路径
        paths_to_check = [
            (self.background_music_file, "背景音乐文件"),
            (self.subtitles_file, "字幕文件"),
            (self.font_file, "字体文件"),
            (self.hzh_video_file if self.include_hzh else "", "画中画视频文件"),
            (self.watermark_image_path if self.watermark_type == 'image' else "", "图片水印文件"),
            (self.watermark_video_path if self.watermark_type == 'video' else "", "视频水印文件")
        ]
        for path, desc in paths_to_check:
            if path and not os.path.exists(path):
                raise FileNotFoundError(f"{desc} {path} 不存在")

    @staticmethod
    def is_valid_color(color_str: str) -> bool:
        """
        检查颜色字符串是否有效（支持颜色名称或 HEX 码）。

        参数:
            color_str: 颜色字符串，例如 'yellow' 或 '#FFFF00'

        返回:
            bool: True 表示颜色有效，False 表示无效
        """
        if color_str.startswith('#'):
            return bool(re.match(r'^#[0-9A-Fa-f]{6}$', color_str))
        valid_colors = ['yellow', 'red', 'green', 'blue', 'white', 'black']
        return color_str.lower() in valid_colors
