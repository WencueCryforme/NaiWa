"""把 catalog/dist 下各级 manifest.json 合并成分类型的 catalog

处理流程:

- 读取 `catalog/dist/manifest.json` 的 `types` 列表
- 对每个类型读取 `catalog/dist/<类型>/manifest.json` 的 `albums` 列表与 `format`
- 逐个读取 `catalog/dist/<类型>/<合集>/manifest.json` 的 `files` 列表与 `format`
- 写出 `catalog/catalog.<类型>.json`

manifest 由 gen_manifest.py 生成,按 dist 的层级镜像存放于 catalog/dist/ 下;
本脚本只读取 dist 目录用于确定层级,不读取 dist 内的 manifest。

产物结构与 manifest 风格保持一致:

```
{"name":"NaiWa-catalog-<类型>","type":"<类型>","format":"<扩展名>","albums":[{"name":"<合集>","format":"<扩展名>","files":["<文件名>"]}]}
```

各级条目均按名称的拼音升序排序(见 pinyin_sort_key),不沿用 manifest 内的顺序,
因此上游 manifest 即使顺序有误,产物仍是升序;输出同样为去除空白符的 JSON,输出
目录缺失时自动创建。缺失任何一级 manifest 时给出提示并返回退出码 2,此时先运行
gen_manifest.py 生成 manifest 即可。

路径说明:所有路径均以脚本所在目录的上级(仓库根目录)为基准解析,不依赖当前
工作目录,也不写入任何绝对路径。

依赖:pypinyin 与标准库,脚本自身即为独立可运行文件(不与他人共用模块,需要
复用的排序键在本文件内自行保留);pypinyin 缺位时在启动阶段报错并给出安装提示。

用法示例:
    python scripts/gen_catalog.py
    python scripts/gen_catalog.py --dist-dir dist --catalog-dir catalog
"""

from __future__ import annotations

import argparse
import json
import os
import sys

try:
    from pypinyin import Style, lazy_pinyin
except ImportError:
    raise SystemExit(
        "缺少依赖 pypinyin,安装方式:\n"
        '    python -m pip install "pypinyin==0.55.0"\n'
        "依赖说明见 scripts/README.md"
    ) from None


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

DEFAULT_DIST_DIR = "dist"
DEFAULT_CATALOG_DIR = "catalog"

# 各级 manifest 按 dist 的层级镜像存放在 catalog/dist/ 下,不放进 dist 本体
DEFAULT_MANIFEST_ROOT = "catalog/dist"

MANIFEST_NAME = "manifest.json"

# JSON 输出为去除空白符的版本:分隔符不带空格,且不写行尾换行
JSON_SEPARATORS = (",", ":")

# 条目排序使用的拼音样式:常规拼音且不带声调,保证排序结果只取决于名称本身
PINYIN_STYLE = Style.NORMAL

CATALOG_NAME_PREFIX = "NaiWa-catalog-"
CATALOG_FILE_PREFIX = "catalog."
CATALOG_FILE_SUFFIX = ".json"


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


def pinyin_sort_key(name: str) -> tuple[list[str], str]:
    """名称的拼音升序比较键

    汉字逐字转为不带声调的拼音音节,非汉字字符原样保留并参与比较,因此排序结果与
    中文使用者按名称升序的直觉一致(等价于 Windows 资源管理器的名称排列);拼音
    相同时以原始名称的码位序作为次键,保证排序结果与目录枚举顺序无关。
    """
    return lazy_pinyin(name, style=PINYIN_STYLE), name


def read_json(path: str):
    """读取 JSON,文件缺失或格式错误时抛出异常"""
    with open(path, encoding="utf-8") as source:
        return json.load(source)


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


def catalog_file_name(type_name: str) -> str:
    """类型对应的 catalog 文件名,例如 meme -> catalog.meme.json"""
    return f"{CATALOG_FILE_PREFIX}{type_name}{CATALOG_FILE_SUFFIX}"


