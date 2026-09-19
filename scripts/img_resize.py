"""批量静态图片压缩脚本(纯 OpenCV 方案)

扫描输入目录(默认 .input/)下的全部静态图片文件,按仓库 dist 级规格输出为统一
`.jpg` 格式、体积不大于 500KB 的图片:

- 源文件体积未超过上限:只做格式转换(重新编码为 JPEG),不缩放
- 源文件体积超过上限:先转格式,再按上限缩小到范围内

`.gif` 动图请改用 gif_resize.py,该脚本只压缩、不做格式转换。

压缩方法:缩放统一使用 INTER_AREA 面积平均插值(抗混叠与抗摩尔纹表现最好),
体积控制用面积比估算加二分逼近,取不超过上限的最大尺寸。JPEG 质量由
`JPEG_QUALITY` 控制,可命令行覆盖;输出为无损格式时体积效率过低(同一张插画
无损 PNG 约为 JPEG 的 6 倍),因此静态图统一使用有损 JPEG。带透明通道的素材
会与白色底合成,并在日志中提示。

依赖:opencv-python >= 4.11 与 numpy,安装方式见 scripts/README.md。

用法示例:
    python scripts/img_resize.py
    python scripts/img_resize.py -R
    python scripts/img_resize.py 图片素材 -o 输出目录 -R
    python scripts/img_resize.py 图片素材 --max-size 400 --quality 92
"""

from __future__ import annotations

import argparse
import sys

import cv2

from resize_common import (
    JPG_EXTENSION,
    JPEG_QUALITY,
    KB,
    STATIC_EXTENSIONS,
    BatchPlan,
    add_common_arguments,
    configure_stdout,
    describe_scale,
    encode_image,
    ensure_directories,
    fit_bytes,
    flatten_to_bgr,
    read_image,
    resize_area,
    run_batch,
)


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

JPEG_MAX_SIZE_KB = 500


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器,所有参数均带默认值"""
    parser = argparse.ArgumentParser(
        prog="img_resize",
        description=f"批量把静态图片转换为不大于 {JPEG_MAX_SIZE_KB}KB 的 JPEG",
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--max-size",
        type=int,
        default=JPEG_MAX_SIZE_KB,
        metavar="KB",
        help=f"输出图片的体积上限,单位 KB,默认为 {JPEG_MAX_SIZE_KB}",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=JPEG_QUALITY,
        metavar="1-100",
        help=f"JPEG 编码质量,默认为 {JPEG_QUALITY}",
    )
    return parser


def compress_one(
    src_path: str, dst_path: str, max_bytes: int, quality: int
) -> tuple[str, bool]:
    """把单张静态图片转换并压缩为 JPEG 写入输出路径

    返回策略说明与是否达标
    """
    image = read_image(src_path)
    if image is None:
        raise IOError("无法解码该图片")
    image, flattened = flatten_to_bgr(image)

    def encode(scale: float) -> bytes:
        return encode_image(
            JPG_EXTENSION,
            resize_area(image, scale),
            [cv2.IMWRITE_JPEG_QUALITY, quality],
        )

    data, scale = fit_bytes(encode, max_bytes)
    with open(dst_path, "wb") as output_file:
        output_file.write(data)
    width = max(1, int(round(image.shape[1] * min(scale, 1.0))))
    note = f"JPEG q{quality} · {describe_scale(scale)} · {width}px"
    if flattened:
        note += " · 透明已合成白底"
    return note, len(data) <= max_bytes


def main(argv: list[str] | None = None) -> int:
    """脚本入口,依次处理全部收集到的静态图片并输出汇总信息"""
    configure_stdout()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.max_size <= 0:
        parser.error("--max-size 必须为正数")
    if not 1 <= args.quality <= 100:
        parser.error("--quality 取值范围为 1-100")
    if not ensure_directories(args.input_dir, args.output_dir):
        return 1
    plan = BatchPlan(
        input_extensions=STATIC_EXTENSIONS,
        output_extension=JPG_EXTENSION,
        max_bytes_for=lambda extension: args.max_size * KB,
        compress_one=lambda src, dst, cap: compress_one(src, dst, cap, args.quality),
    )
    return run_batch(args.input_dir, args.output_dir, args.recursive, plan)


if __name__ == "__main__":
    sys.exit(main())
