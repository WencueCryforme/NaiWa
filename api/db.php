<?php
/* ============================================================
   奶蛙宇宙门户统计后端 - SQLite 数据库初始化
   数据库文件位于 api/data/stats.db, 首次访问时自动建库建表
   作者: WencueCryforme <https://github.com/WencueCryforme>
   ============================================================ */

/* 数据库文件目录(相对于本文件所在目录), 已列入 .gitignore */
define('NAIWA_DATA_DIR', __DIR__ . DIRECTORY_SEPARATOR . 'data');
define('NAIWA_DB_FILE', NAIWA_DATA_DIR . DIRECTORY_SEPARATOR . 'stats.db');

/* 返回共享的 PDO SQLite 连接, 建库建表只执行一次 */
function naiwa_db(): PDO
{
    static $pdo = null;
    if ($pdo !== null) {
        return $pdo;
    }
    if (!is_dir(NAIWA_DATA_DIR)) {
        mkdir(NAIWA_DATA_DIR, 0775, true);
    }
    $pdo = new PDO('sqlite:' . NAIWA_DB_FILE);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $pdo->exec('PRAGMA journal_mode = WAL');
    $pdo->exec('PRAGMA busy_timeout = 5000');
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS media_stats ('
        . ' media TEXT PRIMARY KEY,'
        . ' views INTEGER NOT NULL DEFAULT 0,'
        . ' likes INTEGER NOT NULL DEFAULT 0,'
        . ' favorites INTEGER NOT NULL DEFAULT 0'
        . ')'
    );
    return $pdo;
}

/* 把 media 键规范为 "类型/合集/文件" 的原始中文名
 * GET 查询参数已被 PHP 自动解码; POST JSON 里的值仍是逐段百分号编码, 需手动解码 */
function naiwa_media_key(string $media, bool $already_decoded): string
{
    return $already_decoded ? $media : rawurldecode($media);
}
