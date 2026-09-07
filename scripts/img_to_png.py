"""批量图片转 PNG 脚本

扫描输入目录(默认 .input/)下的全部图片文件:文件大小不超过目标
上限(默认 500KB)的图片原样复制到输出目录,保留原文件名与扩展名;
超过上限的图片压缩转换为文件大小落在目标范围(默认 400-500KB)
内的 .png 图片。输出到指定输出目录(默认 .output/),支持递归扫描
子目录,输出目录中保留与输入目录一致的相对路径结构,便于多子目录
场景下避免同名冲突。

依赖:Pillow 库。转换 GIF 等多帧图片时只取首帧。

用法示例:
    python scripts/img_to_png.py
    python scripts/img_to_png.py -R
    python scripts/img_to_png.py 图片素材 -o 输出目录 -R --min-size 300 --max-size 500
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from collections.abc import Callable

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
DEFAULT_MIN_SIZE_KB = 300
DEFAULT_MAX_SIZE_KB = 500

IMAGE_EXTENSIONS = frozenset(
    (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".tiff", ".tif", ".ico")
)

PALETTE_MAX_COLORS = 256
KB = 1024


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器,所有参数均带默认值"""
    parser = argparse.ArgumentParser(
        prog="img_to_png",
        description="批量把图片转换为目标大小范围内的 PNG 图片",
    )
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
    parser.add_argument(
        "--min-size",
        type=int,
        default=DEFAULT_MIN_SIZE_KB,
        help=f"目标文件大小下限,单位 KB,默认为 {DEFAULT_MIN_SIZE_KB}",
    )
    parser.add_argument(
        "--max-size",
        type=int,
        default=DEFAULT_MAX_SIZE_KB,
        help=f"目标文件大小上限,单位 KB,默认为 {DEFAULT_MAX_SIZE_KB}",
    )
    return parser


