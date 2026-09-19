"""批量动图压缩脚本

扫描输入目录(默认 .input/)下的全部 `.gif` 文件,按仓库 dist 级规格输出为
体积不大于 2MB 的 `.gif`:体积已达标的文件原样复制并保留文件名,超过上限
的文件压缩到上限以内,全程保留全部帧、逐帧时长与循环方式。静态图片请
改用 img_resize.py。

压缩方法:先尝试原始调色板保真重编码,再按色数由高到低量化并使用统一
调色板(避免逐帧独立调色带来的体积膨胀与播放闪烁),每个策略内部用面积比
估算缩放比例收窄范围,再逼近到不超过上限的最大缩放比例,减少编码次数。
带透明通道的素材会把透明区域收敛到独立调色板索引,避免透明背景变成
黑色底板。

依赖:Pillow 库。

用法示例:
    python scripts/gif_resize.py
    python scripts/gif_resize.py -R
    python scripts/gif_resize.py 动图素材 -o 输出目录 -R
    python scripts/gif_resize.py 动图素材 --max-size 1024
"""

from __future__ import annotations

import argparse
import io
import sys
from dataclasses import dataclass, field

from resize_common import (
    GIF_EXTENSION,
    KB,
    BatchPlan,
    add_common_arguments,
    build_palette_reference,
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

GIF_MAX_SIZE_KB = 2048

# 策略色数序列,顺序即画质由高到低,GIF 本身基于调色板,故不含真彩色策略
GIF_STRATEGY_COLORS = (256, 128, 64, 32)

# 源文件缺失逐帧时长时使用的兜底帧时长
DEFAULT_FRAME_DURATION_MS = 100


@dataclass
class GifSource:
    """GIF 素材,保留原始帧与播放参数"""

    frames_palette: list[Image.Image] = field(default_factory=list)
    frames_rgba: list[Image.Image] = field(default_factory=list)
    durations: list[int] = field(default_factory=list)
    loop: int = 0
    transparent: bool = False
    has_duration: bool = False
    has_loop: bool = False

    @property
    def frame_count(self) -> int:
        return len(self.frames_rgba)


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器,所有参数均带默认值"""
    parser = argparse.ArgumentParser(
        prog="gif_resize",
        description=f"批量把 GIF 动图压缩为不大于 {GIF_MAX_SIZE_KB}KB 的 GIF",
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--max-size",
        type=int,
        default=GIF_MAX_SIZE_KB,
        metavar="KB",
        help=f"输出 GIF 的体积上限,单位 KB,默认为 {GIF_MAX_SIZE_KB}",
    )
    return parser


def load_gif_source(path: str) -> GifSource:
    """读取 GIF 的全部帧与播放参数

    同时保留原始 P 模式帧与 RGBA 帧:前者用于保真重编码,后者用于
    统一调色板量化与缩放
    """
    source = GifSource()
    with Image.open(path) as image:
        for index in range(getattr(image, "n_frames", 1)):
            image.seek(index)
            source.frames_palette.append(image.copy())
            source.frames_rgba.append(image.convert("RGBA"))
            source.durations.append(
                int(image.info.get("duration", DEFAULT_FRAME_DURATION_MS))
            )
            if "duration" in image.info:
                source.has_duration = True
            if "transparency" in image.info:
                source.transparent = True
        if "loop" in image.info:
            source.has_loop = True
            source.loop = int(image.info["loop"])
    return source


def quantize_frames(
    frames: list[Image.Image],
    colors: int,
    transparent: bool,
    palette_reference: Image.Image | None,
) -> list[Image.Image]:
    """按统一调色板量化全部帧,带透明信息时退回逐帧量化"""
    if transparent or palette_reference is None:
        return [quantize_frame(frame, colors) for frame in frames]
    return [
        frame.convert("RGB").quantize(
            palette=palette_reference, dither=Image.Dither.NONE
        )
        for frame in frames
    ]


def encode_gif(
    frames: list[Image.Image],
    scale: float,
    colors: int | None,
    source: GifSource,
    palette_reference: Image.Image | None = None,
) -> bytes:
    """把 GIF 的全部帧编码为 GIF 字节,保留帧序、逐帧时长与循环方式

    colors 为 None 时使用原始调色板保真重编码,此时不缩放;源文件没有
    记录的播放参数不会凭空补写
    """
    if colors is None:
        encoded = frames
    else:
        resized = [resize_image(frame, scale) for frame in frames]
        encoded = quantize_frames(
            resized, colors, source.transparent, palette_reference
        )
    options: dict = {
        "format": "GIF",
        "save_all": True,
        "append_images": encoded[1:],
        "optimize": True,
    }
    if source.has_duration:
        options["duration"] = (
            source.durations if len(encoded) > 1 else source.durations[0]
        )
    if source.has_loop:
        options["loop"] = source.loop
    buffer = io.BytesIO()
    encoded[0].save(buffer, **options)
    return buffer.getvalue()


def shrink_gif(source: GifSource, max_bytes: int) -> tuple[bytes, str, bool]:
    """压缩 GIF 到上限以内,返回字节数据、策略说明与是否达标

    先尝试原始调色板保真重编码,再按色数由高到低量化并使用统一
    调色板,每个策略内部对缩放比例逼近,全程保留全部帧、逐帧时长
    与循环方式
    """
    data = encode_gif(source.frames_palette, 1.0, None, source)
    if len(data) <= max_bytes:
        return data, "保真重编码", True
    best: tuple[bytes, str] = (data, "保真重编码")
    for colors in GIF_STRATEGY_COLORS:
        palette_reference = None
        if not source.transparent:
            palette_reference = build_palette_reference(source.frames_rgba, colors)
        encode = cached_encode(
            lambda scale, colors=colors, reference=palette_reference: encode_gif(
                source.frames_rgba, scale, colors, source, reference
            )
        )
        data, scale = fit_encode(encode, max_bytes)
        note = describe_strategy(colors, scale)
        if len(data) < len(best[0]):
            best = (data, note)
        if len(data) <= max_bytes:
            return data, note, True
    data, note = best
    return data, note, False


def compress_one(src_path: str, dst_path: str, max_bytes: int) -> tuple[str, bool]:
    """把单个 GIF 压缩到上限以内并写入输出路径"""
    data, note, ok = shrink_gif(load_gif_source(src_path), max_bytes)
    with open(dst_path, "wb") as output_file:
        output_file.write(data)
    return note, ok


def main(argv: list[str] | None = None) -> int:
    """脚本入口,依次处理全部收集到的 GIF 并输出汇总信息"""
    configure_stdout()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.max_size <= 0:
        parser.error("--max-size 必须为正数")
    if not ensure_directories(args.input_dir, args.output_dir):
        return 1
    plan = BatchPlan(
        input_extensions=frozenset((GIF_EXTENSION,)),
        output_extension=GIF_EXTENSION,
        max_bytes_for=lambda extension: args.max_size * KB,
        compress_one=compress_one,
    )
    return run_batch(args.input_dir, args.output_dir, args.recursive, plan)


if __name__ == "__main__":
    sys.exit(main())
