<?php
/* ============================================================
   奶蛙宇宙门户统计后端 - 统一数据接口
   与前端 main.js 的 apiGet / apiPost 封装对应, 全部接口支持跨域
   作者: WencueCryforme <https://github.com/WencueCryforme>
   接口契约:
     GET  {BACKEND_API}/stats.php?stats&media[]=<encoded>[&media[]=...]
          批量查询统计; 同名参数必须用 media[] 数组语法, PHP 才会解析为数组
          返回 {stats: [{media, views, likes, favorites}]}
     GET  {BACKEND_API}/stats.php?hot&limit=<数量, 默认 200>
          返回 {hot: [{media, views, likes, favorites, score}]}
          score 为综合权值: (views + likes * 2 + favorites * 3) / 6
     POST {BACKEND_API}/stats.php  请求体 {media, action}
          action 取值 view / like / favorite
          返回 {ok: true, stats: {media, views, likes, favorites}}
   media 键为 "类型/合集/文件"; GET 参数已被 PHP 自动解码,
   POST JSON 中的值是逐段百分号编码, 由 db.php 的 naiwa_media_key 统一解码
   部署: 服务器启用 php-fpm 后把本目录指给站点即可, 数据库自动建在 api/data/
   ============================================================ */

require __DIR__ . '/db.php';

header('Access-Control-Allow-Origin: *');
header('Access-Control-Allow-Methods: GET, POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');
header('Content-Type: application/json; charset=utf-8');

if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(204);
    exit;
}

try {
    $pdo = naiwa_db();
} catch (Throwable $e) {
    http_response_code(500);
    echo json_encode(['ok' => false, 'error' => 'database unavailable']);
    exit;
}

/* 输出单条统计行 */
function stats_row(array $row): array
{
    return [
        'media' => $row['media'],
        'views' => (int)$row['views'],
        'likes' => (int)$row['likes'],
        'favorites' => (int)$row['favorites'],
    ];
}

$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET' && isset($_GET['stats'])) {
    /* 批量查询统计 */
    $mediaList = $_GET['media'] ?? [];
    if (!is_array($mediaList)) {
        $mediaList = [$mediaList];
    }
    $mediaList = array_values(array_filter(array_map('strval', $mediaList), 'strlen'));
    $stats = [];
    if ($mediaList) {
        $placeholders = implode(',', array_fill(0, count($mediaList), '?'));
        $stmt = $pdo->prepare("SELECT media, views, likes, favorites FROM media_stats WHERE media IN ($placeholders)");
        $stmt->execute($mediaList);
        $found = [];
        foreach ($stmt->fetchAll() as $row) {
            $found[$row['media']] = stats_row($row);
        }
        /* 未入库的键补零返回, 保证前端每项都有数据 */
        foreach ($mediaList as $media) {
            $stats[] = $found[$media] ?? ['media' => $media, 'views' => 0, 'likes' => 0, 'favorites' => 0];
        }
    }
    echo json_encode(['ok' => true, 'stats' => $stats]);
    exit;
}

if ($method === 'GET' && isset($_GET['hot'])) {
    /* 热门排行: 综合权值降序 */
    $limit = (int)($_GET['limit'] ?? 200);
    $limit = max(1, min($limit, 1000));
    $stmt = $pdo->query(
        'SELECT media, views, likes, favorites,'
        . ' (views + likes * 2.0 + favorites * 3.0) / 6.0 AS score'
        . ' FROM media_stats ORDER BY score DESC LIMIT ' . $limit
    );
    $hot = [];
    foreach ($stmt->fetchAll() as $row) {
        $entry = stats_row($row);
        $entry['score'] = round((float)$row['score'], 4);
        $hot[] = $entry;
    }
    echo json_encode(['ok' => true, 'hot' => $hot]);
    exit;
}

if ($method === 'POST') {
    /* 行为上报: view / like / favorite */
    $body = json_decode(file_get_contents('php://input'), true);
    if (!is_array($body)) {
        http_response_code(400);
        echo json_encode(['ok' => false, 'error' => 'invalid json body']);
        exit;
    }
    $media = naiwa_media_key((string)($body['media'] ?? ''), false);
    $action = (string)($body['action'] ?? '');
    if ($media === '' || !in_array($action, ['view', 'like', 'favorite'], true)) {
        http_response_code(400);
        echo json_encode(['ok' => false, 'error' => 'invalid media or action']);
        exit;
    }
    $columnMap = ['view' => 'views', 'like' => 'likes', 'favorite' => 'favorites'];
    $column = $columnMap[$action];
    $pdo->prepare('INSERT INTO media_stats (media, ' . $column . ') VALUES (:media, 1)'
        . ' ON CONFLICT(media) DO UPDATE SET ' . $column . ' = ' . $column . ' + 1')
        ->execute([':media' => $media]);
    $stmt = $pdo->prepare('SELECT media, views, likes, favorites FROM media_stats WHERE media = :media');
    $stmt->execute([':media' => $media]);
    echo json_encode(['ok' => true, 'stats' => stats_row($stmt->fetch())]);
    exit;
}

http_response_code(400);
echo json_encode(['ok' => false, 'error' => 'unsupported request']);
