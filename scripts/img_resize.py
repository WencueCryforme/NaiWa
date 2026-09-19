"""批量静态图片压缩脚本

扫描输入目录(默认 .input/)下的全部静态图片文件,按仓库 dist 级规格输出
为体积不大于 500KB 的 `.png`:体积已达标且原本就是 `.png` 的文件原样复制
并保留文件名,其余文件压缩转换到上限以内。`.gif` 动图请改用 gif_resize.py。

压缩方法:按色数由高到低依次尝试若干编码策略(量化 256 色、真彩色、
量化 128/64/32 色),表情包以平涂插画为主,先量化几乎不损观感却能保住
分辨率;每个策略内部用面积比估算缩放比例收窄范围,再逼近到不超过上限
的最大缩放比例,减少编码次数。带透明通道的素材会把透明区域收敛到独立
调色板索引,避免透明背景变成黑色底板。

依赖:Pillow 库。

用法示例:
    python scripts/img_resize.py
    python scripts/img_resize.py -R
    python scripts/img_resize.py 图片素材 -o 输出目录 -R
    python scripts/img_resize.py 图片素材 --max-size 400
"""

from __future__ import annotations

import argparse
import io
import sys

from resize_common import (
    KB,
    PNG_COMPRESS_LEVEL,
    PNG_EXTENSION,
    STATIC_EXTENSIONS,
    BatchPlan,
    add_common_arguments,
    cached_encode,
    configure_stdout,
    describe_strategy,
    ensure_directories,
    fit_encode,
    quantize_frame,
    resize_image,
    run_batch,
)

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

PNG_MAX_SIZE_KB = 500

# 策略色数序列,None 表示真彩色不量化,顺序即画质由高到低
# 表情包以平涂插画为主,先量化到 256 色几乎看不出差异却能把分辨率保住,
# 真彩色作为次选,最后才逐级降低色数
PNG_STRATEGY_COLORS = (256, None, 128, 64, 32)


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器,所有参数均带默认值"""
    parser = argparse.ArgumentParser(
        prog="img_resize",
        description=f"批量把静态图片压缩为不大于 {PNG_MAX_SIZE_KB}KB 的 PNG",
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--max-size",
        type=int,
        default=PNG_MAX_SIZE_KB,
        metavar="KB",
        help=f"输出 PNG 的体积上限,单位 KB,默认为 {PNG_MAX_SIZE_KB}",
    )
    return parser


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


def encode_png(image: Image.Image, scale: float, colors: int | None) -> bytes:
    """按缩放比例与色数把单帧图片编码为 PNG 字节"""
    resized = resize_image(image, scale)
    if colors is not None:
        resized = quantize_frame(resized, colors)
    buffer = io.BytesIO()
    resized.save(
        buffer, format="PNG", optimize=True, compress_level=PNG_COMPRESS_LEVEL
    )
    return buffer.getvalue()


def shrink_png(image: Image.Image, max_bytes: int) -> tuple[bytes, str, bool]:
    """压缩单帧图片到上限以内,返回字节数据、策略说明与是否达标

    策略按色数由高到低排列(量化 256 色、真彩色、量化 128/64/32 色),
    每个策略内部对缩放比例逼近到上限以内,优先保住分辨率,最后才
    逐级牺牲色数
    """
    best: tuple[bytes, str] | None = None
    for colors in PNG_STRATEGY_COLORS:
        encode = cached_encode(
            lambda scale, colors=colors: encode_png(image, scale, colors)
        )
        data, scale = fit_encode(encode, max_bytes)
        if best is None or len(data) < len(best[0]):
            best = (data, describe_strategy(colors, scale))
        if len(data) <= max_bytes:
            return data, describe_strategy(colors, scale), True
    data, note = best
    return data, note, False


def compress_one(
    src_path: str, dst_path: str, max_bytes: int
) -> tuple[str, bool]:
    """把单张静态图片压缩为 PNG 并写入输出路径"""
    data, note, ok = shrink_png(load_first_frame(src_path), max_bytes)
    with open(dst_path, "wb") as output_file:
        output_file.write(data)
    return note, ok


def main(argv: list[str] | None = None) -> int:
    """脚本入口,依次处理全部收集到的静态图片并输出汇总信息"""
    configure_stdout()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.max_size <= 0:
        parser.error("--max-size 必须为正数")
    if not ensure_directories(args.input_dir, args.output_dir):
        return 1
    plan = BatchPlan(
        input_extensions=STATIC_EXTENSIONS,
        output_extension=PNG_EXTENSION,
        max_bytes_for=lambda extension: args.max_size * KB,
        compress_one=compress_one,
    )
    return run_batch(args.input_dir, args.output_dir, args.recursive, plan)


if __name__ == "__main__":
    sys.exit(main())
