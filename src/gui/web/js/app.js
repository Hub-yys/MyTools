/* ══════════════════════════════════════════════════════════════════════════
   app.js —— 应用外壳逻辑（路由 / 皮肤 / 壁纸 / 状态）

   ## 职责边界

   * ``app.js``   —— 外壳：侧栏、标题栏、路由、壁纸、皮肤、窗口控制
   * ``pages/*.js`` —— 单个页面内部的内容

   页面通过 :data:`App.registerPage` 注册，自己不碰 DOM 外壳。

   ## 路由

   页面 key → ``<section class="page" data-page="KEY">``。
   工具详情页用 ``tool:<key>``，由本文件动态创建 section
   （工具是数据驱动的，7 个工具不该在 index.html 里写 7 个空 section）。

   ## ★ 无平铺（本项目的核心目标）

   壁纸是 ``position: fixed; inset: 0`` 的 ``<video>`` —— 它绑在
   **viewport** 上。窗口放大 → viewport 变大 → 视频重新铺满。
   这是浏览器原生行为，不存在「纹理被平铺」的可能。

   为了让这一点可验证，本文件暴露 :meth:`App.debugLayout`，
   返回 viewport / 各区域的实际尺寸，测试脚本可以直接断言
   「放大后 body 宽度 = 新窗口宽度」。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  // ════════════════════════════════════════════════════════════════════════
  //  图标：用 SVG path 画（不依赖外部字体/图片）
  //
  //  ★ 为什么用 mask 而不是 <img>
  //  mask 让图标继承 currentColor —— 导航项 hover/active 时图标自动变色，
  //  不用给每个状态准备一份不同颜色的图。
  // ════════════════════════════════════════════════════════════════════════

  /** SVG path 数据（24x24 viewBox）*/
  const ICONS = {
    HOME:
      'M12 3 2 10.5V21h7v-6h6v6h7V10.5L12 3z',
    TASK:
      'M9 3h6a2 2 0 0 1 2 2v1h2a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h2V5a2 2 0 0 1 2-2zm0 3h6V5H9v1zm-3 5 2.5 2.5L14 8',
    SETTING:
      'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zm8.4 4c0 .5-.05 1-.13 1.5l2 1.55-2 3.45-2.35-.95c-.8.62-1.7 1.1-2.67 1.4L15 21h-6l-.25-2.1a8 8 0 0 1-2.67-1.4L3.73 18.4l-2-3.45 2-1.55A8.5 8.5 0 0 1 3.6 12c0-.5.05-1 .13-1.5l-2-1.55 2-3.45 2.35.95c.8-.62 1.7-1.1 2.67-1.4L9 3h6l.25 2.1c.97.3 1.87.78 2.67 1.4l2.35-.95 2 3.45-2 1.55c.08.5.13 1 .13 1.5z',
    SKIN:
      'M12 2a10 10 0 1 0 0 20c1.1 0 2-.9 2-2 0-.53-.2-1-.53-1.36-.34-.36-.47-.83-.47-1.32 0-1.1.9-2 2-2H17a5 5 0 0 0 5-5c0-4.42-4.48-8-10-8zm-5.5 9a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3-4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm5 0a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3zm3 4a1.5 1.5 0 1 1 0-3 1.5 1.5 0 0 1 0 3z',
    UPDATE:
      'M12 4V1L8 5l4 4V6a6 6 0 1 1-6 6H4a8 8 0 1 0 8-8z',
    BELL:
      'M12 22a2.5 2.5 0 0 0 2.45-2h-4.9A2.5 2.5 0 0 0 12 22zm7-6V11a7 7 0 0 0-5.5-6.84V3.5a1.5 1.5 0 0 0-3 0v.66A7 7 0 0 0 5 11v5l-2 2v1h18v-1l-2-2z',
    LIBRARY:
      'M4 3h4v18H4V3zm6 0h4v18h-4V3zm6.5 1.2 3.4 16.9-3.9.8L12.6 5l3.9-.8z',
    TOOLS:
      'M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z',
    GAME:
      'M21 6H3a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h18a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2zM8 15H6v-2H4v-2h2V9h2v2h2v2H8v2zm6.5-1a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5zm3-3a1.25 1.25 0 1 1 0-2.5 1.25 1.25 0 0 1 0 2.5z',
    DATABASE:
      'M12 2C7.58 2 4 3.79 4 6v12c0 2.21 3.58 4 8 4s8-1.79 8-4V6c0-2.21-3.58-4-8-4zm0 2c3.87 0 6 1.5 6 2s-2.13 2-6 2-6-1.5-6-2 2.13-2 6-2zM6 18v-1.5c1.34 1 3.5 1.5 6 1.5s4.66-.5 6-1.5V18c0 .5-2.13 2-6 2s-6-1.5-6-2z',
    DOCUMENT:
      'M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8l-6-6zm0 7V3.5L18.5 9H14z',
    APPLICATION:
      'M4 4h7v7H4V4zm9 0h7v7h-7V4zM4 13h7v7H4v-7zm9 0h7v7h-7v-7z',
    HISTORY:
      'M13 3a9 9 0 0 0-9 9H1l4 4 4-4H6a7 7 0 1 1 2.05 4.95l-1.42 1.42A9 9 0 1 0 13 3zm-1 5v5l4 2 .75-1.23-3.25-1.92V8H12z',
    CERTIFICATE:
      'M12 2 4 5v6c0 5 3.4 9.7 8 11 4.6-1.3 8-6 8-11V5l-8-3zm-1 13-3-3 1.4-1.4L11 12.2l4.6-4.6L17 9l-6 6z'
  };

  /** 生成一个 data: URI 的 SVG mask */
  function iconOf(name) {
    const path = ICONS[name] || ICONS.APPLICATION;
    const svg =
      '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">' +
      '<path fill="#000" d="' + path + '"/></svg>';
    //: encodeURIComponent 处理 # 和引号，避免 data URI 被截断
    return 'url("data:image/svg+xml,' + encodeURIComponent(svg) + '")';
  }

  // ════════════════════════════════════════════════════════════════════════
  //  常量
  // ════════════════════════════════════════════════════════════════════════

  /** 任务页日志最多保留多少行（超出丢最早的）*/
  const LOG_MAX_LINES = 500;

  /**
   * ok-ww 引擎状态轮询间隔（毫秒）。
   *
   * 和工具页 ``combatPoll()`` 同一个节奏（1.5 秒）——
   * 引擎冷启动实测要 ~20 秒，比这慢就看着像卡住了。
   */
  const ENGINE_POLL_MS = 1500;

  // ════════════════════════════════════════════════════════════════════════
  //  应用状态
  // ════════════════════════════════════════════════════════════════════════
  const App = {
    /** 当前页面 key */
    page: 'home',
    /** 所有工具（getTools 的结果）*/
    tools: [],
    /** 侧栏导航项 */
    nav: [],
    /** 当前皮肤 */
    skin: null,
    /** 当前壁纸 {id, title, url} */
    wallpaper: null,
    /** 壁纸列表 */
    wallpapers: [],
    /** 应用信息 */
    info: {displayName: '鸣潮工具箱', version: '—'},
    /** 运行状态 */
    status: {running: '', progress: 0},
    /** ★ ok-ww 引擎状态（getEngineStatus 的结果；侧栏药丸据此上色）*/
    engine: null,
    /** 引擎报错原因（药丸只显示短文案，完整原因留给工具页/日志）*/
    _engineError: '',
    /** 引擎状态轮询定时器 */
    _engineTimer: null,
    /** 已注册的页面渲染函数 {key: fn} */
    _pages: new Map(),
    /** 页面容器缓存 */
    _sections: new Map(),

    // ──────────────────────────────────────────────────────────────────────
    //  注册
    // ──────────────────────────────────────────────────────────────────────

    /**
     * 注册一个页面。
     *
     * @param {string} key - 页面 key（和侧栏 routeKey 一致）
     * @param {function} render - (container, ctx) => void
     *
     * ## ★ 工具面板也用这个注册（P4）
     *
     * 工具面板就是 ``tool:<toolKey>`` 这个页面，所以直接用本方法：
     *
     * .. code:: js
     *
     *     App.registerPage('tool:echo_change', function (section, app) {
     *       // section = <section class="page" data-page="tool:echo_change">
     *       return renderEchoChange(section, app);   // 可以返回 Promise
     *     });
     *
     * 没注册的工具会退回 P1 的占位面板（:meth:`_renderToolStub`），不会白屏。
     *
     * ⚠ **为什么没有单独的 ``registerToolPanel``**：曾经加过，但它是
     * 本方法的完全子集 —— 多一个入口只会让"面板到底注册在哪"变得不一致。
     * 工具面板和普通页面在路由层是同一种东西。
     */
    registerPage(key, render) {
      this._pages.set(key, render);
    },

    /** 图标名字 → CSS mask 值（页面里也能用）*/
    icon: iconOf,

    // ──────────────────────────────────────────────────────────────────────
    //  路由
    // ──────────────────────────────────────────────────────────────────────

    /**
     * 切到某个页面。
     *
     * @param {string} key - 'home' / 'tasks' / 'tool:echo_enhance' / ...
     * @param {object} [opts]
     * @param {boolean} [opts.silent] - 不通知 Python（Python 主动要求切页时用）
     */
    async go(key, opts) {
      opts = opts || {};
      key = String(key || 'home');

      const section = this._ensureSection(key);
      if (!section) {
        console.warn('[app] 未知页面:', key, '→ 回到主页');
        return this.go('home', opts);
      }

      // 1) 切 DOM
      for (const el of document.querySelectorAll('.page')) {
        el.classList.toggle('is-active', el === section);
      }
      this.page = key;

      // 2) 高亮侧栏
      this._syncNavActive(key);

      // 3) 更新窗口标题（页面里不再有标题栏文字 —— 见 index.html 的说明）
      const title = this._titleFor(key);
      const el = document.getElementById('titlebar-title');
      if (el) el.textContent = title;
      document.title = title + ' · ' + this.info.displayName;

      // 4) 懒渲染（第一次进这个页面时）
      if (section.dataset.rendered !== '1') {
        section.dataset.rendered = '1';
        const renderFn = this._pages.get(key);
        if (typeof renderFn === 'function') {
          try {
            await renderFn(section, this);
          } catch (err) {
            console.error('[app] 页面渲染失败:', key, err);
            section.innerHTML =
              '<div class="empty"><div class="empty-title">页面渲染失败</div>' +
              '<div class="empty-hint">' + String(err && err.message || err) +
              '</div></div>';
          }
        } else {
          // 工具页：统一渲染成占位
          this._renderToolStub(section, key);
        }
      }

      // 5) 复位滚动（切页不继承上一页的滚动位置）
      section.scrollTop = 0;

      // 6) 通知 Python（存盘 / 托盘状态用）
      if (!opts.silent) {
        Bridge.call('switchPage', key).catch(function () { /* 忽略 */ });
      }
      return section;
    },

    /** 取/建 section */
    _ensureSection(key) {
      if (this._sections.has(key)) return this._sections.get(key);

      // 静态页面（index.html 里写好的）
      let section = document.querySelector(
        '.page[data-page="' + cssEscape(key) + '"]'
      );

      // 工具页：动态创建
      if (!section && key.indexOf('tool:') === 0) {
        section = document.createElement('section');
        section.className = 'page';
        section.dataset.page = key;
        const content = document.getElementById('content');
        if (content) content.appendChild(section);
      }

      if (section) this._sections.set(key, section);
      return section || null;
    },

    /** 侧栏高亮 */
    _syncNavActive(key) {
      const isTool = key.indexOf('tool:') === 0;
      for (const el of document.querySelectorAll('.nav-item')) {
        const route = el.dataset.route || '';
        const active = route === key;
        el.classList.toggle('is-active', active);
        el.setAttribute('aria-current', active ? 'page' : 'false');
      }

      //: ★ 工具页时，把它的**分组头**也标成"当前所在组"。
      //
      //: 旧界面 `qfluentwidgets` 的行为是：进工具页时分组头保持展开、
      //: 但**不是**高亮状态（只有子项高亮）。所以这里只加一个
      //: `has-active` 类（用于轻微提示），**不加** `is-active`
      //: （避免分组头出现那条主色竖条，看起来像"分组本身被选中"）。
      const groups = document.querySelectorAll('.nav-group');
      for (const group of groups) {
        const hasChildActive = !!group.querySelector('.nav-item.is-active');
        group.classList.toggle('has-active', hasChildActive);
        //: 进工具页时自动展开分组（子项在折叠状态下高亮是看不见的）
        if (isTool && hasChildActive) {
          const children = group.querySelector('.nav-group-children');
          const head = group.querySelector('.nav-group-head');
          if (children && children.hidden) {
            children.hidden = false;
            group.classList.remove('is-collapsed');
            if (head) head.setAttribute('aria-expanded', 'true');
          }
        }
      }
    },

    /** 页面标题 */
    _titleFor(key) {
      if (key.indexOf('tool:') === 0) {
        const k = key.slice(5);
        const meta = this.tools.find(function (t) { return t.key === k; });
        return meta ? meta.name : '工具';
      }
      const item = this.nav.find(function (n) { return n.key === key; });
      if (item) return item.name;
      const names = {
        home: '主页', tasks: '任务', config: '配置',
        skin: '主题皮肤', update: '检查更新',
        notice: '消息通知', library: '资源库'
      };
      return names[key] || key;
    },

    /** 工具页占位渲染 */
    _renderToolStub(section, key) {
      const k = key.slice(5);
      const meta = this.tools.find(function (t) { return t.key === k; });
      const name = meta ? meta.name : k;
      const desc = meta ? (meta.desc || '') : '';
      section.innerHTML =
        '<div class="page-head"><div class="page-head-text">' +
        '<div class="page-title">' + escapeHtml(name) + '</div>' +
        '<div class="page-subtitle">' + escapeHtml(desc || '工具面板') +
        '</div></div></div>' +
        // ★ 明确告诉用户**怎么退回旧界面** —— 只是说"还没做"不够，
        // 用户会以为功能没了、甚至以为程序坏了。
        '<div class="card-stub-notice">' +
        '  <div class="card-stub-notice-title">这个工具的面板还在迁移中</div>' +
        '  <div class="card-stub-notice-body">' +
        '    功能本身没删，旧界面里仍然完整可用。<br>' +
        '    想用完整版：在<b>系统环境变量</b>里设 ' +
        '    <code>MYTOOLS_WEB_SHELL=0</code>，然后重启程序。' +
        '  </div>' +
        '</div>' +
        '<div class="card-glass" style="padding:26px">' +
        '<div class="empty" style="padding:32px 16px">' +
        '<div class="empty-icon"><div class="nav-icon" style="width:20px;height:20px;' +
        'background-color:var(--dim);' +
        'mask-image:' + iconOf(meta && meta.icon || 'APPLICATION') + ';' +
        '-webkit-mask-image:' + iconOf(meta && meta.icon || 'APPLICATION') + '">' +
        '</div></div>' +
        '<div class="empty-title">' + escapeHtml(name) + ' 面板</div>' +
        '<div class="empty-hint">' +
        '  后端接口已经就绪（' + escapeHtml(k) + ' 的工具逻辑可以直接调用），' +
        '  缺的只是这一页的 HTML 界面 —— 正在按顺序迁移。' +
        '</div>' +
        '</div></div>';
    },

    // ──────────────────────────────────────────────────────────────────────
    //  侧栏 / 标题栏
    // ──────────────────────────────────────────────────────────────────────

    /** 画侧栏 */
    renderNav() {
      const nav = document.getElementById('nav');
      if (!nav) return;
      nav.innerHTML = '';

      const self = this;

      function makeItem(route, label, iconName, opts) {
        opts = opts || {};
        const btn = document.createElement('button');
        btn.className = 'nav-item' + (opts.sub ? ' is-sub' : '');
        //: ★ 分组头**不设** data-route —— 它不参与路由高亮
        if (route) btn.dataset.route = route;
        btn.type = 'button';

        const icon = document.createElement('span');
        icon.className = 'nav-icon';
        const mask = iconOf(iconName);
        icon.style.maskImage = mask;
        icon.style.webkitMaskImage = mask;
        icon.style.backgroundColor = 'currentColor';
        btn.appendChild(icon);

        const text = document.createElement('span');
        text.className = 'nav-label';
        text.textContent = label;
        btn.appendChild(text);

        if (opts.badge) {
          const badge = document.createElement('span');
          badge.className = 'nav-badge';
          badge.textContent = opts.badge;
          btn.appendChild(badge);
        }

        if (opts.title) btn.title = opts.title;

        btn.addEventListener('click', function () {
          if (opts.onClick) {
            opts.onClick();
          } else if (route) {
            self.go(route);
          }
        });
        return btn;
      }

      /**
       * ★ 可展开分组（P5 新增）—— 对齐旧界面 `main_window._build_tool_group`。
       *
       * ## 旧界面的行为（``main_window.py`` L874-888）
       *
       * .. code:: python
       *
       *   self.navigationInterface.addItem(
       *       routeKey=TOOL_GROUP_KEY, text="工具",
       *       selectable=False,          # ← 分组本身**不切页面**
       *       tooltip="展开查看所有工具")
       *   for meta in metas:
       *       self.addSubInterface(host, icon, meta.name, parent=TOOL_GROUP_KEY)
       *
       * 所以：点分组头 = **展开/收起**，不是切页；子项挂在它下面。
       *
       * ## ⚠ 分组头**不能**用 ``.nav-item``
       *
       * ``layout.css`` 里 ``.nav-item.is-active::before`` 是那条主色竖条。
       * 分组头如果带 ``.nav-item``，进工具页时会被通用逻辑染上 active 态，
       * 看起来像"分组本身被选中了" —— 而旧界面没有这个视觉。
       *
       * 所以分组头单独用 ``.nav-group-head``（样式在 ``css/pages/pages.css``）。
       *
       * @param {object} item - nav 里的 group 项
       */
      function makeGroup(item) {
        const wrapper = document.createElement('div');
        wrapper.className = 'nav-group';
        wrapper.dataset.groupKey = item.key || 'tool_group';

        const expanded = item.expanded !== false;   //: 默认展开
        if (!expanded) wrapper.classList.add('is-collapsed');

        // ── 分组头（可点，只做展开/收起）──
        const head = document.createElement('button');
        head.className = 'nav-group-head';
        head.type = 'button';
        head.title = item.tooltip || '';
        head.setAttribute('aria-expanded', expanded ? 'true' : 'false');

        const icon = document.createElement('span');
        icon.className = 'nav-icon';
        const mask = iconOf(item.icon || 'TOOLS');
        icon.style.maskImage = mask;
        icon.style.webkitMaskImage = mask;
        icon.style.backgroundColor = 'currentColor';
        head.appendChild(icon);

        const text = document.createElement('span');
        text.className = 'nav-label';
        text.textContent = item.name || '工具';
        head.appendChild(text);

        //: 折叠箭头（旧界面是 qfluentwidgets 自带的 chevron）
        const chevron = document.createElement('span');
        chevron.className = 'nav-group-chevron';
        head.appendChild(chevron);

        // ── 子项容器 ──
        const children = document.createElement('div');
        children.className = 'nav-group-children';
        children.hidden = !expanded;

        //: ★ 优先用后端给的 ``children``（顺序 = ToolRegistry.all_metas()）
        //: 后端没给时才从 ``this.tools`` 兜底拼
        const kids = (Array.isArray(item.children) && item.children.length)
          ? item.children
          : self.tools.map(function (tool) {
              return {
                key: 'tool:' + tool.key,
                name: tool.name,
                icon: tool.icon || 'APPLICATION'
              };
            });

        if (!kids.length) {
          //: 一个工具都没有时，别留一个空分组（旧界面 L862-871 也这么处理）
          children.appendChild(makeItem(
            '', '（暂无工具）', 'APPLICATION',
            {sub: true, onClick: function () { /* 不可点 */ }}
          ));
        } else {
          for (const child of kids) {
            children.appendChild(makeItem(
              child.key, child.name, child.icon || 'APPLICATION', {sub: true}
            ));
          }
        }

        // ── 展开/收起 ──
        head.addEventListener('click', function () {
          const willExpand = children.hidden;
          children.hidden = !willExpand;
          wrapper.classList.toggle('is-collapsed', !willExpand);
          head.setAttribute('aria-expanded', willExpand ? 'true' : 'false');
        });

        wrapper.appendChild(head);
        wrapper.appendChild(children);
        return wrapper;
      }

      // ══════════════════════════════════════════════════════════════════
      //  ★ 严格按后端 ``getNav()`` 的顺序渲染
      //
      //  旧界面顺序（``main_window.py`` 的 addSubInterface 调用）：
      //    主页 → 配置 → 任务 → 主题皮肤 → 检查更新 → 消息通知
      //    → **工具（分组）** → 资源库
      //
      //  ⚠ P5 之前这里是「固定项全渲染完，再无条件追加工具分组」——
      //  于是工具分组永远在最后（资源库后面），和旧界面对不上。
      // ══════════════════════════════════════════════════════════════════
      for (const item of this.nav) {
        const isGroup = item.kind === 'group' || item.group === true
          || item.selectable === false;
        if (isGroup) {
          nav.appendChild(makeGroup(item));
        } else {
          nav.appendChild(makeItem(item.key, item.name, item.icon));
        }
      }

      //: 后端一个分组都没给（老版本 getNav）→ 兜底追加工具分组
      const hasGroup = this.nav.some(function (n) {
        return n.kind === 'group' || n.group === true;
      });
      if (!hasGroup && this.tools.length) {
        nav.appendChild(makeGroup({
          key: 'tool_group',
          name: '工具',
          icon: 'TOOLS',
          expanded: true
        }));
      }
    },

    /** 标题栏按钮 */
    bindTitlebar() {
      const self = this;
      //: 这些动作交给 Python（Qt 侧真的去动窗口）——
      //: 页面自己没法最小化原生窗口。
      function hook(id, method) {
        const el = document.getElementById(id);
        if (!el) return;
        el.addEventListener('click', function () {
          Bridge.call('windowAction', method).catch(function () { /* 忽略 */ });
        });
      }
      hook('btn-min', 'minimize');
      //: ★★★ 2026-11-03 修「放大后不能缩小」：这里原本发的是 **'maximize'**
      //:
      //: ## 症状
      //:
      //: 用户：「程序启动后窗口不能拖拽，放大窗口后，还不能缩小」。
      //:
      //: 点一次 □ 窗口最大化 ✅，**再点一次不动了**（窗口永远停在最大化）。
      //: 实测（真鼠标点两次同一个位置）：
      //:
      //: .. code:: text
      //:
      //:     第 1 次点 □ → isMaximized = True
      //:     第 2 次点 □ → isMaximized = True    ← 还原不了
      //:     对照 togglemaximize → isMaximized = False  ✅
      //:
      //: ## 原因
      //:
      //: Python 侧 ``maximize`` 是**单向**的：``view.showMaximized()``。
      //: 窗口已经最大化时再调，还是最大化 —— 永远回不去。
      //:
      //: ## 修法
      //:
      //: 换成 ``toggleMaximize``（后端 ``_on_window_action`` 里有
      //: ``togglemaximize`` 分支：已最大化就 ``showNormal()``）。
      //:
      //: ⚠ 顺带和双击标题栏的行为**统一**了 —— 那边一直用的是
      //: ``toggleMaximize``，只有这个按钮写错成 ``maximize``。
      hook('btn-max', 'toggleMaximize');
      hook('btn-close', 'close');

      //: ★★★ 2026-11-03 修「放大后图标不对」
      //:
      //: ## 症状
      //:
      //: 用户圈图：「放大后，这个缩小框不对把，应该右图那样」。
      //:
      //: 窗口最大化之后，□ 按钮**还是那个单框图标** —— 但这时候点它是
      //: 「还原」，应该显示成两个叠起来的方框（Windows 的 ChromeRestore）。
      //:
      //: ## 图标码位（Segoe Fluent Icons / Segoe MDL2 Assets）
      //:
      //: ==========  ===========  ============================
      //: 窗口状态     码位          外观
      //: ==========  ===========  ============================
      //: 普通         ``E922``     单个方框（ChromeMaximize）
      //: 最大化       ``E923``     两个叠起来的方框（ChromeRestore）
      //: ==========  ===========  ============================
      //:
      //: ## 状态从哪来
      //:
      //: 页面自己**判断不了** —— 用户可能双击标题栏、点 □、拖到屏幕边缘
      //: Aero Snap、按 Win+↑、点任务栏预览菜单…… 都不经过 JS。
      //:
      //: 所以由 Python 侧 ``WebShell._push_window_state()`` 监听 Qt 的
      //: ``WindowStateChange`` 推过来（``windowStateChanged`` 事件）。
      //: 这里只负责按状态换图标 + 改 tooltip。
      this.bindMaxButtonIcon();

      //: 双击标题栏 = 最大化/还原
      const tb = document.getElementById('titlebar');
      if (tb) {
        tb.addEventListener('dblclick', function (ev) {
          if (ev.target.closest('.tb-btn')) return;
          Bridge.call('windowAction', 'toggleMaximize')
            .catch(function () { /* 忽略 */ });
        });

        //: ★★★ 拖拽移动窗口（2026-11-02 无边框后必须自己接）
        //:
        //: 去掉 Windows 原生标题栏之后，「按住标题栏拖走窗口」这个能力
        //: 也没了 —— 这里补上。
        //:
        //: ⚠ **只调一次就够**，不用跟 mousemove/mouseup：
        //: Python 侧走的是 Win32 ``ReleaseCapture`` +
        //: ``SendMessage(WM_NCLBUTTONDOWN, HTCAPTION)``，让 Windows
        //: **自己接管**拖动 —— 之后拖到哪里、贴边分屏全由系统处理。
        //: 自己算位移的版本拖快了会掉帧、贴边不会分屏。
        //:
        //: ⚠ 只响应**左键**、且不在按钮上 —— 否则点最小化时会顺带拖窗口。
        tb.addEventListener('mousedown', function (ev) {
          if (ev.button !== 0) return;
          if (ev.target.closest('.tb-btn')) return;
          if (typeof Bridge === 'undefined' || !Bridge) return;
          Bridge.call('startWindowDrag').catch(function () { /* 忽略 */ });
        });
      }
      void self;
    },

    /**
     * ★ 按窗口最大化状态切换 □ 按钮的图标（2026-11-03）。
     *
     * @param {boolean} maximized - 是否最大化
     *
     * ## 为什么要单独一个方法
     *
     * 两个调用点：
     *   ① ``bindTitlebar()`` 里绑一次 —— 处理「启动时就是最大化」的情况
     *   ② ``handleEvent('windowStateChanged')`` —— 运行中状态变化
     *
     * ## 图标码位（Segoe Fluent Icons / Segoe MDL2 Assets）
     *
     * ==========  ===========  ============================
     * 窗口状态     码位          外观
     * ==========  ===========  ============================
     * 普通         ``E922``     单个方框（ChromeMaximize）
     * 最大化       ``E923``     两个叠起来的方框（ChromeRestore）
     * ==========  ===========  ============================
     *
     * ⚠ ``aria-label`` 和 ``title`` 也要跟着改 —— 否则鼠标悬停还是
     * 显示「最大化」，读屏软件也念错。
     */
    setMaxButtonIcon(maximized) {
      const el = document.getElementById('btn-max');
      if (!el) return;
      maximized = !!maximized;
      this.windowMaximized = maximized;
      //: E922 = ChromeMaximize（单框） / E923 = ChromeRestore（双框）
      const glyph = maximized ? '\uE923' : '\uE922';
      const label = maximized ? '还原' : '最大化';
      if (el.textContent !== glyph) el.textContent = glyph;
      el.title = label;
      el.setAttribute('aria-label', label);
      el.setAttribute('data-state', maximized ? 'restore' : 'maximize');
    },

    /**
     * 绑定 □ 按钮的图标初始化（兜住「页面加载时窗口已经最大化」）。
     *
     * ⚠ 页面**主动问一次** Python，别只等推送 ——
     * ``_push_window_state()`` 在 ``show()`` 里就推了，
     * 而那时页面的 ``Bridge`` 可能还没连上（QWebChannel 握手在
     * ``window.onload`` 之后才完成），那条推送会丢。
     */
    bindMaxButtonIcon() {
      const self = this;
      //: 先按当前已知状态画一次（避免闪错图标）
      this.setMaxButtonIcon(!!this.windowMaximized);
      //: 再问 Python 要准确值（Bridge 未连上时会 reject，忽略即可）
      if (typeof Bridge === 'undefined' || !Bridge) return;
      Bridge.call('getWindowState').then(function (res) {
        if (res && typeof res.maximized === 'boolean') {
          self.setMaxButtonIcon(res.maximized);
        }
      }).catch(function () { /* 忽略：Bridge 没连上就用默认值 */ });
    },

    // ──────────────────────────────────────────────────────────────────────
    //  皮肤
    // ──────────────────────────────────────────────────────────────────────

    /** 把 getSkin 的结果刷成 CSS 变量 */
    applySkin(skin) {
      if (!skin || typeof skin !== 'object') return;
      this.skin = skin;
      const root = document.documentElement;
      const set = function (name, value) {
        if (value) root.style.setProperty(name, value);
      };

      set('--primary', skin.primary);
      set('--dim', skin.dim);
      set('--text', skin.text);
      if (skin.bg) set('--bg', skin.bg);
      if (skin.card) set('--card', skin.card);
      if (skin.border) set('--border', skin.border);

      //: 主色派生的半透明值（导航高亮 / 光晕）
      if (skin.primary) {
        const rgb = hexToRgb(skin.primary);
        if (rgb) {
          root.style.setProperty('--primary-dim',
            'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.16)');
          root.style.setProperty('--primary-glow',
            'rgba(' + rgb.r + ',' + rgb.g + ',' + rgb.b + ',0.42)');

          //: ★★★ 2026-11-05：主色同时当「填充底」和「文字色」用，两者要的字色相反。
          //:
          //: 起因：用户「千咲主题改成黑色主题」。纯黑/近黑当按钮底很好看，
          //: 但当**文字色**就等于隐形（黑底黑字），`--primary-glow` 也没有发光感。
          //:
          //: 规则：
          //:
          //: * ``--on-primary``  —— 画在主色填充**上面**的字。
          //:   近黑 / 近白两个候选，**按 WCAG 对比度实际算一遍选高的**。
          //:   为什么不算阈值：长离 ``#D8503C`` 的 luma 107.5 按阈值会选浅字
          //:   （3.89:1），而深字是 4.47:1 —— 唯一不会判错的判据就是真比。
          //: * ``--primary-text`` —— 把主色**当文字/图标**用时的那份颜色。
          //:   主色够亮 → 直接用；太暗 → 混白提亮到能读（保色相）。
          //: * ``data-primary-dark`` —— 给 CSS 一个「这是暗主色」的钩子，
          //:   让 hover 之类需要额外补偿的地方能分叉（见 layout.css）。
          const dOnDark = contrastRatio(ON_DARK_TEXT, rgb);   // 深字压在主色上
          const dOnLight = contrastRatio(ON_LIGHT_TEXT, rgb); // 浅字压在主色上
          const useLight = dOnLight > dOnDark;
          root.style.setProperty('--on-primary',
            useLight ? 'rgba(248, 249, 252, 0.95)' : '#15112b');

          //: ★★★ 2026-11-05（第二轮）：**填充色本身**也要能微调。
          //:
          //: 有些主题落在「中间调」（心月狐 #D8323C、长离 #D8503C）——
          //: 配浅字 4.49:1、配深字 4.47:1，**两条路都够不到 WCAG AA 的 4.5**。
          //: 这时能调的只剩底色：往选定字色的反方向推一点（配浅字就压暗、
          //: 配深字就提亮），推到刚好达标为止，**只推最小幅度**保住主题观感。
          //:
          //: 为什么单独一个 ``--primary-fill`` 而不是改 ``--primary``：
          //: 主题色还要给导航/选中态/光晕等**非填充**处当色相参考，
          //: 那里改了会让整个界面偏色。填充只有按钮底、开关滑块、进度条、
          //: 选中 chip 这几处（见 layout.css / pages.css 的 ``var(--primary-fill)``）。
          const fill = nudgeFill(rgb, useLight);
          root.style.setProperty('--primary-fill', rgbToHex(fill));
          const fillText = useLight ? 'rgba(248, 249, 252, 0.95)' : '#15112b';
          //: 微调后重新算一遍（日志/探针都能看到真实比值）
          const dFill = contrastRatio(
            useLight ? ON_LIGHT_TEXT : ON_DARK_TEXT, fill);
          const readable = readableFrom(rgb);
          root.style.setProperty('--primary-text', rgbToHex(readable));
          //: 暗主色的「发光」用提亮后的那份，否则 shadow 是一片黑
          root.style.setProperty('--primary-glow',
            'rgba(' + Math.round(readable.r) + ',' + Math.round(readable.g) +
            ',' + Math.round(readable.b) + ',0.42)');
          const isDark = lumaOf(rgb) < 110;
          if (isDark) {
            root.setAttribute('data-primary-dark', '1');
          } else {
            root.removeAttribute('data-primary-dark');
          }
          console.info('[app] 主色', skin.primary,
            '→ 填充上的字用' + (useLight ? '浅色' : '深色'),
            '(' + Math.max(dOnDark, dOnLight).toFixed(2) + ':1)',
            '填充色 =', rgbToHex(fill),
            '(' + dFill.toFixed(2) + ':1' +
              (dFill + 1e-9 >= 4.5 ? '' : ' ⚠ 未达 AA') + ')',
            '文字色 =', rgbToHex(readable),
            isDark ? '(暗主色)' : '(亮主色)');
        }
      }

      //: 深色 / 浅色主题 —— 决定玻璃可读性下限（DSH: 0.59 / 0.45）
      const mode = skin.mode === 'light' ? 'light' : 'dark';
      root.setAttribute('data-theme', mode);
      root.style.setProperty(
        '--we-readability-floor-base',
        mode === 'light' ? '0.45' : '0.59'
      );

      //: 让页面知道皮肤变了
      Bridge.emit('skinApplied', skin);
    },

    // ──────────────────────────────────────────────────────────────────────
    //  壁纸
    // ──────────────────────────────────────────────────────────────────────

    /** 换壁纸 */
    setWallpaper(wp) {
      if (!wp || typeof wp !== 'object') return;
      const video = document.getElementById('wallpaper-video');
      const fallback = document.getElementById('wallpaper-fallback');
      if (!video) return;

      this.wallpaper = wp;

      //: ★ 2026-11-05：告诉 CSS 当前壁纸是**视频**还是静态
      //
      //: 用户 m15532：「抽卡页一直在闪」。查下来是视频壁纸的亮度在
      //: 58~86 之间来回抖（200 帧实测），而抽卡页的文字块遮挡率是 **0%**
      //: —— 30 帧/秒的明暗变化直接透在字底下，看起来就是闪。
      //:
      //: 但 2026-11-04 用户又明确说过「这个透明度就很好」，不能全站加深。
      //: → 按类型分岔：只有视频壁纸才给裸文字块垫底板
      //: （``base.css`` 的 ``body[data-wall="video"]`` + ``--we-video-plate``）。
      const markWall = function (kind) {
        try {
          if (kind) document.body.dataset.wall = kind;
          else delete document.body.dataset.wall;
        } catch (err) { /* 极老的浏览器才没有 dataset，忽略 */ }
      };

      if (!wp.url) {
        //: 没有可播的壁纸 → 显示渐变兜底
        markWall('');
        video.classList.remove('is-playing');
        video.removeAttribute('src');
        try { video.load(); } catch (err) { /* 忽略 */ }
        if (fallback) fallback.classList.remove('hidden');
        console.info('[app] 壁纸不可用，用渐变兜底:', wp.title || '(无)');
        return;
      }

      //: 静态图（.png/.jpg）不需要垫底板 —— 画面不动就不会闪。
      //: 现在的壁纸全是转好的 webm，走视频分支。
      const isVideo = /\.(webm|mp4|ogv|ogg|mov|mkv)(\?|$)/i.test(String(wp.url));
      markWall(isVideo ? 'video' : 'image');

      if (video.src === wp.url && video.classList.contains('is-playing')) {
        return;   // 已经是这个了
      }

      if (fallback) fallback.classList.add('hidden');
      video.classList.remove('is-playing');
      video.src = wp.url;
      video.loop = true;
      video.muted = true;

      const onReady = function () {
        video.classList.add('is-playing');
      };
      video.addEventListener('loadeddata', onReady, {once: true});
      video.addEventListener('error', function (ev) {
        console.error('[app] 壁纸播放失败:', wp.url, ev);
        video.classList.remove('is-playing');
        if (fallback) fallback.classList.remove('hidden');
      }, {once: true});

      const p = video.play();
      if (p && typeof p.catch === 'function') {
        p.catch(function (err) {
          //: autoplay 策略会拒绝 —— muted 视频一般没问题，但保险起见记一条
          console.warn('[app] 自动播放被拒:', err && err.message);
        });
      }
    },

    // ──────────────────────────────────────────────────────────────────────
    //  状态
    // ──────────────────────────────────────────────────────────────────────

    /** 更新侧栏底部状态药丸 */
    setStatus(state, text) {
      const pill = document.getElementById('status-pill');
      const label = document.getElementById('status-text');
      if (pill) pill.dataset.state = state;
      if (label) label.textContent = text;
    },

    // ──────────────────────────────────────────────────────────────────────
    //  ok-ww 引擎状态（侧栏底部药丸）
    // ──────────────────────────────────────────────────────────────────────

    /**
     * ★ 把引擎状态画到侧栏底部那颗药丸上（2026-11-04 用户圈图要求）。
     *
     * 用户原话：
     *
     * > 如果 okww 引擎启动成功，原点就变绿色，文字变成引擎就绪；
     * > 如果失败，原点变成红色，文字变成引擎启动失败，
     * > 而且各种任务、工具无法运行
     *
     * ## 为什么状态判定全放在后端
     *
     * ``getEngineStatus`` 直接给 ``ready`` / ``state``，页面只做**翻译**。
     * 让页面自己从 ``state`` 猜「能不能跑」的话，后端加一个新状态
     * （比如 ``booting``）页面就会静默显示错的东西 —— 而这条药丸
     * 恰恰是用户判断「现在能不能点运行」的唯一依据。
     *
     * ## 和桥接层运行状态的关系
     *
     * 药丸显示**优先级**：
     *
     * 1. 引擎启动失败 → 红（最要紧 —— 这时按运行也跑不起来）
     * 2. 桥接层有任务在跑 → 绿「运行中」
     * 3. 引擎就绪 → 绿「引擎就绪」
     * 4. 引擎正在启动 → 灰「引擎启动中…」
     * 5. 其它 → 灰「就绪」
     *
     * @param {{state:string, ready:boolean, available:boolean,
     *          bootError:string, runningTask:string}} st
     */
    applyEngineStatus(st) {
      this.engine = st || null;
      if (!st) return;
      const pill = document.getElementById('status-pill');
      //: 药丸窄，失败原因放悬停提示（完整原因仍在工具页状态行/日志里）
      const why = String(st.bootError || '').trim();
      if (pill) {
        if (st.state === 'error' || st.available === false) {
          pill.title = st.available === false
            ? 'ok-ww 引擎模块导入失败 —— 任务和工具都跑不了，详见日志'
            : ('ok-ww 引擎启动失败' + (why ? '：' + why : '')
               + ' —— 任务和工具都跑不了');
        } else if (st.ready) {
          pill.title = st.state === 'running'
            ? 'ok-ww 引擎就绪，正在跑：' + (st.runningTask || '某个任务')
            : 'ok-ww 引擎就绪 —— 任务和工具可以运行';
        } else if (st.state === 'booting' || st.pendingStart) {
          pill.title = 'ok-ww 引擎正在启动（首次冷启动约 20 秒）';
        } else {
          pill.title = '';
        }
      }
      //: 桥接层有任务在跑时戴「运行中」的帽子（引擎那格留给下面判断）
      if (this.status && this.status.running) {
        this.setStatus('running', '运行中');
        return;
      }
      //: 模块都导不进来 / 引擎报错过 → 红
      if (st.available === false || st.state === 'error') {
        //: 药丸窄，只给短文案；完整原因见悬停提示与工具页状态行
        const short = st.available === false ? '引擎不可用' : '引擎启动失败';
        this.setStatus('error', short);
        this._engineError = why;
        return;
      }
      if (st.state === 'running') {
        //: 引擎正在跑任务 —— 呼吸绿光晕（和「就绪」的静止绿区分开）
        this.setStatus('running', '引擎运行中');
      } else if (st.ready) {
        //: 就绪：绿点绿字，但不呼吸 —— 一眼能看出「没在跑、但能跑」
        this.setStatus('ready', '引擎就绪');
      } else if (st.state === 'booting' || st.pendingStart) {
        this.setStatus('idle', '引擎启动中…');
      } else {
        this.setStatus('idle', '就绪');
      }
    },

    /** 拉一次引擎状态并画药丸（失败静默 —— 别为一条提示打断界面）*/
    async pollEngineStatus() {
      if (typeof Bridge === 'undefined' || !Bridge) return null;
      try {
        const res = await Bridge.call('getEngineStatus');
        this.applyEngineStatus(res || {});
        return res;
      } catch (err) {
        //: 桥接断开时上面已经画过「桥接断开」了，这里不要覆盖
        return null;
      }
    },

    /** 启动引擎状态轮询（boot 末尾调一次；重复调用无害）*/
    startEnginePoll() {
      const self = this;
      if (this._engineTimer) return;
      this.pollEngineStatus();
      this._engineTimer = setInterval(function () {
        self.pollEngineStatus();
      }, ENGINE_POLL_MS);
    },

    /** 追加一行日志到任务页（如果存在）*/
    appendLog(text, level) {
      const box = document.getElementById('task-log');
      if (!box) return;
      const line = document.createElement('div');
      line.className = 'log-line';
      line.dataset.level = level || 'info';
      line.textContent = text;
      box.appendChild(line);
      //: 只留最后 LOG_MAX_LINES 行，防内存涨
      //
      //: ⚠ 用局部计数而不是每次读 box.childElementCount ——
      //: 读 childElementCount 会触发**同步布局重算**（强制 reflow）。
      //: 实测：一万条日志时，每行都 reflow 会把页面主线程彻底卡死
      //: （外层 runJavaScript 连回调都拿不到）。
      this._logCount = (this._logCount || 0) + 1;
      if (this._logCount > LOG_MAX_LINES) {
        if (box.firstElementChild) box.removeChild(box.firstElementChild);
        this._logCount = LOG_MAX_LINES;
      }
      //: 滚动也走 rAF 批量做 —— 每行都设 scrollTop 同样是强制布局
      this._scheduleLogScroll(box);
    },

    /**
     * 日志区自动滚到底（**批量**，每帧最多一次）。
     *
     * 每来一行都写 ``scrollTop`` 会让浏览器每行都重排一次。
     * 用 requestAnimationFrame 合并：一帧内来多少行都只滚一次。
     */
    _scheduleLogScroll(box) {
      if (this._logScrollPending) return;
      this._logScrollPending = true;
      const done = () => {
        this._logScrollPending = false;
        box.scrollTop = box.scrollHeight;
      };
      if (typeof requestAnimationFrame === 'function') {
        requestAnimationFrame(done);
      } else {
        setTimeout(done, 16);
      }
    },

    /** 更新进度条 */
    setProgress(value, text) {
      this.status.progress = value;
      const bar = document.getElementById('task-progress-bar');
      if (bar) bar.style.width = Math.max(0, Math.min(100, value)) + '%';
      const label = document.getElementById('task-progress-text');
      if (label && text) label.textContent = text;
    },

    // ──────────────────────────────────────────────────────────────────────
    //  调试 / 验证
    // ──────────────────────────────────────────────────────────────────────

    /**
     * ★ 布局探针 —— 给无头测试脚本用，断言「放大无平铺」。
     *
     * 平铺的表现是：viewport 变大了，但内部某个盒子还是旧尺寸
     * （或者被按旧尺寸重复贴）。所以这里把**每一层的实际像素尺寸**
     * 都报出来，窗口放大后这些数字必须**跟着变**。
     *
     * @returns {object}
     */
    debugLayout() {
      const q = function (sel) {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        return {
          w: Math.round(r.width),
          h: Math.round(r.height),
          //: ⚠ 用 tagName 而不是 className —— SVG 元素的 className
          //: 是 SVGAnimatedString（不是字符串），JSON 序列化后会变成
          //: 一个对象，Python 侧拿去当字符串用会炸。
          tag: el.tagName
        };
      };
      const video = document.getElementById('wallpaper-video');
      return {
        viewport: {
          w: window.innerWidth,
          h: window.innerHeight,
          dpr: window.devicePixelRatio
        },
        body: {
          w: document.body.clientWidth,
          h: document.body.clientHeight
        },
        app: q('#app'),
        sidebar: q('#sidebar'),
        titlebar: q('#titlebar'),
        content: q('#content'),
        activePage: q('.page.is-active'),
        wallpaperLayer: q('#wallpaper-layer'),
        video: video ? {
          w: video.videoWidth,
          h: video.videoHeight,
          clientW: video.clientWidth,
          clientH: video.clientHeight,
          readyState: video.readyState,
          playing: video.classList.contains('is-playing')
        } : null,
        page: this.page,
        tools: this.tools.length,
        nav: this.nav.length
      };
    }
  };

  // ════════════════════════════════════════════════════════════════════════
  //  小工具函数
  // ════════════════════════════════════════════════════════════════════════
  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /** CSS.escape 的兜底（QtWebEngine 版本差异）*/
  function cssEscape(text) {
    if (window.CSS && typeof window.CSS.escape === 'function') {
      return window.CSS.escape(text);
    }
    return String(text).replace(/[^a-zA-Z0-9_-]/g, function (ch) {
      return '\\' + ch;
    });
  }

  function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(String(hex || '').trim());
    if (!m) return null;
    let h = m[1];
    if (h.length === 3) {
      h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
    }
    return {
      r: parseInt(h.slice(0, 2), 16),
      g: parseInt(h.slice(2, 4), 16),
      b: parseInt(h.slice(4, 6), 16)
    };
  }

  /** 相对亮度（WCAG，0~255 尺度）—— 用来判断主色该配深字还是浅字。 */
  function lumaOf(rgb) {
    if (!rgb) return 0;
    return 0.2126 * rgb.r + 0.7152 * rgb.g + 0.0722 * rgb.b;
  }

  /** WCAG 相对亮度（线性化后的 0~1，对比度公式用的就是它）。 */
  function relLum(rgb) {
    if (!rgb) return 0;
    const f = function (v) {
      const c = v / 255;
      return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(rgb.r) + 0.7152 * f(rgb.g) + 0.0722 * f(rgb.b);
  }

  /** WCAG 对比度（1~21）。 */
  function contrastRatio(a, b) {
    const la = relLum(a);
    const lb = relLum(b);
    const hi = Math.max(la, lb);
    const lo = Math.min(la, lb);
    return (hi + 0.05) / (lo + 0.05);
  }

  //: 主色填充上两种候选字色。**不猜阈值，直接比对比度** ——
  //: 实测反例：长离 ``#D8503C`` 的 luma 是 107.5，按「<110 当暗色」猜会选浅字
  //: （3.89:1），但深字其实是 4.47:1，更好。比一比就没有这种边界问题。
  const ON_DARK_TEXT = { r: 0x15, g: 0x11, b: 0x2b };   // #15112b 近黑
  const ON_LIGHT_TEXT = { r: 0xf8, g: 0xf9, b: 0xfc };  // #f8f9fc 近白

  function rgbToHex(rgb) {
    const h = function (v) {
      const s = Math.max(0, Math.min(255, Math.round(v))).toString(16);
      return s.length < 2 ? '0' + s : s;
    };
    return '#' + h(rgb.r) + h(rgb.g) + h(rgb.b);
  }

  /**
   * 主色太暗时，把**当文字用**的那份提亮到能读（保色相）。
   *
   * 做法：往白色混，直到亮度到 150 —— 数学上等价于
   * ``mix(primary, white, t)``，用 HSL 保色相更自然，但没有 HSL 依赖，
   * 直接线性混白（人眼对这个变化很平滑，实测可读性够）。
   */
  function readableFrom(rgb) {
    let out = { r: rgb.r, g: rgb.g, b: rgb.b };
    let guard = 0;
    while (lumaOf(out) < 150 && guard < 24) {
      out = {
        r: out.r + (255 - out.r) * 0.12,
        g: out.g + (255 - out.g) * 0.12,
        b: out.b + (255 - out.b) * 0.12
      };
      guard += 1;
    }
    return out;
  }

  /**
   * 把**填充色**往某方向推，直到它上面的字达到 WCAG AA（4.5:1）。
   *
   * ## 为什么需要（2026-11-05 第二轮）
   *
   * 有些主色落在「中间调」——心月狐 ``#D8323C`` 配浅字 4.49:1、配深字
   * 4.47:1；长离 ``#D8503C`` 配浅字 4.47:1、配深字 4.47:1。
   * **两条路都够不到 4.5**，光挑字色解决不了。
   *
   * 能调的只剩底色。规则：
   *
   * * 上面要放**浅字** → 把底**压暗**（往 ``#000`` 混）
   * * 上面要放**深字** → 把底**提亮**（往 ``#fff`` 混）
   *
   * 每轮混 4%，最多 20 轮（0%~80%）。**只在没达标时才推，且取最小够用幅度**
   * —— 心月狐只需推 2 轮（约 8%）就从 4.49 到 4.5+，肉眼几乎看不出色差。
   *
   * @param {{r:number,g:number,b:number}} rgb 原始主色
   * @param {boolean} lightText 上面放的是浅字还是深字
   */
  function nudgeFill(rgb, lightText) {
    const text = lightText ? ON_LIGHT_TEXT : ON_DARK_TEXT;
    const target = lightText ? 0 : 255;
    let out = { r: rgb.r, g: rgb.g, b: rgb.b };
    let guard = 0;
    while (contrastRatio(text, out) < 4.5 && guard < 20) {
      out = {
        r: out.r + (target - out.r) * 0.04,
        g: out.g + (target - out.g) * 0.04,
        b: out.b + (target - out.b) * 0.04
      };
      guard += 1;
    }
    return out;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  启动
  // ════════════════════════════════════════════════════════════════════════
  async function boot() {
    // ── 0) 先把壁纸兜底显示出来（万一 getWallpaper 慢）──
    App.setStatus('idle', '正在连接…');

    // ── 1) 等桥接 ──
    try {
      await Bridge.ready;
    } catch (err) {
      console.error('[app] 桥接不可用:', err);
      App.setStatus('error', '桥接断开');
      showFatal('无法连接到 Python 后端', String(err && err.message || err));
      return;
    }

    // ── 2) 握手 ──
    try {
      await Bridge.call('ping');
    } catch (err) {
      console.warn('[app] ping 失败（继续）:', err);
    }

    // ── 3) 并行拉初始数据 ──
    const [info, nav, tools, skin, wallpaper] = await Promise.all([
      safeCall('getAppInfo', {}),
      safeCall('getNav', []),
      safeCall('getTools', []),
      safeCall('getSkin', null),
      safeCall('getWallpaper', null)
    ]);

    App.info = info || App.info;
    App.nav = Array.isArray(nav) ? nav : [];
    App.tools = Array.isArray(tools) ? tools : [];
    App.skin = skin;
    App.wallpapers = (wallpaper && Array.isArray(wallpaper.items))
      ? wallpaper.items : [];
    App.wallpaper = wallpaper;

    // ── 4) 应用 ──
    const vEl = document.getElementById('brand-version');
    if (vEl) vEl.textContent = 'v' + (App.info.version || '—');
    const nameEl = document.querySelector('.brand-name');
    if (nameEl && App.info.displayName) {
      nameEl.textContent = App.info.displayName;
    }

    if (skin) App.applySkin(skin);
    App.renderNav();
    App.bindTitlebar();
    if (wallpaper) App.setWallpaper(wallpaper);

    // ── 5) 订阅 Python 推送 ──
    Bridge.subscribe(function (name, data) {
      handleEvent(name, data);
    });

    // ── 6) 进首页 ──
    await App.go('home', {silent: true});

    //: ★ 2026-11-04：药丸改成反映 ok-ww 引擎状态（用户圈图要求），
    //: 不再写死「就绪」—— 先拉一次，再每 1.5 秒轮询。
    App.startEnginePoll();
    console.info(
      '[app] 就绪：%d 个工具，%d 个导航项，壁纸 %d 个',
      App.tools.length, App.nav.length, App.wallpapers.length
    );

    //: 通知 Python 侧「前端脚本已跑完」—— 无头测试靠这个判断加载成功
    //
    //: ⚠ 必须不传参数。QWebChannel 会按 **JS 实参个数**去 Python 侧
    //: 找签名匹配的 Slot；多传一个参数就变成
    //: "No candidates found for 'frontendReady' with 1 arguments"，
    //: 而且**静默失败**（不抛异常，只是不执行）。
    Bridge.call('frontendReady')
      .catch(function () { /* 老版本后端可能没有这个方法，忽略 */ });
  }

  /** 安全调用：出错返回默认值，不中断启动 */
  async function safeCall(method, fallback) {
    try {
      const v = await Bridge.call(method);
      return v === null || v === undefined ? fallback : v;
    } catch (err) {
      console.warn('[app] ' + method + ' 失败:', err);
      return fallback;
    }
  }

  /** Python 推送事件分发 */
  function handleEvent(name, data) {
    switch (name) {
      case 'logLine':
        App.appendLog(data.text || '', data.level);
        break;
      case 'progress':
        App.setProgress(data.value || 0, data.text || '');
        break;
      case 'taskStarted':
        App.status.running = data.key || '';
        App.setStatus('running', '运行中');
        App.appendLog('▶ 开始运行 ' + (data.key || ''), 'ok');
        App.setProgress(0, '');
        break;
      case 'taskFinished':
        App.status.running = '';
        //: ★ 结束之后**别写死「就绪」** —— 药丸归引擎状态管
        //: （引擎挂了还显示「就绪」就是骗人）
        App.setStatus('idle', '就绪');
        App.pollEngineStatus();
        App.appendLog('■ 结束：' + (data.summary || data.key || ''), 'ok');
        App.setProgress(100, '完成');
        break;
      case 'skinChanged':
        App.applySkin(data);
        break;
      case 'wallpaperChanged':
        App.setWallpaper(data);
        break;
      case 'pageRequested':
        if (data && data.key) App.go(data.key, {silent: true});
        break;
      case 'windowStateChanged':
        //: ★ 最大化/还原 → 换 □ 按钮图标（2026-11-03）
        App.setMaxButtonIcon(!!(data && data.maximized));
        break;
      default:
        //: 未知事件 —— 用调试日志留痕，静默吞掉
        console.debug('[app] 未处理事件:', name, data);
    }
  }

  /** 致命错误：在内容区中间显示，别留白屏 */
  function showFatal(title, detail) {
    const content = document.getElementById('content');
    if (!content) return;
    content.innerHTML =
      '<div class="empty" style="height:100%">' +
      '<div class="empty-icon"><div class="nav-icon" style="width:20px;height:20px;' +
      'background-color:#fca5a5;mask-image:' + iconOf('APPLICATION') + ';' +
      '-webkit-mask-image:' + iconOf('APPLICATION') + '"></div></div>' +
      '<div class="empty-title">' + escapeHtml(title) + '</div>' +
      '<div class="empty-hint selectable">' + escapeHtml(detail) + '</div>' +
      '</div>';
  }

  //: 暴露到全局
  window.App = App;

  //: 等 DOM 就绪再启动
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, {once: true});
  } else {
    boot();
  }
})();
