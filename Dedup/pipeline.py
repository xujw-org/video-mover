# -*- coding: utf-8 -*-
"""视频处理编排（VideoHandler）：协调音频、视频与字幕的处理流程。

拆分自 Dedup/dedup.py（第二批改进）。本模块负责流程编排：分离音视频、
生成 / 加载字幕、处理音频、按帧交换顺序生成帧、分批并行处理单帧、
再把处理后的帧写回输出视频。具体的配置、FFmpeg、音频、字幕与逐帧
特效分别在 config / ffmpeg_utils / audio / subtitles / filters 模块里。

重依赖（cv2 / ffmpeg / pysrt / numpy / Pillow）在模块级用 try/except
导入，缺失时为 None；只有真正处理视频时才会用到它们。"""

from __future__ import annotations

import logging
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Generator, List, Tuple

try:
    import cv2
except ImportError:  # 未安装 opencv-python 时为 None，处理视频时再报错
    cv2 = None  # type: ignore[assignment]

try:
    import ffmpeg
except ImportError:  # 未安装 ffmpeg-python 时为 None，处理视频时再报错
    ffmpeg = None  # type: ignore[assignment]

try:
    import pysrt
except ImportError:  # 未安装 pysrt 时为 None，加载字幕文件时再报错
    pysrt = None  # type: ignore[assignment]

try:
    import numpy as np
except ImportError:  # 未安装 numpy 时为 None，处理视频时再报错
    np = None  # type: ignore[assignment]

try:
    from PIL import Image
except ImportError:  # 未安装 Pillow 时为 None，预加载图片水印时再报错
    Image = None  # type: ignore[assignment]

try:
    from .audio import AudioHandler
    from .config import VideoConfig
    from .ffmpeg_utils import FFmpegHandler
    from .filters import VideoEffects
    from .subtitles import SubtitleHandler
except ImportError:  # 作为顶层模块直接导入时（见 Dedup/dedup.py 垫片的回退路径）
    from audio import AudioHandler
    from config import VideoConfig
    from ffmpeg_utils import FFmpegHandler
    from filters import VideoEffects
    from subtitles import SubtitleHandler


