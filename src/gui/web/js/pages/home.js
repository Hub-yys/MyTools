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

    // ── 页头 ──
    //
    //: ★★★ 2026-11-03 用户圈图：「标记处都干掉」
    //:
    //: 砍掉的是：
    //:   * 标题栏里的「主页」三个字（页面已经高亮在侧栏，标题重复）
    //:   * 副标题「v1.1.2 · 已收录 7 个工具，点击卡片直接打开」
    //:   * 统计芯片条（7 个工具 / 7 个可直接运行 / 2 个分类 / 2 个壁纸）
    //:   * 右上角「换壁纸」「任务中心」两个按钮
    //:
    //: ## 为什么砍（不用纠结"这是功能不是说明文字"）
    //:
    //: 旧界面 ``HomeInterface`` 只有 **标题 + 副标题 + 工具网格**，
    //: 没有任何统计条和右上角按钮 —— 用户三次强调「不要擅自修改原先的
    //: 布局内容」「再对着旧界面的代码复刻」。
    //:
    //: 这几块都是我自己加的「信息密度装饰」，现在按用户要求删掉。
    //:
    //: ⚠ 副标题一并删了 —— 用户的原话是「标记处都干掉」，
    //:   而副标题正是他自己圈出来的那一行。
    const head = P.pageHead({
      //: ★★★ 2026-11-03（第二批）用户又圈了一次：这个页头标题写
      //: 「鸣潮工具箱」不对，**「改成主页」**。
      //:
      //: ⚠ 别和「标题栏里的页面名」搞混 —— 那个上一轮已经删了
      //: （``index.html`` 的 ``#titlebar-title``，侧栏已高亮当前页）。
      //: 这里是**内容区的页头标题**（``.page-title``）。
      //:
      //: 旧界面 ``HomeInterface`` 用的是 ``TitleLabel(APP_DISPLAY_NAME)``，
      //: 但用户现在明确要求「主页」—— 以最新要求为准。
      title: '主页'
    });
    section.appendChild(head.head);

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
