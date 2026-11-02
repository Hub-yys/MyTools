/* ══════════════════════════════════════════════════════════════════════════
   pages/skin.js —— 主题皮肤页（**对齐旧界面**）

   ## ⚠ P5 重写：用户反馈「我怎么自己选择皮肤呢」

   P4 版本做了「当前皮肤色板 + 全部皮肤卡片 + 切换提示」——
   **那是我自己设计的，旧界面根本没有这些。**

   读了 ``src/gui/skin_page.py``（1102 行）才发现真相：

   .. code:: text

     SkinInterface 里被用户要求删掉的东西（L480-L544 的注释）：
       ✗ 「角色主题」卡片组       —— 2026-10-31 删
       ✗ 「配色主题」卡片组       —— 2026-10-31 删（背景不透明会盖住壁纸）
       ✗ 「当前主题」标题 + 说明   —— 2026-11-01 删（只留一款，没得选，纯占地方）
       ✗ 「壁纸外观」10 个滑块     —— 2026-11-01 删（参数已对齐 DSH，不用调）

     **现在这一页只有「Wallpaper Engine 壁纸」一个内容。**

   所以用户问「我怎么自己选择皮肤呢」的答案是：
   **皮肤（配色）根本没得选** —— 旧界面就一款「液态玻璃」，
   而且用户自己要求删掉了选择 UI。**能选的是壁纸。**

   ## 因此这一版

   * **删掉**所有「皮肤列表 / 切换提示 / 玻璃参数」—— 那是我加的，不属于旧界面
   * **照抄**旧界面的「Wallpaper Engine 壁纸」卡片墙：
     缩略图 → 标题 → 「使用中」/「使用这个壁纸」

   ## 旧界面的卡片结构（``skin_page.py`` L315-400 ``WallpaperCard``）

   .. code:: text

     ┌────────────────┤
     │   缩略图 preview   │  ← CARD_WIDTH 宽、PREVIEW_H 高，圆角 8px
     │                  │     没缩略图时显示「（无缩略图）」
     ├──────────────────┤
     │ 标题        [使用中] │  ← 13px 加粗；使用中的有绿色角标
     │ [使用这个壁纸]      │  ← 不支持的（scene/web）禁用 + 标原因
     └──────────────────┘

   ``supported === false`` 的壁纸**按钮禁用并标注原因**（旧界面 L324-326）：
   它们需要 WebGL 渲染，本项目不提供。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  if (!window.App) {
    console.error('[skin] app.js 没先加载');
    return;
  }

  const P = window.Pages;
  const App = window.App;

  if (!P) {
    console.error('[skin] _shared.js 没先加载');
    return;
  }

  //: 旧界面 ``skin_page.CARD_WIDTH`` = 268、``PREVIEW_H`` = 132
  //: —— 照抄，别自己定
  const CARD_WIDTH = 268;
  const PREVIEW_H = 132;

  const state = {
    wallpapers: [],
    currentId: ''
  };

  P.ready(function () {
    App.registerPage('skin', renderSkin);
  });

  // ════════════════════════════════════════════════════════════════════════
  //  渲染（照抄旧界面：标题 + 说明 + 壁纸卡片墙）
  // ════════════════════════════════════════════════════════════════════════
  async function renderSkin(section, app) {
    //: ★ 照抄旧界面 ``SkinInterface.__init__`` L465-477 的**两段**文字：
    //:   ① 顶部标题（22px 加粗）
    //:   ② hint（13px、dim、**两行**）：
    //:        "配色主题：点一下立刻生效，所有选择都会记住。"
    //:        "壁纸：从本机 Wallpaper Engine 创意工坊读取（视频型可播放，
    //:         Scene 型需要 WebGL 渲染，暂不支持）。"
    const head = P.pageHead({ title: '主题皮肤' });
    section.appendChild(head.head);

    //: 两行说明（旧界面 L470-475 原话，逐字照抄）
    section.appendChild(P.el('div', {
      class: 'skin-top-hint',
      html: '配色主题：点一下立刻生效，所有选择都会记住。<br>' +
            '壁纸：从本机 Wallpaper Engine 创意工坊读取' +
            '（视频型可播放，Scene 型需要 WebGL 渲染，暂不支持）。'
    }));

    await loadWallpapers(app);

    // ── 分区标题（旧界面 L536-539「Wallpaper Engine 壁纸」，15px 加粗）──
    section.appendChild(P.el('div', {
      class: 'skin-section-title',
      text: 'Wallpaper Engine 壁纸'
    }));

    // ── 说明行（旧界面 L905-906，带**真实计数**）──
    const hint = P.el('div', { class: 'skin-section-hint' });
    section.appendChild(hint);
    updateHint(hint);

    // ── 卡片墙 ──
    if (!state.wallpapers.length) {
      section.appendChild(P.panel({
        padding: '26px',
        body: P.empty(
          '没有找到壁纸',
          '壁纸从本机 Wallpaper Engine 的创意工坊目录读取。' +
          '没装 Wallpaper Engine、或者创意工坊里没有视频型壁纸时，这里会是空的。',
          'SKIN'
        )
      }));
      return;
    }

    const grid = P.el('div', { class: 'wallpaper-grid' });
    for (const item of state.wallpapers) {
      grid.appendChild(buildWallpaperCard(item, app));
    }
    section.appendChild(grid);

    //: 订阅壁纸变更（别处换了壁纸，这里跟着变「使用中」）
    const off = window.Bridge.on('wallpaperChanged', function (data) {
      if (data && data.id != null) {
        state.currentId = String(data.id);
        refreshActive();
        updateHint(document.querySelector('.skin-section-hint'));
      }
    });
    section._offs = (section._offs || []).concat([off]);
  }

  async function loadWallpapers(app) {
    //: 优先用 app 已经拿到的（避免重复请求）
    if (Array.isArray(app.wallpapers) && app.wallpapers.length) {
      state.wallpapers = app.wallpapers;
      state.currentId = String((app.wallpaper && app.wallpaper.id) || '');
      return;
    }
    const result = await P.call('getWallpaper');
    if (result.ok && result.data) {
      state.wallpapers = Array.isArray(result.data.items)
        ? result.data.items : [];
      state.currentId = String(result.data.id || '');
    }
  }

  /**
   * 说明行 —— **照抄旧界面 L905-906**：
   *
   * .. code:: python
   *
   *   f"扫到 {len(items)} 个壁纸（可播放 {ok_count} 个视频型；"
   *   f"Scene / Web 型需要 WebGL 渲染，暂不支持）。"
   *
   * ⚠ 关键是**真实计数**，不是一句"共 N 个"——旧界面会告诉你
   * 有几个是能播的、其余为什么不能播。
   */
  function updateHint(el) {
    if (!el) return;
    const items = state.wallpapers;
    if (!items.length) {
      el.textContent = '没有找到可用的壁纸。';
      return;
    }
    const okCount = items.filter(function (w) {
      return w.supported !== false;
    }).length;
    el.textContent = '扫到 ' + items.length + ' 个壁纸（可播放 ' + okCount +
      ' 个视频型；Scene / Web 型需要 WebGL 渲染，暂不支持）。';
  }

  // ════════════════════════════════════════════════════════════════════════
  //  一张壁纸卡片（照抄 ``WallpaperCard`` L343-400）
  // ════════════════════════════════════════════════════════════════════════
  function buildWallpaperCard(item, app) {
    const id = String(item.id || '');
    const active = id === String(state.currentId);
    const supported = item.supported !== false;

    const card = P.el('div', {
      class: 'wallpaper-card' + (active ? ' is-active' : ''),
      dataset: { wpId: id },
      style: 'width:' + CARD_WIDTH + 'px'
    });

    // ── ① 缩略图 ──
    //
    //: ⚠ 旧界面用 Wallpaper Engine 的 ``preview.jpg``。
    //: Web 侧拿不到那个文件路径，所以**视频型用 <video> 首帧**当预览 ——
    //: 效果等价（都是这张壁纸的画面），不需要额外接口。
    const preview = P.el('div', {
      class: 'wallpaper-preview',
      style: 'height:' + PREVIEW_H + 'px'
    });

    if (supported && item.url) {
      const video = P.el('video', {
        src: item.url,
        muted: true,
        loop: true,
        playsinline: true,
        preload: 'metadata'
      });
      //: 首帧到了才算有画面
      video.addEventListener('loadeddata', function () {
        preview.classList.add('has-frame');
      }, { once: true });
      //: 加载失败 → 占位文字（别留黑框）
      video.addEventListener('error', function () {
        preview.innerHTML = '';
        preview.appendChild(P.el('div', {
          class: 'wallpaper-no-preview',
          text: '（无缩略图）'
        }));
      }, { once: true });
      //: 悬停播一下，让用户看清是什么壁纸
      card.addEventListener('mouseenter', function () {
        const p = video.play();
        if (p && typeof p.catch === 'function') {
          p.catch(function () { /* 自动播放被拒，忽略 */ });
        }
      });
      card.addEventListener('mouseleave', function () {
        video.pause();
        video.currentTime = 0;
      });
      preview.appendChild(video);
    } else {
      //: 不支持的（scene / web 型）—— 旧界面显示「（无缩略图）」
      preview.appendChild(P.el('div', {
        class: 'wallpaper-no-preview',
        text: '（无缩略图）'
      }));
    }
    card.appendChild(preview);

    // ── ② 标题 + 「使用中」角标 ──
    const titleRow = P.el('div', { class: 'wallpaper-title-row' });
    titleRow.appendChild(P.el('div', {
      class: 'wallpaper-title',
      text: String(item.title || '（未命名）')
    }));
    if (active) {
      titleRow.appendChild(P.el('span', {
        class: 'wallpaper-badge',
        text: '使用中'
      }));
    }
    card.appendChild(titleRow);

    // ── ②-b 类型标签（旧界面 L391）──
    //
    //: ``("▶ 视频" if wp_type == "video" else f"{wp_type}") if ok``
    //: —— 只有 supported 的才显示；不支持的不显示类型（按钮那边已经说明原因）
    const supportedType = supported;
    if (supportedType && item.type) {
      card.appendChild(P.el('div', {
        class: 'wallpaper-type',
        text: item.type === 'video' ? '▶ 视频' : String(item.type)
      }));
    }

    // ── ③ 按钮 / 不支持说明 ──
    const actions = P.el('div', { class: 'wallpaper-actions' });

    if (supported) {
      const btn = P.button(active ? '取消使用' : '使用这个壁纸', {
        kind: active ? '' : 'primary',
        size: 'sm',
        onClick: function () { applyWallpaper(item, app, btn); }
      });
      btn.dataset.action = 'apply';
      actions.appendChild(btn);
    } else {
      //: ★ 旧界面：``supported=False`` 时按钮禁用并标注原因
      const btn = P.button('不支持', { size: 'sm', disabled: true });
      btn.dataset.action = 'unsupported';
      actions.appendChild(btn);
      actions.appendChild(P.el('span', {
        class: 'wallpaper-unsupported',
        text: '需要 WebGL 渲染'
      }));
    }
    card.appendChild(actions);

    return card;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  切换壁纸
  // ════════════════════════════════════════════════════════════════════════
  async function applyWallpaper(item, app, btn) {
    const id = String(item.id || '');
    const isActive = id === String(state.currentId);

    btn.disabled = true;
    btn.textContent = isActive ? '关闭中…' : '切换中…';

    //: 旧界面「取消使用」= 传空串关掉壁纸（L328 ``chosen.emit("")``）
    const target = isActive ? '' : id;
    const result = await P.call('setWallpaper', target);

    btn.disabled = false;

    if (!result.ok) {
      btn.textContent = isActive ? '取消使用' : '使用这个壁纸';
      app.appendLog('切换壁纸失败：' + (result.missing
        ? '桥接缺少 setWallpaper'
        : String(result.error && result.error.message || result.error)), 'error');
      return;
    }

    const data = result.data || {};
    if (data.ok === false) {
      btn.textContent = isActive ? '取消使用' : '使用这个壁纸';
      app.appendLog('切换壁纸失败：' + (data.message || data.reason || '未知原因'),
        'warn');
      return;
    }

    //: 更新本地状态 + 界面
    state.currentId = target;
    app.setWallpaper(data);
    refreshActive();
    updateHint(document.querySelector('.skin-section-hint'));
  }

  /** 重新标「使用中」角标（不重建卡片，避免视频重新加载）*/
  function refreshActive() {
    const cards = document.querySelectorAll('.wallpaper-card');
    for (const card of cards) {
      const id = String(card.dataset.wpId || '');
      const active = id === String(state.currentId);
      card.classList.toggle('is-active', active);

      const row = card.querySelector('.wallpaper-title-row');
      const badge = card.querySelector('.wallpaper-badge');
      if (active && !badge && row) {
        row.appendChild(P.el('span', {
          class: 'wallpaper-badge',
          text: '使用中'
        }));
      } else if (!active && badge) {
        badge.remove();
      }

      const btn = card.querySelector('[data-action="apply"]');
      if (btn) btn.textContent = active ? '取消使用' : '使用这个壁纸';
    }
  }
})();
