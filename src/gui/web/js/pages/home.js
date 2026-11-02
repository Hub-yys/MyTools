/* ══════════════════════════════════════════════════════════════════════════
   pages/home.js —— 主页（工具卡片网格）

   **P2 重写**。P1 版本能渲染 7 张卡片，但几何和 Qt 版对不上、也没有运行入口。

   ## 数据来源

   ``bridge.getTools()`` —— 即 ``ToolRegistry.all_metas()``，7 个工具全部平铺，
   不按分类分组（和 Qt 版 ``home_interface.py`` 一致：工具不多时分组只是白占
   几行标题）。

   ## 几何参数从哪来

   严格对齐 ``src/app_config.py``（**不是**凭观感）：

   ==================  ======  ====================================
   常量                  值      用途
   ==================  ======  ====================================
   ``CARD_WIDTH``       158px   卡片宽
   ``CARD_HEIGHT``      128px   卡片高
   ``CARD_GRID_SPACING`` 12px    卡片间距
   ``CARD_ICON_SIZE``    46px    图标边长
   ==================  ======  ====================================

   ⚠ 图标是 **46px 不是 64px**。任务书里写的 64 是 ``library_interface``
   的 ``AVATAR_SIZE``（角色头像），不是工具卡片图标。

   ## 列数

   不用 JS 算：CSS ``grid-template-columns: repeat(auto-fill, 158px)`` 的
   结果就是 ``floor((可用宽 + 12) / (158 + 12))``，和 Qt 的
   ``ToolGrid._columns_for_width()`` 是同一个公式。窗口缩放时浏览器自动重排。

   ## 卡片点击

   * 点**卡片本体** → 进工具详情页（``tool:<key>``），和 Qt 版一致
   * 点右上角**运行图标**（hover 才出现）→ 直接 ``bridge.runTask(key)``

   Qt 版没有「运行」快捷入口（只能进工具页再点），这里加是为了兑现任务书
   里「点击触发 bridge.runTask(key) 或切到任务页」的那一半。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  if (!window.App) {
    console.error('[home] app.js 没先加载');
    return;
  }

  //: 公共层由 index.html 在 app.js 之后、本文件之前加载
  //: （见 index.html 的 script 顺序说明）。缺失就是骨架被改坏了 ——
  //: 直接报错比静默少渲染半个页面好。
  if (!window.Pages) {
    console.error('[home] _shared.js 没先加载');
    return;
  }

  const P = window.Pages;

  P.ready(function () {
    window.App.registerPage('home', renderHome);
  });

  // ────────────────────────────────────────────────────────────────────────
  //  页面
  // ────────────────────────────────────────────────────────────────────────
  function renderHome(section, app) {
    const tools = app.tools || [];
    const total = tools.length;
    const ready = tools.filter(function (t) { return !t.comingSoon; }).length;

    // ── 页头 ──
    const head = P.pageHead({
      title: app.info.displayName || '鸣潮工具箱',
      subtitle: 'v' + (app.info.version || '—') +
                ' · 已收录 ' + total + ' 个工具，点击卡片直接打开'
    });

    //: 「换壁纸」按钮 —— 桥接的双向能力展示（切壁纸真的走 Python）
    if (app.wallpapers && app.wallpapers.length) {
      head.actions.appendChild(buildWallpaperButton(app));
    }
    //: 「任务」入口
    head.actions.appendChild(P.button('任务中心', {
      icon: 'TASK',
      size: 'sm',
      onClick: function () { app.go('tasks'); }
    }));
    section.appendChild(head.head);

    // ── 统计条 ──
    section.appendChild(buildStats(app, tools));

    // ── 工具网格 ──
    if (!total) {
      section.appendChild(P.panel({
        padding: '26px',
        body: P.empty(
          '还没有可用的工具',
          '在 <code>src/tools/&lt;包名&gt;/</code> 下放一个继承 BaseTool 的类，' +
          '用 <code>@registry.register</code> 装饰，它就会自动出现在这里。',
          'APPLICATION'
        )
      }));
      return;
    }

    const grid = P.el('div', { class: 'tool-grid', id: 'home-tool-grid' });
    for (const tool of tools) {
      grid.appendChild(buildCard(tool, app));
    }
    section.appendChild(grid);

    //: 把「正在运行的是哪个工具」标到卡片上（切页回来时状态不丢）
    syncRunning(app);

    //: 订阅运行状态 —— 运行时给对应卡片打绿点，结束就撤掉
    const offs = [
      window.Bridge.on('taskStarted', function (data) {
        markRunning(tools, data && data.key);
      }),
      window.Bridge.on('taskFinished', function () {
        markRunning(tools, '');
      })
    ];
    //: 页面是懒渲染 + 常驻 DOM，这里不主动退订（页面永不销毁）；
    //: 但记在 section 上，万一将来支持重建也能收尾。
    section._offs = (section._offs || []).concat(offs);
  }

  // ────────────────────────────────────────────────────────────────────────
  //  统计条
  // ────────────────────────────────────────────────────────────────────────
  function buildStats(app, tools) {
    const bar = P.el('div', { class: 'home-stats' });

    function chip(label, value, accent) {
      return P.el('div', { class: 'stat-chip' + (accent ? ' is-accent' : '') }, [
        P.el('b', { text: String(value) }),
        P.el('span', { text: label })
      ]);
    }

    bar.appendChild(chip('个工具', tools.length, true));
    bar.appendChild(chip('可直接运行',
      tools.filter(function (t) { return !t.comingSoon; }).length));

    //: 分类去重（ToolMeta.category.display_name）
    const categories = [];
    for (const tool of tools) {
      const name = tool.categoryName || tool.category;
      if (name && categories.indexOf(name) < 0) categories.push(name);
    }
    if (categories.length) categories.length = Math.min(categories.length, 99);
    bar.appendChild(chip('个分类', categories.length));

    if (app.wallpapers && app.wallpapers.length) {
      bar.appendChild(chip('个壁纸', app.wallpapers.length));
    }
    return bar;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  壁纸切换按钮
  // ────────────────────────────────────────────────────────────────────────
  function buildWallpaperButton(app) {
    const items = app.wallpapers || [];
    let index = items.findIndex(function (w) {
      return app.wallpaper && w.id === app.wallpaper.id;
    });
    if (index < 0) index = 0;

    const btn = P.button('换壁纸', {
      size: 'sm',
      title: '在 ' + items.length + ' 个壁纸之间切换',
      onClick: async function () {
        if (!items.length) return;
        index = (index + 1) % items.length;
        btn.disabled = true;
        const result = await P.call('setWallpaper', items[index].id);
        btn.disabled = false;
        if (result.ok && result.data && result.data.ok) {
          //: Python 那边已经 emit 了 wallpaperChanged；这里顺手同步一次，
          //: 免得事件比回调先到 / 后到导致的状态差
          app.setWallpaper(result.data);
        } else if (!result.ok) {
          console.warn('[home] 切壁纸失败:', result.error);
        }
      }
    });
    return btn;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  一张工具卡片
  // ────────────────────────────────────────────────────────────────────────
  function buildCard(tool, app) {
    const card = P.el('button', {
      class: 'card-glass tool-card',
      type: 'button',
      title: tool.desc || tool.name,
      dataset: { toolKey: tool.key },
      onClick: function () {
        app.go('tool:' + tool.key);
      }
    });

    // ── 图标 ──
    const iconBox = P.el('div', { class: 'tool-card-icon' });
    if (tool.iconUrl) {
      const img = P.el('img', { src: tool.iconUrl, alt: '' });
      //: 图片 404 就退回 SVG mask —— 不留一个空白方块
      img.addEventListener('error', function () {
        iconBox.innerHTML = '';
        iconBox.appendChild(maskIcon(tool.icon));
      }, { once: true });
      iconBox.appendChild(img);
    } else {
      iconBox.appendChild(maskIcon(tool.icon));
    }
    card.appendChild(iconBox);

    // ── 名字 ──
    card.appendChild(P.el('div', { class: 'tool-card-name', text: tool.name }));

    // ── 运行快捷入口（hover 出现，不占常驻空间）──
    if (!tool.comingSoon && tool.supportsTaskRun !== false) {
      const runBtn = P.el('span', {
        class: 'tool-card-run',
        title: '运行「' + tool.name + '」',
        role: 'button',
        tabindex: '0',
        dataset: { runKey: tool.key },
        onClick: function (ev) {
          //: ★ 必须拦掉冒泡 —— 否则会同时触发卡片本身的跳转
          ev.stopPropagation();
          ev.preventDefault();
          runTool(tool, app);
        },
        onKeydown: function (ev) {
          if (ev.key === 'Enter' || ev.key === ' ') {
            ev.stopPropagation();
            ev.preventDefault();
            runTool(tool, app);
          }
        }
      });
      const runIcon = P.el('span', { class: 'nav-icon' });
      const mask = window.App.icon('TASK');
      runIcon.style.maskImage = mask;
      runIcon.style.webkitMaskImage = mask;
      runIcon.style.backgroundColor = 'currentColor';
      runBtn.appendChild(runIcon);
      card.appendChild(runBtn);
    }

    // ── 即将到来角标 ──
    if (tool.comingSoon) {
      card.appendChild(P.el('span', {
        class: 'badge-soon',
        text: '即将到来'
      }));
    }

    return card;
  }

  /** 用 SVG mask 画图标（继承 currentColor）*/
  function maskIcon(iconName) {
    const span = P.el('span', { class: 'nav-icon' });
    const mask = window.App.icon(iconName || 'APPLICATION');
    span.style.maskImage = mask;
    span.style.webkitMaskImage = mask;
    span.style.backgroundColor = 'currentColor';
    span.style.color = 'var(--text)';
    return span;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  运行
  // ────────────────────────────────────────────────────────────────────────
  async function runTool(tool, app) {
    const result = await P.call('runTask', tool.key);

    if (!result.ok) {
      //: 桥接没有 runTask / 调用炸了
      app.appendLog('✗ 无法运行 ' + tool.name + '：' + describeError(result), 'error');
      app.go('tasks');
      return;
    }

    const data = result.data || {};
    if (data.ok) {
      app.setStatus('running', '运行中');
      //: 切到任务页看日志 —— 工具本身没有界面，日志只能在那儿看
      app.go('tasks');
      return;
    }

    //: ★ 后端给的 message 是**写给用户看的**（不带异常类名前缀），优先用它。
    //: 典型：前置检查失败「鸣潮客户端没在运行，先把游戏打开…」。
    //:
    //: 以前这里只读 result.error —— 那是 **JS 侧异常对象**，
    //: 后端「拒绝运行」时根本没有，于是用户看到
    //: 「✗ 无法运行：undefined」，一点信息都没有。
    const message = data.message || data.hint || '';
    const reason = data.reason || '';

    let text;
    if (reason === 'precheck') {
      text = message || '前置检查未通过：游戏客户端没在运行';
    } else if (reason === 'busy') {
      text = '已有任务在运行（' + (data.running || '未知') + '），请先停止';
    } else if (reason === 'not_runnable') {
      text = message || ('「' + tool.name + '」没有实现自动运行');
    } else if (reason === 'unknown_tool') {
      text = message || ('没有这个工具：' + tool.key);
    } else {
      text = message || ('无法运行 ' + tool.name +
                         (reason ? '（' + reason + '）' : '：未知原因'));
    }

    app.appendLog('✗ ' + text, 'warn');

    //: 只有真正跑起来才切任务页 —— 被拒绝时留在原地，
    //: 切过去只会打断用户看提示。
    if (reason !== 'precheck' && reason !== 'busy') {
      app.go('tasks');
    }
  }

  function describeError(result) {
    if (result && result.missing) return '桥接缺少 runTask 方法';
    const err = result && result.error;
    return String(err && err.message || err || '未知错误');
  }

  // ────────────────────────────────────────────────────────────────────────
  //  运行状态标记
  // ────────────────────────────────────────────────────────────────────────
  function markRunning(tools, runningKey) {
    const grid = document.getElementById('home-tool-grid');
    if (!grid) return;
    for (const card of grid.querySelectorAll('.tool-card')) {
      card.dataset.running =
        runningKey && card.dataset.toolKey === runningKey ? '1' : '0';
    }
    void tools;
  }

  /** 页面刚渲染时补一次（比如从任务页切回来，任务还在跑）*/
  function syncRunning(app) {
    const running = app.status && app.status.running;
    if (running) {
      markRunning(app.tools, running);
    }
  }
})();
