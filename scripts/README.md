# 脚本说明

本目录存放表情包压缩与辅助脚本,均为纯 OpenCV(不依赖 Pillow、不依赖 ffmpeg)实现。

## 脚本清单

| 脚本 | 职责 |
|:---:|:---|
| `resize_common.py` | 两份压缩脚本共用的能力: 常量、文件扫描、缩放、上限逼近与批处理流程 |
| `img_resize.py` | 扫描静态图片(png、jpg、jpeg、bmp、webp、tiff、tif、ico),统一输出不大于 500KB 的 jpg,忽略 gif |
| `gif_resize.py` | 扫描 gif 动图,输出不大于 2MB 的 gif,保留全部帧、逐帧时长、循环次数与透明区域 |
| `gen_manifest.py` | 单文件脚本: 扫描 dist 各级结构,按相同层级在 `catalog/dist/` 下生成各级 manifest.json |
| `gen_catalog.py` | 单文件脚本: 合并各级 manifest.json 为 `catalog/catalog.<类型>.json` |
| `build_pages.py` | 单文件脚本: 依据 catalog 与 pages/ 模板构建门户静态产物到 `pages/dist/`, 并把 dist 媒体复制到 `pages/dist/files/` |
| `runPython.bat` | Windows 运行入口: 转发全部参数给 python,并在运行前自检 opencv-python 是否可用 |

## 依赖要求

| 依赖 | 版本要求 | 说明 |
|:---:|:---:|:---|
| Python | 3.9 及以上 | 脚本使用 `X \| None` 等现代类型标注语法 |
| opencv-python | 4.11 及以上 | 4.11 起提供 Animation API(`imreadanimation` / `imwriteanimation`),gif 压缩必需 |
| numpy | 由 opencv-python 自动安装 | 脚本以 numpy 数组承载图像数据 |
| pypinyin | 固定 0.55.0 | manifest 与 catalog 的条目按名称的拼音升序排序,排序结果取决于该库词典,固定版本以保证同一输入再次生成逐字节一致 |

## 安装指令

```bash
pip install --upgrade "opencv-python>=4.11"
```

若同时需要指定 Python 解释器(例如本机存在多个 Python):

```bash
"<Python 可执行文件路径>" -m pip install --upgrade "opencv-python>=4.11"
```

无图形界面的服务器环境可改用 headless 版本,功能一致、体积更小:

```bash
pip install --upgrade "opencv-python-headless>=4.11"
```

压缩脚本之外的 manifest 与 catalog 生成脚本还需要 pypinyin 用于排序,按固定版本安装(版本与工作流一致):

```bash
pip install --upgrade "pypinyin==0.55.0"
```

## 安装后自检

确认版本与 GIF 编解码是否可用(需要输出 `GIF 支持: True`):

```bash
python -c "import cv2, numpy as np; a=cv2.Animation(); a.frames=[np.zeros((8,8,3),np.uint8)]*2; a.durations=[100,100]; print('OpenCV', cv2.__version__); print('GIF 支持:', bool(cv2.imencodeanimation('.gif', a)[0]))"
```

版本低于 4.11,或编译时未启用 GIF 编解码时,`gif_resize.py` 会在启动阶段直接报错并给出升级提示。

## 用法

```bash
python scripts/img_resize.py                           # 默认扫描 .input/,输出到 .output/
python scripts/img_resize.py -R                        # 递归扫描子目录
python scripts/img_resize.py <输入目录> -o <输出目录> -R
python scripts/img_resize.py <输入目录> --max-size 400  # 收紧体积上限,单位 KB
python scripts/img_resize.py <输入目录> --quality 92    # JPEG 质量,默认 90

python scripts/gif_resize.py                           # 只处理 .gif
python scripts/gif_resize.py <输入目录> -o <输出目录> -R --max-size 1024
```

- `-R` 递归扫描时,若输出目录位于输入目录内,脚本会自动跳过输出目录分支
- `img_resize.py` 的处理规则: 源文件未超过上限时**只做格式转换**(重新编码为 jpg,不缩放),超过上限时**转格式并缩小**到上限以内;本身已是 jpg 且未超限的文件原样复制
- `gif_resize.py` 的处理规则: 未超过上限的 gif 原样复制,超过上限的压缩到上限以内,不做格式转换
- 两份脚本各自只处理本格式范围的输入,可在同一目录上分工使用,例如:

