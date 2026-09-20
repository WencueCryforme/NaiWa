"""构建门户网站静态产物

处理流程:

- 读取 `catalog/dist/manifest.json` 的 `types` 列表与各类型的 `catalog/catalog.<类型>.json`(含 `format` 与 `albums`)
- 把 `pages/` 下的模板文件复制到 `pages/dist/`
- 把 catalog 数据与构建信息写为 `pages/dist/catalog-data.js`,由前端运行时读取
- 把 `dist/` 媒体按原层级复制到 `pages/dist/files/`(方案甲: 站点根 = pages/dist,
  媒体位于站点根的 files/ 子目录,与模板 main.js 的 DIST_SOURCE = "./files/" 配套)

防缓存说明:main.css、main.js、catalog-data.js 每次构建都会在扩展名之前插入一个
8 位随机后缀(字符集 [0-9a-zA-Z],例如 main-0daJbnAW.js),并同步改写产物 index.html
内的引用,使部署后浏览器强制拉取最新产物;上一次构建留下的旧后缀文件会被清理,
产物目录不随构建次数累积。

中文路径说明:catalog-data.js 中保存的是原始中文文件名,媒体 URL 的百分号编码
由前端 main.js 的 encodeKey 逐段调用 encodeURIComponent 完成,生成脚本不做编码,
冒烟测试(temp/pages-template/smoke_test.py)已覆盖中文路径取图。

构建时间说明:BUILD_TIME 取 dist 目录树中最新的文件修改时间并换算为固定的
中国标准时间(UTC+8)的 `yyyy-MM-dd HH:mm:ss+HH:mm` 格式,因此同样的 dist 输入
在本地与 GitHub Actions 上重复运行产物一致,满足幂等要求;该字段的语义是
素材内容最后一次变更的时间。

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
import random
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

# 需要加随机后缀以强制刷新浏览器缓存的文件清单(相对产物根的文件名)
# 每次构建都会为这些文件重新生成随机后缀, 后缀插入在扩展名之前, 例如 main-0daJbnAW.js;
# index.html 内对它们的引用会被同步改写, 因此用户浏览器不会命中旧版缓存
HASHED_FILES = ["main.css", "main.js", "catalog-data.js"]

# 随机后缀的字符集与长度: [0-9a-zA-Z] 取 8 位
CACHE_BUSTER_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
CACHE_BUSTER_LENGTH = 8

# 前端数据文件的固定文件名,模板 index.html 按此名称引用
CATALOG_DATA_NAME = "catalog-data.js"

# 站点仓库地址,写入构建信息供关于页展示
SITE_BUILD_REPO = "https://github.com/WencueCryforme/NaiWa"

# 构建信息输出格式: 固定时区 yyyy-MM-dd HH:mm:ss+HH:mm
BUILD_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"

# 构建时间固定采用的时区(中国标准时间 UTC+8),不取运行机器的本地时区
# 原因: 本地开发机与 GitHub Actions 运行器的本地时区不同,取本地时区会导致
# 同一份 dist 输入在不同环境产出不同的构建时间,破坏产物的确定性
BUILD_TIME_TIMEZONE = timezone(timedelta(hours=8))

# 版本号文件,位于仓库根目录,构建时读入并注入到页脚
DEFAULT_VERSION_FILE = "VERSION"


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


def make_cache_buster() -> str:
    """生成一个随机后缀,用于强制浏览器重新拉取构建产物"""
    return "".join(random.choice(CACHE_BUSTER_ALPHABET) for _ in range(CACHE_BUSTER_LENGTH))


def hashed_name(name: str, suffix: str) -> str:
    """把后缀插入文件名主体与扩展名之间,例如 main.js + 0daJbnAW -> main-0daJbnAW.js"""
    stem, ext = os.path.splitext(name)
    return "%s-%s%s" % (stem, suffix, ext)


def read_text(path: str) -> str:
    """读取文本文件,保持原有换行不被改写"""
    with open(path, "r", encoding="utf-8", newline="") as f:
        return f.read()


def write_text(path: str, text: str) -> None:
    """写出文本文件,不额外追加换行"""
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def rewrite_index_references(output_dir: str, mapping: dict) -> int:
    """把 index.html 中对带后缀文件的引用改为带随机后缀的新名称,返回替换处数

    只按文件名整体匹配, 因此 `main.css` 不会误伤 `main.css.map` 之类;
    引用在模板中同时出现在 <link> 与 <script> 标签里, 一并处理。
    """
    index_path = os.path.join(output_dir, "index.html")
    if not os.path.isfile(index_path):
        print("[缺失] 产物中没有 index.html,跳过引用改写")
        return 0
    text = read_text(index_path)
    count = 0
    for original, renamed in mapping.items():
        # 用引号包裹以精确匹配属性值, 避免子串误替换
        for quote in ('"', "'"):
            needle = quote + original + quote
            replacement = quote + renamed + quote
            occurrences = text.count(needle)
            if occurrences:
                text = text.replace(needle, replacement)
                count += occurrences
    write_text(index_path, text)
    return count


def local_tz() -> timezone:
    """构建时间固定采用的时区(见 BUILD_TIME_TIMEZONE),与运行机器的本地时区无关"""
    return BUILD_TIME_TIMEZONE


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


def read_version(version_file: str) -> str:
    """读取仓库根目录的版本号文件,失败时返回空字符串"""
    try:
        with open(resolve(version_file), "r", encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, IOError):
        return ""


def load_catalog_data(catalog_dir: str) -> dict:
    """合并全部类型 catalog 为前端数据结构 {types: [{name, format, albums}]}"""
    types = load_types(catalog_dir)
    merged = []
    for type_name in types:
        path = os.path.join(resolve(catalog_dir), "catalog.%s.json" % type_name)
        if not os.path.isfile(path):
            print("[缺失] %s,请先运行 gen_catalog.py" % relative(path))
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged.append({
            "name": type_name,
            "format": data.get("format", ""),
            "albums": data.get("albums", []),
        })
    return {"types": merged}


def write_catalog_data_js(output_dir: str, catalog_data: dict, build_time: str, version: str, output_name: str) -> str:
    """把 catalog 数据与构建信息写为前端可加载的 JS 文件,返回相对路径"""
    build_info = {"time": build_time, "repo": SITE_BUILD_REPO}
    if version:
        build_info["version"] = version
    lines = [
        "/* 由 scripts/build_pages.py 生成,请勿手工编辑 */",
        "window.NAIWA_CATALOG = %s;" % json.dumps(catalog_data, ensure_ascii=False, separators=(",", ":")),
        "window.NAIWA_BUILD = %s;" % json.dumps(build_info, ensure_ascii=False, separators=(",", ":")),
    ]
    path = os.path.join(output_dir, output_name)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return relative(path)


def copy_template(output_dir: str, template_dir: str, suffix: str) -> list:
    """复制模板文件到产物根,需要防缓存的文件改名后再写出,返回已复制的相对路径列表"""
    copied = []
    for name in TEMPLATE_FILES:
        src = os.path.join(resolve(template_dir), name)
        if not os.path.isfile(src):
            print("[缺失] 模板文件 %s,跳过" % relative(src))
            continue
        target_name = hashed_name(name, suffix) if name in HASHED_FILES else name
        dst = os.path.join(output_dir, target_name)
        shutil.copy2(src, dst)
        copied.append(relative(dst))
    return copied


def list_old_bundles(output_dir: str, keep: set) -> list:
    """列出产物根下本次未生成、可以清理的旧文件

    每次构建后缀都会变, 旧后缀文件必须清掉, 产物目录才不随构建次数累积;
    同时兼容历史上曾直接以原名输出的产物(例如 main.js), 一并清理。
    只识别 HASHED_FILES 对应的主体, 不会误删 index.html、favicon.png 与媒体目录。
    """
    old = []
    if not os.path.isdir(output_dir):
        return old
    stems = {os.path.splitext(name)[0] for name in HASHED_FILES}
    for name in sorted(os.listdir(output_dir)):
        path = os.path.join(output_dir, name)
        if not os.path.isfile(path) or name in keep:
            continue
        # 旧版直接以原名输出的产物
        if name in HASHED_FILES:
            old.append(relative(path))
            continue
        stem, ext = os.path.splitext(name)
        parts = stem.rsplit("-", 1)
        if len(parts) != 2 or parts[0] not in stems:
            continue
        marker = parts[1]
        if len(marker) == CACHE_BUSTER_LENGTH and all(c in CACHE_BUSTER_ALPHABET for c in marker):
            old.append(relative(path))
    return old


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


def build(template_dir: str, media_source_dir: str, output_dir: str, catalog_dir: str, version_file: str) -> int:
    """执行构建,返回进程退出码"""
    output_dir = resolve(output_dir)
    os.makedirs(output_dir, exist_ok=True)

    catalog_data = load_catalog_data(catalog_dir)
    if not catalog_data["types"]:
        print("[错误] catalog 数据为空,请先运行 gen_manifest.py 与 gen_catalog.py")
        return 2

    build_time = format_tz(datetime.fromtimestamp(latest_mtime(resolve(media_source_dir)), local_tz()))
    version = read_version(version_file)

    # 本次构建的随机后缀: 加在 main.css / main.js / catalog-data.js 上并同步改写 index.html,
    # 保证部署后用户浏览器不会命中旧版缓存
    suffix = make_cache_buster()
    mapping = {name: hashed_name(name, suffix) for name in HASHED_FILES}

    copied = copy_template(output_dir, template_dir, suffix)
    data_path = write_catalog_data_js(
        output_dir, catalog_data, build_time, version, mapping[CATALOG_DATA_NAME]
    )
    replaced = rewrite_index_references(output_dir, mapping)
    media_count, media_root = copy_media(output_dir, media_source_dir)
    stale = list_stale_files(output_dir, media_source_dir)

    # 清理上一次构建留下的旧后缀文件, 避免产物目录随构建次数累积
    old_bundles = list_old_bundles(output_dir, set(mapping.values()))
    for path in old_bundles:
        os.remove(resolve(path))

    print("[完成] 模板文件 %d 个, 媒体 %d 个 -> %s" % (len(copied), media_count, relative(output_dir)))
    print("[完成] 数据文件 %s(构建时间 %s)" % (data_path, build_time))
    print("[完成] 随机后缀 %s,index.html 引用改写 %d 处" % (suffix, replaced))
    print("[完成] 媒体根目录 %s" % media_root)
    for path in old_bundles:
        print("[清理] %s(上一次构建的旧后缀文件)" % path)
    for path in stale:
        print("[残留] %s(源中已不存在,建议手动清理)" % path)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="构建门户网站静态产物到 pages/dist")
    parser.add_argument("--template-dir", default=DEFAULT_TEMPLATE_DIR, help="模板目录(默认 pages)")
    parser.add_argument("--media-source-dir", default=DEFAULT_MEDIA_SOURCE_DIR, help="媒体源目录(默认 dist)")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="产物输出目录(默认 pages/dist)")
    parser.add_argument("--catalog-dir", default=DEFAULT_CATALOG_DIR, help="catalog 目录(默认 catalog)")
    parser.add_argument("--version-file", default=DEFAULT_VERSION_FILE, help="版本号文件(默认 VERSION)")
    args = parser.parse_args()

    return build(args.template_dir, args.media_source_dir, args.output_dir, args.catalog_dir, args.version_file)


if __name__ == "__main__":
    sys.exit(main())
