/* ============================================================
   奶蛙宇宙门户 - main.js
   单文件实现: 视图路由, 媒体网格, 懒加载, 无限滚动, 全屏查看,
   本地收藏, 后端统计对接(留空自动降级), 设置面板, 飘窗提醒
   ============================================================ */

(function () {
  'use strict';

  /* ---------- 常量(设计细节集中区, 可个性化调整) ---------- */

  /* 作者信息(宏常量, 页脚渲染来源) */
  const AUTHOR = 'JularDepick';
  const AUTHOR_URL = 'https://github.com/JularDepick';
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

  /* 请求超时毫秒数 */
  const FETCH_TIMEOUT = 8000;

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
  const favorites = store.get('favorites', []);       /* 有序收藏 key 列表 */
  const favSet = new Set(favorites);
  let currentView = store.get('currentView', 'home'); /* home/album/favorites/hot/about */
  let currentType = catalog.types.length ? catalog.types[0].name : '';
  let currentAlbum = null;
  let albumPage = 0;
  let hotPage = 0;
  let hotList = [];
  let degradeToastShown = false;
  const albumItems = [];   /* 当前合集的全部条目缓存 */
  const hotItems = [];

  /* ---------- DOM 引用 ---------- */
  const $ = (id) => document.getElementById(id);
  const dom = {
    tabNav: $('tabNav'), typeNav: $('typeNav'), albumNav: $('albumNav'),
    crumbBar: $('crumbBar'), crumbHome: $('crumbHome'), crumbType: $('crumbType'), crumbAlbum: $('crumbAlbum'),
    noticeBar: $('noticeBar'), noticeText: $('noticeText'), noticeClose: $('noticeClose'),
    albumGrid: $('albumGrid'), albumLoadIndicator: $('albumLoadIndicator'), albumNoMore: $('albumNoMore'),
    favoritesGrid: $('favoritesGrid'), favoritesEmpty: $('favoritesEmpty'),
    hotGrid: $('hotGrid'), hotEmpty: $('hotEmpty'), hotNoMore: $('hotNoMore'),
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
   *      返回 { hot: [{ media, views, likes, favorites, score }] }
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
    dom.albumNoMore.hidden = true;
    dom.albumLoadIndicator.hidden = false;
    dom.crumbType.textContent = typeName;
    dom.crumbAlbum.textContent = albumName;
    switchView('album');
    loadAlbumPage();
  }
  function loadAlbumPage() {
    const start = albumPage * PAGE_SIZE;
    if (start >= albumItems.length) {
      dom.albumLoadIndicator.hidden = true;
      dom.albumNoMore.hidden = albumItems.length === 0;
      return;
    }
    const slice = albumItems.slice(start, start + PAGE_SIZE);
    slice.forEach((item) => dom.albumGrid.appendChild(createMediaCard(item)));
    albumPage += 1;
    if (albumPage * PAGE_SIZE >= albumItems.length) {
      dom.albumLoadIndicator.hidden = true;
      dom.albumNoMore.hidden = albumItems.length === 0;
    } else {
      dom.albumLoadIndicator.hidden = true;
    }
    applySettings();
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
      favorites.push(item.key);
      toast('已收藏');
      reportAction(item.key, 'favorite');
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
        /* 确认等待期内忽略外层重复进入, 只响应确认按钮流程 */
        if (clear.classList.contains('confirming')) return;
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

  /* ---------- 危险操作确认: 按钮替换流程(3 秒内确认, 超时回归) ---------- */
  function confirmButton(btn, confirmText, onConfirm) {
    const original = btn.textContent;
    btn.textContent = confirmText;
    btn.classList.add('confirming');
    btn.disabled = true;
    let done = false;
    const handler = () => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      btn.removeEventListener('click', handler);
      onConfirm();
    };
    const timer = setTimeout(() => {
      if (done) return;
      done = true;
      btn.removeEventListener('click', handler);
      btn.textContent = original;
      btn.classList.remove('confirming');
      btn.disabled = false;
    }, 3000);
    /* 替换完成后立即重新可点, 等待第二次点击确认 */
    requestAnimationFrame(() => {
      btn.disabled = false;
      btn.addEventListener('click', handler, { once: true });
    });
  }

  /* ---------- 热门视图(依赖后端, 禁用时降级) ---------- */
  function renderHot() {
    dom.hotGrid.innerHTML = '';
    dom.hotNoMore.hidden = true;
    if (!backendOn) {
      dom.hotEmpty.hidden = false;
      $('hotEmptyText').textContent = '热门统计需要后端服务, 当前未启用';
      degradeNotice();
      return;
    }
    dom.hotEmpty.hidden = false;
    $('hotEmptyText').textContent = '热门数据加载中';
    fetchHot().then((list) => {
      dom.hotEmpty.hidden = true;
      hotList.length = 0;
      hotList.push.apply(hotList, list);
      hotPage = 0;
      loadHotPage();
    }).catch(() => {
      dom.hotEmpty.hidden = false;
      $('hotEmptyText').textContent = '热门数据获取失败, 请稍后再试';
      toast('热门数据获取失败', 'warn');
    });
  }
  function loadHotPage() {
    const start = hotPage * PAGE_SIZE;
    if (start >= hotList.length) {
      dom.hotNoMore.hidden = hotList.length === 0;
      if (hotList.length === 0) {
        dom.hotEmpty.hidden = false;
        $('hotEmptyText').textContent = '暂无热门数据';
      }
      return;
    }
    hotList.slice(start, start + PAGE_SIZE).forEach((row, i) => {
      const item = itemByKey(decodeKey(row.media));
      if (!item) return;
      dom.hotGrid.appendChild(createMediaCard(item, { rank: String(start + i + 1) }));
    });
    hotPage += 1;
    if (hotPage * PAGE_SIZE < hotList.length) dom.hotNoMore.hidden = true;
    else dom.hotNoMore.hidden = hotList.length === 0;
    applySettings();
  }
  function decodeKey(enc) {
    return enc.split('/').map(decodeURIComponent).join('/');
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
  function switchView(name) {
    if (VIEWS.indexOf(name) < 0) name = 'home';
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

  /* ---------- 全屏查看 ---------- */
  let zoomLevel = 1;
  function openFullscreen(item) {
    zoomLevel = 1;
    dom.fullscreenMedia.classList.remove('zoomed');
    dom.fullscreenMedia.style.transform = 'scale(1)';
    dom.fullscreenMedia.src = mediaUrl(item);
    dom.fullscreenMedia.alt = item.file;
    dom.fullscreenCaption.textContent = item.type + ' / ' + item.album + ' / ' + item.file;
    dom.fullscreenModal.hidden = false;
    document.body.style.overflow = 'hidden';
    reportAction(item.key, 'view');
  }
  function closeFullscreen() {
    dom.fullscreenModal.hidden = true;
    dom.fullscreenMedia.src = '';
    document.body.style.overflow = '';
  }
  function applyZoom() {
    dom.fullscreenMedia.style.transform = 'scale(' + zoomLevel + ')';
  }

  /* ---------- 设置面板 ---------- */
  function renderSettings() {
    dom.colSwitch.querySelectorAll('.col-btn').forEach((b) => {
      b.classList.toggle('active', Number(b.dataset.col) === settings.cols);
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

  /* ---------- 无限滚动 ---------- */
  const sentinel = document.createElement('div');
  sentinel.id = 'infiniteSentinel';
  const observer = new IntersectionObserver((entries) => {
    if (!entries[0].isIntersecting) return;
    if (currentView === 'album' && albumPage * PAGE_SIZE < albumItems.length) {
      loadAlbumPage();
    } else if (currentView === 'hot' && backendOn && hotPage * PAGE_SIZE < hotList.length) {
      loadHotPage();
    }
  }, { rootMargin: '400px' });

  /* ---------- 事件绑定 ---------- */
  function bindEvents() {
    dom.tabNav.querySelectorAll('.tab-btn').forEach((b) => {
      b.addEventListener('click', () => switchView(b.dataset.view));
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
    dom.zoomIn.addEventListener('click', () => { zoomLevel = Math.min(5, zoomLevel * 1.25); applyZoom(); });
    dom.zoomOut.addEventListener('click', () => { zoomLevel = Math.max(0.2, zoomLevel / 1.25); applyZoom(); });
    dom.zoomReset.addEventListener('click', () => {
      zoomLevel = 1;
      dom.fullscreenMedia.classList.toggle('zoomed');
      dom.fullscreenMedia.style.transform = 'scale(1)';
    });
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
    window.addEventListener('scroll', () => {
      dom.btnBackTop.classList.toggle('show', window.scrollY > 300);
    });
    dom.btnBackTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    document.body.appendChild(sentinel);
    observer.observe(sentinel);
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
    rest.textContent = ' | 内容以 ' + (buildInfo.repo || REPO_URL).replace('https://', '') + ' 仓库为准';
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
  }

  init();
})();
