# -*- coding: utf-8 -*-
"""逐帧视觉特效（VideoEffects）：水印、字幕、标题、模糊、旋转、裁剪、
淡入淡出、画中画、颜色调整、帧内特效等。

拆分自 Dedup/dedup.py（第二批改进）。cv2 / numpy / Pillow 在模块级用
try/except 导入，缺失时为 None；只有真正处理视频帧时才会用到它们。"""

from __future__ import annotations

import logging
import os
import random
from typing import Tuple

try:
    import cv2
except ImportError:  # 未安装 opencv-python 时为 None，处理视频帧时再报错
    cv2 = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:  # 未安装 numpy 时为 None，处理视频帧时再报错
    np = None  # type: ignore[assignment]

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # 未安装 Pillow 时为 None，绘制水印 / 字幕时再报错
    Image = ImageDraw = ImageFont = None  # type: ignore[assignment]


class VideoEffects:
    """
    视频特效类，包含水印、字幕、模糊等效果的实现。
    """
    @staticmethod
    def add_watermark(frame: np.ndarray, config: VideoConfig, frame_idx: int, total_frames: int, handler: 'VideoHandler' = None) -> np.ndarray:
        """
        在视频帧上添加水印（支持文本、图片和视频水印）。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象
            frame_idx: 当前帧索引
            total_frames: 视频总帧数

        返回:
            np.ndarray: 添加水印后的帧
        """
        h, w = frame.shape[:2]
        
        if config.watermark_type == 'text' and config.watermark_text:
            # 保持原有文本水印逻辑不变
            font_size = max(10, min(h // 20, w // len(config.watermark_text)))
            font = ImageFont.truetype(config.font_file, font_size) if config.custom_font_enabled and os.path.exists(config.font_file) else ImageFont.load_default()
            pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            draw = ImageDraw.Draw(pil_img)
            text_bbox = draw.textbbox((0, 0), config.watermark_text, font=font)
            text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            x, y = VideoEffects.get_watermark_position(config.watermark_direction, frame_idx, total_frames, w, h, text_width, text_height)
            x, y = max(0, min(x, w - text_width)), max(0, min(y, h - text_height))
            color = VideoEffects.parse_color(config.watermark_color)
            border_size = config.text_border_size
            opacity = config.watermark_opacity
            
            if opacity < 1.0:
                watermark_img = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
                watermark_draw = ImageDraw.Draw(watermark_img)
                border_color = (0, 0, 0, int(255 * opacity))
                for dx in range(-border_size, border_size + 1):
                    for dy in range(-border_size, border_size + 1):
                        if dx != 0 or dy != 0:
                            watermark_draw.text((x + dx, y + dy), config.watermark_text, font=font, fill=border_color)
                text_color = (*color, int(255 * opacity))
                watermark_draw.text((x, y), config.watermark_text, font=font, fill=text_color)
                pil_img = Image.alpha_composite(pil_img.convert('RGBA'), watermark_img).convert('RGB')
            else:
                for dx in range(-border_size, border_size + 1):
                    for dy in range(-border_size, border_size + 1):
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, y + dy), config.watermark_text, font=font, fill=(0, 0, 0))
                draw.text((x, y), config.watermark_text, font=font, fill=color)
            return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        
        elif config.watermark_type == 'image' and config.watermark_image_path and handler and handler.wm_rgb is not None:
            wm_width, wm_height = handler.watermark_img.size
            x, y = VideoEffects.get_watermark_position(config.watermark_direction, frame_idx, total_frames, w, h, wm_width, wm_height)
            if x + wm_width > w or y + wm_height > h or x < 0 or y < 0:
                return frame
            roi = frame[y:y+wm_height, x:x+wm_width]
            for c in range(3):
                roi[:, :, c] = (1 - handler.wm_alpha) * roi[:, :, c] + handler.wm_alpha * handler.wm_rgb[:, :, c]
            frame[y:y+wm_height, x:x+wm_width] = roi
        
        elif config.watermark_type == 'video' and config.watermark_video_path:
            # 视频水印（未来扩展）
            # 这里仅提供占位逻辑，实际实现需要同步视频帧
            # 由于需要同步视频帧，复杂度较高，此处仅记录为待实现功能，可在未来通过在 VideoHandler 中加载水印视频帧并传递到此方法实现。
            logging.warning("视频水印功能尚未实现")
            pass
        
        return frame

    @staticmethod
    def parse_color(color_str: str) -> Tuple[int, int, int]:
        """将颜色字符串解析为 BGR 元组"""
        if color_str.startswith('#'):  # 支持 HEX 码
            r, g, b = tuple(int(color_str[i:i+2], 16) for i in (1, 3, 5))
            return (b, g, r)  # 返回 BGR
        colors = {
            'yellow': (0, 255, 255),  # BGR
            'red': (0, 0, 255),
            'green': (0, 255, 0),
            'blue': (255, 0, 0),
            'white': (255, 255, 255),
            'black': (0, 0, 0),
            'cyan': (255, 255, 0),
            'magenta': (255, 0, 255),
            'orange': (0, 165, 255),
            'purple': (128, 0, 128),
            'brown': (42, 42, 165),
            'gray': (128, 128, 128)
        }
        return colors.get(color_str.lower(), (255, 255, 255))  # 默认白色

    @staticmethod
    def get_watermark_position(direction: str, frame_index: int, total_frames: int,
                               video_width: int, video_height: int, watermark_width: int,
                               watermark_height: int) -> Tuple[int, int]:
        """
        计算动态水印的坐标位置，支持米字形8方向运动。

        参数:
            direction: 运动方向，支持以下模式：
                - 'left_to_right': 从左侧到右侧水平移动
                - 'right_to_left': 从右侧到左侧水平移动
                - 'top_to_bottom': 从顶部到底部垂直移动
                - 'bottom_to_top': 从底部到顶部垂直移动
                - 'lt_to_rb': 左上到右下对角线移动
                - 'rt_to_lb': 右上到左下对角线移动
                - 'lb_to_rt': 左下到右上对角线移动
                - 'rb_to_lt': 右下到左上对角线移动
            frame_index: 当前帧序号 (从0开始)
            total_frames: 视频总帧数
            video_width: 视频宽度 (像素)
            video_height: 视频高度 (像素)
            watermark_width: 水印宽度 (像素)
            watermark_height: 水印高度 (像素)

        返回:
            Tuple[int, int]: 水印的 x, y 坐标
        """
        MARGIN = 20  # 安全边距

        if direction == 'random':
            # 随机生成 x 和 y 坐标，确保在安全边距内
            x = random.randint(MARGIN, video_width - watermark_width - MARGIN)
            y = random.randint(MARGIN, video_height - watermark_height - MARGIN)
        else:
            progress = frame_index / total_frames
            
            # 计算可用移动范围
            range_x = video_width - watermark_width - 2 * MARGIN
            range_y = video_height - watermark_height - 2 * MARGIN
            
            if direction == 'left_to_right':
                x = MARGIN + int(range_x * progress)
                y = (video_height - watermark_height) // 2  # 垂直居中
            elif direction == 'right_to_left':
                x = video_width - MARGIN - watermark_width - int(range_x * progress)
                y = (video_height - watermark_height) // 2
            elif direction == 'top_to_bottom':
                x = (video_width - watermark_width) // 2    # 水平居中
                y = MARGIN + int(range_y * progress)
            elif direction == 'bottom_to_top':
                x = (video_width - watermark_width) // 2
                y = video_height - MARGIN - watermark_height - int(range_y * progress)
            elif direction == 'lt_to_rb':  # 左上→右下
                x = MARGIN + int(range_x * progress)
                y = MARGIN + int(range_y * progress)
            elif direction == 'rt_to_lb':  # 右上→左下
                x = video_width - MARGIN - watermark_width - int(range_x * progress)
                y = MARGIN + int(range_y * progress)
            elif direction == 'lb_to_rt':  # 左下→右上
                x = MARGIN + int(range_x * progress)
                y = video_height - MARGIN - watermark_height - int(range_y * progress)
            elif direction == 'rb_to_lt':  # 右下→左上
                x = video_width - MARGIN - watermark_width - int(range_x * progress)
                y = video_height - MARGIN - watermark_height - int(range_y * progress)
            else:  # 默认居中显示
                x = (video_width - watermark_width) // 2
                y = (video_height - watermark_height) // 2

        return (x, y)

    @staticmethod
    def add_subtitles(frame: np.ndarray, config: VideoConfig, frame_idx: int, 
                    fps: float, subs: pysrt.SubRipFile) -> np.ndarray:
        """
        在视频帧上添加字幕。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象
            frame_idx: 当前帧索引
            fps: 视频帧率
            subs: 字幕文件对象

        返回:
            np.ndarray: 添加字幕后的帧
        """
        if not config.subtitles_file or not os.path.exists(config.subtitles_file) or not subs:
            return frame
        current_time = frame_idx / fps
        def time_to_seconds(time_obj):
            return (time_obj.hours * 3600 + time_obj.minutes * 60 + 
                    time_obj.seconds + time_obj.milliseconds / 1000.0)
        for sub in subs:
            start_time = time_to_seconds(sub.start)
            end_time = time_to_seconds(sub.end)
            if start_time <= current_time <= end_time:
                pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(pil_img)
                font = ImageFont.truetype(config.font_file, 30) if config.custom_font_enabled and os.path.exists(config.font_file) else ImageFont.load_default()
                text_bbox = draw.textbbox((0, 0), sub.text, font=font)
                text_width = text_bbox[2] - text_bbox[0]
                text_height = text_bbox[3] - text_bbox[1]
                x = (frame.shape[1] - text_width) // 2
                y = frame.shape[0] - text_height - 20
                color = VideoEffects.parse_color(config.subtitles_color)
                border_size = config.text_border_size
                opacity = config.subtitles_opacity
                if opacity < 1.0:
                    # 创建透明的字幕层
                    subtitle_img = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
                    subtitle_draw = ImageDraw.Draw(subtitle_img)
                    # 绘制外边框，透明度一致
                    border_color = (0, 0, 0, int(255 * opacity))
                    for dx in range(-border_size, border_size + 1):
                        for dy in range(-border_size, border_size + 1):
                            if dx != 0 or dy != 0:
                                subtitle_draw.text((x + dx, y + dy), sub.text, font=font, fill=border_color)
                    # 绘制文字，透明度一致
                    text_color = (*color, int(255 * opacity))
                    subtitle_draw.text((x, y), sub.text, font=font, fill=text_color)
                    # 合成图像
                    pil_img = Image.alpha_composite(pil_img.convert('RGBA'), subtitle_img).convert('RGB')
                else:
                    # 无透明度，直接绘制
                    for dx in range(-border_size, border_size + 1):
                        for dy in range(-border_size, border_size + 1):
                            if dx != 0 or dy != 0:
                                draw.text((x + dx, y + dy), sub.text, font=font, fill=(0, 0, 0))
                    draw.text((x, y), sub.text, font=font, fill=color)
                return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        return frame

    @staticmethod
    def add_titles(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        在视频帧上添加顶部和底部标题。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 添加标题后的帧
        """
        pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_img)
        font = ImageFont.truetype(config.font_file, 30) if config.custom_font_enabled and os.path.exists(config.font_file) else ImageFont.load_default()
        color = VideoEffects.parse_color(config.titles_color)
        border_size = config.text_border_size
        opacity = config.titles_opacity

        if config.top_title:
            text_bbox = draw.textbbox((0, 0), config.top_title, font=font)
            text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            x = (frame.shape[1] - text_width) // 2
            y = int(frame.shape[0] * config.top_title_margin / 100)
            if opacity < 1.0:
                # 创建透明的标题层
                title_img = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
                title_draw = ImageDraw.Draw(title_img)
                # 绘制外边框，透明度一致
                border_color = (0, 0, 0, int(255 * opacity))
                for dx in range(-border_size, border_size + 1):
                    for dy in range(-border_size, border_size + 1):
                        if dx != 0 or dy != 0:
                            title_draw.text((x + dx, y + dy), config.top_title, font=font, fill=border_color)
                # 绘制文字，透明度一致
                text_color = (*color, int(255 * opacity))
                title_draw.text((x, y), config.top_title, font=font, fill=text_color)
                # 合成图像
                pil_img = Image.alpha_composite(pil_img.convert('RGBA'), title_img).convert('RGB')
            else:
                # 无透明度，直接绘制
                for dx in range(-border_size, border_size + 1):
                    for dy in range(-border_size, border_size + 1):
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, y + dy), config.top_title, font=font, fill=(0, 0, 0))
                draw.text((x, y), config.top_title, font=font, fill=color)

        if config.bottom_title:
            text_bbox = draw.textbbox((0, 0), config.bottom_title, font=font)
            text_width, text_height = text_bbox[2] - text_bbox[0], text_bbox[3] - text_bbox[1]
            x = (frame.shape[1] - text_width) // 2
            y = frame.shape[0] - text_height - int(frame.shape[0] * config.bottom_title_margin / 100)
            if opacity < 1.0:
                # 创建透明的标题层
                title_img = Image.new('RGBA', pil_img.size, (0, 0, 0, 0))
                title_draw = ImageDraw.Draw(title_img)
                # 绘制外边框，透明度一致
                border_color = (0, 0, 0, int(255 * opacity))
                for dx in range(-border_size, border_size + 1):
                    for dy in range(-border_size, border_size + 1):
                        if dx != 0 or dy != 0:
                            title_draw.text((x + dx, y + dy), config.bottom_title, font=font, fill=border_color)
                # 绘制文字，透明度一致
                text_color = (*color, int(255 * opacity))
                title_draw.text((x, y), config.bottom_title, font=font, fill=text_color)
                # 合成图像
                pil_img = Image.alpha_composite(pil_img.convert('RGBA'), title_img).convert('RGB')
            else:
                # 无透明度，直接绘制
                for dx in range(-border_size, border_size + 1):
                    for dy in range(-border_size, border_size + 1):
                        if dx != 0 or dy != 0:
                            draw.text((x + dx, y + dy), config.bottom_title, font=font, fill=(0, 0, 0))
                draw.text((x, y), config.bottom_title, font=font, fill=color)

        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    @staticmethod
    def apply_gaussian_blur(frame: np.ndarray, config: VideoConfig, frame_idx: int) -> np.ndarray:
        """
        在指定帧上应用高斯模糊效果。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象
            frame_idx: 当前帧索引

        返回:
            np.ndarray: 应用高斯模糊后的帧
        """
        if config.gaussian_blur_interval == 0 or frame_idx % config.gaussian_blur_interval != 0:
            return frame
        kernel = config.gaussian_blur_kernel_size if config.gaussian_blur_kernel_size % 2 == 1 else config.gaussian_blur_kernel_size + 1
        area_size = config.gaussian_blur_area_percentage / 100
        h, w = frame.shape[:2]
        blur_h = int(h * area_size)
        blur_w = int(w * area_size)
        # 只模糊指定区域，避免重复处理整个帧
        frame[0:blur_h, :] = cv2.GaussianBlur(frame[0:blur_h, :], (kernel, kernel), 0)
        frame[h-blur_h:h, :] = cv2.GaussianBlur(frame[h-blur_h:h, :], (kernel, kernel), 0)
        frame[:, 0:blur_w] = cv2.GaussianBlur(frame[:, 0:blur_w], (kernel, kernel), 0)
        frame[:, w-blur_w:w] = cv2.GaussianBlur(frame[:, w-blur_w:w], (kernel, kernel), 0)
        return frame

    @staticmethod
    def rotate_frame(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        旋转视频帧。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 旋转后的帧
        """
        if config.rotation_angle != 0:
            h, w = frame.shape[:2]
            center = (w // 2, h // 2)
            matrix = cv2.getRotationMatrix2D(center, config.rotation_angle, 1.0)
            frame = cv2.warpAffine(frame, matrix, (w, h))
        return frame

    @staticmethod
    def adjust_sbc(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        调整视频帧的饱和度、亮度和对比度。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 调整后的帧
        """
        if config.enable_sbc:
            frame = cv2.convertScaleAbs(frame, alpha=config.contrast, beta=config.brightness * 255)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hsv[:, :, 1] = np.clip(hsv[:, :, 1] * config.saturation, 0, 255)
            frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        return frame

    @staticmethod
    def apply_hue_shift(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        对视频帧应用色相偏移（第 2 步新增）。

        链路里走到这里时帧是 RGB，先转 HSV，把 H 通道整体平移再转回来。
        OpenCV 的 H 通道是 0-179（对应 0-360°），所以 1° = 0.5 个单位。
        hue_shift 为 0 时原样返回。

        参数:
            frame: 当前视频帧（RGB）
            config: 视频处理配置对象

        返回:
            np.ndarray: 应用色相偏移后的帧
        """
        if not config.hue_shift:
            return frame
        delta = int(round(config.hue_shift / 2))
        if delta == 0:
            return frame
        hsv = cv2.cvtColor(frame, cv2.COLOR_RGB2HSV)
        hsv[:, :, 0] = (hsv[:, :, 0].astype(np.int16) + delta) % 180
        return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)

    @staticmethod
    def apply_zoom(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        对视频帧应用轻微缩放（第 2 步新增）。

        先把帧放大 zoom_factor 倍，再居中裁回原尺寸：画面内容整体
        外扩一圈，每像素的位置都变了，但构图几乎看不出差别。
        zoom_factor <= 1.0 时原样返回。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 应用缩放后的帧（尺寸与输入相同）
        """
        if not config.zoom_factor or config.zoom_factor <= 1.0:
            return frame
        h, w = frame.shape[:2]
        new_h, new_w = int(h * config.zoom_factor), int(w * config.zoom_factor)
        if new_h <= h or new_w <= w:
            return frame
        enlarged = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        top = (new_h - h) // 2
        left = (new_w - w) // 2
        return enlarged[top:top + h, left:left + w].copy()

    @staticmethod
    def blur_background(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        对视频帧的背景应用模糊效果。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 应用背景模糊后的帧
        """
        if not config.blur_background_enabled:
            return frame
        h, w = frame.shape[:2]
        top = int(h * config.top_blur_percentage / 100)
        bottom = int(h * config.bottom_blur_percentage / 100)
        side = int(w * config.side_blur_percentage / 100)
        frame[:top, :] = cv2.GaussianBlur(frame[:top, :], (21, 21), 0)
        frame[-bottom:, :] = cv2.GaussianBlur(frame[-bottom:, :], (21, 21), 0)
        frame[:, :side] = cv2.GaussianBlur(frame[:, :side], (21, 21), 0)
        frame[:, -side:] = cv2.GaussianBlur(frame[:, -side:], (21, 21), 0)
        return frame

    @staticmethod
    def apply_fade_effect(frame: np.ndarray, config: VideoConfig, frame_idx: int, total_frames: int) -> np.ndarray:
        """
        在单帧级别应用淡入淡出效果。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象
            frame_idx: 当前帧索引
            total_frames: 视频总帧数

        返回:
            np.ndarray: 应用淡入淡出效果后的帧
        """
        if frame_idx < config.fade_in_frames:
            alpha = frame_idx / config.fade_in_frames
            frame = cv2.addWeighted(frame, alpha, np.zeros_like(frame), 1 - alpha, 0)
        elif frame_idx >= total_frames - config.fade_out_frames:
            alpha = (total_frames - frame_idx) / config.fade_out_frames
            frame = cv2.addWeighted(frame, alpha, np.zeros_like(frame), 1 - alpha, 0)
        return frame

    @staticmethod
    def color_shift(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        对视频帧应用颜色偏移效果。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 应用颜色偏移后的帧
        """
        if config.enable_color_shift:
            b, g, r = cv2.split(frame)
            shift = random.randint(-config.color_shift_range, config.color_shift_range)
            b = b.astype(np.int16)
            g = g.astype(np.int16)
            b = np.clip(b + shift, 0, 255).astype(np.uint8)
            g = np.clip(g - shift, 0, 255).astype(np.uint8)
            frame = cv2.merge((b, g, r))
        return frame

    @staticmethod
    def add_hzh_effect(frame: np.ndarray, config: VideoConfig, frame_idx: int, total_frames: int) -> np.ndarray:
        """
        在视频帧上添加画中画效果。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象
            frame_idx: 当前帧索引
            total_frames: 视频总帧数

        返回:
            np.ndarray: 添加画中画效果后的帧
        """
        if not config.include_hzh or not os.path.exists(config.hzh_video_file):
            return frame
        cap = cv2.VideoCapture(config.hzh_video_file)
        hzh_frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        hzh_idx = frame_idx % hzh_frame_count
        cap.set(cv2.CAP_PROP_POS_FRAMES, hzh_idx)
        ret, hzh_frame = cap.read()
        cap.release()
        if ret:
            h, w = frame.shape[:2]
            hzh_h, hzh_w = int(h * config.hzh_scale), int(w * config.hzh_scale)
            hzh_frame = cv2.resize(hzh_frame, (hzh_w, hzh_h))
            hzh_frame = cv2.cvtColor(hzh_frame, cv2.COLOR_BGR2RGB)  # 转换为 RGB
            # 计算居中位置
            x = (w - hzh_w) // 2
            y = (h - hzh_h) // 2
            # 检查画中画是否超出原视频尺寸
            if x < 0 or y < 0 or x + hzh_w > w or y + hzh_h > h:
                # 当尺寸超出时，直接覆盖整个画面
                frame = cv2.resize(hzh_frame, (w, h))
            else:
                # 正常情况下，使用透明度混合
                roi = frame[y:y+hzh_h, x:x+hzh_w]
                blended = cv2.addWeighted(roi, 1 - config.hzh_opacity, hzh_frame, config.hzh_opacity, 0)
                frame[y:y+hzh_h, x:x+hzh_w] = blended
        return frame

    @staticmethod
    def scramble_phase(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        在频域中对视频帧进行扰乱处理。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 应用频域扰乱后的帧
        """
        if not config.scramble_frequency:
            return frame
        # 将元组转换为列表，以便修改
        channels = list(cv2.split(frame))
        
        # 处理每个通道
        for i in range(len(channels)):
            # 傅里叶变换
            f = np.fft.fft2(channels[i])
            fshift = np.fft.fftshift(f)
            # 获取幅度和相位
            magnitude = np.abs(fshift)
            phase = np.angle(fshift)
            # 扰动相位
            phase += np.random.uniform(-config.scramble_frequency, config.scramble_frequency, phase.shape)
            # 重构频域信号
            fshift_new = magnitude * np.exp(1j * phase)
            f_ishift = np.fft.ifftshift(fshift_new)
            # 逆傅里叶变换并更新通道
            img_back = np.fft.ifft2(f_ishift)
            channels[i] = np.abs(img_back).astype(np.uint8)
        # 合并处理后的通道
        return cv2.merge(channels)
    
    @staticmethod
    def add_texture_noise(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        为视频帧添加纹理噪声。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 添加纹理噪声后的帧
        """
        if not config.enable_texture_noise:
            return frame
        # 生成高斯噪声并乘以强度系数
        noise = np.random.normal(0, 1, frame.shape).astype(np.float32) * config.texture_noise_strength
        # 限制噪声范围并转换为整数
        noise = np.clip(noise, -255, 255).astype(np.int16)
        # 将帧转换为 int16 类型以避免溢出
        frame = frame.astype(np.int16)
        frame += noise
        # 裁剪回 uint8 范围
        frame = np.clip(frame, 0, 255).astype(np.uint8)
        return frame

    @staticmethod
    def apply_edge_blur(frame: np.ndarray, config: VideoConfig) -> np.ndarray:
        """
        对视频帧的边缘应用模糊效果。

        参数:
            frame: 当前视频帧
            config: 视频处理配置对象

        返回:
            np.ndarray: 应用边缘模糊后的帧
        """
        if not config.enable_blur_edge:
            return frame
        edges = cv2.Canny(frame, 100, 200)
        blurred = cv2.GaussianBlur(edges, (21, 21), 0)
        return cv2.addWeighted(frame, 0.9, cv2.cvtColor(blurred, cv2.COLOR_GRAY2BGR), 0.1, 0)
