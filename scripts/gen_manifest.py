"""生成 dist 目录各级 manifest.json(输出到 catalog/dist/)

扫描 dist 目录的层级结构,按相同层级在 `catalog/dist/` 下写出 manifest.json,
不把 manifest 放进 dist 本体:

- `catalog/dist/manifest.json`                 -> `types`: dist 下的子目录名列表(类型列表)
- `catalog/dist/<类型>/manifest.json`          -> `albums`: 该类型下的合集目录名列表
- `catalog/dist/<类型>/<合集>/manifest.json`   -> `files`: 该合集内的文件名列表

字段结构与命名沿用仓库已有 manifest 的写法:name 为 `NaiWa-<dist 下目录相对仓库
根目录的路径以 - 连接>-manifest`,dist 根级沿用现有字面量;name 描述的是 dist 下
的路径,与 manifest 自身的存放位置无关。输出为去除空白符的 JSON(分隔符不带空格、
无行尾换行),条目按名称的 Unicode 码位排序,保证同样内容每次生成结果一致;输出
目录缺失时自动逐级创建。

路径说明:所有路径均以脚本所在目录的上级(仓库根目录)为基准解析,不依赖当前
工作目录,也不写入任何绝对路径。

依赖:仅标准库,脚本自身即为独立可运行文件。

用法示例:
    python scripts/gen_manifest.py
    python scripts/gen_manifest.py --dist-dir dist --manifest-root catalog/dist
"""

from __future__ import annotations

import argparse
import json
import os
import sys


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

DEFAULT_DIST_DIR = "dist"

# 各级 manifest 按 dist 的层级镜像存放在 catalog/dist/ 下,不放进 dist 本体
DEFAULT_MANIFEST_ROOT = "catalog/dist"

MANIFEST_NAME = "manifest.json"

# JSON 输出为去除空白符的版本:分隔符不带空格,且不写行尾换行
JSON_SEPARATORS = (",", ":")

MANIFEST_NAME_PREFIX = "NaiWa-"
MANIFEST_NAME_SUFFIX = "-manifest"

# dist 根级 manifest 的 name 字面量(描述 dist 根级类型列表,与存放位置无关)
DIST_ROOT_MANIFEST_NAME = "NaiWa-dist-types-manifest"