```bash
python scripts/img_resize.py dist/meme -o build/img -R
python scripts/gif_resize.py dist/meme -o build/gif -R
```

Windows 下也可以借 `runPython.bat` 作为运行入口,它会转发全部参数:

```bat
scripts\runPython.bat img_resize.py -o .output -R --max-size 400
```

- 解释器固定在文件开头的 `set "PYTHON=python"` 一行;若本机 `python` 指向的解释器没有安装 opencv-python,改这一行即可,例如改成 `set "PYTHON=C:\Program Files\Python\current\python.exe"`
- 运行前会先做一次依赖自检(`"%PYTHON%" -c "import cv2"`),缺失时打印安装提示并以退出码 1 结束
- 结尾的 `pause` 是为双击运行保留的,命令行调用时直接回车即可

## manifest 与 catalog

两个脚本都是**自包含单文件**(不共用模块、互不 import),除排序用的 pypinyin 外只需 Python 标准库,不依赖 opencv-python;所有路径均以仓库根目录为基准解析,与当前工作目录无关;输出目录缺失时自动逐级创建。

```bash
python scripts/gen_manifest.py    # 按 dist 层级生成 catalog/dist/ 下各级 manifest.json
python scripts/gen_catalog.py     # 合并为 catalog/catalog.<类型>.json
```

`gen_manifest.py` 会按 dist 的层级在 `catalog/dist/` 下写出三级 manifest(不写进 dist 本体):

| 位置 | 字段 | 内容 |
|:---:|:---:|:---|
| `catalog/dist/manifest.json` | `types` | dist 下的子目录名列表(类型列表) |
| `catalog/dist/<类型>/manifest.json` | `albums` | 该类型下的合集目录名列表 |
| `catalog/dist/<类型>/<合集>/manifest.json` | `files` | 该合集内的文件名列表 |

`gen_catalog.py` 按类型合并三级 manifest,产物结构与 manifest 风格一致:

```json
{"name":"NaiWa-catalog-meme","type":"meme","albums":[{"name":"奶蛙爆笑合集","files":["奶蛙大笑.gif"]}]}
```

约定与注意事项:

- `name` 字段为 `NaiWa-<dist 下目录相对仓库根目录的路径,以 - 连接>-manifest`;dist 根级字面量为 `NaiWa-dist-types-manifest`(描述 dist 根级的类型列表),该字段描述的是 dist 下的路径,与 manifest 自身的存放位置无关
- 两个脚本的产物均为**去除空白符**的 JSON(分隔符不带空格、无行尾换行),便于体积与 diff 稳定
- 条目按名称的拼音升序排序: 汉字逐字取不带声调的拼音音节,非汉字字符原样参与比较,拼音相同时以原始名称的码位序为准;该顺序与中文读者按名称升序的直觉、Windows 资源管理器的名称排列一致,同样内容每次生成结果逐字节一致
- 产物一律按上述规则重排,manifest 内手工填写的顺序不会被保留;`gen_catalog.py` 也自行排序,不沿用 manifest 的顺序
- 排序结果取决于 pypinyin 的词典,因此该库固定为 0.55.0(工作流与本说明一致);升级版本可能改变条目顺序,升级后需重新生成 catalog
- 合集级 manifest 只登记文件,不登记 `manifest.json` 自身,跳过隐藏文件(以 `.` 开头)
- `gen_manifest.py` 会检查 dist 本体内是否残留旧位置的 manifest,发现时列出路径提醒删除
- `gen_manifest.py` 还会清理 `catalog/dist/` 下已从 dist 中消失的镜像目录: 类型或合集被更名、删除后,旧目录不会被覆盖而会残留,脚本按镜像相对路径到 dist 反查,不存在的目录整棵删除,并自下而上清理因此变空的父目录
- `gen_catalog.py` 发现任何一级 manifest 缺失时会列出缺失路径并返回退出码 2,先运行 `gen_manifest.py` 即可
- `gen_catalog.py` 同样会清理 `catalog/` 下已不再对应任何类型的 `catalog.<旧类型>.json`,避免类型更名后留下空壳;只处理符合该命名规则的文件,不触碰其他文件
- 当 main 分支的 dist 目录或 pages 目录有 push 时,入口工作流 `.github/workflows/while-push-dist-or-pages.yml` 会调用可复用工作流 `.github/workflows/gen-manifest-catalog.yml`,在 GitHub 上依次运行这两个脚本,并以 `github-actions[bot]` 身份把 catalog/ 回传仓库;本地手动运行时按上面的命令顺序执行即可

