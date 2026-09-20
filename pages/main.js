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
    return album.files.map((file) => ({
      key: typeName + '/' + albumName + '/' + file,
      type: typeName, album: albumName, file: file
    }));
  }
  function itemByKey(key) {
    const parts = key.split('/');
    if (parts.length !== 3) return null;
    return { key: key, type: parts[0], album: parts[1], file: parts[2] };
  }
  function mediaUrl(item) {
    return DIST_SOURCE + encodeKey(item.key);
  }
  function fileKind(name) {
    return name.toLowerCase().endsWith('.gif') ? 'gif' : 'img';
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

  /* ---------- 媒体卡片 ---------- */
  function createMediaCard(item, opts) {
    opts = opts || {};
    const card = document.createElement('div');
    card.className = 'media-card';

    const wrap = document.createElement('div');
    wrap.className = 'media-thumb-wrap';
    const img = document.createElement('img');
    img.className = 'media-thumb';
    img.loading = 'lazy';
    img.alt = item.file;
    img.src = mediaUrl(item);
    /* 素材缺失或读取失败时给出可见占位, 避免留下浏览器默认的裂图 */
    img.addEventListener('error', () => {
      wrap.classList.add('thumb-failed');
      img.removeAttribute('src');
    });
    wrap.appendChild(img);

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

    wrap.addEventListener('click', () => openFullscreen(item));
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
    return card;
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
      count.textContent = album.files.length + ' 张表情包';
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
    dom.albumGrid.innerHTML = '';
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
    dom.favoritesGrid.innerHTML = '';
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
      label.textContent = '共 ' + items.length + ' 张收藏';
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
    dom.hotGrid.innerHTML = '';
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

  function applyFsTransform() {
    dom.fullscreenMedia.style.transform =
      'translate(' + fsOffsetX + 'px, ' + fsOffsetY + 'px) scale(' + fsScale + ')';
    dom.fullscreenMedia.classList.toggle('grabbing', fsDragging);
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
    dom.fullscreenMedia.src = mediaUrl(item);
    dom.fullscreenMedia.alt = item.file;
    dom.fullscreenCaption.textContent = item.type + ' / ' + item.album + ' / ' + item.file;
    dom.fullscreenModal.hidden = false;
    document.body.style.overflow = 'hidden';
    recordView(item.key);
  }
  function closeFullscreen() {
    dom.fullscreenModal.hidden = true;
    dom.fullscreenMedia.removeAttribute('src');
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
    /* 缩放后拖拽平移 */
    dom.fullscreenMedia.addEventListener('mousedown', (e) => {
      if (fsScale <= 1) return;
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
    const span = document.createElement('span');
    span.textContent = '作者 ';
    const a = document.createElement('a');
    a.href = AUTHOR_URL;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = AUTHOR;
    span.appendChild(a);
    const rest = document.createElement('span');
    rest.textContent = ' | 内容以 ';
    const repoUrl = buildInfo.repo || REPO_URL;
    const repoLink = document.createElement('a');
    repoLink.href = repoUrl;
    repoLink.target = '_blank';
    repoLink.rel = 'noopener';
    repoLink.textContent = repoUrl.replace('https://', '');
    rest.appendChild(repoLink);
    rest.appendChild(document.createTextNode(' 仓库为准'));
    dom.siteFooter.appendChild(span);
    dom.siteFooter.appendChild(rest);
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
  }

  init();
})();
