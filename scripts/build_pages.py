"""构建门户网站静态产物

处理流程:

- 读取 `catalog/dist/manifest.json` 的 `types` 列表与各类型的 `catalog/catalog.<类型>.json`
- 把 `pages/` 下的模板文件复制到 `pages/dist/`
- 把 catalog 数据与构建信息写为 `pages/dist/catalog-data.js`,由前端运行时读取
- 把 `dist/` 媒体按原层级复制到 `pages/dist/files/`(方案甲: 站点根 = pages/dist,
  媒体位于站点根的 files/ 子目录,与模板 main.js 的 DIST_SOURCE = "./files/" 配套)

中文路径说明:catalog-data.js 中保存的是原始中文文件名,媒体 URL 的百分号编码
由前端 main.js 的 encodeKey 逐段调用 encodeURIComponent 完成,生成脚本不做编码,
冒烟测试(temp/pages-template/smoke_test.py)已覆盖中文路径取图。

构建时间说明:BUILD_TIME 取 dist 目录树中最新的文件修改时间并换算为本地时区的
`yyyy-MM-dd HH:mm:ss+HH:mm` 格式,因此同样的 dist 输入重复运行产物一致,
满足幂等要求;该字段的语义是素材内容最后一次变更的时间。

残留说明:本脚本只做覆盖写与新增写,不删除 pages/dist 中的旧文件;若 dist 中
删除了某素材,本地重复构建会在 files/ 中留下残留,脚本会列出这些残留路径提醒
手动处理,GitHub Actions 全新检出的环境下不存在该问题。

路径说明:所有路径均以脚本所在目录的上级(仓库根目录)为基准解析,不依赖当前
工作目录,也不写入任何绝对路径。

依赖:仅标准库,脚本自身即为独立可运行文件。

用法示例:
    python scripts/build_pages.py
    python scripts/build_pages.py --template-dir pages --media-source-dir dist --output-dir pages/dist
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# 全局常量,属于可个性化修改的设计细节,集中在此处便于开发者知悉和维护
# ---------------------------------------------------------------------------

DEFAULT_TEMPLATE_DIR = "pages"
DEFAULT_MEDIA_SOURCE_DIR = "dist"
DEFAULT_OUTPUT_DIR = "pages/dist"
DEFAULT_CATALOG_DIR = "catalog"

# 媒体在站点内相对于站点根(pages/dist)的目录名,与模板 main.js 的 DIST_SOURCE 配套
MEDIA_OUTPUT_NAME = "files"

# 随模板复制进产物根的文件清单(数据文件 catalog-data.js 由本脚本生成,不在其中)
TEMPLATE_FILES = ["index.html", "main.css", "main.js", "favicon.png"]

# 前端数据文件的固定文件名,模板 index.html 按此名称引用
CATALOG_DATA_NAME = "catalog-data.js"

# 站点仓库地址,写入构建信息供关于页展示
SITE_BUILD_REPO = "https://github.com/WencueCryforme/NaiWa"

# 构建信息输出格式:本地时区 yyyy-MM-dd HH:mm:ss+HH:mm
BUILD_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


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


def local_tz() -> timezone:
    """本机时区对象,用于把时间戳换算为带偏移量的本地时间"""
    return datetime.now().astimezone().tzinfo


def format_tz(dt: datetime) -> str:
    """格式化为 yyyy-MM-dd HH:mm:ss+HH:mm,偏移量带冒号"""
    base = dt.strftime(BUILD_TIME_FORMAT)
    offset = dt.utcoffset() or timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    total_minutes = abs(total_minutes)
    return "%s%s%02d:%02d" % (base, sign, total_minutes // 60, total_minutes % 60)


def latest_mtime(directory: str) -> float:
    """返回目录树中最新的文件修改时间,目录不存在或为空时返回 0"""
    latest = 0.0
    for dirpath, dirnames, filenames in os.walk(directory):
        for name in filenames:
            mtime = os.path.getmtime(os.path.join(dirpath, name))
            if mtime > latest:
                latest = mtime
    return latest


def load_types(catalog_dir: str) -> list:
    """读取 dist 根级 manifest 的类型列表,缺失时返回空列表"""
    path = os.path.join(resolve(catalog_dir), "dist", "manifest.json")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("types", [])


def load_catalog_data(catalog_dir: str) -> dict:
    """合并全部类型 catalog 为前端数据结构 {types: [{name, albums}]}"""
    types = load_types(catalog_dir)
    merged = []
    for type_name in types:
        path = os.path.join(resolve(catalog_dir), "catalog.%s.json" % type_name)
        if not os.path.isfile(path):
            print("[缺失] %s,请先运行 gen_catalog.py" % relative(path))
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged.append({"name": type_name, "albums": data.get("albums", [])})
    return {"types": merged}


def write_catalog_data_js(output_dir: str, catalog_data: dict, build_time: str) -> str:
    """把 catalog 数据与构建信息写为前端可加载的 JS 文件,返回相对路径"""
    lines = [
        "/* 由 scripts/build_pages.py 生成,请勿手工编辑 */",
        "window.NAIWA_CATALOG = %s;" % json.dumps(catalog_data, ensure_ascii=False, separators=(",", ":")),
        "window.NAIWA_BUILD = %s;" % json.dumps(
            {"time": build_time, "repo": SITE_BUILD_REPO}, ensure_ascii=False, separators=(",", ":")),
    ]
    path = os.path.join(output_dir, CATALOG_DATA_NAME)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return relative(path)


def copy_template(output_dir: str, template_dir: str) -> list:
    """复制模板文件到产物根,返回已复制的相对路径列表"""
    copied = []
    for name in TEMPLATE_FILES:
        src = os.path.join(resolve(template_dir), name)
        if not os.path.isfile(src):
            print("[缺失] 模板文件 %s,跳过" % relative(src))
            continue
        dst = os.path.join(output_dir, name)
        shutil.copy2(src, dst)
        copied.append(relative(dst))
    return copied


def copy_media(output_dir: str, media_source_dir: str) -> tuple:
    """把 dist 媒体按原层级复制到产物 files/ 目录,返回(数量, 相对路径)"""
    source = resolve(media_source_dir)
    target = os.path.join(output_dir, MEDIA_OUTPUT_NAME)
    count = 0
    for dirpath, dirnames, filenames in os.walk(source):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            src = os.path.join(dirpath, name)
            dst = os.path.join(target, os.path.relpath(src, source))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            count += 1
    return count, relative(target)


def list_stale_files(output_dir: str, media_source_dir: str) -> list:
    """列出产物 files/ 中不存在于 dist 源的残留文件(只提醒,不删除)"""
    source = resolve(media_source_dir)
    target = os.path.join(output_dir, MEDIA_OUTPUT_NAME)
    stale = []
    if not os.path.isdir(target):
        return stale
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for name in filenames:
            if name.startswith("."):
                continue
            src = os.path.join(source, os.path.relpath(os.path.join(dirpath, name), target))
            if not os.path.isfile(src):
                stale.append(relative(os.path.join(dirpath, name)))
    return stale


def build(template_dir: str, media_source_dir: str, output_dir: str, catalog_dir: str) -> int:
    """执行构建,返回进程退出码"""
    output_dir = resolve(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    catalog_data = load_catalog_data(catalog_dir)
    if not catalog_data["types"]:
        print("[错误] catalog 数据为空,请先运行 gen_manifest.py 与 gen_catalog.py")
        return 2

    build_time = format_tz(datetime.fromtimestamp(latest_mtime(resolve(media_source_dir)), local_tz()))

    copied = copy_template(output_dir, template_dir)
    data_path = write_catalog_data_js(output_dir, catalog_data, build_time)
    media_count, media_root = copy_media(output_dir, media_source_dir)
    stale = list_stale_files(output_dir, media_source_dir)

    print("[完成] 模板文件 %d 个, 媒体 %d 个 -> %s" % (len(copied), media_count, relative(output_dir)))
    print("[完成] 数据文件 %s(构建时间 %s)" % (data_path, build_time))
    print("[完成] 媒体根目录 %s" % media_root)
    for path in stale:
        print("[残留] %s(源中已不存在,建议手动清理)" % path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="构建门户网站静态产物到 pages/dist")
    parser.add_argument("--template-dir", default=DEFAULT_TEMPLATE_DIR, help="模板目录(默认 pages)")
    parser.add_argument("--media-source-dir", default=DEFAULT_MEDIA_SOURCE_DIR, help="媒体源目录(默认 dist)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="产物输出目录(默认 pages/dist)")
    parser.add_argument("--catalog-dir", default=DEFAULT_CATALOG_DIR, help="catalog 目录(默认 catalog)")
    args = parser.parse_args()

    return build(args.template_dir, args.media_source_dir, args.output_dir, args.catalog_dir)


if __name__ == "__main__":
    sys.exit(main())