class VideoHandler:
    """
    视频处理主类，协调音频和视频的处理流程。
    """
    def __init__(self, config: VideoConfig):
        """
        初始化视频处理器，验证配置。

        参数:
            config: 视频处理配置对象
        """
        self.config = config
        self.config.validate()
        self.subs = None        # 字幕对象，延迟到 process_video 中加载
        self.batch_size = min(100, max(10, os.cpu_count() * 10))  # 动态调整

        # 预加载图片水印
        self.watermark_img = None
        self.wm_rgb = None
        self.wm_alpha = None
        if config.watermark_type == 'image' and config.watermark_image_path:
            self.watermark_img = Image.open(config.watermark_image_path).convert("RGBA")

    def process_video(self, input_path: str, output_path: str) -> None:
        """
        处理整个视频，包括音频和视频的处理，并将结果保存。

        参数:
            input_path: 输入视频文件路径
            output_path: 输出视频文件路径
        """
        if not os.path.exists(input_path):
            raise FileNotFoundError(f"输入视频 {input_path} 不存在")
        
        # 检查并启用 GPU 加速
        if self.config.enable_gpu:
            try:
                cv2.ocl.setUseOpenCL(True)
                logging.info("GPU 加速已启用")
            except Exception as e:
                logging.warning(f"启用 GPU 加速失败: {str(e)}")
        
        video_stream, audio_stream = FFmpegHandler.split_av_streams(input_path)
        width, height, fps = FFmpegHandler.get_video_properties(input_path)
        cap = cv2.VideoCapture(input_path)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        # 按分辨率限制批大小：4K 单帧就 25MB，按 CPU 数×10 算成 100 帧 =
        # 2.5GB 常驻（再加上处理后的副本），很容易把内存吃满。给每批一个
        # 256MB 的预算，4K 下大约 10 帧一批。
        frame_bytes = max(width * height * 3, 1)
        self.batch_size = max(4, min(self.batch_size, (256 * 1024 * 1024) // frame_bytes))
        temp_files = []
        subtitles_file = None

        try:
            # 预处理图片水印大小
            if self.config.watermark_type == 'image' and self.watermark_img:
                wm_width = width // 5
                wm_height = int(wm_width * self.watermark_img.height / self.watermark_img.width)
                self.watermark_img = self.watermark_img.resize((wm_width, wm_height), Image.Resampling.LANCZOS)
                wm_array = np.array(self.watermark_img)
                self.wm_rgb = cv2.cvtColor(wm_array[:, :, :3], cv2.COLOR_RGB2BGR)
                self.wm_alpha = wm_array[:, :, 3] / 255.0 * self.config.watermark_opacity
            # 获取视频时长并根据 subtitles_duration 决定是否加载字幕
            probe = ffmpeg.probe(input_path)
            duration = float(probe['format']['duration'])
            # 音频采样率：变调（asetrate）需要它，拿不到就跳过变调只变速。
            audio_sample_rate = None
            audio_info = next(
                (s for s in probe.get('streams', [])
                 if s.get('codec_type') == 'audio'), None)
            if audio_info and audio_info.get('sample_rate'):
                try:
                    audio_sample_rate = int(audio_info['sample_rate'])
                except (TypeError, ValueError):
                    audio_sample_rate = None
            if self.config.include_subtitles and duration > self.config.subtitles_duration:
                if self.config.use_whisper:
                    subtitles_file = SubtitleHandler.generate_subtitles(input_path, self.config.whisper_model_name)
                    temp_files.append(subtitles_file)
                    logging.info(f"使用 Whisper 生成字幕: {subtitles_file}")
                else:
                    subtitles_file = self.config.subtitles_file
                
                if subtitles_file and os.path.exists(subtitles_file):
                    self.subs = pysrt.open(subtitles_file)
                    logging.info(f"字幕文件已加载: {subtitles_file}")
                else:
                    logging.warning(f"字幕文件 {subtitles_file} 不存在，跳过字幕加载")
                    self.subs = None
            else:
                logging.info(f"不添加字幕：include_subtitles={self.config.include_subtitles}, duration={duration}, subtitles_duration={self.config.subtitles_duration}")
                self.subs = None

            # 处理音频
            audio_path = tempfile.mktemp(suffix='.wav')
            temp_files.append(audio_path)
            if audio_stream:
                audio_stream.output(audio_path, format='wav').run(overwrite_output=True)
                processed_audio_path = AudioHandler.remove_silence(audio_path, self.config)
                temp_files.append(processed_audio_path)
                if self.config.include_background_music and self.config.background_music_file and os.path.exists(self.config.background_music_file):
                    mixed_audio_path = AudioHandler.mix_bgm(processed_audio_path, self.config.background_music_file, self.config.background_music_volume)
                    temp_files.append(mixed_audio_path)
                    audio_stream = ffmpeg.input(mixed_audio_path)
                else:
                    audio_stream = ffmpeg.input(processed_audio_path)

            # 第 3 步：音频多样化（音量 / 变调 / 变速），见 _apply_audio_effects。
            # 无音频流时原样返回 None；变速后音频时长与视频新时长一致。
            audio_stream = self._apply_audio_effects(
                audio_stream, self.config, audio_sample_rate)

            # 定义帧交换生成器（流式，不 seek）
            #
            # 原实现是“对每个输出帧 cap.set(POS_FRAMES) 再 read”，在 HEVC 4K 上
            # 逐帧定位要 170 秒（8 秒的视频！），而且 seek 失败就直接 break，
            # 会造成输出视频被截断。这里改成顺序读 + 每块内交换前两帧，
            # 内存只用 1 帧，语义与 get_original_idx 一致。
            def swapped_frame_generator(cap, interval):
                out_idx = 0
                pending = None          # 当前块的第 0 帧，等第 1 帧来了再一起吐
                block_pos = 0           # 当前块内已处理的帧数
                for _in_idx, frame in self._frame_generator(cap):
                    if interval <= 1:
                        yield out_idx, frame
                        out_idx += 1
                        continue
                    if block_pos == 0:
                        pending = frame
                        block_pos = 1
                        continue
                    if block_pos == 1:
                        # 先输出第 1 帧，再输出第 0 帧（交换）
                        yield out_idx, frame
                        out_idx += 1
                        yield out_idx, pending
                        out_idx += 1
                        pending = None
                        block_pos = 2
                        continue
                    yield out_idx, frame
                    out_idx += 1
                    block_pos += 1
                    if block_pos >= interval:
                        block_pos = 0
                # 尾块只剩一帧时原样输出（没有可交换的对象）
                if pending is not None:
                    yield out_idx, pending

            # 根据 enable_frame_swap 选择帧生成器
            if self.config.enable_frame_swap:
                frame_generator = swapped_frame_generator(cap, self.config.frame_swap_interval)
            else:
                frame_generator = self._frame_generator(cap)

            # 分批处理视频帧
            # 第 2 步：播放速度。输出帧率 = 原帧率 × 速度，帧数不变，
            # 所以输出时长 = 原时长 / 速度；音频已用 atempo 同步变速，
            # 音画同步不变。字幕按原时间查（_process_frames 仍传原 fps），
            # 否则字幕会整体漂移；只有写帧时用新帧率。
            out_fps = fps * self.config.playback_speed
            processed_frame_generator = self._process_frames(frame_generator, total_frames, fps, height, width)
            self._write_frames(processed_frame_generator, output_path, width, height, out_fps, audio_stream)

        finally:
            cap.release()
            for temp_file in temp_files:
                if os.path.exists(temp_file):
                    os.remove(temp_file)

    @staticmethod
    def _apply_audio_effects(audio_stream, config: VideoConfig,
                             sample_rate=None):
        """第 3 步：给最终音频流加音量 / 变调 / 变速（ffmpeg 滤镜）。

        顺序与算术（保证时长只跟速度走、音调只跟 pitch 走）：
        1. volume：主音频音量倍率；
        2. asetrate(sr*pitch) + aresample(sr)：音调变 pitch 倍，
           时长变为原来的 1/pitch（需要采样率，拿不到就跳过变调）；
        3. atempo(speed/pitch)：把时长从 1/pitch 补到 1/speed，
           与视频新时长（原时长 / speed）一致，音调不受 atempo 影响。
        pitch 为 1.0 时第 2 步跳过，atempo 因子就是 speed。
        无音频流时返回 None；全部为默认值时返回原流，不加任何滤镜。
        """
        if audio_stream is None:
            return None
        stream = audio_stream
        if config.audio_volume != 1.0:
            stream = stream.filter('volume', config.audio_volume)
        pitch_applied = False
        if config.pitch_shift != 1.0 and sample_rate:
            new_rate = int(sample_rate * config.pitch_shift)
            # asetrate 同时改采样率和音调，接着 aresample 回原采样率；
            # 显式指定 soxr，重建误差比默认 swr 更小。
            stream = stream.filter('asetrate', new_rate)
            stream = stream.filter('aresample', int(sample_rate), resampler='soxr')
            pitch_applied = True
        tempo = config.playback_speed / config.pitch_shift if pitch_applied \
            else config.playback_speed
        if tempo != 1.0:
            stream = stream.filter('atempo', round(tempo, 4))
        # 抖音原声常常已经顶到 0dBFS，混 BGM / 变调 / 变速之后再进 AAC 很容易削顶，
        # 削顶听感上是“糊/撕裂”。留 1dB 余量，用限制器挡一下。
        stream = stream.filter('alimiter', limit=0.89)
        return stream

    def _frame_generator(self, cap: cv2.VideoCapture) -> Generator[Tuple[int, np.ndarray], None, None]:
        """
        生成器：逐帧读取视频帧。

        参数:
            cap: OpenCV 视频捕获对象

        返回:
            Generator[Tuple[int, np.ndarray], None, None]: 帧索引和帧数据的生成器
        """
        frame_idx = 0
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break
            yield frame_idx, frame
            frame_idx += 1

    def _process_frames(self, frame_generator: Generator[Tuple[int, np.ndarray], None, None], 
                        total_frames: int, fps: float, orig_height: int, orig_width: int) -> Generator[np.ndarray, None, None]:
        """
        分批处理视频帧，并返回处理后的帧生成器。

        参数:
            frame_generator: 原始帧生成器
            total_frames: 视频总帧数
            fps: 视频帧率
            orig_height: 原始视频高度
            orig_width: 原始视频宽度

        返回:
            Generator[np.ndarray, None, None]: 处理后的帧生成器
        """
        batch = []
        for frame_idx, frame in frame_generator:
            batch.append((frame_idx, frame))
            if len(batch) >= self.batch_size:
                processed_batch = self._process_batch(batch, total_frames, fps, orig_height, orig_width)
                for _, processed_frame in processed_batch:
                    yield processed_frame
                batch = []
        if batch:
            processed_batch = self._process_batch(batch, total_frames, fps, orig_height, orig_width)
            for _, processed_frame in processed_batch:
                yield processed_frame

    def _process_batch(self, batch: List[Tuple[int, np.ndarray]], total_frames: int, fps: float, 
                       orig_height: int, orig_width: int) -> List[Tuple[int, np.ndarray]]:
        """
        并行处理一批视频帧。

        参数:
            batch: 待处理的帧批次
            total_frames: 视频总帧数
            fps: 视频帧率
            orig_height: 原始视频高度
            orig_width: 原始视频宽度

        返回:
            List[Tuple[int, np.ndarray]]: 处理后的帧列表，按帧索引排序
        """
        with ThreadPoolExecutor(max_workers=min(4, os.cpu_count())) as executor:
            futures = [executor.submit(self._process_single_frame, frame, idx, self.config, fps, total_frames, orig_height, orig_width)
                       for idx, frame in batch]
            return sorted([f.result() for f in futures], key=lambda x: x[0])

    def _process_single_frame(self, frame: np.ndarray, frame_idx: int, config: VideoConfig, 
                          fps: float, total_frames: int, orig_height: int, orig_width: int) -> Tuple[int, np.ndarray]:
        """
        处理单个视频帧，应用所有特效。
        
        参数:
            frame: 当前视频帧
            frame_idx: 当前帧索引
            config: 视频处理配置对象
            fps: 视频帧率
            total_frames: 视频总帧数
            orig_height: 原始视频高度
            orig_width: 原始视频宽度
        
        返回:
            Tuple[int, np.ndarray]: 帧索引和处理后的帧
        """
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        if config.flip_horizontal:
            frame = cv2.flip(frame, 1)
        frame = VideoEffects.rotate_frame(frame, config)
        h, w = frame.shape[:2]
        
        # 应用按比例裁剪
        crop_h = int(orig_height * config.crop_percentage)
        crop_w = int(orig_width * config.crop_percentage)
        top, bottom, left, right = crop_h, crop_h, crop_w, crop_w
        if top + bottom < h and left + right < w:
            frame = frame[top:h - bottom, left:w - right]
        
        # 缩放回原始尺寸
        if frame.shape[0] != orig_height or frame.shape[1] != orig_width:
            frame = cv2.resize(frame, (orig_width, orig_height), interpolation=cv2.INTER_AREA)
        
        frame = VideoEffects.apply_zoom(frame, config)
        frame = VideoEffects.adjust_sbc(frame, config)
        frame = VideoEffects.apply_hue_shift(frame, config)
        if config.include_watermark:
            frame = VideoEffects.add_watermark(frame, config, frame_idx, total_frames, self)  # 传递 self
        if self.config.include_subtitles and self.subs:
            frame = VideoEffects.add_subtitles(frame, config, frame_idx, fps, self.subs)
        if self.config.include_titles:
            frame = VideoEffects.add_titles(frame, config)
        frame = VideoEffects.add_hzh_effect(frame, config, frame_idx, total_frames)
        frame = VideoEffects.color_shift(frame, config)
        frame = VideoEffects.blur_background(frame, config)
        frame = VideoEffects.scramble_phase(frame, config)
        frame = VideoEffects.add_texture_noise(frame, config)
        frame = VideoEffects.apply_edge_blur(frame, config)
        frame = VideoEffects.apply_gaussian_blur(frame, config, frame_idx)
        frame = VideoEffects.apply_fade_effect(frame, config, frame_idx, total_frames)
        
        return (frame_idx, cv2.cvtColor(frame, cv2.COLOR_RGB2BGR))

    def _write_frames(self, frame_generator: Generator[np.ndarray, None, None], output_path: str, 
                      width: int, height: int, fps: float, audio_stream: ffmpeg.Stream) -> None:
        """
        将处理后的帧写入输出视频。

        参数:
            frame_generator: 处理后的帧生成器
            output_path: 输出视频文件路径
            width: 原始视频宽度
            height: 原始视频高度
            fps: 视频帧率
            audio_stream: 处理后的音频流
        """
        first_frame = next(frame_generator)
        adjusted_width, adjusted_height = first_frame.shape[1], first_frame.shape[0]
        video_stream = ffmpeg.input('pipe:', format='rawvideo', pix_fmt='bgr24', 
                                    s=f'{adjusted_width}x{adjusted_height}', framerate=fps)
        process = video_stream.output(
            audio_stream, output_path, vcodec='libx264', acodec='aac', preset='fast',
            # 必须显式 yuv420p：管道里送的是 bgr24，x264 会默认选 yuv444p
            #（High 4:4:4 Predictive），手机/抖音/多数播放器解不了，表现为
            # “前几秒正常后面一帧卡住”，文件也大到离谱（同片 12.8MB -> 2MB）。
            pix_fmt='yuv420p', crf=23,
            # 音频（变调/变速 + BGM 混音后）可能比视频流长一点，不加 -shortest 时
            # 容器时长跟音频走，播放器会把最后一帧定住几百毫秒（看着像“卡住”）。
            shortest=None,
            r=fps, s=f'{adjusted_width}x{adjusted_height}'
        ).overwrite_output().run_async(pipe_stdin=True)
        written = 0
        started = time.time()
        process.stdin.write(first_frame.tobytes())
        written += 1
        for frame in frame_generator:
            process.stdin.write(frame.tobytes())
            written += 1
            # 每 25 帧打一下进度与速度：4K 源很贵，看不清是哪一步慢的时候有用
            if written % 25 == 0:
                logging.info(
                    f"已写入 {written} 帧，平均 {written / (time.time() - started):.1f} 帧/秒"
                )
        process.stdin.close()
        process.wait()
        logging.info(
            f"视频处理完成，写入 {written} 帧（{written / max(time.time() - started, 1e-6):.1f} 帧/秒），"
            f"输出到 {output_path}"
        )
