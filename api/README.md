# 统计后端说明

轻量统计后端, PHP + php-fpm + SQLite 实现, 为门户静态页提供浏览/点赞/收藏计数与热门排行。前端通过 `main.js` 的 `BACKEND_API` 常量指向本后端根地址跨域访问; 该常量留空时前端相关功能自动降级, 详见 `pages/main.js`。

## 文件清单

| 文件 | 职责 |
|:---:|:---|
| `stats.php` | 统一数据接口, 承载全部 GET/POST 路由与跨域响应头 |
| `db.php` | SQLite 连接与建库建表, 数据库文件自动生成于 `data/stats.db` |
| `data/` | 运行时数据目录(含 SQLite 数据库), 已列入 `.gitignore`, 不入库 |

依赖: PHP 7.4 及以上, 需启用 `pdo_sqlite` 扩展(本机 PHP 未加载 php.ini 时可用 `php -c <ini>` 指定启用该扩展的配置文件)。

## 接口契约

所有接口的 `media` 键为 `类型/合集/文件` 形式的媒体标识; GET 查询参数的值由 PHP 自动解码, 前端按逐段百分号编码拼接(`encodeURIComponent` 每段后以 `/` 连接)。

### 批量查询统计

```
GET {BACKEND_API}/stats.php?stats&media[]=<media>&media[]=<media>
```

- 同名参数必须使用 `media[]` 数组语法, PHP 才会解析为数组
- 返回 `{ok: true, stats: [{media, views, likes, favorites}]}`
- 未入库的键补零返回, 保证每个请求键都有对应条目, 顺序与请求顺序一致

### 热门排行

```
GET {BACKEND_API}/stats.php?hot&limit=<数量, 默认 200, 上限 1000>
```

- 返回 `{ok: true, hot: [{media, views, likes, favorites, score}]}`
- `score` 为综合权值 `(views + likes * 2 + favorites * 3) / 6`, 按其降序排列

### 行为上报

```
POST {BACKEND_API}/stats.php
Content-Type: application/json

{"media": "<media>", "action": "view | like | favorite"}
```

- 请求体中的 `media` 为逐段百分号编码值, 由服务端统一解码
- 返回 `{ok: true, stats: {media, views, likes, favorites}}`, 即上报后的最新计数
- 非法请求体或非法 `action` 返回 400

### 跨域

全部响应携带 `Access-Control-Allow-Origin: *`, 并处理 OPTIONS 预检(204)。

## 本地验证

```bash
php -S 127.0.0.1:8125 -t api
```

之后按上面契约直接请求 `http://127.0.0.1:8125/stats.php`; 完整的前后端联调方式见 `temp/api-test/`(临时目录, 不入库)。

## 部署

服务器启用 php-fpm 后把 `api/` 目录指给站点即可; 数据库在首次访问时自动建库建表, 无需手工初始化。前端把 `pages/main.js` 的 `BACKEND_API` 填为后端根地址(例如 `https://example.com/api`)即可启用统计功能。