## 门户构建

`build_pages.py` 也是**自包含单文件**,只需 Python 标准库;路径以仓库根为基准解析,输出目录缺失时自动创建。

```bash
python scripts/build_pages.py    # 读取 catalog 与 pages/ 模板,生成 pages/dist/
```

构建内容:

| 产物 | 来源 | 说明 |
|:---:|:---:|:---|
| `pages/dist/index.html` 等模板文件 | `pages/` | 平铺复制,清单见脚本 `TEMPLATE_FILES` 常量 |
| `pages/dist/catalog-data-<后缀>.js` | `catalog/` | 由脚本生成的前端数据文件,含 catalog 数据与构建信息 |
| `pages/dist/files/` | `dist/` | 媒体按原层级复制,供前端以路径 `/files/` 引用 |

- 构建时间取 dist 目录树中最新的文件修改时间,换算为固定的中国标准时间(UTC+8)的 `yyyy-MM-dd HH:mm:ss+HH:mm`;不取运行机器的本地时区,因此本地与 GitHub Actions 上同样输入重复运行产物一致
- 媒体 URL 的中文百分号编码由前端 `main.js` 运行时完成,数据文件保存原始文件名
- 当 main 分支的 dist 目录有 push 时,入口工作流会在生成 catalog 之后自动调用本脚本并把 `pages/dist/` 部署到 GitHub Pages

### 门户卡片结构

`pages/main.js` 的 `MediaCard` 类负责构建媒体卡片,结构与项目内参考实现一致,自上而下分两层:

| 层 | 类名 | 说明 |
|:---:|:---:|:---|
| 媒体区域 | `card-media-wrap` | 承载图片/视频/音频与卡片内播放控件;固定比例下由 `aspect-ratio` 决定视窗,原始比例下由媒体自身撑开高度 |
| 操作栏 | `control-bar` | 位于卡片底部,与媒体区域分离;按钮由 `createCtrlBtn` 生成 |

- 卡片**不渲染标签横幅**;本项目不使用标签,参考实现中的 `card-label-banner` 一套不予移植
- 操作栏按钮依次为浏览、点赞、收藏、全屏、分享;每个按钮纵向排布 `ctrl-icon` 图标与 `ctrl-count` 计数
- 浏览按钮为只读展示(`.ctrl-btn-static`),不接受点击;点赞与收藏各带 `active-like` / `active-fav` 激活态
- 计数取自后端统计缓存 `statsCache`;后端未启用时以本地点赞/收藏状态兜底,保证激活态与数字自洽;点击时先做本地乐观增减,后端返回后由 `syncCounts` 覆盖为新基准
- 文件名不占卡片版面,由媒体区域的 `title` 悬停提示承担

**媒体填充的两种互斥模式**(`main.css`):

| 模式 | 选择器 | 填充方式 |
|:---:|:---:|:---|
| 固定比例 | `.card-media-wrap:not(.ratio-original) .media-thumb` | `height: 100%` + `object-fit: cover`,居中裁切 |
| 原始比例 | `.card-media-wrap.ratio-original .media-thumb` | `height: auto`,按宽度撑满,宽高比等于素材原始比例 |

两条规则各自写全 `width` / `height` / `object-fit`,**不写成"基类 + 部分覆盖"**。这是照搬参考实现的结构:覆盖规则一旦漏写 `object-fit`,固定模式的 `cover` 会残留到原始比例模式,症状是卡片高度看着正确但画面被裁掉一截。原始比例模式下容器在 `.media-loaded` 之前用 `aspect-ratio: 1` 占位,加载后转 `auto` 由媒体撑开。

