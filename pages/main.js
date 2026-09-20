/* ============================================================
   奶蛙宇宙门户 - main.js
   单文件实现: 视图路由, 媒体网格, 懒加载, 无限滚动, 全屏查看,
   本地收藏, 后端统计对接(留空自动降级), 设置面板, 飘窗提醒
   ============================================================ */

(function () {
  'use strict';

  /* ---------- 常量(设计细节集中区, 可个性化调整) ---------- */

  /* 作者信息(宏常量, 页脚渲染来源) */
  const AUTHOR = 'WencueCryforme';
  const AUTHOR_URL = 'https://github.com/WencueCryforme';
  const REPO_URL = 'https://github.com/WencueCryforme/NaiWa';

  /* 后端跨域地址: 留空表示不启用后端, 点赞与热门统计自动禁用并降级提示;
     部署 api/ 后填入其完整根地址即可启用, 例如 "https://example.com/api" */
  const BACKEND_API = '';

  /* 媒体源地址: 默认取站点内 files/ 目录(方案甲);
     备用值 "./dist/"(站点根含 dist 时使用) 与
     "https://raw.githubusercontent.com/WencueCryforme/NaiWa/main/dist/"
     (raw 跨域源, 目录结构与本项目 dist/ 完全一致) */
  const DIST_SOURCE = './files/';

  /* 无限滚动每页卡片数 */
  const PAGE_SIZE = 12;

  /* 无限滚动触发提前量: 加载哨兵进入视口下方该距离内即加载下一页 */
  const SCROLL_MARGIN = '400px';

  /* 卡片媒体懒加载触发提前量: 媒体元素进入视口下方该距离内才开始请求 */
  const LAZY_MARGIN = '200px';

  /* 同一媒体重复打开全屏时的浏览上报冷却期(毫秒), 冷却期内不重复计数 */
  const VIEW_COOLDOWN = 30000;

  /* 列数可选范围; 窄屏(移动端)上限收紧为 2 列 */
  const COLS_MIN = 1;
  const COLS_MAX = 5;
  const COLS_MAX_MOBILE = 2;
  const MOBILE_MAX_WIDTH = 767;

  /* 全屏缩放的步进与上下限 */
  const FS_SCALE_STEP = 1.3;
  const FS_SCALE_MIN = 0.2;
  const FS_SCALE_MAX = 10;

  /* 危险操作确认按钮的等待时长(毫秒) */
  const CONFIRM_TIMEOUT = 3000;

  /* 请求超时毫秒数 */
  const FETCH_TIMEOUT = 8000;

  /* 公告内容: 空字符串则不显示公告栏; 修改内容后所有用户会重新看到公告 */
  const NOTICE = '欢迎来到奶蛙宇宙在线版, 表情包持续更新中';

  /* 主题列表(id 与 main.css 中 html[data-theme] 对应) */
  const THEMES = [
    { id: 'light', name: '简约白' },
    { id: 'dark', name: '简约黑' },
    { id: 'sky', name: '天空蓝' },
    { id: 'pink', name: '可爱粉' },
    { id: 'purple', name: '太空紫' },
    { id: 'green', name: '初春绿' }
  ];

  /* 卡片视窗比例列表(id 为 original 时按原图比例自适应高度) */
  const RATIOS = [
    { id: 'original', name: '原图' },
    { id: '2 / 1', name: '2:1' },
    { id: '16 / 9', name: '16:9' },
    { id: '4 / 3', name: '4:3' },
    { id: '1 / 1', name: '1:1' },
    { id: '4 / 5', name: '4:5' },
    { id: '3 / 4', name: '3:4' },
    { id: '9 / 16', name: '9:16' }
  ];

  /* 窄屏判定, 断点与 main.css 的响应式断点保持一致 */
  const mobileQuery = window.matchMedia('(max-width: ' + MOBILE_MAX_WIDTH + 'px)');
  function maxCols() {
    return mobileQuery.matches ? COLS_MAX_MOBILE : COLS_MAX;
  }

  /* ---------- localStorage 工具 ---------- */
  const store = {
    get(key, fallback) {
      try {
        const v = localStorage.getItem(key);
        return v !== null ? JSON.parse(v) : fallback;
      } catch (e) { return fallback; }
    },
    set(key, value) {
      try { localStorage.setItem(key, JSON.stringify(value)); } catch (e) { /* 忽略配额异常 */ }
    }
  };

  /* ---------- 全局状态 ---------- */
  const catalog = window.NAIWA_CATALOG || { types: [] };
  const buildInfo = window.NAIWA_BUILD || { time: '', repo: '' };
  const backendOn = BACKEND_API !== '';
  const settings = store.get('settings', {
    theme: 'light', cols: 3, ratio: '1 / 1', caption: 1
  });
  /* 窄屏下把历史列数收进可选范围, 避免在手机上沿用桌面端的超宽列数 */
  settings.cols = Math.min(Math.max(Number(settings.cols) || 3, COLS_MIN), maxCols());
  store.set('settings', settings);

  const favorites = store.get('favorites', []);          /* 有序收藏 key 列表, 新收藏位于最前 */
  const favSet = new Set(favorites);
  const favNotified = new Set(store.get('favNotified', []));  /* 已上报过后端的收藏 key, 只增不删 */
  const viewCooldowns = store.get('viewCooldowns', {});       /* key -> 上次浏览上报时间戳 */

  let currentView = store.get('currentView', 'home'); /* home/album/favorites/hot/about */
  let currentType = catalog.types.length ? catalog.types[0].name : '';
  let currentAlbum = null;
  let albumPage = 0;
  let hotPage = 0;
  let hotList = [];
  let degradeToastShown = false;
  let inited = false;              /* 初始化完成标志, 用于识别"重复进入当前视图" */
  let isLoadingPage = false;       /* 分页加载并发锁 */
  let sentinel = null;             /* 无限滚动哨兵元素 */
  const albumItems = [];           /* 当前合集的全部条目缓存 */
  const hotItems = [];

  /* ---------- DOM 引用 ---------- */
  const $ = (id) => document.getElementById(id);
  const dom = {
    tabNav: $('tabNav'), typeNav: $('typeNav'), albumNav: $('albumNav'),
    crumbBar: $('crumbBar'), crumbHome: $('crumbHome'), crumbType: $('crumbType'), crumbAlbum: $('crumbAlbum'),
    noticeBar: $('noticeBar'), noticeText: $('noticeText'), noticeClose: $('noticeClose'),
    albumGrid: $('albumGrid'), albumEmpty: $('albumEmpty'), albumNoMore: $('albumNoMore'),
    favoritesGrid: $('favoritesGrid'), favoritesEmpty: $('favoritesEmpty'),
    hotGrid: $('hotGrid'), hotEmpty: $('hotEmpty'), hotEmptyText: $('hotEmptyText'), hotNoMore: $('hotNoMore'),
    aboutBuildTime: $('aboutBuildTime'), aboutRepo: $('aboutRepo'), siteFooter: $('siteFooter'),
    btnBackTop: $('btnBackTop'),
    fullscreenModal: $('fullscreenModal'), fullscreenClose: $('fullscreenClose'),
    fullscreenWrap: $('fullscreenWrap'), fullscreenMedia: $('fullscreenMedia'), fullscreenCaption: $('fullscreenCaption'),
    zoomIn: $('zoomIn'), zoomOut: $('zoomOut'), zoomReset: $('zoomReset'),
    settingsPanel: $('settingsPanel'), settingsToggle: $('settingsToggle'), settingsClose: $('settingsClose'),
    colSwitch: $('colSwitch'), ratioSwitch: $('ratioSwitch'), themeSwitch: $('themeSwitch'), captionSwitch: $('captionSwitch'),
    guideLayer: $('guideLayer'), guideClose: $('guideClose'),
    toastContainer: $('toastContainer'), brandHome: $('brandHome')
  };

  /* ---------- 飘窗提醒(替代原生弹窗) ---------- */
  function toast(msg, type) {
    const el = document.createElement('div');
    el.className = 'toast' + (type ? ' ' + type : '');
    el.textContent = msg;
    dom.toastContainer.appendChild(el);
    requestAnimationFrame(() => el.classList.add('show'));
    setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => el.remove(), 300);
    }, 2600);
  }

  /* ---------- 后端接口封装(与 api/ 接口契约对应) ----------
   * GET  {BACKEND_API}/stats.php?stats&media[]=<编码后的 key>[&media[]=...]
   *      批量查询统计; 同名参数必须用 media[] 数组语法, PHP 才会解析为数组
   *      返回 { stats: [{ media, views, likes, favorites }] }
   * GET  {BACKEND_API}/stats.php?hot&limit=<数量>
   *      返回 { hot: [{ media, views, likes, favorites, score }] }, media 为原始键
   * POST {BACKEND_API}/stats.php  请求体 { media, action }
   *      action 取值 view / like / favorite, 返回 { ok, stats }
   * media 为 "类型/合集/文件" 逐段百分号编码后的值 */
  function encodeKey(key) {
    return key.split('/').map(encodeURIComponent).join('/');
  }
  function apiGet(path) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
    return fetch(BACKEND_API + path, { signal: ctrl.signal })
      .finally(() => clearTimeout(timer))
      .then((r) => { if (!r.ok) throw new Error('http ' + r.status); return r.json(); });
  }
  function apiPost(path, body) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT);
    return fetch(BACKEND_API + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: ctrl.signal
    }).finally(() => clearTimeout(timer))
      .then((r) => { if (!r.ok) throw new Error('http ' + r.status); return r.json(); });
  }
  function reportAction(key, action) {
    if (!backendOn) return;
    apiPost('/stats.php', { media: encodeKey(key), action: action })
      .catch(() => { /* 静默失败, 本地体验不受影响 */ });
  }
  /* 浏览上报: 同一媒体在冷却期内重复打开只计一次 */
  function recordView(key) {
    if (!backendOn) return;
    const now = Date.now();
    if (now - (viewCooldowns[key] || 0) < VIEW_COOLDOWN) return;
    viewCooldowns[key] = now;
    store.set('viewCooldowns', viewCooldowns);
    reportAction(key, 'view');
  }
  /* 收藏上报: 同一媒体只上报一次, 取消收藏不抵消已计数值 */
  function reportFavorite(key) {
    if (!backendOn || favNotified.has(key)) return;
    favNotified.add(key);
    store.set('favNotified', Array.from(favNotified));
    reportAction(key, 'favorite');
  }
  function fetchHot() {
    if (!backendOn) return Promise.reject(new Error('backend off'));
    return apiGet('/stats.php?hot&limit=200').then((data) => data.hot || []);
  }
  /* 后端关闭时的统一降级提示, 每次会话只提示一次 */
  function degradeNotice() {
    if (backendOn || degradeToastShown) return;
    degradeToastShown = true;
    toast('统计服务未启用, 点赞与热门功能已降级', 'degrade');
  }

  /* ---------- 目录工具 ---------- */
  function findType(name) {
    return catalog.types.find((t) => t.name === name) || null;
  }
  function findAlbum(typeName, albumName) {
    const t = findType(typeName);
    return t ? (t.albums.find((a) => a.name === albumName) || null) : null;
  }
  function albumItemsOf(typeName, albumName) {
    const album = findAlbum(typeName, albumName);
    if (!album) return [];
    const format = album.format || '';
    return album.files.map((file) => ({
      key: typeName + '/' + albumName + '/' + file,
      type: typeName, album: albumName, file: file, format: format
    }));
  }
  function itemByKey(key) {
    const parts = key.split('/');
    if (parts.length !== 3) return null;
    return { key: key, type: parts[0], album: parts[1], file: parts[2], format: '' };
  }
  function mediaUrl(item) {
    return DIST_SOURCE + encodeKey(item.key);
  }
  function fileExt(name) {
    const i = name.lastIndexOf('.');
    return i >= 0 ? name.slice(i).toLowerCase() : '';
  }
  function mediaTypeOf(item) {
    const ext = (item.format || fileExt(item.file)).toLowerCase();
    if (['.mp4', '.webm', '.mov', '.mkv'].indexOf(ext) >= 0) return 'video';
    if (['.mp3', '.wav', '.flac', '.aac', '.ogg', '.m4a'].indexOf(ext) >= 0) return 'audio';
    return 'image';
  }

  /* ---------- 分享与深链 ---------- */
  /* 媒体键(类型/合集/文件)中的 / 在 URL 里会与路径分隔语义冲突, 故编码为 which 参数时换成 __ */
  function keyToWhich(key) {
    return key.replace(/\//g, '__');
  }
  function buildShareUrl(item) {
    const base = window.location.origin + window.location.pathname;
    return base + '?which=' + encodeURIComponent(keyToWhich(item.key));
  }
  function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.top = '-1000px';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        resolve();
      } catch (err) { reject(err); }
    });
  }
  function copyShareLink(item) {
    copyToClipboard(buildShareUrl(item))
      .then(() => toast('分享链接已复制到剪贴板'))
      .catch(() => toast('复制失败, 请手动复制地址栏链接'));
  }
  /* 解析 ?which= 深链: 还原为媒体键并校验目录真实存在, 不存在则返回 null */
  function parseWhichKey() {
    const params = new URLSearchParams(window.location.search);
    const raw = params.get('which');
    if (!raw) return null;
    const key = decodeURIComponent(raw).replace(/__/g, '/');
    const item = itemByKey(key);
    if (!item) return null;
    const album = findAlbum(item.type, item.album);
    if (!album || album.files.indexOf(item.file) < 0) return null;
    return item;
  }
  /* 应用深链: 打开对应合集并定位到目标卡片, 解析完成后清理地址栏参数回退干净 URL */
  function applyWhichDeepLink() {
    const item = parseWhichKey();
    if (!item) return;
    /* 经分享链接进入的访客直接看内容, 不展示首次引导层 */
    dom.guideLayer.hidden = true;
    openAlbum(item.type, item.album);
    const targetIndex = albumItems.findIndex((i) => i.key === item.key);
    if (targetIndex >= 0) {
      /* 加载足够分页, 使目标卡片进入 DOM, 再滚动到视野中央 */
      while (albumPage * PAGE_SIZE <= targetIndex) {
        if (albumPage * PAGE_SIZE >= albumItems.length) break;
        loadAlbumPage();
      }
      const card = dom.albumGrid.querySelector('[data-key="' + item.key + '"]');
      if (card) card.scrollIntoView({ block: 'center' });
    }
    /* 解析完成后立即清理地址栏的 which 参数, 回退为干净 URL(不刷新页面) */
    const cleanSearch = new URLSearchParams(window.location.search);
    cleanSearch.delete('which');
    const qs = cleanSearch.toString();
    history.replaceState(null, '', window.location.pathname + (qs ? '?' + qs : ''));
    openFullscreen(item);
  }

  /* ---------- 设置应用 ---------- */
  function applySettings() {
    document.documentElement.dataset.theme = settings.theme;
    document.querySelectorAll('.grid-container').forEach((g) => {
      g.style.setProperty('--cols', settings.cols);
    });
    document.querySelectorAll('.media-thumb-wrap').forEach((w) => {
      if (settings.ratio === 'original') {
        w.style.removeProperty('--ratio');
        w.classList.add('ratio-original');
      } else {
        w.style.setProperty('--ratio', settings.ratio);
        w.classList.remove('ratio-original');
      }
    });
    document.querySelectorAll('.media-caption').forEach((c) => {
      c.style.display = settings.caption ? '' : 'none';
    });
  }

  /* ---------- 媒体卡片 ----------
     采用实例化卡片(MediaCard)而非纯函数构建, 原因:
     - 卡片需要持有自身媒体元素与加载观察者, 视图切换后复用实例可避免重复请求与重复解码
     - 媒体失败时需要能禁用该卡片, 而不是留下永久裂图
     实例登记在 cardInstances 中, 以媒体键为索引 */

  const cardInstances = new Map();

  /* 时长格式化: 秒 -> m:ss, 用于卡片控制栏与全屏播放器 */
  function formatTime(sec) {
    if (!isFinite(sec) || sec < 0) sec = 0;
    const total = Math.floor(sec);
    const m = Math.floor(total / 60);
    const s = total % 60;
    return m + ':' + (s < 10 ? '0' + s : s);
  }

  class MediaCard {
    constructor(item, opts) {
      opts = opts || {};
      this.item = item;
      this.kind = mediaTypeOf(item);
      this.observer = null;
      this.playerBar = null;
      this.playOverlay = null;
      this.failed = false;

      const card = document.createElement('div');
      card.className = 'media-card';
      card.dataset.key = item.key;

      /* 媒体区域: 懒加载与播放控件的挂载点 */
      const wrap = document.createElement('div');
      wrap.className = 'media-thumb-wrap';
      wrap.title = item.file;
      this.wrap = wrap;

      const media = this.buildMedia();
      this.media = media;
      wrap.appendChild(media);

      if (this.kind === 'video' || this.kind === 'audio') {
        this.buildCardPlayer();
      }
      buildCardActions(wrap, item);

      wrap.addEventListener('click', (e) => {
        /* 控制栏与悬浮按钮自行 stopPropagation, 到达这里的点击才进入全屏 */
        if (this.failed) return;
        openFullscreen(item);
      });
      card.appendChild(wrap);

      const cap = document.createElement('div');
      cap.className = 'media-caption';
      cap.textContent = item.file;
      card.appendChild(cap);

      if (opts.rank) {
        const rank = document.createElement('span');
        rank.className = 'media-rank';
        rank.textContent = opts.rank;
        card.appendChild(rank);
      }

      this.el = card;
      cardInstances.set(item.key, this);
    }

    /* 按类型创建媒体元素; 图片走 data-src 懒加载, 视频音频走元数据预加载 */
    buildMedia() {
      const item = this.item;
      if (this.kind === 'video' || this.kind === 'audio') {
        const el = document.createElement(this.kind);
        el.className = 'media-thumb card-media' + (this.kind === 'video' ? ' media-video' : ' audio-el');
        el.preload = 'metadata';
        el.playsInline = true;
        el.controls = false;
        if (this.kind === 'video') el.muted = true;
        el.src = mediaUrl(item);
        el.addEventListener('loadedmetadata', () => {
          this.wrap.classList.add('media-loaded');
          if (this.playerBar) {
            this.playerBar.time.textContent = '0:00 / ' + formatTime(el.duration);
          }
        });
        el.addEventListener('error', () => this.markFailed());
        return el;
      }
      const img = document.createElement('img');
      img.className = 'media-thumb card-media loading';
      img.alt = item.file;
      img.dataset.src = mediaUrl(item);
      img.addEventListener('load', () => {
        img.classList.remove('loading');
        img.classList.add('loaded');
        this.wrap.classList.add('media-loaded');
      });
      img.addEventListener('error', () => this.markFailed());
      this.observeLazy(img);
      return img;
    }

    /* 图片进入视口附近才真正发起请求, 加载后断开观察, 避免一次性请求全部素材 */
    observeLazy(img) {
      if (!('IntersectionObserver' in window)) {
        img.src = img.dataset.src;
        return;
      }
      this.observer = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          if (img.dataset.src && !img.src) img.src = img.dataset.src;
          this.disconnectObserver();
          break;
        }
      }, { rootMargin: LAZY_MARGIN });
      this.observer.observe(img);
    }

    disconnectObserver() {
      if (!this.observer) return;
      this.observer.disconnect();
      this.observer = null;
    }

    /* 卡片内视频音频播放控件: 中心播放遮罩 + 底部播放栏 */
    buildCardPlayer() {
      const el = this.media;
      const overlay = document.createElement('div');
      overlay.className = 'card-play-overlay';
      overlay.innerHTML = '&#9654;';
      overlay.title = '播放';
      overlay.addEventListener('click', (e) => {
        e.stopPropagation();
        if (el.paused) el.play(); else el.pause();
      });
      this.playOverlay = overlay;
      this.wrap.appendChild(overlay);

      const bar = document.createElement('div');
      bar.className = 'card-player-bar';
      bar.innerHTML =
        '<button class="card-ctrl-play" title="播放">&#9654;</button>' +
        '<div class="card-ctrl-progress-wrap"><div class="card-ctrl-buffered"></div><div class="card-ctrl-progress"></div></div>' +
        '<span class="card-ctrl-time">0:00</span>' +
        '<button class="card-ctrl-mute" title="静音">&#128266;</button>';
      bar.addEventListener('click', (e) => e.stopPropagation());
      this.wrap.appendChild(bar);
      this.playerBar = {
        root: bar,
        time: bar.querySelector('.card-ctrl-time'),
        progress: bar.querySelector('.card-ctrl-progress'),
        buffered: bar.querySelector('.card-ctrl-buffered'),
        play: bar.querySelector('.card-ctrl-play'),
        mute: bar.querySelector('.card-ctrl-mute')
      };

      this.playerBar.play.addEventListener('click', () => {
        if (el.paused) el.play(); else el.pause();
      });
      /* 点击进度条按横向位置跳转 */
      const progressWrap = bar.querySelector('.card-ctrl-progress-wrap');
      progressWrap.addEventListener('click', (e) => {
        if (!el.duration) return;
        const rect = progressWrap.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        el.currentTime = ratio * el.duration;
      });
      /* 静音切换仅对视频生效; 音频卡片隐藏该按钮 */
      this.playerBar.mute.addEventListener('click', () => {
        el.muted = !el.muted;
        this.playerBar.mute.innerHTML = el.muted ? '&#128263;' : '&#128266;';
      });
      if (this.kind !== 'video') this.playerBar.mute.style.display = 'none';

      el.addEventListener('play', () => {
        overlay.style.display = 'none';
        bar.classList.add('visible');
        this.playerBar.play.innerHTML = '&#10074;&#10074;';
      });
      el.addEventListener('pause', () => {
        if (el.seeking) return;
        overlay.style.display = '';
        bar.classList.remove('visible');
        this.playerBar.play.innerHTML = '&#9654;';
      });
      el.addEventListener('ended', () => {
        overlay.style.display = '';
        bar.classList.remove('visible');
        this.playerBar.play.innerHTML = '&#9654;';
        this.playerBar.progress.style.width = '0%';
        this.playerBar.time.textContent = '0:00 / ' + formatTime(el.duration);
      });
      el.addEventListener('timeupdate', () => {
        if (!el.duration) return;
        this.playerBar.progress.style.width = (el.currentTime / el.duration * 100) + '%';
        this.playerBar.time.textContent = formatTime(el.currentTime) + ' / ' + formatTime(el.duration);
      });
      el.addEventListener('progress', () => {
        if (el.buffered.length > 0 && el.duration) {
          this.playerBar.buffered.style.width =
            (el.buffered.end(el.buffered.length - 1) / el.duration * 100) + '%';
        }
      });
    }

    /* 媒体加载失败: 给出可见占位并禁用卡片交互, 避免误点进入空全屏 */
    markFailed() {
      this.failed = true;
      this.wrap.classList.add('thumb-failed');
      this.el.classList.add('card-disabled');
      this.disconnectObserver();
      /* 停止音频视频的在途加载, 释放网络与解码资源 */
      if (this.media && (this.kind === 'video' || this.kind === 'audio')) {
        this.media.pause();
        this.media.removeAttribute('src');
        this.media.load();
      }
      /* 图片失败仅移除 src, 不重新赋回 data-src, 避免触发无限重试 */
      if (this.media && this.kind === 'image') this.media.removeAttribute('src');
    }

    /* 视图复用时的状态同步: 懒加载图片在再次进入视图时立即补齐 */
    syncState() {
      const el = this.media;
      if (el && el.tagName === 'IMG' && !el.src && el.dataset.src) {
        el.src = el.dataset.src;
        this.disconnectObserver();
      }
    }

    destroy() {
      this.disconnectObserver();
      if (this.media && (this.kind === 'video' || this.kind === 'audio')) {
        this.media.pause();
        this.media.removeAttribute('src');
      }
      this.el.remove();
      cardInstances.delete(this.item.key);
    }
  }

  /* 卡片悬浮操作按钮(收藏/分享), 与媒体区域解耦, 便于复用 */
  function buildCardActions(wrap, item) {
    const fav = document.createElement('button');
    fav.className = 'media-fav' + (favSet.has(item.key) ? ' on' : '');
    fav.innerHTML = '&#9733;';
    fav.title = favSet.has(item.key) ? '取消收藏' : '收藏';
    fav.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleFavorite(item);
      fav.classList.toggle('on', favSet.has(item.key));
      fav.title = favSet.has(item.key) ? '取消收藏' : '收藏';
    });
    wrap.appendChild(fav);

    const share = document.createElement('button');
    share.className = 'media-share';
    share.title = '复制分享链接';
    share.setAttribute('aria-label', '复制分享链接');
    share.innerHTML = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-1 1"/><path d="M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l1-1"/></svg>';
    share.addEventListener('click', (e) => {
      e.stopPropagation();
      copyShareLink(item);
    });
    wrap.appendChild(share);
  }

  /* 创建或复用卡片: 已登记且仍在 DOM 中的实例直接返回, 否则新建 */
  function createMediaCard(item, opts) {
    const existing = cardInstances.get(item.key);
    if (existing && existing.el.isConnected) {
      existing.syncState();
      return existing.el;
    }
    return new MediaCard(item, opts).el;
  }

  /* 清空一个网格并销毁其下全部卡片实例, 释放播放中的媒体与未触发的懒加载观察者 */
  function clearGrid(grid) {
    if (!grid) return;
    grid.querySelectorAll('.media-card').forEach((el) => {
      const inst = cardInstances.get(el.dataset.key);
      if (inst && inst.el === el) inst.destroy();
    });
    grid.innerHTML = '';
  }

  /* ---------- 首页视图 ---------- */
  function renderHome() {
    dom.typeNav.innerHTML = '';
    catalog.types.forEach((t) => {
      const btn = document.createElement('button');
      btn.className = 'type-btn' + (t.name === currentType ? ' active' : '');
      btn.textContent = t.name;
      btn.addEventListener('click', () => {
        currentType = t.name;
        renderHome();
      });
      dom.typeNav.appendChild(btn);
    });

    dom.albumNav.innerHTML = '';
    const type = findType(currentType);
    (type ? type.albums : []).forEach((album) => {
      const card = document.createElement('div');
      card.className = 'album-card';
      const name = document.createElement('p');
      name.className = 'album-name';
      name.textContent = album.name;
      const count = document.createElement('p');
      count.className = 'album-count';
      count.textContent = album.files.length + ' 个资源';
      card.appendChild(name);
      card.appendChild(count);
      card.addEventListener('click', () => openAlbum(currentType, album.name));
      dom.albumNav.appendChild(card);
    });
  }

  /* ---------- 合集视图(懒加载 + 无限滚动) ---------- */
  function openAlbum(typeName, albumName) {
    currentType = typeName;
    currentAlbum = albumName;
    albumItems.length = 0;
    albumItems.push.apply(albumItems, albumItemsOf(typeName, albumName));
    albumPage = 0;
    clearGrid(dom.albumGrid);
    dom.albumEmpty.hidden = true;
    dom.albumNoMore.hidden = true;
    dom.crumbType.textContent = typeName;
    dom.crumbAlbum.textContent = albumName;
    switchView('album');
    loadAlbumPage();
  }
  function loadAlbumPage() {
    if (isLoadingPage) return;
    isLoadingPage = true;
    const start = albumPage * PAGE_SIZE;
    if (start < albumItems.length) {
      albumItems.slice(start, start + PAGE_SIZE).forEach((item) => {
        dom.albumGrid.appendChild(createMediaCard(item));
      });
      albumPage += 1;
      applySettings();
    }
    const allLoaded = albumPage * PAGE_SIZE >= albumItems.length;
    /* 空合集与到底提示互斥, 避免空合集也显示"已经到底了" */
    dom.albumEmpty.hidden = albumItems.length > 0;
    dom.albumNoMore.hidden = albumItems.length === 0 || !allLoaded;
    isLoadingPage = false;
    if (!allLoaded) armSentinel();
  }

  /* ---------- 收藏视图 ---------- */
  function toggleFavorite(item) {
    if (favSet.has(item.key)) {
      favSet.delete(item.key);
      const idx = favorites.indexOf(item.key);
      if (idx >= 0) favorites.splice(idx, 1);
      toast('已取消收藏');
    } else {
      favSet.add(item.key);
      favorites.unshift(item.key);   /* 新收藏置顶, 与收藏视图顺序一致 */
      toast('已收藏');
      reportFavorite(item.key);
    }
    store.set('favorites', favorites);
    if (currentView === 'favorites') renderFavorites();
  }
  function renderFavorites() {
    clearGrid(dom.favoritesGrid);
    const items = favorites.map(itemByKey).filter(Boolean);
    dom.favoritesEmpty.hidden = items.length > 0;
    const clearBar = document.getElementById('favoritesBar');
    if (clearBar) clearBar.remove();
    if (items.length > 0) {
      const bar = document.createElement('div');
      bar.className = 'favorites-bar';
      bar.id = 'favoritesBar';
      const label = document.createElement('span');
      label.className = 'favorites-count';
      label.textContent = '共 ' + items.length + ' 个收藏';
      bar.appendChild(label);
      const clear = document.createElement('button');
      clear.className = 'clear-btn';
      clear.textContent = '清空收藏';
      clear.addEventListener('click', () => {
        confirmButton(clear, '确认清空', () => {
          favSet.clear();
          favorites.length = 0;
          store.set('favorites', favorites);
          renderFavorites();
          toast('收藏已清空');
        });
      });
      bar.appendChild(clear);
      dom.favoritesGrid.parentNode.insertBefore(bar, dom.favoritesGrid);
    }
    items.forEach((item) => dom.favoritesGrid.appendChild(createMediaCard(item)));
    applySettings();
  }

  /* ---------- 危险操作确认: 按钮替换流程 ----------
     首次点击替换为确认文案, 等待期内再次点击才执行, 超时或点击别处即回归初始状态 */
  function confirmButton(btn, confirmText, onConfirm) {
    if (btn.classList.contains('confirming')) {
      resetConfirmButton(btn);
      onConfirm();
      return;
    }
    btn.dataset.label = btn.textContent;
    btn.textContent = confirmText;
    btn.classList.add('confirming');
    btn._confirmTimer = setTimeout(() => resetConfirmButton(btn), CONFIRM_TIMEOUT);
  }
  function resetConfirmButton(btn) {
    if (!btn.classList.contains('confirming')) return;
    clearTimeout(btn._confirmTimer);
    btn._confirmTimer = null;
    btn.classList.remove('confirming');
    btn.textContent = btn.dataset.label || '';
  }

  /* ---------- 热门视图(依赖后端, 禁用时降级) ---------- */
  function renderHot() {
    clearGrid(dom.hotGrid);
    dom.hotNoMore.hidden = true;
    if (!backendOn) {
      dom.hotEmpty.hidden = false;
      dom.hotEmptyText.textContent = '热门统计需要后端服务, 当前未启用';
      degradeNotice();
      return;
    }
    dom.hotEmpty.hidden = false;
    dom.hotEmptyText.textContent = '热门数据加载中';
    fetchHot().then((list) => {
      dom.hotEmpty.hidden = true;
      hotList.length = 0;
      hotList.push.apply(hotList, list);
      hotPage = 0;
      loadHotPage();
    }).catch(() => {
      dom.hotEmpty.hidden = false;
      dom.hotEmptyText.textContent = '热门数据获取失败, 请稍后再试';
      toast('热门数据获取失败', 'warn');
    });
  }
  function loadHotPage() {
    if (isLoadingPage) return;
    isLoadingPage = true;
    const start = hotPage * PAGE_SIZE;
    let appended = 0;
    if (start < hotList.length) {
      hotList.slice(start, start + PAGE_SIZE).forEach((row) => {
        /* 后端返回的 media 已是原始键, 无需再次解码 */
        const item = itemByKey(row.media);
        if (!item) return;
        appended += 1;
        dom.hotGrid.appendChild(createMediaCard(item, { rank: String(start + appended) }));
      });
      hotPage += 1;
      applySettings();
    }
    const allLoaded = hotPage * PAGE_SIZE >= hotList.length;
    dom.hotEmpty.hidden = hotList.length > 0;
    if (hotList.length === 0) dom.hotEmptyText.textContent = '暂无热门数据';
    dom.hotNoMore.hidden = !allLoaded || hotList.length === 0;
    isLoadingPage = false;
    if (!allLoaded) armSentinel();
  }

  /* ---------- 关于视图 ---------- */
  function renderAbout() {
    dom.aboutBuildTime.textContent = buildInfo.time || '-';
    dom.aboutRepo.innerHTML = '';
    const a = document.createElement('a');
    a.href = buildInfo.repo || REPO_URL;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = buildInfo.repo || REPO_URL;
    dom.aboutRepo.appendChild(a);
  }

  /* ---------- 视图切换 ---------- */
  const VIEWS = ['home', 'album', 'favorites', 'hot', 'about'];
  function switchView(name, force) {
    if (VIEWS.indexOf(name) < 0) name = 'home';
    /* 重复进入当前视图只回到顶部, 不重新渲染也不重新请求; 显式要求重载时照常渲染 */
    if (!force && inited && name === currentView && name !== 'album') {
      window.scrollTo({ top: 0 });
      return;
    }
    currentView = name;
    store.set('currentView', name === 'album' ? 'home' : name);
    VIEWS.forEach((v) => {
      const el = $('view' + v.charAt(0).toUpperCase() + v.slice(1));
      if (el) el.hidden = v !== name;
    });
    dom.crumbBar.hidden = name !== 'album';
    dom.tabNav.querySelectorAll('.tab-btn').forEach((b) => {
      b.classList.toggle('active', b.dataset.view === (name === 'album' ? 'home' : name));
    });
    if (name === 'home') renderHome();
    if (name === 'favorites') renderFavorites();
    if (name === 'hot') renderHot();
    if (name === 'about') renderAbout();
    window.scrollTo({ top: 0 });
  }

  /* ---------- 全屏查看(缩放 + 拖拽平移) ---------- */
  let fsScale = 1;
  let fsOffsetX = 0;
  let fsOffsetY = 0;
  let fsDragging = false;
  let fsDragOrigin = null;
  let fsPinchDist = 0;

  function fsMediaEl() {
    return dom.fullscreenMedia.firstElementChild;
  }
  function applyFsTransform() {
    const el = fsMediaEl();
    if (el && el.tagName === 'IMG') {
      el.style.transform =
        'translate(' + fsOffsetX + 'px, ' + fsOffsetY + 'px) scale(' + fsScale + ')';
      el.classList.toggle('grabbing', fsDragging);
    }
  }
  function resetFsTransform() {
    fsScale = 1;
    fsOffsetX = 0;
    fsOffsetY = 0;
    fsDragging = false;
    fsDragOrigin = null;
    fsPinchDist = 0;
    applyFsTransform();
  }
  function zoomStep(scale) {
    fsScale = Math.min(Math.max(scale, FS_SCALE_MIN), FS_SCALE_MAX);
    applyFsTransform();
  }
  function openFullscreen(item) {
    resetFsTransform();
    /* 进入全屏前停止卡片内正在播放的媒体, 避免与全屏播放器同时出声 */
    const card = cardInstances.get(item.key);
    if (card && card.media && (card.kind === 'video' || card.kind === 'audio')) {
      card.media.pause();
    }
    dom.fullscreenMedia.innerHTML = '';
    const kind = mediaTypeOf(item);
    let el;
    if (kind === 'video') {
      el = document.createElement('video');
      el.className = 'fullscreen-media-el';
      el.controls = true;
      el.playsInline = true;
      el.src = mediaUrl(item);
    } else if (kind === 'audio') {
      el = document.createElement('audio');
      el.className = 'fullscreen-media-el';
      el.controls = true;
      el.src = mediaUrl(item);
    } else {
      el = document.createElement('img');
      el.className = 'fullscreen-media-el';
      el.src = mediaUrl(item);
      el.alt = item.file;
    }
    dom.fullscreenMedia.appendChild(el);
    dom.fullscreenCaption.textContent = item.type + ' / ' + item.album + ' / ' + item.file;
    dom.fullscreenModal.hidden = false;
    document.body.style.overflow = 'hidden';
    recordView(item.key);
  }
  function closeFullscreen() {
    dom.fullscreenModal.hidden = true;
    const media = dom.fullscreenMedia.querySelector('video, audio');
    if (media) { media.pause(); media.removeAttribute('src'); media.load(); }
    dom.fullscreenMedia.innerHTML = '';
    document.body.style.overflow = '';
    resetFsTransform();
  }

  /* ---------- 设置面板 ---------- */
  function renderSettings() {
    const limit = maxCols();
    dom.colSwitch.querySelectorAll('.col-btn').forEach((b) => {
      const n = Number(b.dataset.col);
      const off = n > limit;         /* 窄屏下禁用超范围列数 */
      b.disabled = off;
      b.classList.toggle('disabled', off);
      b.classList.toggle('active', n === settings.cols);
    });
    dom.ratioSwitch.innerHTML = '';
    RATIOS.forEach((r) => {
      const b = document.createElement('button');
      b.className = 'ratio-btn' + (settings.ratio === r.id ? ' active' : '');
      b.textContent = r.name;
      b.addEventListener('click', () => {
        settings.ratio = r.id;
        store.set('settings', settings);
        renderSettings();
        applySettings();
      });
      dom.ratioSwitch.appendChild(b);
    });
    dom.themeSwitch.innerHTML = '';
    THEMES.forEach((t) => {
      const opt = document.createElement('option');
      opt.value = t.id;
      opt.textContent = t.name;
      opt.selected = settings.theme === t.id;
      dom.themeSwitch.appendChild(opt);
    });
    dom.captionSwitch.querySelectorAll('.col-btn').forEach((b) => {
      b.classList.toggle('active', Number(b.dataset.caption) === settings.caption);
    });
  }
  function openSettings() {
    renderSettings();
    dom.settingsPanel.hidden = false;
  }
  function closeSettings() {
    dom.settingsPanel.hidden = true;
  }

  /* ---------- 无限滚动(加载哨兵) ---------- */
  const sentinelObserver = new IntersectionObserver((entries) => {
    if (!entries[0].isIntersecting) return;
    if (currentView === 'album' && albumPage * PAGE_SIZE < albumItems.length) {
      loadAlbumPage();
    } else if (currentView === 'hot' && backendOn && hotPage * PAGE_SIZE < hotList.length) {
      loadHotPage();
    }
  }, { rootMargin: SCROLL_MARGIN });

  /* 把哨兵挂到文档末尾并重新观察; 每页加载后重新观察可强制投递一次初始相交状态,
     否则内容增长而哨兵始终未离开视口时回调不再触发, 分页会停在半途 */
  function armSentinel() {
    if (!sentinel) {
      sentinel = document.createElement('div');
      sentinel.id = 'infiniteSentinel';
      sentinel.style.height = '1px';
      document.body.appendChild(sentinel);
    }
    sentinelObserver.unobserve(sentinel);
    sentinelObserver.observe(sentinel);
  }

  /* ---------- 事件绑定 ---------- */
  function bindEvents() {
    dom.tabNav.querySelectorAll('.tab-btn').forEach((b) => {
      b.addEventListener('click', () => switchView(b.dataset.view));
      /* 双击当前 tab 重新渲染当前视图(热门视图借此重新请求数据) */
      b.addEventListener('dblclick', () => switchView(b.dataset.view, true));
    });
    dom.brandHome.addEventListener('click', () => switchView('home'));
    dom.crumbHome.addEventListener('click', () => switchView('home'));
    dom.noticeClose.addEventListener('click', () => {
      dom.noticeBar.hidden = true;
      store.set('noticeRead', NOTICE);
    });
    dom.fullscreenClose.addEventListener('click', closeFullscreen);
    dom.fullscreenModal.addEventListener('click', (e) => {
      if (e.target === dom.fullscreenModal || e.target === dom.fullscreenWrap) closeFullscreen();
    });
    dom.zoomIn.addEventListener('click', () => zoomStep(fsScale * FS_SCALE_STEP));
    dom.zoomOut.addEventListener('click', () => zoomStep(fsScale / FS_SCALE_STEP));
    dom.zoomReset.addEventListener('click', resetFsTransform);
    /* 滚轮缩放 */
    dom.fullscreenModal.addEventListener('wheel', (e) => {
      if (dom.fullscreenModal.hidden) return;
      e.preventDefault();
      zoomStep(e.deltaY < 0 ? fsScale * FS_SCALE_STEP : fsScale / FS_SCALE_STEP);
    }, { passive: false });
    /* 缩放后拖拽平移(仅图片支持) */
    dom.fullscreenMedia.addEventListener('mousedown', (e) => {
      const el = fsMediaEl();
      if (!el || el.tagName !== 'IMG' || fsScale <= 1) return;
      fsDragging = true;
      fsDragOrigin = { x: e.clientX - fsOffsetX, y: e.clientY - fsOffsetY };
      applyFsTransform();
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!fsDragging) return;
      fsOffsetX = e.clientX - fsDragOrigin.x;
      fsOffsetY = e.clientY - fsDragOrigin.y;
      applyFsTransform();
    });
    document.addEventListener('mouseup', () => {
      if (!fsDragging) return;
      fsDragging = false;
      applyFsTransform();
    });
    /* 双指缩放(移动端) */
    dom.fullscreenModal.addEventListener('touchstart', (e) => {
      fsPinchDist = e.touches.length === 2 ? touchDistance(e) : 0;
    }, { passive: true });
    dom.fullscreenModal.addEventListener('touchmove', (e) => {
      if (e.touches.length !== 2) return;
      e.preventDefault();
      const dist = touchDistance(e);
      if (fsPinchDist > 0) zoomStep(fsScale * (dist / fsPinchDist));
      fsPinchDist = dist;
    }, { passive: false });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (!dom.fullscreenModal.hidden) closeFullscreen();
        else if (!dom.settingsPanel.hidden) closeSettings();
      }
    });
    dom.settingsToggle.addEventListener('click', () => {
      if (dom.settingsPanel.hidden) openSettings(); else closeSettings();
    });
    dom.settingsClose.addEventListener('click', closeSettings);
    dom.colSwitch.querySelectorAll('.col-btn').forEach((b) => {
      b.addEventListener('click', () => {
        if (Number(b.dataset.col) > maxCols()) return;
        settings.cols = Number(b.dataset.col);
        store.set('settings', settings);
        renderSettings();
        applySettings();
      });
    });
    dom.themeSwitch.addEventListener('change', () => {
      settings.theme = dom.themeSwitch.value;
      store.set('settings', settings);
      applySettings();
    });
    dom.captionSwitch.querySelectorAll('.col-btn').forEach((b) => {
      b.addEventListener('click', () => {
        settings.caption = Number(b.dataset.caption);
        store.set('settings', settings);
        renderSettings();
        applySettings();
      });
    });
    dom.guideClose.addEventListener('click', () => {
      dom.guideLayer.hidden = true;
      store.set('guideDone', true);
    });
    /* 点击设置面板与齿轮之外的区域关闭面板 */
    document.addEventListener('click', (e) => {
      if (dom.settingsPanel.hidden) return;
      if (dom.settingsPanel.contains(e.target) || dom.settingsToggle.contains(e.target)) return;
      closeSettings();
    });
    /* 点击确认按钮之外的区域立即取消二次确认, 回归初始状态 */
    document.addEventListener('click', (e) => {
      document.querySelectorAll('.confirming').forEach((el) => {
        if (!el.contains(e.target)) resetConfirmButton(el);
      });
    });
    window.addEventListener('scroll', () => {
      dom.btnBackTop.classList.toggle('show', window.scrollY > window.innerHeight);
    }, { passive: true });
    dom.btnBackTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    armSentinel();
  }
  function touchDistance(e) {
    return Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
  }

  /* ---------- 页脚与公告 ---------- */
  function renderFooter() {
    dom.siteFooter.innerHTML = '';
    const fragments = [];

    const version = buildInfo.version || '';
    const buildTime = buildInfo.time || '';
    if (version) {
      const versionSpan = document.createElement('span');
      versionSpan.textContent = '版本 ' + version + (buildTime ? ' [' + buildTime + ']' : '');
      fragments.push(versionSpan);
    }

    const authorSpan = document.createElement('span');
    authorSpan.textContent = '作者 ';
    const a = document.createElement('a');
    a.href = AUTHOR_URL;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = AUTHOR;
    authorSpan.appendChild(a);
    fragments.push(authorSpan);

    const repoSpan = document.createElement('span');
    repoSpan.textContent = '内容以 ';
    const repoUrl = buildInfo.repo || REPO_URL;
    const repoLink = document.createElement('a');
    repoLink.href = repoUrl;
    repoLink.target = '_blank';
    repoLink.rel = 'noopener';
    repoLink.textContent = repoUrl;
    repoSpan.appendChild(repoLink);
    repoSpan.appendChild(document.createTextNode(' 仓库为准'));
    fragments.push(repoSpan);

    fragments.forEach((frag, i) => {
      if (i > 0) dom.siteFooter.appendChild(document.createTextNode(' \u00b7 '));
      dom.siteFooter.appendChild(frag);
    });
  }
  function renderNotice() {
    if (!NOTICE || store.get('noticeRead', '') === NOTICE) return;
    dom.noticeText.textContent = NOTICE;
    dom.noticeBar.hidden = false;
  }

  /* ---------- 初始化 ---------- */
  function init() {
    /* 刷新页面时回到顶部, 不恢复上次滚动位置 */
    if ('scrollRestoration' in history) history.scrollRestoration = 'manual';
    applySettings();
    renderFooter();
    renderNotice();
    bindEvents();
    if (!store.get('guideDone', false)) dom.guideLayer.hidden = false;
    if (currentView === 'album') currentView = 'home';
    switchView(currentView);
    if (!backendOn) {
      const hotTab = dom.tabNav.querySelector('[data-view="hot"]');
      if (hotTab) hotTab.classList.add('disabled');
    }
    /* 屏幕宽度跨断点时重新收敛列数 */
    mobileQuery.addEventListener('change', () => {
      settings.cols = Math.min(settings.cols, maxCols());
      store.set('settings', settings);
      renderSettings();
      applySettings();
    });
    dom.btnBackTop.classList.toggle('show', window.scrollY > window.innerHeight);
    inited = true;
    /* 入口深链: 若 URL 带 which 参数, 跳转到对应模块/专辑/卡片 */
    applyWhichDeepLink();
  }

  init();
})();
