"""构建门户网站静态产物

处理流程:

- 读取 `catalog/dist/manifest.json` 的 `types` 列表与各类型的 `catalog/catalog.<类型>.json`(含 `format` 与 `albums`)
- 把 `pages/` 下的模板文件复制到 `pages/dist/`
- 把 catalog 数据与构建信息写为 `pages/dist/catalog-data.js`,由前端运行时读取
- 把 `dist/` 媒体按原层级复制到 `pages/dist/files/`(方案甲: 站点根 = pages/dist,
  媒体位于站点根的 files/ 子目录,与模板 main.js 的 DIST_SOURCE = "./files/" 配套)
- 依据 catalog 为每个「类型/合集」生成一份预渲染静态页,并生成 robots.txt 与 sitemap.xml

搜索引擎优化说明:门户是客户端渲染的单页应用,初始 HTML 只有一个空容器,不保证执行
JavaScript 的爬虫(含多数 AI 检索爬虫)看不到任何素材名、合集名与内容链接。因此本脚本
把全部内容在构建期落进 HTML:

- `pages/dist/<类型>/<合集>/index.html` 是预渲染副本,内含 h1 标题、带 alt 的素材缩略图、
  指向媒体的直链、指向同类型其他合集的真实 a 标签内链、面包屑与集合级 JSON-LD
- `pages/dist/index.html` 由模板改写而来,注入 canonical、Open Graph、Twitter 卡片、
  首页级 JSON-LD、h1 与一份列出全部类型/合集/素材的语义化清单(noscript 与页脚目录区)
- `pages/dist/robots.txt` 与 `pages/dist/sitemap.xml` 覆盖首页、集合页与全部素材直链
- 预渲染页面向用户复用站点模板的 main.css 与 main.js(以根路径绝对地址引用,支持站点
  任意子路径挂载),页脚横幅提示可回到交互式门户;爬虫与无 JS 环境看到的是完整内容

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
import html
import json
import os
import random
import shutil
import sys
from datetime import datetime, timedelta, timezone
from urllib.parse import quote


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
TEMPLATE_FILES = ["index.html", "main.css", "main.js", "seo.css", "favicon.png"]

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
SITE_BUILD_REPO = "https://github.com/WencueCryforme/NaiWa-Universe"

# 站点线上基址(GitHub Pages 默认域名), 用于生成 canonical、Open Graph、sitemap 等需要
# 绝对 URL 的字段; 结尾不带斜杠, 子路径部署时把子路径一并写入(如 ".../NaiWa-Universe")
SITE_BASE_URL = "https://wencuecryforme.github.io/NaiWa-Universe"

# 站点在域名下的部署子路径(项目站点的站点根不在域名根时非空), 结尾带斜杠;
# 预渲染页位于深层目录, 页内一律使用以它开头的站点根绝对路径, 避免相对路径解析错层
SITE_PATH_PREFIX = "/NaiWa-Universe/"

# 站点名称与默认描述, 用于 title 后缀、Open Graph 与 JSON-LD
SITE_NAME = "奶蛙宇宙"
SITE_DESCRIPTION = (
    "奶蛙表情包宇宙在线版, 收录奶蛙、小奶蛙系列表情包动图与静态图, 以及奶蛙爆笑音视频, "
    "按类型与合集在线浏览、支持收藏与热门排序, 全部素材可免费下载。"
)

# 搜索引擎爬虫与普通访客共用的站点级关键字
SITE_KEYWORDS = (
    "奶蛙,奶蛙表情包,奶蛙宇宙,小奶蛙,奶蛙动图,奶蛙gif,表情包大全,"
    "聊天表情包,奶蛙爆笑视频,表情包下载,NaiWa"
)

# 站点主题色, 用于 Open Graph 与 theme-color
SITE_THEME_COLOR = "#3aa675"

# 类型目录名到中文显示名与描述的映射; 未登记的目录名回退为目录名本身
TYPE_META = {
    "meme": {
        "label": "表情包",
        "description": "奶蛙系列表情包动图与静态图, 覆盖爆笑、日常、对称、双枪射手等主题合集。",
    },
    "sound": {
        "label": "音频",
        "description": "奶蛙系列音频素材, 包含爆笑原声与专属背景音乐。",
    },
    "video": {
        "label": "视频",
        "description": "奶蛙系列短视频素材, 包含爆笑、校园生活与神圣合集。",
    },
}

# 媒体扩展名到中文类型名的映射, 用于预渲染页与结构化数据中的描述文案
MEDIA_KIND_LABEL = {
    ".jpg": "静态图", ".jpeg": "静态图", ".png": "静态图", ".webp": "静态图",
    ".gif": "动图",
    ".mp4": "视频", ".webm": "视频", ".mov": "视频", ".mkv": "视频",
    ".mp3": "音频", ".wav": "音频", ".flac": "音频", ".aac": "音频",
    ".ogg": "音频", ".m4a": "音频",
}

# SEO 资产文件名
ROBOTS_NAME = "robots.txt"
SITEMAP_NAME = "sitemap.xml"

# 预渲染页中列出的单页素材上限: 超出部分以纯文字清单继续完整列出, 保证内容不漏
PRERENDER_MEDIA_LIMIT = 48

# 站点级 Open Graph 图片与站点图标
OG_IMAGE_NAME = "favicon.png"

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


# ---------------------------------------------------------------------------
# 搜索引擎优化(SEO)资产: 预渲染页、robots.txt、sitemap.xml 与元数据注入
# ---------------------------------------------------------------------------


def site_base(extra: str = "") -> str:
    """拼接站点绝对基址, extra 为站点内路径(可带尾斜杠, 决定是否为目录型 URL)

    extra 为空或本身以斜杠结尾时按目录型 URL 拼出结尾斜杠; 否则按文件型 URL 处理。
    集合类页面的磁盘形态是 `<路径>/index.html`, 对外规范 URL 必须带尾斜杠, 否则该 URL
    会被 Web 服务器 301 跳到带斜杠的版本, canonical 与 sitemap 的 loc 都不应指向跳转前地址。
    """
    base = SITE_BASE_URL.rstrip("/")
    if not extra:
        return base + "/"
    if extra.endswith("/"):
        return base + "/" + extra.lstrip("/")
    return base + "/" + extra.lstrip("/")


def type_page_url(type_name: str) -> str:
    """类型索引页的绝对 URL, 目录型 URL 必须带尾斜杠"""
    return site_base("%s/" % quote(type_name))


def type_label(type_name: str) -> str:
    """类型目录名对应的中文显示名,未登记的目录名原样返回"""
    meta = TYPE_META.get(type_name)
    return meta["label"] if meta else type_name


def type_description(type_name: str) -> str:
    """类型目录名对应的描述文案,未登记的目录名给出通用描述"""
    meta = TYPE_META.get(type_name)
    if meta:
        return meta["description"]
    return "%s 类型的奶蛙表情包素材合集。" % type_name


def media_kind(file_name: str) -> str:
    """按扩展名给出媒体的中文类型名,用于预渲染页与结构化数据"""
    ext = os.path.splitext(file_name)[1].lower()
    return MEDIA_KIND_LABEL.get(ext, "素材")


def album_path(type_name: str, album_name: str) -> str:
    """合集页在站点内的相对路径,统一使用正斜杠并以斜杠结尾"""
    return "%s/%s/" % (quote(type_name), quote(album_name))


def album_href(type_name: str, album_name: str) -> str:
    """合集页在站点内的站点根绝对路径, 供深层目录页面内链使用"""
    return SITE_PATH_PREFIX + album_path(type_name, album_name)


def type_href(type_name: str) -> str:
    """类型索引页在站点内的站点根绝对路径"""
    return SITE_PATH_PREFIX + "%s/" % quote(type_name)

def album_page_url(type_name: str, album_name: str) -> str:
    """合集页的绝对 URL(作为 canonical 与 sitemap 的 loc), 目录型 URL 必须带尾斜杠"""
    return site_base(album_path(type_name, album_name))


def media_url(key: str) -> str:
    """媒体键(类型/合集/文件)对应的绝对 URL"""
    return site_base("%s/%s" % (MEDIA_OUTPUT_NAME, "/".join(quote(p) for p in key.split("/"))))


def media_rel_url(key: str) -> str:
    """媒体键对应的站点根绝对 URL(带部署子路径前缀)

    预渲染页位于 `<类型>/<合集>/` 这类深层目录, 相对路径会按文档 URL 的目录解析而
    指向不存在的层级, 因此统一以 `/` 开头的站点根绝对路径表达; 站点本身按子路径部署
    (GitHub Pages 项目站点), 故前缀由 SITE_PATH_PREFIX 提供。
    """
    return "%s%s/%s" % (
        SITE_PATH_PREFIX,
        MEDIA_OUTPUT_NAME,
        "/".join(quote(p) for p in key.split("/")),
    )


def item_key(type_name: str, album_name: str, file_name: str) -> str:
    """媒体键: 类型/合集/文件,与前端 main.js 的键格式一致"""
    return "%s/%s/%s" % (type_name, album_name, file_name)


def find_album(catalog_data: dict, type_name: str, album_name: str) -> dict | None:
    """在合并后的 catalog 数据中定位某个合集,不存在时返回 None"""
    for t in catalog_data.get("types", []):
        if t.get("name") != type_name:
            continue
        for album in t.get("albums", []):
            if album.get("name") == album_name:
                return album
    return None


def plain_text(text: str) -> str:
    """把标题类文本中的书名号与引号替换为 空格,便于生成不含标点的描述语"""
    for ch in "《》\u201c\u201d":
        text = text.replace(ch, " ")
    return " ".join(text.split())


def json_ld_script(payload: dict) -> str:
    """把结构化数据渲染为 JSON-LD 的 script 标签,转义 < > & 避免破坏 HTML 解析"""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    raw = raw.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return '<script type="application/ld+json">%s</script>' % raw


def meta_tag(attr: str, key: str, content: str) -> str:
    """渲染单个 meta 标签"""
    return '<meta %s="%s" content="%s">' % (attr, html.escape(key, quote=True), html.escape(content, quote=True))


def sanitize_brand(text: str) -> str:
    """OG 站点名前缀必须用英文括号,避免部分抓取器的解析异常"""
    return text.replace("(", "\\ue002").replace(")", "\\ue003")


def build_breadcrumb_ld(trail: list) -> dict:
    """由 (名称, 绝对URL) 组成的路径构建 BreadcrumbList 结构化数据"""
    elements = []
    for index, (name, url) in enumerate(trail, start=1):
        elements.append({
            "@type": "ListItem",
            "position": index,
            "name": name,
            "item": url,
        })
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": elements}


def build_catalog_ld(name: str, description: str, url: str, keys: list) -> dict:
    """构建 CollectionPage 结构化数据, mainEntity 为包含全部媒体的 ItemList"""
    elements = []
    for position, key in enumerate(keys, start=1):
        file_name = key.split("/")[-1]
        elements.append({
            "@type": "ListItem",
            "position": position,
            "name": os.path.splitext(file_name)[0],
            "item": {
                "@type": "CreativeWork",
                "name": os.path.splitext(file_name)[0],
                "url": media_url(key),
                "encodingFormat": os.path.splitext(file_name)[1].lower().lstrip("."),
            },
        })
    return {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": name,
        "description": description,
        "url": url,
        "inLanguage": "zh-CN",
        "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": site_base()},
        "mainEntity": {"@type": "ItemList", "itemListElement": elements},
    }


def build_media_object_ld(type_name: str, album_name: str, file_name: str) -> dict:
    """单个媒体的结构化数据: 图片记 ImageObject, 音视频记 MediaObject"""
    key = item_key(type_name, album_name, file_name)
    stem = os.path.splitext(file_name)[0]
    kind = media_kind(file_name)
    if kind in ("静态图", "动图"):
        payload = {
            "@context": "https://schema.org",
            "@type": "ImageObject",
            "name": stem,
            "contentUrl": media_url(key),
            "caption": stem,
            "representativeOfPage": False,
            "isPartOf": {"@type": "CollectionPage", "name": album_name, "url": album_page_url(type_name, album_name)},
        }
    else:
        payload = {
            "@context": "https://schema.org",
            "@type": "MediaObject",
            "name": stem,
            "contentUrl": media_url(key),
            "encodingFormat": os.path.splitext(file_name)[1].lower().lstrip("."),
            "isPartOf": {"@type": "CollectionPage", "name": album_name, "url": album_page_url(type_name, album_name)},
        }
    return payload


def site_stylesheet_link() -> str:
    """站点样式表引用: 用根路径绝对地址,兼容站点部署在任意子路径"""
    return "%s/main.css" % SITE_BASE_URL.rstrip("/")


def seo_stylesheet_link() -> str:
    """预渲染页专用样式表引用: 同样使用根路径绝对地址"""
    return "%s/seo.css" % SITE_BASE_URL.rstrip("/")


def render_album_banner(type_name: str, album_name: str) -> str:
    """预渲染页顶部的横幅: 说明这是只读内容页并提供回到交互式门户的出口"""
    return (
        '<div class="seo-banner">'
        '<div class="seo-banner-inner">'
        '<span class="seo-banner-text">合集内容页 · %s / %s</span>'
        '<a class="seo-banner-link" href="%s">回到奶蛙宇宙门户</a>'
        "</div>"
        "</div>"
    ) % (
        html.escape(type_label(type_name)),
        html.escape(album_name),
        html.escape(site_base(), quote=True),
    )


def render_album_links(catalog_data: dict, type_name: str, current_album: str) -> str:
    """同类型其他合集的真实 a 标签内链,供爬虫发现与用户跳转"""
    links = []
    for t in catalog_data.get("types", []):
        if t.get("name") != type_name:
            continue
        for album in t.get("albums", []):
            name = album.get("name", "")
            if not name or name == current_album:
                continue
            links.append(
                '<li><a href="%s">%s</a><span class="seo-count">%d 个资源</span></li>'
                % (html.escape(album_href(type_name, name), quote=True), html.escape(name),
                   len(album.get("files", [])))
            )
    if not links:
        return ""
    return (
        '<nav class="seo-section" aria-label="同类合集">'
        "<h2>同类型的其他合集</h2>"
        '<ul class="seo-link-list">%s</ul>'
        "</nav>"
    ) % "".join(links)


def render_album_media(key: str, stem: str, kind: str) -> str:
    """单个媒体的预渲染卡片: 图片直接内联缩略图, 音视频给出带图标的直链"""
    url = html.escape(media_rel_url(key), quote=True)
    if kind in ("静态图", "动图"):
        return (
            '<figure class="seo-media">'
            '<a href="%s"><img src="%s" alt="%s" loading="lazy" decoding="async"></a>'
            '<figcaption><a href="%s">%s</a><span class="seo-kind">%s</span></figcaption>'
            "</figure>"
        ) % (url, url, html.escape(stem, quote=True), url, html.escape(stem), kind)
    return (
        '<figure class="seo-media seo-media-file">'
        '<a class="seo-file-link" href="%s"><span class="seo-file-icon">%s</span></a>'
        '<figcaption><a href="%s">%s</a><span class="seo-kind">%s</span></figcaption>'
        "</figure>"
    ) % (url, kind, url, html.escape(stem), kind)


def render_album_plain_list(keys: list) -> str:
    """超出缩略图上限的媒体以纯文字链接清单继续完整列出, 保证内容一条不漏"""
    if not keys:
        return ""
    items = []
    for key in keys:
        file_name = key.split("/")[-1]
        stem = os.path.splitext(file_name)[0]
        items.append(
            '<li><a href="%s">%s</a><span class="seo-kind">%s</span></li>'
            % (html.escape(media_rel_url(key), quote=True), html.escape(stem), media_kind(file_name))
        )
    return (
        '<section class="seo-section">'
        "<h2>更多素材</h2>"
        '<ul class="seo-link-list seo-plain-list">%s</ul>'
        "</section>"
    ) % "".join(items)


def render_album_page(catalog_data: dict, type_name: str, album_name: str, album: dict, build_time: str) -> str:
    """生成单个合集的预渲染静态页,返回完整 HTML 文本"""
    files = album.get("files", [])
    keys = [item_key(type_name, album_name, f) for f in files]
    label = type_label(type_name)
    page_url = album_page_url(type_name, album_name)
    title = "%s表情包合集 - 奶蛙宇宙" % album_name
    if type_name != "meme":
        title = "%s%s合集 - 奶蛙宇宙" % (album_name, label)
    counts = {}
    for f in files:
        kind = media_kind(f)
        counts[kind] = counts.get(kind, 0) + 1
    composition = ", ".join("%s %d 个" % (k, v) for k, v in counts.items())
    description = "%s收录 %d 个奶蛙%s素材(%s), 可在线查看与下载。" % (
        plain_text(album_name), len(files), label, composition,
    )
    if len(description) > 150:
        description = description[:148] + "。"
    headline = "%s · %s" % (album_name, label)

    thumb_keys = keys[:PRERENDER_MEDIA_LIMIT]
    rest_keys = keys[PRERENDER_MEDIA_LIMIT:]
    thumbs = "".join(
        render_album_media(k, os.path.splitext(k.split("/")[-1])[0], media_kind(k.split("/")[-1]))
        for k in thumb_keys
    )
    plain = render_album_plain_list(rest_keys)

    ld_blocks = [
        json_ld_script(build_catalog_ld(
            "%s - %s" % (album_name, SITE_NAME),
            description,
            page_url,
            keys,
        )),
        json_ld_script(build_breadcrumb_ld([
            (SITE_NAME, site_base()),
            (label, type_page_url(type_name)),
            (album_name, page_url),
        ])),
    ]
    # 逐条媒体的结构化数据: 节流到缩略图数量, 避免单页 JSON-LD 体积失控
    for key in thumb_keys:
        parts = key.split("/")
        ld_blocks.append(json_ld_script(build_media_object_ld(parts[0], parts[1], parts[2])))

    head = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN" data-theme="light">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>%s</title>" % html.escape(title),
        meta_tag("name", "description", description),
        meta_tag("name", "keywords", "%s,%s,%s" % (album_name, SITE_KEYWORDS, label)),
        meta_tag("name", "theme-color", SITE_THEME_COLOR),
        meta_tag("name", "author", "WencueCryforme"),
        meta_tag("name", "robots", "index, follow"),
        '<link rel="canonical" href="%s">' % html.escape(page_url, quote=True),
        '<link rel="icon" href="%s" type="image/png">' % html.escape(site_base(OG_IMAGE_NAME), quote=True),
        # 只引预渲染页专用样式: 门户的 main.css/main.js 依赖完整门户 DOM, 在此不引入
        '<link rel="stylesheet" href="%s">' % html.escape(seo_stylesheet_link(), quote=True),
        '<meta property="og:type" content="website">',
        meta_tag("property", "og:site_name", sanitize_brand(SITE_NAME)),
        meta_tag("property", "og:title", title),
        meta_tag("property", "og:description", description),
        meta_tag("property", "og:url", page_url),
        meta_tag("property", "og:image", site_base(OG_IMAGE_NAME)),
        meta_tag("property", "og:locale", "zh_CN"),
        '<meta name="twitter:card" content="summary">',
        meta_tag("name", "twitter:title", title),
        meta_tag("name", "twitter:description", description),
    ] + ld_blocks + [
        "</head>",
        '<body class="seo-page">',
    ]

    body = [
        render_album_banner(type_name, album_name),
        '<main class="seo-wrap">',
        '<nav class="seo-crumb" aria-label="面包屑">'
        '<a href="%s">首页</a><span class="seo-sep">/</span>'
        '<a href="%s">%s</a><span class="seo-sep">/</span>'
        '<span class="seo-crumb-current">%s</span></nav>' % (
            html.escape(site_base(), quote=True),
            html.escape(type_href(type_name), quote=True),
            html.escape(label),
            html.escape(album_name),
        ),
        '<header class="seo-head">',
        "<h1>%s</h1>" % html.escape(headline),
        '<p class="seo-lead">%s</p>' % html.escape(description),
        "</header>",
        '<section class="seo-section">',
        "<h2>合集素材（%d）</h2>" % len(files),
        '<div class="seo-grid">%s</div>' % thumbs,
        "</section>",
        plain,
        render_album_links(catalog_data, type_name, album_name),
        '<p class="seo-note">本页为无脚本环境与搜索引擎准备的合集内容页, 交互式浏览请前往 '
        '<a href="%s">奶蛙宇宙门户</a>。素材更新于 %s。</p>' % (
            html.escape(site_base(), quote=True), html.escape(build_time),
        ),
        "</main>",
        '<footer class="seo-footer">'
        '作者 <a href="https://github.com/WencueCryforme" target="_blank" rel="noopener">WencueCryforme</a>'
        ' · 内容以 <a href="%s" target="_blank" rel="noopener">%s</a> 仓库为准'
        "</footer>" % (
            html.escape(SITE_BUILD_REPO, quote=True), html.escape(SITE_BUILD_REPO),
        ),
        "</body>",
        "</html>",
    ]
    return "\n".join(head + body) + "\n"


def render_type_index_page(catalog_data: dict, type_name: str, build_time: str) -> str:
    """生成类型索引页(站点根的 <类型>/index.html),列出该类型全部合集"""
    label = type_label(type_name)
    description = type_description(type_name)
    page_url = type_page_url(type_name)
    title = "%s - %s - 奶蛙宇宙" % (label, "奶蛙系列素材")
    links = []
    total = 0
    for t in catalog_data.get("types", []):
        if t.get("name") != type_name:
            continue
        for album in t.get("albums", []):
            name = album.get("name", "")
            if not name:
                continue
            count = len(album.get("files", []))
            total += count
            links.append(
                '<li><a href="%s">%s</a><span class="seo-count">%d 个资源</span></li>'
                % (html.escape(album_href(type_name, name), quote=True), html.escape(name), count)
            )

    head = [
        "<!DOCTYPE html>",
        '<html lang="zh-CN" data-theme="light">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>%s</title>" % html.escape(title),
        meta_tag("name", "description", "%s 共 %d 个合集, %d 个素材。" % (description, len(links), total)),
        meta_tag("name", "keywords", "%s,%s" % (label, SITE_KEYWORDS)),
        meta_tag("name", "theme-color", SITE_THEME_COLOR),
        meta_tag("name", "robots", "index, follow"),
        '<link rel="canonical" href="%s">' % html.escape(page_url, quote=True),
        '<link rel="icon" href="%s" type="image/png">' % html.escape(site_base(OG_IMAGE_NAME), quote=True),
        # 只引预渲染页专用样式: 门户的 main.css/main.js 依赖完整门户 DOM, 在此不引入
        '<link rel="stylesheet" href="%s">' % html.escape(seo_stylesheet_link(), quote=True),
        '<meta property="og:type" content="website">',
        meta_tag("property", "og:site_name", sanitize_brand(SITE_NAME)),
        meta_tag("property", "og:title", title),
        meta_tag("property", "og:description", description),
        meta_tag("property", "og:url", page_url),
        meta_tag("property", "og:image", site_base(OG_IMAGE_NAME)),
        meta_tag("property", "og:locale", "zh_CN"),
        json_ld_script({
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "%s - %s" % (label, SITE_NAME),
            "description": description,
            "url": page_url,
            "inLanguage": "zh-CN",
            "isPartOf": {"@type": "WebSite", "name": SITE_NAME, "url": site_base()},
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": len(links),
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": index,
                        "name": album.get("name", ""),
                        "url": album_page_url(type_name, album.get("name", "")),
                    }
                    for index, album in enumerate(
                        [a for t in catalog_data.get("types", []) if t.get("name") == type_name
                         for a in t.get("albums", []) if a.get("name")], start=1
                    )
                ],
            },
        }),
        json_ld_script(build_breadcrumb_ld([(SITE_NAME, site_base()), (label, page_url)])),
        "</head>",
        '<body class="seo-page">',
    ]
    body = [
        '<main class="seo-wrap">',
        '<nav class="seo-crumb" aria-label="面包屑">'
        '<a href="%s">首页</a><span class="seo-sep">/</span>'
        '<span class="seo-crumb-current">%s</span></nav>' % (html.escape(site_base(), quote=True), html.escape(label)),
        '<header class="seo-head">',
        "<h1>%s</h1>" % html.escape(label),
        '<p class="seo-lead">%s</p>' % html.escape(description),
        "</header>",
        '<nav class="seo-section" aria-label="合集列表">',
        "<h2>全部合集（%d）</h2>" % len(links),
        '<ul class="seo-link-list">%s</ul>' % "".join(links),
        "</nav>",
        '<p class="seo-note">本页为搜索引擎与无脚本环境准备的索引页, 交互式浏览请前往 '
        '<a href="%s">奶蛙宇宙门户</a>。素材更新于 %s。</p>' % (
            html.escape(site_base(), quote=True), html.escape(build_time),
        ),
        "</main>",
        '<footer class="seo-footer">'
        '作者 <a href="https://github.com/WencueCryforme" target="_blank" rel="noopener">WencueCryforme</a>'
        ' · 内容以 <a href="%s" target="_blank" rel="noopener">%s</a> 仓库为准'
        "</footer>" % (
            html.escape(SITE_BUILD_REPO, quote=True), html.escape(SITE_BUILD_REPO),
        ),
        "</body>",
        "</html>",
    ]
    return "\n".join(head + body) + "\n"


def inject_index_seo(output_dir: str, catalog_data: dict, build_time: str, version: str) -> dict:
    """把首页级 SEO 内容注入产物 index.html,返回注入项计数"""
    index_path = os.path.join(output_dir, "index.html")
    if not os.path.isfile(index_path):
        print("[缺失] 产物中没有 index.html,跳过 SEO 注入")
        return {"meta": 0, "list": 0}

    text = read_text(index_path)
    types = catalog_data.get("types", [])
    total = sum(len(a.get("files", [])) for t in types for a in t.get("albums", []))
    album_count = sum(len(t.get("albums", [])) for t in types)
    type_names = ", ".join(type_label(t.get("name", "")) for t in types if t.get("name"))

    description = SITE_DESCRIPTION
    if len(description) > 150:
        description = description[:148] + "。"

    head_blocks = [
        meta_tag("name", "keywords", SITE_KEYWORDS),
        meta_tag("name", "author", "WencueCryforme"),
        meta_tag("name", "robots", "index, follow, max-image-preview:large"),
        '<link rel="canonical" href="%s">' % html.escape(site_base(), quote=True),
        '<link rel="icon" href="favicon.png" type="image/png">',
        '<meta property="og:type" content="website">',
        meta_tag("property", "og:site_name", sanitize_brand(SITE_NAME)),
        meta_tag("property", "og:title", "%s - 奶蛙表情包在线浏览与下载" % SITE_NAME),
        meta_tag("property", "og:description", description),
        meta_tag("property", "og:url", site_base()),
        meta_tag("property", "og:image", site_base(OG_IMAGE_NAME)),
        meta_tag("property", "og:locale", "zh_CN"),
        '<meta name="twitter:card" content="summary">',
        meta_tag("name", "twitter:title", "%s - 奶蛙表情包在线浏览与下载" % SITE_NAME),
        meta_tag("name", "twitter:description", description),
        '<meta name="twitter:image" content="%s">' % html.escape(site_base(OG_IMAGE_NAME), quote=True),
        json_ld_script({
            "@context": "https://schema.org",
            "@type": "WebSite",
            "name": SITE_NAME,
            "alternateName": "NaiWa",
            "url": site_base(),
            "description": description,
            "inLanguage": "zh-CN",
            "keywords": SITE_KEYWORDS,
            "author": {"@type": "Person", "name": "WencueCryforme", "url": "https://github.com/WencueCryforme"},
            "license": SITE_BUILD_REPO + "/blob/main/LICENSE",
            "publisher": {
                "@type": "Organization",
                "name": SITE_NAME,
                "logo": {"@type": "ImageObject", "url": site_base(OG_IMAGE_NAME)},
            },
            "potentialAction": {
                "@type": "ReadAction",
                "target": {"@type": "EntryPoint", "urlTemplate": site_base()},
            },
        }),
        json_ld_script(build_catalog_ld(
            "%s素材总览" % SITE_NAME,
            description,
            site_base(),
            [item_key(t.get("name", ""), a.get("name", ""), f)
             for t in types for a in t.get("albums", []) for f in a.get("files", [])],
        )),
    ]

    # 1) 标题与描述按内容规模改写,便于搜索结果呈现覆盖范围
    text = text.replace(
        "<title>%s</title>" % SITE_NAME,
        "<title>%s - 奶蛙表情包大全（%d 个素材 %d 个合集）</title>" % (SITE_NAME, total, album_count),
        1,
    )
    text = text.replace(
        'content="奶蛙表情包宇宙在线版',
        'content="%s' % description.replace('"', ""),
        1,
    )
    # 2) 消费模板中的 SEO 占位注释, 避免遗留无用标记
    text = text.replace("<!-- SEO_HEAD -->", "", 1)

    # 3) 全部 meta 与结构化数据插入到 </head> 之前
    if "</head>" in text:
        text = text.replace("</head>", "\n  ".join(head_blocks) + "\n</head>", 1)
        meta_count = len(head_blocks)
    else:
        meta_count = 0

    write_text(index_path, text)
    return {"meta": meta_count, "types": type_names, "total": total}


def write_album_pages(output_dir: str, catalog_data: dict, build_time: str) -> list:
    """为每个类型生成索引页, 为每个合集生成预渲染页, 返回写出的相对路径列表"""
    written = []
    for t in catalog_data.get("types", []):
        type_name = t.get("name", "")
        if not type_name:
            continue
        type_dir = os.path.join(output_dir, type_name)
        os.makedirs(type_dir, exist_ok=True)
        type_index = os.path.join(type_dir, "index.html")
        write_text(type_index, render_type_index_page(catalog_data, type_name, build_time))
        written.append(relative(type_index))
        for album in t.get("albums", []):
            album_name = album.get("name", "")
            if not album_name:
                continue
            album_dir = os.path.join(type_dir, album_name)
            os.makedirs(album_dir, exist_ok=True)
            page = os.path.join(album_dir, "index.html")
            write_text(page, render_album_page(catalog_data, type_name, album_name, album, build_time))
            written.append(relative(page))
    return written


def sitemap_urls(catalog_data: dict) -> list:
    """汇总需要进入 sitemap 的 URL: 首页、类型索引页、合集页与全部媒体直链"""
    urls = [site_base()]
    for t in catalog_data.get("types", []):
        type_name = t.get("name", "")
        if not type_name:
            continue
        urls.append(type_page_url(type_name))
        for album in t.get("albums", []):
            album_name = album.get("name", "")
            if not album_name:
                continue
            urls.append(album_page_url(type_name, album_name))
            for f in album.get("files", []):
                urls.append(media_url(item_key(type_name, album_name, f)))
    return urls


def write_robots(output_dir: str) -> str:
    """写出 robots.txt: 允许全部爬虫抓取, 并声明 sitemap 位置"""
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "Sitemap: %s" % site_base(SITEMAP_NAME),
        "",
    ]
    path = os.path.join(output_dir, ROBOTS_NAME)
    write_text(path, "\n".join(lines))
    return relative(path)


def write_sitemap(output_dir: str, catalog_data: dict, lastmod: str) -> str:
    """写出 sitemap.xml, 覆盖首页、类型索引页、合集页与全部媒体直链"""
    entries = []
    for url in sitemap_urls(catalog_data):
        entries.append(
            "<url><loc>%s</loc><lastmod>%s</lastmod></url>"
            % (html.escape(url, quote=True), html.escape(lastmod))
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    path = os.path.join(output_dir, SITEMAP_NAME)
    write_text(path, body)
    return relative(path)


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

    # SEO 资产: 先注入首页元数据, 再生成类型索引页与合集预渲染页,
    # 最后由汇总的 URL 集合写出 robots.txt 与 sitemap.xml
    seo = inject_index_seo(output_dir, catalog_data, build_time, version)
    album_pages = write_album_pages(output_dir, catalog_data, build_time)
    robots_path = write_robots(output_dir)
    sitemap_path = write_sitemap(output_dir, catalog_data, build_time[:10])

    # 清理上一次构建留下的旧后缀文件, 避免产物目录随构建次数累积
    old_bundles = list_old_bundles(output_dir, set(mapping.values()))
    for path in old_bundles:
        os.remove(resolve(path))

    print("[完成] 模板文件 %d 个, 媒体 %d 个 -> %s" % (len(copied), media_count, relative(output_dir)))
    print("[完成] 数据文件 %s(构建时间 %s)" % (data_path, build_time))
    print("[完成] 随机后缀 %s,index.html 引用改写 %d 处" % (suffix, replaced))
    print("[完成] 媒体根目录 %s" % media_root)
    print("[SEO] 首页注入 meta 与结构化数据 %d 项; 类型: %s"
          % (seo["meta"], seo.get("types", "")))
    print("[SEO] 预渲染页 %d 个(类型索引页与合集内容页)" % len(album_pages))
    print("[SEO] %s 与 %s 已写出" % (robots_path, sitemap_path))
    for path in album_pages:
        print("[SEO] %s" % path)
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