def repo_root() -> str:
    """仓库根目录:以脚本所在目录的上级为基准解析,不依赖当前工作目录"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve(path: str) -> str:
    """把相对路径解析为相对仓库根目录的绝对路径,传入绝对路径时原样返回"""
    if os.path.isabs(path):
        return path
    return os.path.join(repo_root(), path)


def relative(path: str) -> str:
    """把路径转换为相对仓库根目录的路径,统一使用正斜杠"""
    return os.path.relpath(path, repo_root()).replace(os.sep, "/")


def mirror_path(source_dir: str, mirror_root: str, directory: str) -> str:
    """把 source_dir 下的目录映射为镜像根目录下的 manifest 路径,层级保持一致

    例如 (dist, catalog/dist, dist/meme/某合集) -> catalog/dist/meme/某合集/manifest.json
    """
    relative_path = os.path.relpath(directory, source_dir)
    if relative_path == os.curdir:
        return os.path.join(mirror_root, MANIFEST_NAME)
    return os.path.join(mirror_root, relative_path, MANIFEST_NAME)


def list_subdirs(directory: str) -> list[str]:
    """列出目录下的子目录名,按名称排序,跳过隐藏目录"""
    if not os.path.isdir(directory):
        return []
    return sorted(
        name
        for name in os.listdir(directory)
        if not name.startswith(".") and os.path.isdir(os.path.join(directory, name))
    )


def list_files(directory: str) -> list[str]:
    """列出目录下的文件名,按名称排序,跳过隐藏文件与 manifest.json 自身"""
    if not os.path.isdir(directory):
        return []
    return sorted(
        name
        for name in os.listdir(directory)
        if not name.startswith(".")
        and name != MANIFEST_NAME
        and os.path.isfile(os.path.join(directory, name))
    )


def write_json(path: str, data) -> int:
    """写出去除空白符的 JSON,返回文件字节数;输出目录缺失时自动逐级创建"""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, separators=JSON_SEPARATORS)
    with open(path, "w", encoding="utf-8", newline="") as output_file:
        output_file.write(text)
    return len(text.encode("utf-8"))


def configure_stdout() -> None:
    """把标准输出与标准错误切到 UTF-8,保证中文名称正常打印"""
    if sys.stdout is not None and hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if sys.stderr is not None and hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def manifest_name(directory: str) -> str:
    """按现有写法生成 manifest 的 name 字段

    规则为 `NaiWa-<dist 下目录相对仓库根目录的路径,以 - 连接>-manifest`;
    dist 根级使用既有字面量
    """
    path_relative = relative(directory)
    if path_relative == DEFAULT_DIST_DIR:
        return DIST_ROOT_MANIFEST_NAME
    return f"{MANIFEST_NAME_PREFIX}{path_relative.replace('/', '-')}{MANIFEST_NAME_SUFFIX}"


def write_manifest(
    dist_dir: str,
    manifest_root: str,
    directory: str,
    key: str,
    values: list[str],
) -> tuple[str, int]:
    """在镜像目录下写出一个 manifest,返回 (相对路径, 字节数)"""
    target = mirror_path(dist_dir, manifest_root, directory)
    size = write_json(target, {"name": manifest_name(directory), key: values})
    return relative(target), size


def find_stale_manifests(dist_dir: str) -> list[str]:
    """列出 dist 本体中残留的 manifest(dist 内不再存放 manifest)"""
    stale: list[str] = []
    for current, dirs, names in os.walk(dist_dir):
        if MANIFEST_NAME in names:
            stale.append(relative(os.path.join(current, MANIFEST_NAME)))
    return sorted(stale)


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器,所有参数均带默认值"""
    parser = argparse.ArgumentParser(
        prog="gen_manifest",
        description="扫描 dist 目录层级结构,在 catalog/dist/ 下生成各级 manifest.json",
    )
    parser.add_argument(
        "--dist-dir",
        default=DEFAULT_DIST_DIR,
        help=f"dist 目录,相对仓库根目录,默认为 {DEFAULT_DIST_DIR}",
    )
    parser.add_argument(
        "--manifest-root",
        default=DEFAULT_MANIFEST_ROOT,
        help=f"manifest 输出根目录,相对仓库根目录,默认为 {DEFAULT_MANIFEST_ROOT}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """脚本入口,逐级生成 manifest 并输出汇总信息"""
    configure_stdout()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    dist_dir = resolve(args.dist_dir)
    manifest_root = resolve(args.manifest_root)
    if not os.path.isdir(dist_dir):
        sys.stderr.write(f"错误:dist 目录不存在:{args.dist_dir}\n")
        return 1
    print(f"扫描 {relative(dist_dir)}/,输出到 {relative(manifest_root)}/")

    written: list[tuple[str, int]] = []
    album_count = 0

    # dist 级:类型列表
    types = list_subdirs(dist_dir)
    written.append(write_manifest(dist_dir, manifest_root, dist_dir, "types", types))

    # 类型级:合集列表;合集级:文件列表
    for type_name in types:
        type_dir = os.path.join(dist_dir, type_name)
        albums = list_subdirs(type_dir)
        album_count += len(albums)
        written.append(
            write_manifest(dist_dir, manifest_root, type_dir, "albums", albums)
        )
        for album_name in albums:
            album_dir = os.path.join(type_dir, album_name)
            written.append(
                write_manifest(
                    dist_dir, manifest_root, album_dir, "files", list_files(album_dir)
                )
            )

    for path, size in written:
        print(f"[写出] {path} ({size} 字节)")
    print(f"完成:类型 {len(types)} 个,合集 {album_count} 个,manifest 共 {len(written)} 个。")

    stale = find_stale_manifests(dist_dir)
    if stale:
        sys.stderr.write(
            f"警告:dist 内仍存在 {len(stale)} 个旧位置的 manifest,请删除:\n"
        )
        for path in stale:
            sys.stderr.write(f"  {path}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
