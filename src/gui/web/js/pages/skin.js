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

  //: ★ 卡片缩略图停在哪一秒 —— **不能是 0**（2026-11-05 用户圈图
  //: 「这个为什么是糊的，移过去又变清晰了」）。
  //:
  //: 有些壁纸的开头是淡入 / 虚化，实测爱弥斯那段 webm：
  //: ``t=0`` 锐度 62.7，``t=1`` 秒就跳到 347.6（差 5.8 倍）；
  //: 其余几张（守岸人 310 / 尤诺 621 / 心月狐 838）t=0 本来就清晰。
  //:
  //: 取 2 秒是因为实测 7 张壁纸在 t≥2 时锐度都已稳定。
  const POSTER_SEEK = 2;

  const state = {
    wallpapers: [],
    currentId: '',
    //: 页面实例 —— 后台转码好了要就地重建卡片，buildWallpaperCard 需要它
    app: null
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

    //: 后台转码好了要重建卡片 —— 把页面实例存下来（见 applyWallpaperReady）
    state.app = app;

    await loadWallpapers(app);

    // ── 分区标题（旧界面 L536-539「Wallpaper Engine 壁纸」，15px 加粗）──
    section.appendChild(P.el('div', {
      class: 'skin-section-title',
      text: 'Wallpaper Engine 壁纸'
    }));

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

    //: ★ 订阅后台转码完成（2026-11-04）——
    //:
    //: QtWebEngine 没有 H.264 解码器，mp4 壁纸必须先转 webm。
    //: 转码很慢（4K 20~60 秒），后端在 daemon 线程里一个个补，
    //: 每好一个推一条 ``wallpaperReady`` → 这里把那张卡的
    //: 缩略图和「使用这个壁纸」按钮点亮，**不用整页刷新**。
    const offReady = window.Bridge.on('wallpaperReady', function (data) {
      if (!data || !data.id) return;
      applyWallpaperReady(String(data.id), String(data.url || ''));
    });
    section._offs = (section._offs || []).concat([offReady]);
  }

  /**
   * 一张壁纸转码好了 → 就地重建那张卡（保留滚动位置和「使用中」状态）。
   *
   * ⚠ 只重建这一张，不重画整页：重建整页会让所有缩略图的
   * ``<video>`` 重新加载，屏幕闪一下，而且会打断用户正在 hover 的那张。
   */
  function applyWallpaperReady(id, url) {
    let hit = null;
    for (const item of state.wallpapers) {
      if (String(item.id) === id) { hit = item; break; }
    }
    if (!hit) return;
    if (!url) return;
    hit.url = url;
    hit.supported = true;
    hit.pending = false;

    const old = document.querySelector(
      '.wallpaper-card[data-wp-id="' + id + '"]');
    if (!old) return;   // 页面已经切走了
    const fresh = buildWallpaperCard(hit, state.app);
    if (old.parentNode) old.parentNode.replaceChild(fresh, old);
    updateHint(document.querySelector('.skin-section-hint'));
    //: 转好了，如果正好是当前壁纸也该换上新的 src
    if (id === String(state.currentId) && state.app) {
      state.app.setWallpaper({
        id: id, title: hit.title, url: url, theme: hit.theme || null
      });
    }
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
   *
   * ★ 2026-11-04 文案改了：Scene 型（心月狐）现在会从 ``scene.pkg``
   * 里抽内嵌视频，能播的就不该再说「不支持」。
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
    let text = '扫到 ' + items.length + ' 个壁纸（可播放 ' + okCount +
      ' 个；取不到内嵌视频的 Scene / Web 型需要 WebGL 渲染）。';
    //: ★ 有壁纸在后台转码时说明一下，免得用户以为这张卡坏了（2026-11-04）
    //
    //: 「转码中」这个承诺只有在**后端找得到 ffmpeg** 时才算数 ——
    //: ``_scan_wallpapers`` 会给每条带 ``canTranscode``。
    //: 正式版里 ffmpeg 是随包装进来的（``_internal/tools/ffmpeg.exe``），
    //: 但用户自己删了、或从 zip 里解出来丢了文件时就会缺，那时要如实说。
    const pending = items.filter(function (w) {
      return w.pending === true;
    }).length;
    if (pending > 0) {
      const can = items.some(function (w) { return w.canTranscode !== false; });
      text += can
        ? ' 有 ' + pending + ' 个正在后台转码（大约每张 20~60 秒），转好会自动出现。'
        : ' 有 ' + pending + ' 个需要 ffmpeg 才能转码，但当前环境找不到 ffmpeg' +
          '（应在程序目录的 tools\\ffmpeg.exe），所以暂时放不了。';
    }
    el.textContent = text;
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
        //: ★★★ 2026-11-05 用户圈图「这个为什么是糊的，移过去又变清晰了，
        //: 我想让他一直处于清晰的状态」。
        //:
        //: 根因：缩略图停的是**视频第 0 帧**，而有些壁纸的开头是淡入 / 虚化
        //: （实测爱弥斯那段 webm 的 t=0 锐度只有 62.7，t=1 秒就到 347.6
        //: —— 差 5.8 倍）。鼠标移上去播放 → 画面变清晰；移开时
        //: ``currentTime = 0`` 又**退回那张虚化帧** → 又糊。
        //:
        //: 修法：不要停在第 0 帧，停在 **POSTER_SEEK** 秒（取 2 秒，
        //: 实测那之后各壁纸的锐度都稳定了）。鼠标移开也回到同一帧。
        try { video.currentTime = POSTER_SEEK; } catch (err) { void err; }
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
        //: ★ 回到**清晰那一帧**（不是 0）—— 见 loadeddata 里那段说明
        try { video.currentTime = POSTER_SEEK; } catch (err) { void err; }
      });
      preview.appendChild(video);
    } else {
      //: 暂时没 URL 的卡分两种，别一律写「（无缩略图）」：
      //:
      //: ① ``pending`` —— mp4 等着转 webm（QtWebEngine 只认 VP9），
      //:    转好会推 ``wallpaperReady`` 就地重建这张卡；
      //: ② 真不支持 —— 抠不出内嵌视频的 Scene / Web 型，需要 WebGL。
      preview.appendChild(P.el('div', {
        class: 'wallpaper-no-preview',
        text: item.pending ? '转码中…' : '（无缩略图）'
      }));
    }
    card.appendChild(preview);

    // ── ② 名字行 + 「使用中」角标 ──
    //
    //: ★ 2026-11-04 **第二次**圈图（第一次只删了「▶ 视频」，标题还留着）。
    //: 用户这次把**标题**全框住：「守岸人钢琴版 / 尤诺 / 心月狐 /
    //: 爱弥斯-Joe / 长离 / 鸣潮 千咲「回眸」 Wuthering Waves Chisa」，
    //: 批注「这些都删掉啊，下面坎特蕾拉也是，**后面如果新加壁纸也不要这些**」。
    //:
    //: 那些是 Wallpaper Engine 创意工坊的**目录标题**，不是我们起的名字：
    //: 带「-Joe」「Wuthering Waves Chisa」这种上游残留，和下面那行
    //: 「X 主题」重复了一遍。精选主题的卡有主题名当名字，标题纯属噪音。
    //:
    //: ⚠ 没有主题的卡（用户自己放进 ``wallpapers`` 目录的视频）**仍保留标题**
    //: —— 那种卡没有「X 主题」行，去掉标题就整张没名字了，认不出是哪一张。
    const hasTheme = !!(item.theme && item.theme.primary);
    //: 两种卡的行样式不同（主题行 11px 淡色 + 色点；标题行 13px 加粗），
    //: 但都要能挂「使用中」角标、都要被 ``refreshActive()`` 找到 ——
    //: 所以给两者都加一个稳定的 ``wallpaper-label`` 类当选择器。
    const labelRow = P.el('div', {
      class: hasTheme
        ? 'wallpaper-theme wallpaper-label'
        : 'wallpaper-title-row wallpaper-label'
    });
    if (hasTheme) {
      //: 主色是**人工挑好写死**在后端 ``core/wallpaper_themes.py`` 里的
      //: —— 自动抽色给不出用户点名的红/粉红/黑红（实测心月狐抽成橙、
      //: 千咲抽成紫），这里只负责把主题名和色块显示出来。
      labelRow.appendChild(P.el('span', {
        class: 'wallpaper-theme-dot',
        style: 'background-color:' + String(item.theme.primary)
      }));
      labelRow.appendChild(P.el('span', {
        class: 'wallpaper-theme-name',
        text: String(item.theme.name || '') + ' 主题'
      }));
      if (item.theme.desc) {
        labelRow.title = String(item.theme.desc);
      }
    } else {
      labelRow.appendChild(P.el('div', {
        class: 'wallpaper-title',
        text: String(item.title || '（未命名）')
      }));
    }
    if (active) {
      labelRow.appendChild(P.el('span', {
        class: 'wallpaper-badge',
        text: '使用中'
      }));
    }
    card.appendChild(labelRow);

    // ── ②-b 类型标签 —— ★ 2026-11-04 第一次圈图要求删掉 ──
    //
    //: 原样是 ``("▶ 视频" if wp_type == "video" else f"{wp_type}") if ok``
    //: （旧界面 ``skin_page.py`` L391）。每张卡都挂一条「▶ 视频」纯属噪音：
    //: 能在这里列出来的、能点「使用这个壁纸」的，本来就是视频。
    //:
    //: ⚠ 不要以为删掉它会丢掉「不支持」的提示 —— 那种卡走的是 ③ 分支的
    //: 禁用按钮 + 「需要 WebGL 渲染」，跟类型标签无关。

    // ── ③ 按钮 / 不支持说明 ──
    const actions = P.el('div', { class: 'wallpaper-actions' });

    if (supported) {
      //: ★ 2026-11-04（用户圈图）：「取消使用」删掉，只能换不能关 ——
      //: 「取消使用之后用什么的？原生的吗」这句是对的：关掉壁纸只会退回
      //: 一片深色底，对用户没有任何价值。后端 ``setWallpaper("")``
      //: （空串 = 关壁纸）保留不动 —— ``_apply_wallpaper_accent()``
      //: 靠「没有当前壁纸」退回默认精选主题色。
      //:
      //: ★ 2026-11-04（第二次反馈）：「使用中应该占用着使用这个壁纸，
      //: 已经在使用中了，怎么还能使用？」—— 当前那张的按钮**置灰 + 改文案**，
      //: 否则整排 7 个一模一样的实心按钮，看着像哪张都能点。
      //: 文案用「正在使用」而不是「使用中」，是为了跟旁边那个绿色角标
      //: （也是「使用中」）区分开，不然一行里出现两个同样的词。
      const btn = P.button('使用这个壁纸', {
        kind: 'primary',
        size: 'sm',
        onClick: function () { applyWallpaper(item, app, btn); }
      });
      btn.dataset.action = 'apply';
      paintButton(btn, active);
      actions.appendChild(btn);
    } else if (item.pending) {
      //: ★ 2026-11-04：mp4 还在转 webm（QtWebEngine 没有 H.264 解码器），
      //: 转好会推 ``wallpaperReady`` 把这张卡整体重建。
      //: 按钮置灰但**文案要说清为什么**，不然用户只会觉得这卡坏了。
      const btn = P.button(
        item.canTranscode === false ? '缺 ffmpeg' : '转码中…',
        { size: 'sm', disabled: true });
      btn.dataset.action = 'pending';
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

  /**
   * 按「是否当前壁纸」给按钮上色 / 改文案。
   *
   * 当前那张：文案「正在使用」+ ``disabled``（点了也没有任何意义的东西，
   * 就不该是可点的样子）；其余：主色实心「使用这个壁纸」。
   *
   * ⚠ 单独抽成函数是因为有**四处**要调它（建卡、切换成功、切换失败回滚、
   * ``refreshActive()`` 重算角标），散着写必然出现「点完永久停在切换中…」
   * 那种漏复原的 bug（2026-11-04 截到过一次）。
   */
  function paintButton(btn, active) {
    if (!btn) return;
    btn.disabled = !!active;
    btn.textContent = active ? '正在使用' : '使用这个壁纸';
  }

  async function applyWallpaper(item, app, btn) {
    const id = String(item.id || '');

    btn.disabled = true;
    btn.textContent = '切换中…';

    //: 恒传真实 id —— 「取消使用」已删，不再有"传空串关壁纸"这条路。
    const target = id;
    const result = await P.call('setWallpaper', target);

    if (!result.ok) {
      paintButton(btn, false);
      app.appendLog('切换壁纸失败：' + (result.missing
        ? '桥接缺少 setWallpaper'
        : String(result.error && result.error.message || result.error)), 'error');
      return;
    }

    const data = result.data || {};
    if (data.ok === false) {
      paintButton(btn, false);
      app.appendLog('切换壁纸失败：' + (data.message || data.reason || '未知原因'),
        'warn');
      return;
    }

    //: 更新本地状态 + 界面。按钮自己这行**必须**在 refreshActive() 之前复原
    //: 一次 —— 切换成功后这张就从"可点"变成"正在使用"，由 refreshActive()
    //: 统一重算；这里先复位是为了防止 refreshActive() 因为找不到卡片而漏掉它。
    state.currentId = target;
    paintButton(btn, true);
    app.setWallpaper(data);
    refreshActive();
    updateHint(document.querySelector('.skin-section-hint'));
  }

  /** 重新标「使用中」角标 + 重算按钮状态（不重建卡片，避免视频重新加载）*/
  function refreshActive() {
    const cards = document.querySelectorAll('.wallpaper-card');
    for (const card of cards) {
      const id = String(card.dataset.wpId || '');
      const active = id === String(state.currentId);
      card.classList.toggle('is-active', active);

      //: ★ 2026-11-04：名字行有两种（精选主题卡 = ``.wallpaper-theme``、
      //: 自备视频卡 = ``.wallpaper-title-row``），统一带 ``.wallpaper-label``
      //: 类，这里只认那个 —— 不然给自备卡加角标会静默找不到行。
      const row = card.querySelector('.wallpaper-label');
      const badge = card.querySelector('.wallpaper-badge');
      if (active && !badge && row) {
        row.appendChild(P.el('span', {
          class: 'wallpaper-badge',
          text: '使用中'
        }));
      } else if (!active && badge) {
        badge.remove();
      }

      //: 按钮跟着一起重算：当前那张置灰「正在使用」，其余恢复可点。
      paintButton(card.querySelector('[data-action="apply"]'), active);
    }
  }
})();
