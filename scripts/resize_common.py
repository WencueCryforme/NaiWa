"""表情包压缩脚本的共用能力

集中存放 img_resize.py(静态图片)与 gif_resize.py(动图)共用的常量、
批量扫描、量化、缩放逼近与批处理流程,避免两份脚本重复维护同一套逻辑。
常量均属可个性化修改的设计细节,集中在文件顶部便于开发者知悉和维护。

依赖:Pillow 库。
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass

try:
    from PIL import Image
except ImportError:
    sys.stderr.write(
        "错误:缺少 Pillow 依赖库,请先执行 pip install Pillow 后重试。\n"
    )
    sys.exit(1)


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

DEFAULT_INPUT_DIR = ".input"
DEFAULT_OUTPUT_DIR = ".output"

PNG_EXTENSION = ".png"
GIF_EXTENSION = ".gif"

IMAGE_EXTENSIONS = frozenset(
    (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif", ".ico")
)
STATIC_EXTENSIONS = IMAGE_EXTENSIONS - {GIF_EXTENSION}

# 带透明通道的像素 alpha 低于该值视为完全透明,GIF 只支持二值透明
ALPHA_THRESHOLD = 128

# 透明区域在量化前的统一铺底色,该区域最终会被独立索引标记为透明
TRANSPARENT_BACKGROUND = (0, 0, 0)

# 缩放逼近的迭代次数与缩放下限,缩放比例越小体积越小
SEARCH_ITERATIONS = 6
MIN_SCALE = 0.02

# 全局调色板的抽样规模,抽样帧数与抽样总像素
PALETTE_SAMPLE_FRAMES = 16
PALETTE_SAMPLE_PIXELS = 1 << 20

PNG_COMPRESS_LEVEL = 9
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


def copy_file(src_path: str, dst_path: str) -> None:
    """原样复制体积已达标且格式已合规的文件"""
    with open(src_path, "rb") as src_file, open(dst_path, "wb") as dst_file:
        dst_file.write(src_file.read())


def resize_image(image: Image.Image, scale: float) -> Image.Image:
    """按比例缩放图片,使用 LANCZOS 重采样,尺寸下限为 1 像素

    缩放比例不小于 1 时原样返回,避免无效果的高开销重采样
    """
    if scale >= 1.0:
        return image
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def quantize_image(image: Image.Image, colors: int) -> Image.Image:
    """把单帧图片量化到指定颜色数,获得更小的体积

    统一使用快速八叉树算法:实测本项目素材在同等色数下,八叉树的调色板
    与索引排布更利于 PNG 与 GIF 的压缩,原尺寸即可压到上限以内,避免为了
    达标而牺牲分辨率;中位切分法色差更小但体积约为前者的三倍,达不到
    减少信息损失的目的
    """
    try:
        return image.quantize(
            colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE
        )
    except (ValueError, TypeError):
        # 兼容旧版本 Pillow 的参数形式
        return image.quantize(colors=colors, method=Image.FASTOCTREE, dither=0)


def quantize_transparent(image: Image.Image, colors: int) -> Image.Image:
    """把带透明通道的图片量化为 P 模式,并显式标记透明索引

    Pillow 的量化不会自动保留透明信息,这里把透明像素统一收敛到一个
    独立的调色板索引,并在图像信息中把该索引标记为透明色,避免透明
    背景在输出中变成黑色底板。透明区域的 RGB 取值没有意义,量化前先
    统一铺成单色,让调色板只服务于可见内容,同时大幅提升压缩率
    """
    alpha = image.getchannel("A")
    transparent_mask = alpha.point(lambda value: 255 if value < ALPHA_THRESHOLD else 0)
    if transparent_mask.getextrema()[0] > 0:
        # 没有透明像素,退化为普通量化
        return quantize_image(image, colors)
    opaque_mask = alpha.point(lambda value: 255 if value >= ALPHA_THRESHOLD else 0)
    limit = max(2, colors - 1)
    flattened = Image.new("RGB", image.size, TRANSPARENT_BACKGROUND)
    flattened.paste(image.convert("RGB"), (0, 0), opaque_mask)
    quantized = quantize_image(flattened, limit)
    transparent_index = limit
    palette = quantized.getpalette()
    while len(palette) < 3 * (transparent_index + 1):
        palette.append(0)
    palette[3 * transparent_index : 3 * transparent_index + 3] = [0, 0, 0]
    quantized.putpalette(palette)
    quantized.paste(
        transparent_index, (0, 0, quantized.width, quantized.height), transparent_mask
    )
    quantized.info["transparency"] = transparent_index
    return quantized


def quantize_frame(image: Image.Image, colors: int) -> Image.Image:
    """按图片是否真正含透明像素选择量化方式"""
    if image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < ALPHA_THRESHOLD:
        return quantize_transparent(image, colors)
    return quantize_image(image, colors)


def build_palette_reference(frames: list[Image.Image], colors: int) -> Image.Image:
    """把多帧抽样拼接成一张参考图,据此生成全局调色板

    统一调色板让各帧共用同一份颜色表,避免逐帧独立调色导致的体积
    膨胀,也让播放时颜色稳定不闪烁
    """
    step = max(1, len(frames) // PALETTE_SAMPLE_FRAMES)
    samples = frames[::step][:PALETTE_SAMPLE_FRAMES]
    budget = max(1, PALETTE_SAMPLE_PIXELS // len(samples))
    thumbs: list[Image.Image] = []
    for frame in samples:
        thumb = frame.convert("RGB")
        pixels = thumb.width * thumb.height
        if pixels > budget:
            ratio = math.sqrt(budget / pixels)
            thumb = thumb.resize(
                (
                    max(1, round(thumb.width * ratio)),
                    max(1, round(thumb.height * ratio)),
                ),
                Image.Resampling.LANCZOS,
            )
        thumbs.append(thumb)
    columns = math.ceil(math.sqrt(len(thumbs)))
    rows = math.ceil(len(thumbs) / columns)
    cell_width = max(thumb.width for thumb in thumbs)
    cell_height = max(thumb.height for thumb in thumbs)
    canvas = Image.new("RGB", (cell_width * columns, cell_height * rows))
    for index, thumb in enumerate(thumbs):
        canvas.paste(
            thumb, ((index % columns) * cell_width, (index // columns) * cell_height)
        )
    return canvas.quantize(
        colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
    )


def cached_encode(encode: Callable[[float], bytes]) -> Callable[[float], bytes]:
    """包裹编码函数并缓存结果,避免逼近过程中对同一比例重复编码"""
    cache: dict[float, bytes] = {}

    def run(scale: float) -> bytes:
        key = round(scale, 6)
        if key not in cache:
            cache[key] = encode(key)
        return cache[key]

    return run


def fit_encode(encode: Callable[[float], bytes], max_bytes: int) -> tuple[bytes, float]:
    """在缩放区间内逼近不超过上限的最大编码结果

    体积与像素面积近似成正比,因此先用面积比估算缩放比例收窄区间,
    再在区间内二分;先探原尺寸,未超限即直接采用,缩放下限仍超限时
    返回该下限结果作为兜底
    """
    full = encode(1.0)
    if len(full) <= max_bytes:
        return full, 1.0
    estimate = min(1.0, max(MIN_SCALE, math.sqrt(max_bytes / len(full))))
    probe = encode(estimate)
    if len(probe) <= max_bytes:
        best, best_scale = probe, estimate
        lo, hi = estimate, 1.0
    else:
        lowest = encode(MIN_SCALE)
        if len(lowest) > max_bytes:
            return lowest, MIN_SCALE
        best, best_scale = lowest, MIN_SCALE
        lo, hi = MIN_SCALE, estimate
    for _ in range(SEARCH_ITERATIONS):
        mid = (lo + hi) / 2
        if not lo < mid < hi:
            break
        data = encode(mid)
        if len(data) <= max_bytes:
            best, best_scale = data, mid
            lo = mid
        else:
            hi = mid
    return best, best_scale


def describe_strategy(colors: int | None, scale: float) -> str:
    """把策略参数描述为可读文本"""
    color_note = "真彩色" if colors is None else f"量化 {colors} 色"
    if scale >= 1.0:
        return f"{color_note} · 原尺寸"
    return f"{color_note} · 缩放 {scale * 100:.0f}%"


def format_kb(size: int) -> str:
    """把字节数格式化为 KB 字符串,保留一位小数"""
    return f"{size / KB:.1f} KB"


def run_batch(
    input_dir: str, output_dir: str, recursive: bool, plan: BatchPlan
) -> int:
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