**媒体网格采用列容器式 masonry**(`main.css` + `main.js`):

| 层 | 类名 | 说明 |
|:---:|:---:|:---|
| 网格容器 | `grid-container` | 横向 flex 且 `align-items: flex-start`,只负责排列各列 |
| 列容器 | `masonry-col` | 纵向 flex,等宽(`flex: 1 1 0`),卡片紧密相接 |

- 列容器数量即当前列数,由 `ensureColumns` 与 `settings.cols` 对齐;列宽由 `flex` 均分,不再用 CSS 变量 `--cols` 控制
- 卡片由 `appendCard` 轮询追加到各列,保持近似行优先的视觉顺序;列数变化时 `redistribute` 把既有卡片重新分配,卡片实例不销毁只搬动 DOM 节点
- 列高由 `rebalanceGrid` 再平衡:轮询分配在卡片数不被列数整除时必然失衡(如 4 张卡片分 3 列,某列必放 2 张),故按实测高度把最高列中的卡片搬到最低列,且只在能收窄极差时搬动;`scheduleRebalance` 以 300ms 防抖触发,顺带避免用户连续滚动期间重排
- **不得改回 CSS Grid**:网格的行轨道按该行最高卡片取值,原始比例模式下矮卡片会被拉高,多余空间堆在操作栏下方形成空洞(实测单卡可达 200px 以上)
- 卡片高度必须等于 媒体区域 + 操作栏 + 上下边框(2px),任何拉伸都会在卡片内产生死区
- 布局回归由 `.agents/check_masonry.mjs` 覆盖

### 搜索引擎优化资产

门户是客户端渲染的单页应用,初始 HTML 只有一个空容器。不保证执行 JavaScript 的爬虫(含多数 AI 检索爬虫)因此看不到任何素材名、合集名与内容链接。本脚本把全部内容在构建期落进 HTML,产出以下资产:

| 产物 | 说明 |
|:---:|:---|
| `pages/dist/robots.txt` | 允许全部爬虫抓取,并以绝对地址声明 sitemap 位置 |
| `pages/dist/sitemap.xml` | 覆盖首页、类型索引页、合集页与全部媒体直链,每条带 `lastmod` |
| `pages/dist/<类型>/index.html` | 类型索引页,列出该类型全部合集与资源数 |
| `pages/dist/<类型>/<合集>/index.html` | 合集预渲染页,内含 h1、带 `alt` 的素材缩略图、媒体直链、同类型其他合集的真实 `a` 标签内链与面包屑 |

- `index.html` 由构建脚本注入 canonical、Open Graph、Twitter 卡片、`WebSite` 与 `CollectionPage` 结构化数据以及站点级 `h1`;首页不生成站点地图清单区,内容可抓取性由类型索引页与合集预渲染页承担
- 结构化数据统一使用 JSON-LD,覆盖 `WebSite`、`CollectionPage`、`BreadcrumbList`、`ImageObject` 与 `MediaObject`
- **站内路径一律使用站点根绝对路径**:预渲染页位于 `<类型>/<合集>/` 这类深层目录,相对路径会按文档 URL 的目录解析而指向不存在的层级,因此页内链接与图片 `src` 统一写成以 `/` 开头、并带部署子路径前缀 `SITE_PATH_PREFIX`(项目站点为 `/NaiWa-Universe/`)的形式
- **canonical 与 sitemap 的集合类 URL 一律带结尾斜杠**:其磁盘形态是 `<路径>/index.html`,不带斜杠的地址会被 Web 服务器 301 跳到带斜杠的版本,`canonical` 与 `loc` 都不应指向跳转前地址
- 预渲染页**不引入**门户的 `main.css` 与 `main.js`:二者依赖完整门户 DOM(视图容器、设置面板、全屏模态等),在结构精简的预渲染页上会因取不到元素而中断脚本执行;预渲染页只引专用样式 `pages/seo.css`
- 站点基址、部署子路径、站点名称与描述集中在脚本常量 `SITE_BASE_URL`、`SITE_PATH_PREFIX`、`SITE_NAME`、`SITE_DESCRIPTION`、`SITE_KEYWORDS`;切换自建域名时改这几处即可