def read_manifest(
    dist_dir: str, manifest_root: str, directory: str, missing: list[str]
) -> dict:
    """读取目录对应 manifest 的条目列表与格式,缺失时记入 missing 并返回空结构"""
    target = mirror_path(dist_dir, manifest_root, directory)
    if not os.path.isfile(target):
        missing.append(relative(target))
        return {"values": [], "format": ""}
    manifest = read_json(target)
    values: list[str] = []
    for key in ("files", "albums", "types"):
        if key in manifest:
            values = list(manifest[key])
            break
    return {"values": values, "format": manifest.get("format", "")}


def build_arg_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器,所有参数均带默认值"""
    parser = argparse.ArgumentParser(
        prog="gen_catalog",
        description="把 catalog/dist 下各级 manifest.json 合并为 catalog/catalog.<类型>.json",
    )
    parser.add_argument(
        "--dist-dir",
        default=DEFAULT_DIST_DIR,
        help=f"dist 目录,相对仓库根目录,默认为 {DEFAULT_DIST_DIR}",
    )
    parser.add_argument(
        "--manifest-root",
        default=DEFAULT_MANIFEST_ROOT,
        help=f"manifest 存放根目录,相对仓库根目录,默认为 {DEFAULT_MANIFEST_ROOT}",
    )
    parser.add_argument(
        "--catalog-dir",
        default=DEFAULT_CATALOG_DIR,
        help=f"catalog 输出目录,相对仓库根目录,默认为 {DEFAULT_CATALOG_DIR}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """脚本入口,按类型合并 manifest 并输出汇总信息"""
    configure_stdout()
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    dist_dir = resolve(args.dist_dir)
    manifest_root = resolve(args.manifest_root)
    catalog_dir = resolve(args.catalog_dir)
    if not os.path.isdir(dist_dir):
        sys.stderr.write(f"错误:dist 目录不存在:{args.dist_dir}\n")
        return 1

    missing: list[str] = []
    dist_manifest = read_manifest(dist_dir, manifest_root, dist_dir, missing)
    types = sorted(dist_manifest["values"], key=pinyin_sort_key)
    if missing:
        for path in missing:
            sys.stderr.write(f"[缺失] {path}\n")
        sys.stderr.write("错误:缺少 dist 级 manifest,请先运行 python scripts/gen_manifest.py\n")
        return 2
    if not types:
        sys.stderr.write("错误:dist 级 manifest 中没有类型条目\n")
        return 2

    written: list[tuple[str, int, int]] = []
    for type_name in types:
        type_dir = os.path.join(dist_dir, type_name)
        type_manifest = read_manifest(dist_dir, manifest_root, type_dir, missing)
        albums = sorted(type_manifest["values"], key=pinyin_sort_key)
        album_entries = []
        for album_name in albums:
            album_dir = os.path.join(type_dir, album_name)
            album_manifest = read_manifest(dist_dir, manifest_root, album_dir, missing)
            album_entries.append(
                {
                    "name": album_name,
                    "format": album_manifest.get("format", ""),
                    "files": sorted(album_manifest["values"], key=pinyin_sort_key),
                }
            )

        data = {
            "name": f"{CATALOG_NAME_PREFIX}{type_name}",
            "type": type_name,
            "format": type_manifest.get("format", ""),
            "albums": album_entries,
        }
        target = os.path.join(catalog_dir, catalog_file_name(type_name))
        size = write_json(target, data)
        written.append((relative(target), len(album_entries), size))

    for path, album_count, size in written:
        print(f"[写出] {path} (合集 {album_count} 个, {size} 字节)")
    if missing:
        for path in missing:
            sys.stderr.write(f"[缺失] {path}\n")
        sys.stderr.write(
            f"错误:有 {len(missing)} 个 manifest 缺失,请先运行 python scripts/gen_manifest.py\n"
        )
        return 2
    print(f"完成:类型 {len(types)} 个,catalog {len(written)} 个。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
