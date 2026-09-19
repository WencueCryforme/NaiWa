"""批量动图压缩脚本(纯 OpenCV 方案)

扫描输入目录(默认 .input/)下的全部 `.gif` 文件,按仓库 dist 级规格输出为体积
不大于 2MB 的 `.gif`:体积已达标的文件原样复制并保留文件名,超过上限的文件
压缩到上限以内。静态图片请改用 img_resize.py。

压缩方法:逐帧用 INTER_AREA 面积平均缩小(抗混叠与抗摩尔纹表现最好),再用
`IMWRITE_GIF_QUALITY` 控制调色板大小,按「高质量 + 缩放到上限以内」到「低质量
+ 缩放到上限以内」的顺序逐级尝试,取能达标的最大尺寸。全程保留全部帧、逐帧
时长与循环次数,透明区域也一并保留。

注意:`IMWRITE_GIF_SPEED` 自 OpenCV 4.12 起已失效(由帧时长接管),本脚本不使用
该参数;OpenCV 的 GIF 编码器不做帧间差分优化,压缩率不及 gifsicle 等专用工具。

依赖:opencv-python >= 4.11(Animation API)与 numpy,安装方式见 scripts/README.md。

用法示例:
    python scripts/gif_resize.py
    python scripts/gif_resize.py -R
    python scripts/gif_resize.py 动图素材 -o 输出目录 -R
    python scripts/gif_resize.py 动图素材 --max-size 1024
"""

from __future__ import annotations

import argparse
import sys

import cv2

from resize_common import (
    GIF_EXTENSION,
    GIF_QUALITY_HIGH,
    GIF_QUALITY_LOW,
    KB,
    BatchPlan,
    add_common_arguments,
    build_animation,
    configure_stdout,
    describe_scale,
    encode_animation,
    ensure_directories,
    fit_bytes,
    format_kb,
    gif_supported,
    opencv_version,
    read_animation,
    resize_area,
    run_batch,
)


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

GIF_MAX_SIZE_KB = 2048

# 逐级尝试的调色板质量,顺序即画质由高到低
GIF_QUALITY_LADDER = (GIF_QUALITY_HIGH, GIF_QUALITY_LOW)


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


def compress_one(src_path: str, dst_path: str, max_bytes: int) -> tuple[str, bool]:
    """把单个 GIF 压缩到上限以内并写入输出路径

    返回策略说明与是否达标
    """
    animation = read_animation(src_path)
    frames = list(animation.frames)
    durations = [int(value) for value in animation.durations]
    loop_count = int(animation.loop_count)

    def encode(scale: float, quality: int) -> bytes:
        resized = [resize_area(frame, scale) for frame in frames]
        return encode_animation(
            build_animation(resized, durations, loop_count),
            [cv2.IMWRITE_GIF_QUALITY, quality],
        )

    best: tuple[bytes, str] | None = None
    for quality in GIF_QUALITY_LADDER:
        data, scale = fit_bytes(
            lambda scale, quality=quality: encode(scale, quality), max_bytes
        )
        note = (
            f"调色板质量 {quality} · {describe_scale(scale)} ·"
            f" {len(frames)} 帧 · {max(1, int(round(frames[0].shape[1] * min(scale, 1.0))))}px"
        )
        if len(data) <= max_bytes:
            with open(dst_path, "wb") as output_file:
                output_file.write(data)
            return note, True
        if best is None or len(data) < len(best[0]):
            best = (data, note)
    data, note = best
    with open(dst_path, "wb") as output_file:
        output_file.write(data)
    return note, False


def main(argv: list[str] | None = None) -> int:
    """脚本入口,依次处理全部收集到的 GIF 并输出汇总信息"""
    configure_stdout()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.max_size <= 0:
        parser.error("--max-size 必须为正数")
    if not gif_supported():
        sys.stderr.write(
            f"错误:当前环境不支持 GIF 动画读写。\n"
            f"当前 OpenCV 版本 {cv2.__version__},需要 4.11 及以上"
            f"(含 Animation API)且编译时启用了 GIF 编解码。\n"
            f"请升级依赖后重试:pip install --upgrade \"opencv-python>=4.11\"\n"
        )
        return 1
    print(f"OpenCV {cv2.__version__} / 输出上限 {format_kb(args.max_size * KB)}")
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