### 产物文件名与防缓存

`main.css`、`main.js`、`catalog-data.js` 三个文件每次构建都会在文件名主体与扩展名之间插入 8 位随机后缀(字符集 `[0-9a-zA-Z]`),例如 `main-0daJbnAW.js`;`index.html` 中对这三个文件的引用会被同步改写为新文件名。这样每次构建的产物都是全新的 URL,部署后浏览器无法命中旧缓存,会强制拉取最新内容。

- 后缀在**同一次构建内保持一致**(三个文件共用同一个后缀),因此单次构建的产物是一套完整可对应的文件名;跨构建后缀不同,单次构建内部不会出现混搭
- 后缀只在**文件名层面**,不改动 `index.html` 之外的引用位置;`files/` 下的媒体文件名保持原样不受影响(媒体靠 URL 本身区分,且体积大不重复拉取)
- 脚本会顺带清理 `pages/dist/` 根目录下由历史构建留下的同类文件:既包括带其他后缀的旧 `main-<后缀>.css` / `main-<后缀>.js` / `catalog-data-<后缀>.js`,也包括未加后缀的历史产物 `main.css` / `main.js` / `catalog-data.js`,避免产物根随构建次数累积
- 其他模板文件(`index.html`、`favicon.png`、`styles.css` 等)与 `files/` 目录不做改名也不清理,保持覆盖写

## 输出规格

| 级别 | 规格 |
|:---:|:---|
| dist 级 | 已压缩产物,jpg 不大于 500KB、gif 不大于 2MB |
| 上限未达标 | 脚本会打印 `[未达标]` 并让进程返回退出码 2,便于在自动化流程中拦截 |

同一张素材在不同编码方式下的体积对比(692x715 照片类,源 JPEG 26.7KB):

| 输出方式 | 体积 | 相对源 |
|:---:|--:|--:|
| JPEG q90(本脚本默认) | 26.8KB | 100% |
| JPEG q85 | 23.8KB | 89% |
| WebP 有损 q90 | 11.8KB | 44% |
| PNG 无损 | 179.4KB | 673% |

结论: 静态图统一用 JPEG 而非 PNG,是因为照片类素材转无损 PNG 会膨胀到 5-7 倍;JPEG q90 下照片类体积与源文件相当,插画类素材在 500KB 上限内基本能保住原尺寸。

## 实现要点与限制

- **中文路径**: OpenCV 的路径级 API(`imread` / `imwrite` / `imreadanimation`)在 Windows 上不支持非 ASCII 路径,而本仓库素材文件名均为中文,因此脚本统一走字节级 API(`imdecode` / `imencode` / `imdecodeanimation` / `imencodeanimation`)并自行读写文件,调用方无需做额外处理
- **缩放插值**: 统一使用 `INTER_AREA`(面积平均),该插值专为缩小设计,抗混叠与抗摩尔纹表现最好
- **JPEG 质量与分辨率的关系**: 质量越高,同样上限下可保留的尺寸越小;实测 2047px 插画类素材在 q90 下为 454KB(可保原尺寸),q95 下为 744.5KB(需缩到 1651px)。日志会打印实际尺寸与采用的质量
- **有损编码**: JPEG 为有损格式,反复压缩会累积损失,建议始终从 raw 级原始素材生成 dist 级产物,不要对 dist 产物二次压缩
- **gif 编码器**: `IMWRITE_GIF_QUALITY`(1-8)控制调色板大小,`IMWRITE_GIF_SPEED` 自 OpenCV 4.12 起已失效并会被替换为帧时长,脚本不使用该参数;OpenCV 不做帧间差分优化,压缩率不及 gifsicle 等专用工具
- **透明通道**: JPEG 不支持 alpha,alpha 全不透明的素材直接丢弃该通道,存在透明像素时会与白色底合成并在日志中提示;gif 的透明区域与逐帧时长、循环次数一并保留