def collect_image_files(input_dir: str, output_dir: str, recursive: bool) -> list[str]:
    """收集输入目录下的全部图片文件路径,结果按路径排序

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
                if os.path.splitext(name)[1].lower() in IMAGE_EXTENSIONS:
                    files.append(os.path.join(root, name))
    else:
        with os.scandir(input_dir) as entries:
            for entry in entries:
                if (
                    entry.is_file()
                    and os.path.splitext(entry.name)[1].lower() in IMAGE_EXTENSIONS
                ):
                    files.append(entry.path)
        files.sort()
    return files


def load_first_frame(path: str) -> Image.Image:
    """读取图片的首帧,统一转换为 RGB 或 RGBA 模式

    原图为索引色且带透明信息时转换为 RGBA,其余统一转换为 RGB,
    保证后续量化与缩放流程只面对这两种模式
    """
    with Image.open(path) as image:
        image.seek(0)
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            return image.convert("RGBA")
        return image.convert("RGB")


def save_png_to_buffer(image: Image.Image) -> bytes:
    """把图片编码为 PNG 字节并返回,使用最优压缩设置"""
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def resize_image(image: Image.Image, scale: float) -> Image.Image:
    """按比例缩放图片,使用 LANCZOS 重采样,尺寸下限为 1 像素"""
    width = max(1, round(image.width * scale))
    height = max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.LANCZOS)


def quantize_candidate(image: Image.Image, colors: int) -> Image.Image:
    """把图片量化到指定颜色数,获得更小的 PNG 体积

    透明图只支持快速八叉树算法,不透明图使用中位切分法,均不抖动;
    量化透明图失败时退回丢弃透明通道的兜底处理
    """
    if image.mode == "RGBA":
        method = Image.Quantize.FASTOCTREE
    else:
        method = Image.Quantize.MEDIANCUT
    try:
        return image.quantize(
            colors=colors, method=method, dither=Image.Dither.NONE
        )
    except (ValueError, TypeError):
        # 兼容旧版本 Pillow 的参数形式
        legacy_method = Image.FASTOCTREE if image.mode == "RGBA" else Image.MEDIANCUT
        return image.quantize(colors=colors, method=legacy_method, dither=0)
    except Exception:
        if image.mode == "RGBA":
            print("警告:透明通道量化失败,已丢弃透明信息。")
            return image.convert("RGB").quantize(
                colors=colors, method=method, dither=Image.Dither.NONE
            )
        raise


def resize_data_fn(
    original: Image.Image, quantize: bool, colors: int
) -> Callable[[float], bytes]:
    """返回以缩放比例为入参的编码函数,用于二分逼近目标大小"""
    def encode(scale: float) -> bytes:
        enlarged = resize_image(original, scale)
        if quantize:
            return save_png_to_buffer(quantize_candidate(enlarged, colors))
        return save_png_to_buffer(enlarged)
    return encode


def binary_fit(
    data_fn: Callable[[float], bytes],
    lo: float,
    hi: float,
    min_bytes: int,
    max_bytes: int,
    iterations: int = 12,
) -> bytes:
    """在参数区间内二分查找目标大小,参数增大时体积单调不减

    返回第一个落入目标范围的编码结果;未命中时返回不超过上限的
    最大候选,全程超限时返回区间下端的最小候选
    """
    best = None
    for _ in range(iterations):
        mid = (lo + hi) / 2
        if not lo < mid < hi:
            break
        data = data_fn(mid)
        size = len(data)
        if min_bytes <= size <= max_bytes:
            return data
        if size > max_bytes:
            hi = mid
        else:
            lo = mid
            if best is None or size > len(best):
                best = data
    if best is not None:
        return best
    return data_fn(lo)


def shrink_to_range(
    original: Image.Image, min_bytes: int, max_bytes: int
) -> bytes:
    """压缩超过上限的图片,多策略重试直至落入目标区间

    策略按质量从高到低依次尝试:量化 256 色、真彩色、量化 128 色、
    量化 64 色,每个策略内部按缩放比例二分逼近;任一策略命中区间
    立即返回,全部未命中时返回离区间最近的候选
    """
    strategies = (
        (True, PALETTE_MAX_COLORS),
        (False, PALETTE_MAX_COLORS),
        (True, PALETTE_MAX_COLORS // 2),
        (True, PALETTE_MAX_COLORS // 4),
    )
    best = None
    for quantize, colors in strategies:
        data_fn = resize_data_fn(original, quantize, colors)
        data = binary_fit(data_fn, 0.02, 1.0, min_bytes, max_bytes)
        size = len(data)
        if min_bytes <= size <= max_bytes:
            return data
        if best is None or abs(size - min_bytes) < abs(len(best) - min_bytes):
            best = data
    return best


def format_kb(size: int) -> str:
    """把字节数格式化为 KB 字符串,保留一位小数"""
    return f"{size / KB:.1f} KB"


def convert_one(src_path: str, dst_path: str, min_bytes: int, max_bytes: int) -> None:
    """压缩转换单个超过上限的图片文件为 PNG 并写入输出路径"""
    original = load_first_frame(src_path)
    data = shrink_to_range(original, min_bytes, max_bytes)
    with open(dst_path, "wb") as output_file:
        output_file.write(data)


def main(argv: list[str] | None = None) -> int:
    """脚本入口,依次处理全部收集到的图片文件并输出汇总信息"""
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    min_bytes = args.min_size * KB
    max_bytes = args.max_size * KB
    if min_bytes > max_bytes:
        parser.error(f"--min-size({args.min_size}) 不能大于 --max-size({args.max_size})")
    if min_bytes <= 0:
        parser.error("--min-size 必须为正数")
    # 目录补全:输入目录与输出目录不存在时自动创建
    for dir_path, dir_name in ((args.input_dir, "输入"), (args.output_dir, "输出")):
        if os.path.isdir(dir_path):
            continue
        if os.path.exists(dir_path):
            sys.stderr.write(f"错误:{dir_name}路径已存在但不是目录:{dir_path}\n")
            return 1
        os.makedirs(dir_path, exist_ok=True)
        print(f"{dir_name}目录不存在,已自动创建:{dir_path}")

    files = collect_image_files(args.input_dir, args.output_dir, args.recursive)
    if not files:
        sys.stderr.write("未发现可转换的图片文件。\n")
        return 1

    total = len(files)
    ok_count = 0
    skip_count = 0
    fail_count = 0
    for src_path in files:
        relative = os.path.relpath(src_path, args.input_dir)
        src_size = os.path.getsize(src_path)
        if src_size <= max_bytes:
            # 原图不超过上限,原样复制,保留原文件名与扩展名
            dst_path = os.path.join(args.output_dir, relative)
            if os.path.abspath(src_path) == os.path.abspath(dst_path):
                print(f"[跳过] 输入与输出为同一文件:{src_path}")
                skip_count += 1
                continue
            try:
                os.makedirs(os.path.dirname(dst_path) or args.output_dir, exist_ok=True)
                with open(src_path, "rb") as src_file, open(dst_path, "wb") as dst_file:
                    dst_file.write(src_file.read())
                print(f"[复制] {src_path} -> {dst_path} ({format_kb(src_size)})")
                ok_count += 1
            except Exception as error:
                sys.stderr.write(f"[失败] {src_path}: {error}\n")
                fail_count += 1
            continue
        # 原图超过上限,压缩转换为 PNG
        stem = os.path.splitext(relative)[0]
        dst_path = os.path.join(args.output_dir, stem + ".png")
        if os.path.abspath(src_path) == os.path.abspath(dst_path):
            print(f"[跳过] 输入与输出为同一文件:{src_path}")
            skip_count += 1
            continue
        try:
            os.makedirs(os.path.dirname(dst_path) or args.output_dir, exist_ok=True)
            convert_one(src_path, dst_path, min_bytes, max_bytes)
            dst_size = os.path.getsize(dst_path)
            state = "达标" if min_bytes <= dst_size <= max_bytes else "未达标"
            print(
                f"[{state}] {src_path} -> {dst_path} "
                f"({format_kb(src_size)} -> {format_kb(dst_size)})"
            )
            ok_count += 1
        except Exception as error:
            sys.stderr.write(f"[失败] {src_path}: {error}\n")
            fail_count += 1

    print(
        f"完成:共 {total} 个文件,成功 {ok_count} 个,"
        f"跳过 {skip_count} 个,失败 {fail_count} 个。"
    )
    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
