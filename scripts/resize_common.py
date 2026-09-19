"""表情包压缩脚本的共用能力(纯 OpenCV 方案)

集中存放 img_resize.py(静态图片)与 gif_resize.py(动图)共用的常量、文件扫描、
缩放、上限逼近与批处理流程。常量均属可个性化修改的设计细节,集中在文件顶部
便于开发者知悉和维护。

依赖:opencv-python(>=4.11,含 Animation API)与 numpy,安装方式见 scripts/README.md。

平台约束:cv2 的路径级 API(imread/imwrite/imreadanimation)在 Windows 上不支持
非 ASCII 路径,而本仓库素材文件名均为中文,因此本模块统一走字节级 API
(imdecode/imencode/imdecodeanimation/imencodeanimation)并自行读写文件。
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

try:
    import cv2
    import numpy as np
except ImportError:
    sys.stderr.write(
        "错误:缺少 OpenCV 依赖库。\n"
        "请先安装依赖后重试:\n"
        '    pip install --upgrade "opencv-python>=4.11"\n'
        "GIF 动图的压缩需要 OpenCV 4.11 及以上版本(Animation API)。\n"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

DEFAULT_INPUT_DIR = ".input"
DEFAULT_OUTPUT_DIR = ".output"

JPG_EXTENSION = ".jpg"
GIF_EXTENSION = ".gif"

IMAGE_EXTENSIONS = frozenset(
    (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif", ".ico")
)
STATIC_EXTENSIONS = IMAGE_EXTENSIONS - {GIF_EXTENSION}

# JPEG 编码质量 0-100:90 时插画类素材在 500KB 上限内基本能保住原尺寸,
# 照片类素材体积与源文件相当
JPEG_QUALITY = 90

# 带透明通道的素材转 JPEG(不支持 alpha)时使用的合成底色
TRANSPARENT_BACKGROUND = (255, 255, 255)

# 上限逼近的迭代次数与缩放下限,缩放比例越小体积越小
SEARCH_ITERATIONS = 5
MIN_SCALE = 0.02

# GIF 调色板质量(1-8),数值越大颜色越丰富、体积越大
GIF_QUALITY_HIGH = 3
GIF_QUALITY_LOW = 1

# 源文件缺失逐帧时长时使用的兜底帧时长
DEFAULT_FRAME_DURATION_MS = 100

# GIF 动图读写所需的最低 OpenCV 版本
GIF_MIN_OPENCV = (4, 11)

KB = 1024


@dataclass
class BatchPlan:
    """一次批处理的格式约定与处理回调"""

    input_extensions: frozenset[str]
    output_extension: str
    max_bytes_for: Callable[[str], int]
    compress_one: Callable[[str, str, int], tuple[str, bool]]


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    """为命令行解析器补上各压缩脚本共用的参数"""
    parser.add_argument(
        "input_dir",
        nargs="?",
        default=DEFAULT_INPUT_DIR,
        help=f"输入目录,默认为 {DEFAULT_INPUT_DIR}",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"输出目录,默认为 {DEFAULT_OUTPUT_DIR}",
    )
    parser.add_argument(
        "-R",
        "--recursive",
        action="store_true",
        help="递归扫描输入目录下的全部子目录",
    )


def configure_stdout() -> None:
    """把标准输出与标准错误切到 UTF-8,保证中文路径正常打印"""
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def ensure_directories(*dir_paths: str) -> bool:
    """补全缺失的目录,路径被同名文件占用时报告错误"""
    for dir_path in dir_paths:
        if os.path.isdir(dir_path):
            continue
        if os.path.exists(dir_path):
            sys.stderr.write(f"错误:路径已存在但不是目录:{dir_path}\n")
            return False
        os.makedirs(dir_path, exist_ok=True)
        print(f"目录不存在,已自动创建:{dir_path}")
    return True


def collect_image_files(
    input_dir: str, output_dir: str, recursive: bool, extensions: frozenset[str]
) -> list[str]:
    """收集输入目录下符合扩展名的文件路径,结果按路径排序

    递归扫描时若输出目录嵌套在输入目录内,自动剪掉输出目录分支,
    避免把上一次的输出结果再次当成输入扫描
    """
    files: list[str] = []
    if recursive:
        output_abs = os.path.abspath(output_dir)
        for root, dirs, names in os.walk(input_dir):
            dirs.sort()
            dirs[:] = [
                d
                for d in dirs
                if not (
                    os.path.abspath(os.path.join(root, d)) == output_abs
                    or os.path.abspath(os.path.join(root, d)).startswith(
                        output_abs + os.sep
                    )
                )
            ]
            for name in sorted(names):
                if os.path.splitext(name)[1].lower() in extensions:
                    files.append(os.path.join(root, name))
    else:
        with os.scandir(input_dir) as entries:
            for entry in entries:
                if (
                    entry.is_file()
                    and os.path.splitext(entry.name)[1].lower() in extensions
                ):
                    files.append(entry.path)
        files.sort()
    return files


def read_image(path: str) -> np.ndarray | None:
    """按字节读取单帧图片,保留 alpha 通道

    不使用 cv2.imread,因为它无法处理中文路径
    """
    with open(path, "rb") as source:
        buffer = np.frombuffer(source.read(), np.uint8)
    return cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)


def encode_image(
    extension: str, image: np.ndarray, params: list[int] | None = None
) -> bytes:
    """把单帧图片编码为目标格式的字节"""
    ok, buffer = cv2.imencode(extension, image, params or [])
    if not ok:
        raise IOError(f"图片编码失败:{extension}")
    return buffer.tobytes()


def write_image(path: str, image: np.ndarray, params: list[int] | None = None) -> int:
    """按字节写出单帧图片,返回写出字节数

    不使用 cv2.imwrite,因为它无法处理中文路径
    """
    data = encode_image(os.path.splitext(path)[1], image, params)
    with open(path, "wb") as output_file:
        output_file.write(data)
    return len(data)


def opencv_version() -> tuple[int, ...]:
    """当前 OpenCV 版本号元组,取主次版本"""
    parts = []
    for piece in cv2.__version__.split(".")[:2]:
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or 0))
    return tuple(parts)


def gif_supported() -> bool:
    """检测当前环境是否支持 GIF 动画读写

    需要 OpenCV >= 4.11 的 Animation API,且编译时启用了 GIF 编解码
    """
    if opencv_version() < GIF_MIN_OPENCV:
        return False
    if not (hasattr(cv2, "imdecodeanimation") and hasattr(cv2, "imencodeanimation")):
        return False
    try:
        probe = cv2.Animation()
        probe.frames = [np.zeros((8, 8, 3), np.uint8)] * 2
        probe.durations = [100, 100]
        probe.loop_count = 0
        return bool(cv2.imencodeanimation(".gif", probe)[0])
    except Exception:
        return False


def read_animation(path: str) -> cv2.Animation:
    """按字节读取 GIF 动画,保留全部帧、逐帧时长与循环次数"""
    with open(path, "rb") as source:
        buffer = np.frombuffer(source.read(), np.uint8)
    ok, animation = cv2.imdecodeanimation(buffer, cv2.IMREAD_UNCHANGED)
    if not ok or not animation.frames:
        raise IOError(f"无法读取 GIF 动图:{path}")
    return animation


def encode_animation(
    animation: cv2.Animation, params: list[int] | None = None
) -> bytes:
    """把 GIF 动画编码为字节

    注意:帧数与逐帧时长长度必须一致,否则 OpenCV 会断言失败
    """
    ok, buffer = cv2.imencodeanimation(".gif", animation, params or [])
    if not ok:
        raise IOError("GIF 动画编码失败")
    return buffer.tobytes()


def write_animation(
    path: str, animation: cv2.Animation, params: list[int] | None = None
) -> int:
    """按字节写出 GIF 动画,返回写出字节数"""
    data = encode_animation(animation, params)
    with open(path, "wb") as output_file:
        output_file.write(data)
    return len(data)


def build_animation(
    frames: list[np.ndarray], durations: list[int], loop_count: int
) -> cv2.Animation:
    """按帧序列、逐帧时长与循环次数组装动画对象

    时长长度与帧数不一致时按帧数补齐或截断,避免编码断言失败
    """
    animation = cv2.Animation()
    animation.frames = frames
    animation.durations = [
        int(durations[index]) if index < len(durations) else durations[-1]
        for index in range(len(frames))
    ] if durations else [DEFAULT_FRAME_DURATION_MS] * len(frames)
    animation.loop_count = int(loop_count)
    return animation


def copy_file(src_path: str, dst_path: str) -> None:
    """原样复制体积已达标且格式已合规的文件"""
    with open(src_path, "rb") as src_file, open(dst_path, "wb") as output_file:
        output_file.write(src_file.read())


def resize_area(image: np.ndarray, scale: float) -> np.ndarray:
    """按比例缩小图片

    使用 INTER_AREA:该插值专为缩小设计,按面积平均,抗混叠与抗摩尔纹
    表现最好;缩放比例不小于 1 时原样返回
    """
    if scale >= 1.0:
        return image
    height, width = image.shape[:2]
    size = (max(1, int(round(width * scale))), max(1, int(round(height * scale))))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def drop_opaque_alpha(image: np.ndarray) -> np.ndarray:
    """alpha 通道完全不透明时丢弃该通道,减小产物体积"""
    if image.ndim == 3 and image.shape[2] == 4:
        if int(image[:, :, 3].min()) == 255:
            return image[:, :, :3]
    return image


def flatten_to_bgr(
    image: np.ndarray, background: tuple[int, int, int] = TRANSPARENT_BACKGROUND
) -> tuple[np.ndarray, bool]:
    """把带 alpha 的图片合成到纯色底上,得到 JPEG 可写的三通道图

    JPEG 不支持透明通道:alpha 全不透明时直接丢弃该通道,存在透明像素时
    与底色合成。返回 (图片, 是否发生了透明合成)
    """
    if image.ndim != 3 or image.shape[2] != 4:
        return image, False
    alpha = image[:, :, 3]
    if int(alpha.min()) == 255:
        return image[:, :, :3], False
    bgr = image[:, :, :3].astype(np.float32)
    weight = (alpha.astype(np.float32) / 255.0)[:, :, None]
    canvas = np.array(background, dtype=np.float32)[None, None, :]
    merged = bgr * weight + canvas * (1.0 - weight)
    return merged.astype(np.uint8), True


def fit_bytes(encode: Callable[[float], bytes], max_bytes: int) -> tuple[bytes, float]:
    """在缩放区间内逼近不超过上限的最大编码结果

    体积与像素面积近似成正比,因此先用面积比估算缩放比例收窄区间,
    再在区间内二分;先探原尺寸,未超限即直接采用,缩放下限仍超限时
    返回该下限结果作为兜底
    """
    full = encode(1.0)
    if len(full) <= max_bytes:
        return full, 1.0
    estimate = min(1.0, max(MIN_SCALE, (max_bytes / len(full)) ** 0.5))
    probe = encode(estimate)
    if len(probe) <= max_bytes:
        best, best_scale = probe, estimate
        low, high = estimate, 1.0
    else:
        lowest = encode(MIN_SCALE)
        if len(lowest) > max_bytes:
            return lowest, MIN_SCALE
        best, best_scale = lowest, MIN_SCALE
        low, high = MIN_SCALE, estimate
    for _ in range(SEARCH_ITERATIONS):
        middle = (low + high) / 2
        if not low < middle < high:
            break
        data = encode(middle)
        if len(data) <= max_bytes:
            best, best_scale = data, middle
            low = middle
        else:
            high = middle
    return best, best_scale


def describe_scale(scale: float) -> str:
    """把缩放比例描述为可读文本"""
    if scale >= 1.0:
        return "原尺寸"
    return f"缩放 {scale * 100:.0f}%"


def format_kb(size: int) -> str:
    """把字节数格式化为 KB 字符串,保留一位小数"""
    return f"{size / KB:.1f} KB"


def run_batch(input_dir: str, output_dir: str, recursive: bool, plan: BatchPlan) -> int:
    """按计划处理全部文件:未超限且格式合规的原样复制,其余压缩转换

    返回进程退出码,存在失败或未达标的文件时返回 2
    """
    files = collect_image_files(input_dir, output_dir, recursive, plan.input_extensions)
    if not files:
        sys.stderr.write("未发现可处理的图片文件。\n")
        return 1

    total = len(files)
    compress_count = 0
    copy_count = 0
    over_count = 0
    fail_count = 0
    for src_path in files:
        relative = os.path.relpath(src_path, input_dir)
        extension = os.path.splitext(src_path)[1].lower()
        max_bytes = plan.max_bytes_for(extension)
        src_size = os.path.getsize(src_path)
        if src_size <= max_bytes and extension == plan.output_extension:
            # 体积已达标且格式已合规,原样复制
            dst_path = os.path.join(output_dir, relative)
            action = "复制"
        else:
            stem = os.path.splitext(relative)[0]
            dst_path = os.path.join(output_dir, stem + plan.output_extension)
            action = "压缩" if extension == plan.output_extension else "转换"
        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            print(f"[跳过] 输入与输出为同一文件:{src_path}")
            continue
        try:
            os.makedirs(os.path.dirname(dst_path) or output_dir, exist_ok=True)
            if action == "复制":
                copy_file(src_path, dst_path)
                copy_count += 1
                print(f"[复制] {src_path} -> {dst_path} ({format_kb(src_size)})")
                continue
            note, ok = plan.compress_one(src_path, dst_path, max_bytes)
            compress_count += 1
            dst_size = os.path.getsize(dst_path)
            state = "达标" if ok else "未达标"
            print(
                f"[{state}] {src_path} -> {dst_path} "
                f"({format_kb(src_size)} -> {format_kb(dst_size)},"
                f" {note}, 上限 {format_kb(max_bytes)})"
            )
            if not ok:
                over_count += 1
        except Exception as error:
            sys.stderr.write(f"[失败] {src_path}: {error}\n")
            fail_count += 1

    print(
        f"完成:共 {total} 个文件,压缩 {compress_count} 个,复制 {copy_count} 个,"
        f"未达标 {over_count} 个,失败 {fail_count} 个。"
    )
    return 0 if fail_count == 0 and over_count == 0 else 2
