/* ══════════════════════════════════════════════════════════════════════════
   pages/_shared.js —— 页面公共层（P2 新增）

   ## ⚠ 为什么公共代码放在 pages/ 而不是新建 js/core.js

   ``index.html`` 里写死了 6 个 ``<script>``（bridge / app / 6 个页面）。
   那个文件是 web-shell-dev 的写作用域，P2 约定「不改 index.html」，
   所以**不能新增独立的公共 js 文件** —— 它不会被加载。

   解决办法：公共层挂在这里，但**不靠加载顺序**。三个机制一起用：

   1. 本文件暴露 :data:`window.Pages`（幂等 —— 重复加载也不会覆盖已建的）。
   2. 每个页面模块开头调 ``Pages.ready(fn)`` 而不是直接执行：
      如果本文件碰巧还没跑，``ready`` 会**等 DOMContentLoaded** 再跑，
      那时所有 ``<script>`` 都已执行完。
   3. 页面模块自己也能拿到样式（:func:`injectCss`），不依赖 ``<link>``。

   这三条加起来的结果：**任意加载顺序都不炸**，不靠运气。

   ## 样式从哪来

   页面级 CSS 放在 ``css/pages/*.css``，但同样**不在 index.html 的 <link> 里**。
   所以由本文件用 :func:`injectCss` 在运行时插一个 ``<link>`` ——
   路径按 ``document.baseURI`` 解析（页面走 http://127.0.0.1:port/web/），
   加好之后 ``web_shell`` 的 media_server 就能直接服务它，不需要改 index.html。

   为什么不全写内联 style：几百行页面样式塞进 JS 字符串里，
   既没有语法高亮也没法被 CSS 工具检查，改一次错一次。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  //: 已经注入过的样式表（避免重复插 <link>）
  const _cssLoaded = new Set();

  //: 等 DOM 就绪时排队的回调
  const _queue = [];
  let _domReady = document.readyState !== 'loading';

  function flushQueue() {
    _domReady = true;
    while (_queue.length) {
      const fn = _queue.shift();
      try {
        fn();
      } catch (err) {
        console.error('[pages] 初始化回调出错:', err);
      }
    }
  }

  if (!_domReady) {
    document.addEventListener('DOMContentLoaded', flushQueue, { once: true });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  基础工具
  // ════════════════════════════════════════════════════════════════════════

  /**
   * HTML 转义。
   *
   * ⚠ 所有拼字符串的地方都必须走它 —— 工具名、配置名、日志正文
   * 全部来自用户数据（可能是 ``<script>``）。用 textContent 的地方不用。
   */
  function esc(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  /**
   * 建元素。
   *
   * @param {string} tag
   * @param {object} [attrs] - class / id / text / html / style / dataset / on*
   * @param {Array} [children]
   * @returns {HTMLElement}
   *
   * ``text`` 用 textContent（安全），``html`` 用 innerHTML（调用方自己保证已转义）。
   */
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    applyAttrs(node, attrs);
    if (children) {
      for (const child of children) {
        if (child == null) continue;
        node.appendChild(
          typeof child === 'string' ? document.createTextNode(child) : child
        );
      }
    }
    return node;
  }

  function applyAttrs(node, attrs) {
    if (!attrs) return;
    for (const key of Object.keys(attrs)) {
      const value = attrs[key];
      if (value == null || value === false) continue;
      if (key === 'class' || key === 'className') {
        node.className = value;
      } else if (key === 'text') {
        node.textContent = String(value);
      } else if (key === 'html') {
        node.innerHTML = String(value);
      } else if (key === 'style') {
        if (typeof value === 'string') {
          node.setAttribute('style', value);
        } else {
          Object.assign(node.style, value);
        }
      } else if (key === 'dataset') {
        Object.assign(node.dataset, value);
      } else if (key.slice(0, 2) === 'on' && typeof value === 'function') {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value === true) {
        node.setAttribute(key, '');
      } else {
        node.setAttribute(key, String(value));
      }
    }
  }

  /** 清空并塞入内容 */
  function fill(node, content) {
    node.innerHTML = '';
    if (content == null) return node;
    if (typeof content === 'string') {
      node.innerHTML = content;
    } else if (Array.isArray(content)) {
      for (const item of content) {
        node.appendChild(typeof item === 'string' ? document.createTextNode(item) : item);
      }
    } else {
      node.appendChild(content);
    }
    return node;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  样式注入
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 插一个样式表（幂等）。
   *
   * @param {string} href - 相对 ``index.html`` 的路径，如 ``css/pages/pages.css``
   */
  function injectCss(href) {
    if (_cssLoaded.has(href)) return;
    _cssLoaded.add(href);

    //: 已经存在（比如手动加过 <link>）就不重复插
    const existing = document.querySelector('link[href="' + href + '"]');
    if (existing) return;

    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = href;
    link.dataset.pagesCss = '1';
    //: 插在 <head> 末尾 —— 后加载的样式覆盖 base/glass/layout，符合优先级直觉
    document.head.appendChild(link);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  页面骨架（页头 / 面板 / 空态 / 提示条）
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 标准页头。
   *
   * @param {object} spec - {title, subtitle, actions: HTMLElement[]}
   * @returns {object} {head, actions}
   */
  function pageHead(spec) {
    spec = spec || {};
    const actions = el('div', { class: 'page-head-actions' });
    if (spec.actions) {
      for (const item of spec.actions) {
        if (item) actions.appendChild(item);
      }
    }
    const head = el('div', { class: 'page-head' }, [
      el('div', { class: 'page-head-text' }, [
        el('div', { class: 'page-title', text: spec.title || '' }),
        spec.subtitle
          ? el('div', { class: 'page-subtitle', text: spec.subtitle })
          : null
      ]),
      actions
    ]);
    return { head: head, actions: actions };
  }

  /**
   * 一块玻璃面板。
   *
   * @param {object} spec - {title, subtitle, actions:[], body, padding, flat}
   */
  function panel(spec) {
    spec = spec || {};
    const box = el('div', {
      class: spec.flat ? 'card' : 'card-glass',
      style: 'padding:' + (spec.padding || '18px 20px')
    });

    if (spec.title || spec.subtitle || (spec.actions && spec.actions.length)) {
      const bar = el('div', { class: 'panel-head' }, [
        el('div', { class: 'panel-head-text' }, [
          spec.title ? el('div', { class: 'panel-title', text: spec.title }) : null,
          spec.subtitle ? el('div', { class: 'panel-subtitle', text: spec.subtitle }) : null
        ]),
        el('div', { class: 'panel-actions' }, spec.actions || [])
      ]);
      box.appendChild(bar);
    }

    if (spec.body != null) {
      const content = el('div', { class: 'panel-body' });
      fill(content, spec.body);
      box.appendChild(content);
    }
    return box;
  }

  /** 空状态 */
  function empty(title, hint, iconName) {
    const box = el('div', { class: 'empty' });
    if (iconName && window.App) {
      const icon = el('div', { class: 'empty-icon' });
      const span = el('span', { class: 'nav-icon' });
      const mask = window.App.icon(iconName);
      span.style.maskImage = mask;
      span.style.webkitMaskImage = mask;
      span.style.backgroundColor = 'var(--dim)';
      span.style.width = '20px';
      span.style.height = '20px';
      icon.appendChild(span);
      box.appendChild(icon);
    }
    box.appendChild(el('div', { class: 'empty-title', text: title || '' }));
    if (hint) {
      const hintNode = el('div', { class: 'empty-hint' });
      fill(hintNode, hint);
      box.appendChild(hintNode);
    }
    return box;
  }

  /**
   * 提示条（信息 / 警告）。用于「这个页面还没接上后端」这类状态说明。
   *
   * @param {string} text
   * @param {string} [level] - info | warn | error | ok
   */
  function notice(text, level) {
    const box = el('div', { class: 'notice', dataset: { level: level || 'info' } });
    const body = el('div', { class: 'notice-text' });
    fill(body, text);
    box.appendChild(body);
    return box;
  }

  /** 按钮 */
  function button(label, opts) {
    opts = opts || {};
    const btn = el('button', {
      class: 'btn' + (opts.kind ? ' btn-' + opts.kind : '') +
             (opts.size === 'sm' ? ' btn-sm' : ''),
      type: 'button',
      title: opts.title || '',
      onClick: opts.onClick
    });
    if (opts.icon && window.App) {
      const icon = el('span', { class: 'nav-icon' });
      const mask = window.App.icon(opts.icon);
      icon.style.maskImage = mask;
      icon.style.webkitMaskImage = mask;
      icon.style.backgroundColor = 'currentColor';
      icon.style.width = '14px';
      icon.style.height = '14px';
      btn.appendChild(icon);
    }
    btn.appendChild(document.createTextNode(label));
    if (opts.disabled) btn.disabled = true;
    return btn;
  }

  /**
   * 开关（复选）。
   *
   * ## ★ 第 4 个参数 ``opts`` —— 支持「开/关不同文字」
   *
   * 旧界面 ``SwitchButton`` 有 ``setOnText`` / ``setOffText``：
   *
   * .. code:: python
   *
   *   self.crit_switch.setOnText("启用")
   *   self.crit_switch.setOffText("不启用")     # ← 关闭时显示「不启用」
   *
   * ⚠ 是 **「不启用」不是「未启用」**（用户 2026-11-02 说的是「未启用」，
   * 但旧代码原文是「不启用」，照抄旧代码）。
   *
   * @param {string} label - 默认文字（不传 opts.onText/offText 时一直显示它）
   * @param {boolean} checked
   * @param {Function} onChange
   * @param {{onText?:string, offText?:string}} [opts]
   */
  function toggle(label, checked, onChange, opts) {
    opts = opts || {};
    const id = 'sw-' + Math.random().toString(36).slice(2, 9);
    const input = el('input', { type: 'checkbox', id: id, class: 'sw-input' });
    input.checked = !!checked;

    const labelEl = el('span', { class: 'sw-label', text: label || '' });

    /** 按当前状态刷新文字（没有 onText/offText 就保持原样）*/
    function syncText() {
      if (opts.onText == null && opts.offText == null) return;
      labelEl.textContent = input.checked
        ? String(opts.onText == null ? (label || '') : opts.onText)
        : String(opts.offText == null ? (label || '') : opts.offText);
    }
    syncText();

    input.addEventListener('change', function () {
      syncText();
      onChange(input.checked);
    });

    const box = el('label', { class: 'sw', for: id }, [
      input,
      el('span', { class: 'sw-track' }, [el('span', { class: 'sw-thumb' })]),
      labelEl
    ]);
    //: 暴露 ``syncText`` —— 外部用代码改 checked 时也能刷新文字
    box.syncText = syncText;
    return box;
  }

  /** 分段过滤器（角色/武器/属性 这类） */
  function segmented(items, current, onPick) {
    const box = el('div', { class: 'segmented' });
    for (const item of items) {
      const value = typeof item === 'string' ? item : item.value;
      const label = typeof item === 'string' ? item : item.label;
      const btn = el('button', {
        class: 'seg' + (value === current ? ' is-active' : ''),
        type: 'button',
        text: label,
        dataset: { value: value },
        onClick: function () {
          for (const other of box.querySelectorAll('.seg')) {
            other.classList.toggle('is-active', other === btn);
          }
          onPick(value);
        }
      });
      box.appendChild(btn);
    }
    return box;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  桥接辅助
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 调一个**可能存在也可能不存在**的 bridge 方法。
   *
   * ## 为什么需要它
   *
   * P1 的 ``web_bridge.py`` 只有 15 个方法，业务数据接口（任务流程 / 配置 /
   * 图鉴）还没加。如果页面直接 ``Bridge.call('getFlowList')``，
   * 拿到的是一次 reject —— 页面会整块渲染失败、只剩白板。
   *
   * 这里的语义是：**方法不存在 = 功能未就绪**，返回 ``{ok:false, missing:true}``，
   * 页面据此渲染「待接入」双态，而不是崩掉。
   *
   * ## ⚠⚠「参数个数不匹配」伪装成成功（2026-11-02，web-shell-dev 实测）
   *
   * QWebChannel 找**不到**签名匹配的 Slot 时**不会报错也不会 reject** ——
   * 回调照样被调用，给的是**空数组 ``[]``**：：
   *
   * .. code:: js
   *
   *   Bridge.call('deleteConfig', 'loadout')   // 少传一个参数
   *     .then(r => console.log(r))             // → []   不是 undefined，也不炸
   *
   * 于是 ``r.ok`` 是 ``undefined``，代码里「有返回就算成功」的判断会把
   * **根本没执行**的调用当成成功。这比抛异常难查得多。
   *
   * 所以这里显式识别：**空数组 = 参数个数不匹配**，按失败处理。
   *
   * @returns {Promise<{ok:boolean, data?:*, error?:*, missing?:boolean}>}
   */
  async function call(method, arg) {
    if (!window.Bridge) {
      return { ok: false, missing: true, error: new Error('bridge.js 未加载') };
    }
    try {
      const value = arg === undefined
        ? await window.Bridge.call(method)
        : await window.Bridge.call(method, arg);

      //: ★ 空数组 = QWebChannel 没找到匹配的 Slot（实参个数不对）
      if (Array.isArray(value) && value.length === 0) {
        console.warn('[pages] 可能是参数个数不匹配:', method, value);
        return {
          ok: false,
          error: new Error('参数个数不匹配：' + method + ' 返回了空数组'),
          mismatch: true
        };
      }

      return { ok: true, data: value };
    } catch (err) {
      //: QWebChannel 对「方法不存在」抛的是 "bridge 上没有方法: xxx"
      const message = String(err && err.message || err || '');
      const missing = /没有方法|not a function|undefined/i.test(message);
      return { ok: false, error: err, missing: missing };
    }
  }

  /**
   * ★ 多参数调用 —— 给 ``@Slot(str, str, result=str)`` 这类方法用。
   *
   * ## 为什么需要它（这是 QWebChannel 的硬规矩）
   *
   * ``Bridge.call(method, arg)`` 只传**一个**实参。QWebChannel 按
   * **JS 实参个数**去 Python 侧找签名匹配的 Slot，所以像
   * ``deleteConfig(kind, id)`` 这种两参方法，用 ``call`` 调必然
   * `No candidates found ... with 1 arguments` —— 而且**静默失败**
   * （不抛异常、不报错，就是不执行）。
   *
   * ## 实现依赖 ``bridge.js`` 的 ``Bridge.callWith(method, argsArray)``
   *
   * 2026-11-02 由 web-shell-dev 补上（我提的方案 A）。
   * 它和 ``call`` 的区别只有一处：把**实参数组**原样展开给 QWebChannel 代理，
   * 这样 ``@Slot(str, str, result=str)`` 才能匹配上。
   *
   * ``callWith`` 对 0/1 参方法同样通用，所以**理论上可以全用它**；
   * 但 ``call`` 的语义更清楚（单值而非数组），页面里保持分开。
   *
   * @param {string} method
   * @param {Array} args - 按顺序传给 Python Slot 的实参
   * @returns {Promise<{ok:boolean, data?:*, error?:*, missing?:boolean}>}
   */
  async function callMulti(method, args) {
    const list = Array.isArray(args) ? args : [];
    if (!window.Bridge) {
      return { ok: false, missing: true, error: new Error('bridge.js 未加载') };
    }
    //: 老版本 bridge.js 没有 callWith → 明确报缺，别假装成功
    if (typeof window.Bridge.callWith !== 'function') {
      return {
        ok: false,
        missing: true,
        error: new Error(
          'bridge.js 没有 callWith()，无法调用需要 ' + list.length +
          ' 个参数的 ' + method + '（QWebChannel 按实参个数匹配 Slot）'
        )
      };
    }
    try {
      const value = await window.Bridge.callWith(method, list);

      //: ★ 同 call 里的那条：空数组 = 没有匹配的 Slot
      if (Array.isArray(value) && value.length === 0) {
        console.warn('[pages] 参数个数不匹配:', method, list.length, '参数');
        return {
          ok: false,
          error: new Error('参数个数不匹配：' + method + ' 返回了空数组'),
          mismatch: true
        };
      }
      return { ok: true, data: value };
    } catch (err) {
      const message = String(err && err.message || err || '');
      const missing = /没有方法|not a function|undefined/i.test(message);
      return { ok: false, error: err, missing: missing };
    }
  }

  /**
   * 取一个数据接口的列表；接口缺失或返回空都安全。
   *
   * @param {string} method
   * @param {string} [key] - 返回对象里装列表的字段名（有些接口返回 {items:[]}）
   * @returns {Promise<{available:boolean, list:Array, raw:*}>}
   */
  async function fetchList(method, key) {
    const result = await call(method);
    if (!result.ok) {
      return { available: false, list: [], raw: null, error: result.error };
    }
    let data = result.data;
    if (key && data && !Array.isArray(data)) {
      data = data[key];
    }
    if (data == null) data = [];
    if (!Array.isArray(data)) data = [];
    return { available: true, list: data, raw: result.data };
  }

  // ════════════════════════════════════════════════════════════════════════
  //  格式化
  // ════════════════════════════════════════════════════════════════════════

  /** 时间戳 → 「刚刚 / 3 分钟前 / 2026-09-26」 */
  function timeAgo(text) {
    const raw = String(text || '').trim();
    if (!raw) return '';
    //: 后端给的是 "YYYY-MM-DD HH:MM:SS"（本地时间），Safari/Chromium 都能解析
    const parsed = new Date(raw.replace(' ', 'T'));
    if (isNaN(parsed.getTime())) return raw;
    const diff = Date.now() - parsed.getTime();
    if (diff < 0) return raw;
    const minute = 60 * 1000;
    const hour = 60 * minute;
    const day = 24 * hour;
    if (diff < minute) return '刚刚';
    if (diff < hour) return Math.floor(diff / minute) + ' 分钟前';
    if (diff < day) return Math.floor(diff / hour) + ' 小时前';
    if (diff < 7 * day) return Math.floor(diff / day) + ' 天前';
    return raw.slice(0, 10);
  }

  /** 数字 → 带千分位 */
  function num(value) {
    const n = Number(value);
    if (!isFinite(n)) return '—';
    return n.toLocaleString('zh-CN');
  }

  /** 文本截断（不改变原值，只是显示） */
  function clip(text, max) {
    const str = String(text == null ? '' : text);
    if (str.length <= max) return str;
    return str.slice(0, max - 1) + '…';
  }

  // ════════════════════════════════════════════════════════════════════════
  //  导出
  // ════════════════════════════════════════════════════════════════════════

  /**
   * ★ 页面初始化入口 —— 页面模块用它包住自己的 ``registerPage``。
   *
   * 为什么不能直接 ``registerPage``：如果 ``_shared.js`` 还没执行到
   * （比如以后有人调整了 script 顺序），页面模块会拿不到 ``Pages``。
   * 这个函数保证回调一定在「所有脚本执行完 + DOM 就绪」之后跑。
   *
   * @param {function} fn
   */
  function ready(fn) {
    if (_domReady) {
      fn();
    } else {
      _queue.push(fn);
    }
  }

  const Pages = {
    esc: esc,
    el: el,
    fill: fill,
    injectCss: injectCss,
    pageHead: pageHead,
    panel: panel,
    empty: empty,
    notice: notice,
    button: button,
    toggle: toggle,
    segmented: segmented,
    call: call,
    callMulti: callMulti,
    fetchList: fetchList,
    timeAgo: timeAgo,
    num: num,
    clip: clip,
    ready: ready,
    /** 页面级样式表路径（注入一次即可）*/
    CSS: 'css/pages/pages.css'
  };

  window.Pages = Pages;

  //: 立刻把页面样式表挂上（不等 DOMContentLoaded —— <head> 在脚本执行时已可用）
  injectCss(Pages.CSS);
})();
