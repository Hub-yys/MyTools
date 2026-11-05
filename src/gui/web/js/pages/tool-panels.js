/* ══════════════════════════════════════════════════════════════════════════
   pages/tool-panels.js —— ★ 7 个工具的真实面板（P4）

   ## 为什么要一个文件装 7 个面板

   ``index.html`` 的 ``<script>`` 清单是**写死**的（那是 web-shell-dev 的
   写作用域）。加 7 个工具面板如果各占一行 script，每加一个工具都要改
   index.html —— 而工具是可以**从注册表里动态出现**的（``@registry.register``），
   两者天然冲突。

   所以：**一个文件，按 key 注册多个面板**。``index.html`` 只加这一行。

   .. code:: text

     index.html
       └── js/pages/tool-panels.js
             ├── App.registerPage('tool:wuwa_library_update', …)
             ├── App.registerPage('tool:echo_change', …)
             └── …（其余 5 个）

   ## 为什么用 ``registerPage('tool:<key>')`` 而不是新的 ``registerToolPanel``

   ``app.js`` 的 ``App.go()`` 逻辑（第 167-183 行）是：

   .. code:: text

     const renderFn = this._pages.get(key);
     if (renderFn)  await renderFn(section, this);   // 渲染注册的函数
     else           this._renderToolStub(section, key);  // 占位

   也就是说**只要在这个 key 上注册，占位就被顶掉** —— 用的是现有 API，
   不需要给 ``app.js`` 加东西（那是别人的写作用域），也不引入第二套
   "页面注册"机制。

   语义上也对：工具面板**就是**一个页面。

   ## 每个面板的共同结构（见 ``_panels.js``）

   .. code:: text

     render(container)   →  Panels.create() 画骨架
     loadState()         →  拉后端状态（接口不在就双态降级）
     bindEvents()        →  订阅事件
     updateStatus(state) →  Panels 统一处理（空闲/准备/运行/完成/失败/未就绪）

   ``updateStatus`` 是**公共的** —— 7 个工具的状态展示逻辑完全一样，
   各写一遍必然长出 7 种不一致行为。

   ## 本文件当前完成度（P4 分批交付）

   ============================  ==========  ==========================
   工具                           状态         说明
   ============================  ==========  ==========================
   ``wuwa_library_update``       ✅ 已实现    检查 / 应用，含 remoteEmpty 三态
   ``echo_change``               ✅ 已实现    目标属性 + 数量 + 运行/停止
   ``auto_combat``               ⏳ 下一批    复用 okww 接口
   ``nest_sweep``                ⏳ 下一批    目标勾选 + 运行
   ``gacha``                     ⏳ 待接口    需要 analyzeGacha
   ``character_build``           ⏳ 只读缓存  需 getCharacterBuildCache
   ``echo_enhance``              ⏳ 待配置选择 runTask 已可用
   ============================  ==========  ==========================
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const P = window.Pages;
  const Panels = window.Panels;
  const App = window.App;

  if (!P || !Panels || !App) {
    console.error('[tool-panels] 依赖没先加载（需要 _shared.js / _panels.js / app.js）');
    return;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  注册助手
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 注册一个工具面板。
   *
   * @param {string} key - 工具的 ``meta.key``
   * @param {function} render - (container, app, meta) => void
   */
  function registerPanel(key, render) {
    return P.ready(function () {
      App.registerPage('tool:' + key, function (section, app) {
        const meta = findMeta(app, key);
        return render(section, app, meta);
      });
    });
  }

  function findMeta(app, key) {
    const list = (app && app.tools) || [];
    for (const tool of list) {
      if (tool.key === key) return tool;
    }
    return null;
  }

  /** 工具名（meta 拿不到时的兜底）*/
  function nameOf(meta, fallback) {
    return (meta && meta.name) || fallback;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  ① 资源库更新  wuwa_library_update
  // ════════════════════════════════════════════════════════════════════════
  //  ★ ConfigCard 等价物 —— 7 个工具面板共用
  //
  //  旧界面 ``gui/widgets.py`` L555-588 ``ConfigCard``：
  //  ``setContentsMargins(20, 16, 20, 18)`` / ``setSpacing(8)``。
  //
  //  ## ⚠ 说明文字是**纯文本**
  //
  // ════════════════════════════════════════════════════════════════════════
  /**
   * ★ 把 ``<select>`` 的宽度设成「最长选项文字宽 + 一点余量」（2026-11-03）。
   *
   * ## 为什么要手动量
   *
   * 用户：「还是长了…准则是比字的最大长度大一点就行」。
   *
   * 试过 ``width: fit-content`` —— **不可行**：Chromium 里 ``select`` 的
   * ``fit-content`` 不按最宽 ``option`` 算，而是塌成内容区最小宽度，
   * 实测量出来 **79px**，「导电伤害加成」显示不全、箭头压字。
   *
   * 所以用 canvas ``measureText`` 自己算：**最宽那条选项的文字宽**
   * + 左右内边距（26px × 2，右侧是给箭头的）+ 8px 余量。
   *
   * ## 边界
   *
   * ``min = 168px``（再窄放不下箭头），``max = 300px``（旧界面上限）。
   *
   * @param {HTMLElement} selectEl - ``<select>`` 元素
   * @param {Array<string|object>} options - 选项（字符串或 ``{value,label}``）
   */
  function sizeSelectToLongestOption(selectEl, options) {
    if (!selectEl || typeof document === 'undefined') return;
    try {
      const list = Array.isArray(options) ? options : [];
      const labels = list.map(function (o) {
        return typeof o === 'string' ? o : String((o && o.label) || '');
      }).filter(Boolean);
      //: 元素自己已有的 <option> 也算上（``setOptions`` 之后可能变多）
      for (const optEl of selectEl.options) {
        const t = String(optEl.textContent || '').trim();
        if (t && labels.indexOf(t) < 0) labels.push(t);
      }
      //: 没有选项 → 用 CSS 的 min/max 兜底（不写内联宽度即可）。
      //: 这不是"操作失败"，是"本来就没有可量的内容"，所以不是静默失败。
      if (!labels.length) {
        selectEl.style.removeProperty('width');
        return;
      }

      const cs = window.getComputedStyle(selectEl);
      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');
      //: 字体必须取**元素当前算出来的**，否则量出来偏小/偏大
      ctx.font = (cs.fontWeight || '400') + ' ' +
        (cs.fontSize || '12.5px') + ' ' +
        (cs.fontFamily || 'sans-serif');
      let widest = 0;
      for (const label of labels) {
        const w = ctx.measureText(label).width;
        if (w > widest) widest = w;
      }
      //: 左右各 26px 内边距（右侧是箭头位）+ 10px 呼吸余量。
      //:
      //: ★ 2026-11-03 用户两轮都说「有点长」—— 余量从 8px 收到 **6px**，
      //: 并把下限从 168 降到 **96px**（原来那个下限会把「智能切换」
      //: 这种四字选项硬撑到 168，白白多出 60px 空白）。
      //:
      //: 96px 只是**防塌缩**的下限（再窄下拉箭头就压到字上了），
      //: 正常选项都会大于它。
      const total = Math.ceil(widest + 26 + 26 + 6);
      const clamped = Math.max(96, Math.min(300, total));
      selectEl.style.width = clamped + 'px';
      //: ★ 让 flex 别把这个宽度又拉回去（``.cfg-select`` 有 ``flex: 0 0 160px``）
      selectEl.style.flex = '0 0 auto';
    } catch (err) {
      //: 量不出来就退回 CSS 的 min/max 兜底 —— 不该因此白屏
      console.debug('[tool-panels] sizeSelectToLongestOption 失败', err);
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  旧界面的 hint 里有 ``**智能切换**`` 这种 markdown 符号 ——
  //  旧界面**不渲染 markdown**，原样显示。所以这里必须用 ``textContent``。
  //
  //  @param {string} title - 卡片标题
  //  @param {string} [hint] - 灰色说明
  //  @returns {{card: HTMLElement, body: HTMLElement}}
  // ════════════════════════════════════════════════════════════════════════
  function cfgCard(title, hint) {
    const card = P.el('div', { class: 'cfg-card card-glass' });
    if (title) {
      card.appendChild(P.el('div', { class: 'cfg-card-title', text: title }));
    }
    if (hint) {
      card.appendChild(P.el('div', { class: 'cfg-card-hint', text: hint }));
    }
    const body = P.el('div', { class: 'cfg-card-body' });
    card.appendChild(body);
    return { card: card, body: body };
  }

  // ════════════════════════════════════════════════════════════════════════
  //  ① 4C 自动战斗  auto_combat   （**照抄旧界面 5 张卡**）
  //
  //  旧界面 ``auto_combat/tool.py`` L429-468：
  //    run_card(4C 自动战斗 + 启动/停止 + 状态行)
  //    → 战斗方式 → 定时关机 → 战斗报告 → 历史记录
  //
  //  **没有任何「运行前提」块** —— 那是 P5 我们自己加的，用户圈出「干掉」。
  // ════════════════════════════════════════════════════════════════════════

  /** 旧界面 ``rotation.STYLES`` —— (value, label, desc) */
  const COMBAT_STYLES_FALLBACK = [
    {
      value: 'smart',
      label: '智能切换',
      desc: 'ok-ww 原生调度：按 buff 剩余时间和角色定位挑人。' +
            '这是 ok-ww 官方行为，默认就用它。'
    },
    {
      value: 'rotation',
      label: '轮切',
      desc: '固定轴 3 → 2 → 1 循环，协奏一满就换人（超时 12 秒兜底）。'
    },
    {
      value: 'combo',
      label: '合轴',
      desc: '待定 —— 当前等同「智能切换」（不接管切人）。'
    }
  ];

  const DEFAULT_COMBAT_STYLE = 'smart';
  const DEFAULT_SHUTDOWN_MINUTES = 120;
  const MIN_SHUTDOWN_MINUTES = 1;
  const MAX_SHUTDOWN_MINUTES = 1440;
  const SHUTDOWN_WARN_SECONDS = 60;

  //: 「正在启动…」的有效期（毫秒）
  //:
  //: ★ 取 **120 秒** —— 对齐 ok-ww 自己的 ``start_timeout: 120``
  //: （见 ``okww_boot`` 的 config）。引擎首次冷启动要加载 ok-ww +
  //: onnxocr + openvino，实测 20 秒左右，但慢机器/首次装模型会更久。
  //:
  //: ⚠ 第一版写的 30 秒**不够**：实测完整套件跑下来，引擎冷启动 +
  //: 主线程被 ``runOkwwTask`` 阻塞叠加，30 秒就过期了，轮询立刻把
  //: 「正在启动…」擦掉 —— 看起来像"点完没反应"。
  //:
  //: 过期后轮询会接管（显示运行中/被占用/就绪），所以这个值只影响
  //: 「最坏情况下这行字挂多久」，取大一点没有副作用。
  const PENDING_START_MS = 120000;

  /**
   * ★ 标记「刚点了运行，引擎正在起来」（2026-11-03）。
   *
   * ## 为什么需要（实测踩到）
   *
   * 点「运行」时写一行「引擎：正在启动…」，但**轮询每 1.5 秒重算状态行**，
   * 而引擎冷启动要 ~20 秒 —— 期间后端 ``getOkwwState()`` 返回的还是
   * ``state: "idle"``（初始化在别的线程）。轮询看到 idle 就把文案清掉：
   *
   * .. code:: text
   *
   *     t+0.0s  写「引擎：正在启动…」
   *     t+1.5s  轮询 sees idle → 清空  ← 用户看到"点了一下就没反应"
   *     t+20s   引擎才真的 booting
   *
   * 用户视角就是「按钮坏了」。所以给个**截止时间**，在那之前轮询
   * 不许清掉这条反馈。
   *
   * @param {object} state - COMBAT_STATE / CHANGE_STATE / SWEEP_STATE
   */
  function markPendingStart(state) {
    state.pendingUntil = Date.now() + PENDING_START_MS;
  }

  /** 当前是否还在「刚点运行」的有效期内 */
  function isPendingStart(state) {
    return Date.now() < (state.pendingUntil || 0);
  }

  /** 结束「正在启动」标记（失败 / 停止 / 轮询确认跑起来之后调） */
  function clearPendingStart(state) {
    state.pendingUntil = 0;
  }

  /**
   * ★ 轮询里调：确认引擎真的进入运行态后，撤掉「正在启动」标记。
   *
   * 为什么不在提交成功后直接撤：引擎冷启动 ~20 秒，那段期间后端
   * ``getOkwwState()`` 还报 ``idle``，撤了就没人维持「正在启动…」，
   * 轮询看到 idle 会把状态行清空（实测 0.8 秒就白屏）。
   *
   * @returns {boolean} 是否已撤离（true 表示交给正常状态逻辑）
   */
  function settlePendingStart(state, running, pending, stateName) {
    if (!state.pendingUntil) return true;
    const started = !!(running || pending) || stateName === 'booting'
      || stateName === 'running';
    if (started) {
      clearPendingStart(state);
      return true;
    }
    //: 还没起来 —— 继续维持「正在启动…」（除非已超时）
    return !isPendingStart(state);
  }

  const COMBAT_STATE = {
    style: null,
    styles: null,
    shutdownCheck: null,
    shutdownEdit: null,
    shutdownState: null,
    reportHost: null,
    historyHost: null,
    stateLabel: null,
    //: ★ 2026-11-03：「正在启动…」的有效期
    //:
    //: ## 为什么需要（踩到了）
    //:
    //: 点「运行」时先写「引擎：正在启动…」，但**轮询每 1.5 秒会把状态行
    //: 重算一遍** —— 而引擎首次冷启动要 ~20 秒，这期间后端 ``state`` 还是
    //: ``idle``（引擎在别的线程初始化），轮询看到 idle 就把文案清空了。
    //:
    //: 结果：用户点完只闪一下，之后 20 秒一片空白 —— 正是我们想避免的。
    //:
    //: 现在记一个**截止时间**：在这之前，轮询不许清掉「正在启动…」。
    //: 超时（默认 30 秒，覆盖实测 ~20 秒冷启动）后交还给轮询逻辑。
    pendingUntil: 0,
    btnStart: null,
    btnStop: null,
    tracker: null,
    pollTimer: null
  };

  registerPanel('auto_combat', function renderAutoCombat(container, app, meta) {
    container.appendChild(buildCombatRunCard(app, meta));
    container.appendChild(buildCombatStyleCard());
    container.appendChild(buildCombatShutdownCard());
    container.appendChild(buildCombatReportCard());
    container.appendChild(buildCombatHistoryCard());
    combatLoadSettings();
    combatLoadHistory();
  });

  // ── ① 运行卡（旧界面 L430-446）────────────────────────────────────────
  function buildCombatRunCard(app, meta) {
    const built = cfgCard(
      '4C 自动战斗',
      ''
    );
    const btnRow = P.el('div', { class: 'cfg-btn-row' });
    COMBAT_STATE.btnStart = P.el('button', {
      class: 'cfg-btn cfg-btn-primary', type: 'button', text: '启动',
      onClick: function () { combatAction('start'); }
    });
    COMBAT_STATE.btnStop = P.el('button', {
      class: 'cfg-btn', type: 'button', text: '停止',
      onClick: function () { combatAction('stop'); }
    });
    btnRow.appendChild(COMBAT_STATE.btnStart);
    btnRow.appendChild(COMBAT_STATE.btnStop);
    built.body.appendChild(btnRow);

    COMBAT_STATE.stateLabel = P.el('div', {
      class: 'cfg-state',
      text: '',
      //: ★ 2026-11-03 用户圈图「去掉」——常态下不显示任何说明文字。
      //: 失败 / 占用 / 运行中时才由 ``combatUpdateState'' 显示出来。
      //: 见 ``Panels.setStateLabel`` 的说明（不能直接删元素，
      //: 否则连失败反馈一起没了 → 静默失败）。
      hidden: true
    });
    built.body.appendChild(COMBAT_STATE.stateLabel);
    void app; void meta;
    return built.card;
  }

  // ── ② 战斗方式卡（旧界面 L481-530）─────────────────────────────────────
  function buildCombatStyleCard() {
    const built = cfgCard(
      '战斗方式',
      ''
    );
    //: ★ 2026-11-03（第二批）用户圈图：「这个调整成居中」
    //:
    //: 旧界面这一行是 ``[下拉框 160px][说明文字 flex:1]`` —— 说明文字
    //: 撑满右边，所以下拉框**看起来**是靠左但整行是满的。
    //: 上一轮按用户要求把说明文字删了，于是整行只剩一个 160px 的下拉框
    //: 贴在 1224px 宽的卡片最左边，右边一大片空白，很空。
    //:
    //: 现在用 ``.cfg-row-center`` 让这一个控件在行内**水平居中**
    //: （只加在这张卡上，不动 ``.cfg-inline-row`` —— 那个有 8 处在用）。
    const row = P.el('div', { class: 'cfg-inline-row cfg-row-center' });
    COMBAT_STATE.style = Panels.select(
      COMBAT_STYLES_FALLBACK.map(function (s) {
        return { value: s.value, label: s.label };
      }),
      DEFAULT_COMBAT_STYLE
    );
    COMBAT_STATE.style.el.classList.add('cfg-select');
    //: ★ 2026-11-03 用户：「这个下拉框也有点长了」
    //:
    //: 原来 ``.cfg-select`` 写死 160px（旧界面 ``setMinimumWidth(160)``），
    //: 但「智能切换」四个字量出来只要 ~110px —— 160 就显得空。
    //: 改成和「目标属性」下拉一样的**按最长选项量宽度**。
    sizeSelectToLongestOption(COMBAT_STATE.style.el,
      COMBAT_STYLES_FALLBACK.map(function (s) {
        return { value: s.value, label: s.label };
      }));
    row.appendChild(COMBAT_STATE.style.el);
    //: ★★★ 2026-11-03 用户圈图「去掉」——删掉了下拉框右边那行说明：
    //:
    //:   「ok-ww 原生调度：按 buff 剩余时间和角色定位挑人。
    //:     这是 ok-ww 官方行为，默认就用它。」
    //:
    //: 用户在前面几轮已经要求「7 个工具页的说明文字全删」，
    //: 这行是漏网的一个 —— 它跟着下拉选项变，藏得比较深。
    //:
    //: ⚠ 连 ``styleHint`` 节点、``combatUpdateStyleHint()`` 函数、
    //:   ``change`` 监听**一起删干净**了 —— 只删节点、留着对
    //:   ``COMBAT_STATE.styleHint`` 的引用，会触发 ``js_sanity`` 的
    //:   「静默失败」检查（引用了但从未赋值的字段恒为 null），
    //:   那正是本项目反复踩过的坑。
    built.body.appendChild(row);
    return built.card;
  }
  // ── ③ 定时关机卡（旧界面 L602-652）─────────────────────────────────────
  function buildCombatShutdownCard() {
    const built = cfgCard(
      '定时关机',
      ''
    );
    const row = P.el('div', { class: 'cfg-inline-row' });

    const checkWrap = P.el('label', { class: 'cfg-check' });
    COMBAT_STATE.shutdownCheck = P.el('input', { type: 'checkbox' });
    checkWrap.appendChild(COMBAT_STATE.shutdownCheck);
    checkWrap.appendChild(P.el('span', { text: '启用' }));
    row.appendChild(checkWrap);

    COMBAT_STATE.shutdownEdit = Panels.numberInput(DEFAULT_SHUTDOWN_MINUTES, {
      min: MIN_SHUTDOWN_MINUTES, max: MAX_SHUTDOWN_MINUTES
    });
    COMBAT_STATE.shutdownEdit.el.classList.add('cfg-number');
      COMBAT_STATE.shutdownEdit.input.classList.add('cfg-number-input');
    row.appendChild(COMBAT_STATE.shutdownEdit.el);
    row.appendChild(P.el('span', { class: 'cfg-muted', text: '分钟后关机' }));
    row.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    row.appendChild(P.el('span', {
      class: 'cfg-muted',
      text: '（' + MIN_SHUTDOWN_MINUTES + '~' + MAX_SHUTDOWN_MINUTES + ' 分钟）'
    }));
    built.body.appendChild(row);

    COMBAT_STATE.shutdownState = P.el('div', { class: 'cfg-state-muted' });
    built.body.appendChild(COMBAT_STATE.shutdownState);

    COMBAT_STATE.shutdownCheck.addEventListener('change', function () {
      combatRefreshShutdownState();
      combatSaveShutdown();
    });
    COMBAT_STATE.shutdownEdit.el.addEventListener('change', function () {
      combatRefreshShutdownState();
      combatSaveShutdown();
    });
    return built.card;
  }

  function combatRefreshShutdownState() {
    const el = COMBAT_STATE.shutdownState;
    if (!el) return;
    //: ★ 2026-11-03 用户圈图「去掉」——「未启用（不勾选就不会关机）。」
    //: 这行是**纯说明**（复选框本身就是"启用/未启用"的表达），删掉。
    //:
    //: ⚠ 「已启用：跑够 N 分钟后关机。」**保留** —— 那是**当前设置的
    //: 回显**（勾上之后必须能看见自己设了多少分钟），不是说明文字。
    if (!COMBAT_STATE.shutdownCheck.checked) {
      el.textContent = '';
      el.hidden = true;
      return;
    }
    el.hidden = false;
    el.textContent = '已启用：跑够 ' +
      COMBAT_STATE.shutdownEdit.get() + ' 分钟后关机。';
  }

  // ── ④ 战斗报告卡（旧界面 ``BattleReportCard``）─────────────────────────
  function buildCombatReportCard() {
    const built = cfgCard('战斗报告', '');
    COMBAT_STATE.reportHost = P.el('div', { class: 'cfg-report' });
    built.body.appendChild(COMBAT_STATE.reportHost);
    combatRenderReport(null);
    return built.card;
  }

  function combatRenderReport(data) {
    const host = COMBAT_STATE.reportHost;
    if (!host) return;
    P.fill(host, null);
    const rows = [
      ['使用队伍', data && data.team
        ? String(data.team) : '还没识别到（进战斗后会自动读队伍）'],
      ['战斗时长', data && data.duration ? String(data.duration) : '—'],
      ['击杀', data && data.kills != null ? String(data.kills) : '—'],
      ['获得声骸', data && data.echoes != null ? String(data.echoes) : '—']
    ];
    for (const pair of rows) {
      const row = P.el('div', { class: 'cfg-report-row' });
      row.appendChild(P.el('span', { class: 'cfg-report-key', text: pair[0] }));
      row.appendChild(P.el('span', { class: 'cfg-report-val', text: pair[1] }));
      host.appendChild(row);
    }
  }

  // ── ⑤ 历史记录卡（旧界面 L458-470）─────────────────────────────────────
  function buildCombatHistoryCard() {
    const built = cfgCard('历史记录', '');
    const head = P.el('div', { class: 'cfg-inline-row' });
    head.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    head.appendChild(P.button('刷新', {
      size: 'sm',
      onClick: function () { combatLoadHistory(); }
    }));
    built.body.appendChild(head);
    COMBAT_STATE.historyHost = P.el('div', { class: 'cfg-history' });
    built.body.appendChild(COMBAT_STATE.historyHost);
    return built.card;
  }

  // ── 数据 ──────────────────────────────────────────────────────────────
  async function combatLoadSettings() {
    const result = await P.call('getToolSettings', 'auto_combat');
    if (result.ok && result.data && result.data.ok !== false) {
      const data = result.data;
      const choices = (data.choices || {}).style;
      if (Array.isArray(choices) && choices.length) {
        const normalized = choices.map(function (item) {
          if (typeof item === 'string') return { value: item, label: item };
          return {
            value: item.value != null ? item.value : item.key,
            label: item.label != null ? item.label : (item.name || item.value),
            desc: item.desc || item.description || ''
          };
        }).filter(function (s) { return s.value; });
        if (normalized.length) {
          COMBAT_STATE.styles = normalized;
          COMBAT_STATE.style.setOptions(normalized, COMBAT_STATE.style.get());
        }
      }
      const settings = data.settings || {};
      const savedStyle = String(settings.style || '');
      const legal = (COMBAT_STATE.styles || COMBAT_STYLES_FALLBACK)
        .map(function (s) { return s.value; });
      if (savedStyle && legal.indexOf(savedStyle) >= 0) {
        COMBAT_STATE.style.set(savedStyle);
      }
    }

    // ── 定时关机：**独立接口** ``getShutdownTimer()`` ──
    //
    //: ``@Slot(result=str)`` —— **不传参数**。
    //: 返回 ``{enabled, minutes, minMinutes, maxMinutes, defaultMinutes}``。
    //: ⚠ ``enabled=false`` 时 ``minutes`` 仍是上次填的值（旧界面取消勾选不清掉），
    //:   所以输入框显示 ``minutes`` 而不是默认值。
    const sd = await P.call('getShutdownTimer');
    if (sd.ok && sd.data && sd.data.ok !== false) {
      const s = sd.data;
      if (COMBAT_STATE.shutdownCheck) {
        COMBAT_STATE.shutdownCheck.checked = !!s.enabled;
      }
      if (COMBAT_STATE.shutdownEdit) {
        const mins = Number(s.minutes);
        COMBAT_STATE.shutdownEdit.set(
          isFinite(mins) && mins > 0
            ? mins
            : (Number(s.defaultMinutes) || DEFAULT_SHUTDOWN_MINUTES));
        //: 用后端给的 min/max，别把常数抄一遍
        //: ⚠ ``numberInput`` 现在返回的是 ``[−] [input] [+]`` 容器，
        //:   输入框在 ``.input`` 上（``.el`` 是外层 div）
        if (s.minMinutes != null) {
          COMBAT_STATE.shutdownEdit.input.min = s.minMinutes;
        }
        if (s.maxMinutes != null) {
          COMBAT_STATE.shutdownEdit.input.max = s.maxMinutes;
        }
      }
      combatRefreshShutdownState();
    }

    combatPoll();
    COMBAT_STATE.pollTimer = setInterval(combatPoll, 1500);
  }

  /** 存定时关机设置（``setShutdownTimer``，``@Slot(str, result=str)``）*/
  async function combatSaveShutdown() {
    await P.call('setShutdownTimer', JSON.stringify({
      enabled: COMBAT_STATE.shutdownCheck.checked,
      minutes: COMBAT_STATE.shutdownEdit.get()
    }));
  }

  async function combatPoll() {
    const result = await P.call('getOkwwState');
    if (!result.ok || !result.data) return;
    const data = result.data;
    const state = String(data.state || 'idle');
    const running = String(data.runningTask || '');
    const pending = String(data.pendingStart || '');

    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    let myTask = '';
    for (const item of tasks) {
      if (item && item.key === 'auto_combat') {
        myTask = String(item.taskKey || item.name || '');
        break;
      }
    }

    const label = COMBAT_STATE.stateLabel;
    if (label) {
      //: ★★★ 2026-11-03 用户圈图「去掉」—— 删掉了这两条**静态说明**：
      //:
      //:   「引擎：就绪 · 点「启动」开始 4C 刷声骸」  ← 常态挂着那行字
      //:   「引擎：后台加载中…」
      //:
      //: ⚠ 但**「启动中」不能删**：引擎首次冷启动实测 ~20 秒
      //: （ok-ww + onnxocr + openvino 初始化）。这期间界面一声不吭的话，
      //: 用户会以为按钮坏了反复点。
      //:
      //: 判据：**状态会自己变回去的** = 反馈（留）；
      //:       **一直挂着不动的** = 说明（删）。
      if (state === 'error') {
        Panels.setStateLabel(label, '引擎：启动失败 —— ' +
          String(data.bootError || '详见日志'));
      } else if (running && myTask && running !== myTask) {
        Panels.setStateLabel(label, '引擎：被占用（正在跑 ' + running + '）');
      } else if (running) {
        Panels.setStateLabel(label,
          '引擎：运行中 —— ' + running + ' · 点「停止」结束');
      } else if (pending || state === 'booting') {
        //: ★ 反馈：引擎正在起来（会被下面的「运行中 / 失败」覆盖掉）
        Panels.setStateLabel(label, '引擎：正在启动…');
      } else if (!settlePendingStart(COMBAT_STATE, running, pending, state)) {
        //: ★ 刚点完运行、引擎还在冷启动（后端此时仍报 idle）——
        //: 别清掉「正在启动…」，否则用户 20 秒看不到任何反应。
        //: 见 ``settlePendingStart`` 的说明。
        Panels.setStateLabel(label, '引擎：正在启动…');
      } else {
        //: 就绪 —— 常态，不显示任何说明
        Panels.setStateLabel(label, '');
      }
    }

    const isMine = running && myTask && running === myTask;
    if (COMBAT_STATE.btnStart) {
      COMBAT_STATE.btnStart.disabled = !!(running || pending);
    }
    if (COMBAT_STATE.btnStop) {
      COMBAT_STATE.btnStop.disabled = !(running || pending);
    }
    if (COMBAT_STATE.tracker) {
      COMBAT_STATE.tracker.observe({ running: !!isMine, engineState: state });
    }
  }

  async function combatLoadHistory() {
    const host = COMBAT_STATE.historyHost;
    if (!host) return;
    //: ⚠ ``@Slot(str, result=str)`` —— 必须传字符串（不传静默返回 ``[]``）。
    //: 空串 = 用默认（后端 ``limit: str = ""``，内部按 5 条取）。
    const result = await P.call('getCombatHistory', '');
    if (!result.ok) {
      P.fill(host, [P.el('div', {
        class: 'cfg-muted', text: '历史记录接口未就绪。'
      })]);
      return;
    }
    const data = result.data || {};
    const items = Array.isArray(data.items) ? data.items : [];
    P.fill(host, null);
    if (!items.length) {
      host.appendChild(P.el('div', {
        class: 'cfg-muted', text: '还没有历史 —— 跑过一轮后这里会记录。'
      }));
      return;
    }
    for (const rec of items) {
      const row = P.el('div', { class: 'cfg-history-row' });
      row.appendChild(P.el('span', {
        class: 'cfg-history-when', text: String(rec.when || '')
      }));
      const bits = [];
      if (rec.duration) bits.push(String(rec.duration));
      if (rec.battles != null) bits.push('战斗 ' + rec.battles);
      if (rec.echoes != null) bits.push('声骸 ' + rec.echoes);
      if (rec.locked != null) bits.push('锁定 ' + rec.locked);
      row.appendChild(P.el('span', {
        class: 'cfg-history-stat', text: bits.join(' · ')
      }));
      host.appendChild(row);
    }
    if (data.totalText) {
      host.appendChild(P.el('div', {
        class: 'cfg-muted', style: 'margin-top:6px', text: String(data.totalText)
      }));
    }
  }

  async function combatAction(action) {
    if (action === 'start') {
      await P.callMulti('setToolSettings', [JSON.stringify({
        toolKey: 'auto_combat', settings: { style: COMBAT_STATE.style.get() }
      })]);
      COMBAT_STATE.tracker = Panels.trackRun({
        timeoutMs: 20000,
        onFinish: function () { combatRenderReport(null); },
        onGiveUp: function () {}
      });
      COMBAT_STATE.tracker.reset();
      //: ★★★ 2026-11-03 **「正在启动…」必须保留**
      //:
      //: 我一开始把它当"说明文字"删了 —— 那是错的：
      //: 引擎是**首次冷启动**（实测 ~20 秒：加载 ok-ww + onnxocr +
      //: openvino 初始化）。这期间点「运行」如果界面一声不吭，
      //: 用户会以为按钮坏了，反复点。
      //:
      //: 判据：**状态会自己变回去的**就是反馈，**一直挂着不动的**才是说明。
      //: 「正在启动…」→「运行中 / 失败」，属于前者。
      markPendingStart(COMBAT_STATE);
      setStateLabel(COMBAT_STATE.stateLabel, '引擎：正在启动…');
      const result = await P.call('runOkwwTask', JSON.stringify({
        taskKey: 'auto_combat'
      }));
      if (!result.ok) {
        clearPendingStart(COMBAT_STATE);
        setStateLabel(COMBAT_STATE.stateLabel,
          '引擎：启动请求失败（接口未就绪）');
        return;
      }
      const data = result.data || {};
      if (data.ok === false) {
        clearPendingStart(COMBAT_STATE);
        setStateLabel(COMBAT_STATE.stateLabel,
          '引擎：' + String(data.message || data.reason || '启动失败'));
        return;
      }
      //: ★ 受理成功也**保留** pending 标记 —— 引擎冷启动期间后端还报 idle，
      //: 立刻清掉会让轮询把「正在启动…」擦干净（实测 0.8 秒就没了）。
      //: 标记会在轮询真正看到 running/booting 后自然失效，或 30 秒超时。
      if (COMBAT_STATE.tracker) COMBAT_STATE.tracker.accept();
      return;
    }

    //: ★ 停止也要有即时反馈（同「正在启动」的理由 —— 停引擎要几秒）
    clearPendingStart(COMBAT_STATE);
    setStateLabel(COMBAT_STATE.stateLabel, '引擎：正在停止…');
    const r = await P.call('stopOkwwTask');
    if (!r.ok) {
      setStateLabel(COMBAT_STATE.stateLabel,
        '引擎：停止失败（接口未就绪）');
      return;
    }
    const d = r.data || {};
    if (d.ok === false) {
      setStateLabel(COMBAT_STATE.stateLabel,
        '引擎：' + String(d.message || d.reason || '没有正在运行的任务'));
    }
  }
  // ════════════════════════════════════════════════════════════════════════
  //  ⑦ 资源库更新  wuwa_library_update   （**照抄旧界面 2 块**）
  //
  //  ## ⚠ P6 重写
  //
  //  旧界面 ``tools/data/wuwa_library_update.py`` L101-141：
  //
  //  .. code:: python
  //
  //    L101  root.addWidget(TitleLabel("资源库更新"))
  //    L102  note  "数据来源：库街区官方 wiki（…）。检查只发几个轻量请求…
  //                角色名单只增不减：…"
  //    L113  status_card                       ← **一张卡**（不是我们做的 5 块）
  //            title_row: [状态文字] stretch [重新检查][获取最新数据]
  //            _summary: QTextEdit（只读，min-height 180）← 变更摘要
  //
  //  **按钮在卡片标题行右侧**，不是页面右上角。
  //
  //  ## ``_on_checked`` 的三种结局（L188-225）
  //
  //  .. code:: python
  //
  //    if report.remote_empty:            # 远端没返回数据
  //        "没能取到远端数据"              ← ⚠ 这**不是**"已是最新"
  //    elif report.has_updates:
  //        "发现数据更新"
  //    else:
  //        "数据已是最新"
  //
  //  第一种是最容易写错的 —— 网络挂了 / wiki 改结构时会这样，
  //  报"已是最新"等于骗用户"检查过了没事"。
  // ════════════════════════════════════════════════════════════════════════

  const LIB_STATE = {
    autoChecked: false,
    report: null,
    hasSnapshot: false,
    statusLabel: null,
    summaryEl: null,
    recheckBtn: null,
    applyBtn: null
  };

  registerPanel('wuwa_library_update', function renderLibraryUpdate(container, app, meta) {
    // ── ① 标题（旧界面 TitleLabel，22px）──
    container.appendChild(P.el('div', {
      class: 'gk-title', text: '资源库更新'
    }));

    // ── ② 说明（旧界面 L102-111，**逐字照抄**）──
    container.appendChild(P.el('div', {
      class: 'gk-note',
      text: '数据来源：库街区官方 wiki（套装效果 / 声骸掉落池 / 角色名单 / ' +
        '技能说明 / 图标 —— 全部只从它拿）。\n' +
        '检查只发几个轻量请求，不会写任何本地文件。\n' +
        '角色名单只增不减：新角色会加进来（配置页就能选到），已有的不会被删。'
    }));

    // ── ③ 状态卡（旧界面 L113-141，**唯一一张卡**）──
    const statusCard = P.el('div', { class: 'lib-status-card card-glass' });

    const titleRow = P.el('div', { class: 'lib-status-head' });
    LIB_STATE.statusLabel = P.el('div', {
      class: 'lib-status-text', text: '尚未检查'
    });
    titleRow.appendChild(LIB_STATE.statusLabel);
    titleRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));

    //: 两个按钮在**卡片标题行右侧**（旧界面 title_row 里）
    LIB_STATE.recheckBtn = P.button('重新检查', {
      size: 'sm',
      onClick: function () { libCheck(); }
    });
    titleRow.appendChild(LIB_STATE.recheckBtn);

    LIB_STATE.applyBtn = P.button('获取最新数据', {
      kind: 'primary',
      size: 'sm',
      disabled: true,
      onClick: function () { libApply(); }
    });
    titleRow.appendChild(LIB_STATE.applyBtn);
    statusCard.appendChild(titleRow);

    //: 变更摘要（旧界面 ``QTextEdit`` 只读、min-height 180）
    LIB_STATE.summaryEl = P.el('div', {
      class: 'lib-summary',
      id: 'lib-update-summary'
    });
    LIB_STATE.summaryEl.appendChild(P.el('div', {
      class: 'lib-summary-placeholder',
      text: '打开本工具会自动在后台检查更新；发现更新后点「获取最新数据」应用。'
    }));
    statusCard.appendChild(LIB_STATE.summaryEl);
    container.appendChild(statusCard);

    // ── 事件 ──
    window.Bridge.on('libraryChecked', function (data) {
      libOnChecked(data || {});
    });
    window.Bridge.on('libraryApplied', function (data) {
      libOnApplied(data || {});
    });

    //: ★ 打开就自动检查一次（旧界面 ``showEvent`` L144-149 的 ``_auto_checked``）
    if (!LIB_STATE.autoChecked) {
      LIB_STATE.autoChecked = true;
      setTimeout(function () { libCheck(); }, 280);
    } else if (LIB_STATE.report) {
      libRenderReport(LIB_STATE.report);
    }
    void app; void meta;
  });

  /** 状态文字 + 摘要区（旧界面 ``_status_label`` / ``_summary``）*/
  function libSetStatus(text, summaryText) {
    if (LIB_STATE.statusLabel) LIB_STATE.statusLabel.textContent = text || '';
    if (summaryText != null && LIB_STATE.summaryEl) {
      P.fill(LIB_STATE.summaryEl, null);
      const lines = String(summaryText).split('\n');
      for (const line of lines) {
        if (!line) continue;
        LIB_STATE.summaryEl.appendChild(P.el('div', {
          class: 'lib-summary-line', text: line
        }));
      }
    }
  }

  async function libCheck() {
    LIB_STATE.recheckBtn.disabled = true;
    LIB_STATE.applyBtn.disabled = true;
    libSetStatus('正在检查更新…', '');

    const result = await P.call('checkLibraryUpdate');

    if (!result.ok) {
      LIB_STATE.recheckBtn.disabled = false;
      libSetStatus('检查失败',
        '资源库更新需要 bridge 接口 checkLibraryUpdate()，目前还没接通。\n' +
        '数据层 core/wuwa_update.py 是现成的，缺的只是桥接。\n' +
        '现在要更新数据，请用旧界面启动：MYTOOLS_WEB_SHELL=0 python main.py');
      return;
    }

    const data = result.data || {};
    //: 同步拒绝（比如已经在检查中）
    if (data.ok === false) {
      LIB_STATE.recheckBtn.disabled = false;
      libSetStatus(String(data.message || '没能开始检查'), '');
      return;
    }
    //: 已受理 → 等 ``libraryChecked`` 事件
    libSetStatus('正在检查更新…', '');
  }

  function libOnChecked(data) {
    LIB_STATE.recheckBtn.disabled = false;

    //: 检查本身失败（网络异常等）
    if (data.ok === false) {
      LIB_STATE.hasSnapshot = false;
      libSetStatus('没能取到远端数据', String(data.message || ''));
      LIB_STATE.applyBtn.disabled = true;
      return;
    }

    const report = libNormalizeReport(data);
    LIB_STATE.report = report;
    LIB_STATE.hasSnapshot = !report.remoteEmpty;

    // ══════════════════════════════════════════════════════════════════
    //  ★ 三种结局分开（旧界面 ``_on_checked`` L188-225）
    // ══════════════════════════════════════════════════════════════════
    if (report.remoteEmpty) {
      //: ⚠ 远端没返回数据 —— 这**不是**"已是最新"
      libSetStatus('没能取到远端数据', report.summary || (
        '这次没从远端取到任何数据，所以无法判断有没有更新。\n' +
        '多半是网络不通，或者库街区的接口 / 页面结构变了。\n' +
        '请稍后点「重新检查」再试。'));
      LIB_STATE.applyBtn.disabled = true;
      return;
    }

    if (report.hasUpdates) {
      libSetStatus('发现数据更新', report.summary || '');
      LIB_STATE.applyBtn.disabled = false;
      return;
    }

    libSetStatus('数据已是最新',
      report.summary || '远端数据和本地一致，无需更新。');
    LIB_STATE.applyBtn.disabled = true;
  }

  async function libApply() {
    if (!LIB_STATE.hasSnapshot) {
      libSetStatus('没能取到远端数据',
        '请先点「重新检查」拿到远端数据，再应用更新。');
      return;
    }
    LIB_STATE.applyBtn.disabled = true;
    LIB_STATE.recheckBtn.disabled = true;
    libSetStatus('正在获取最新数据…', '');

    const result = await P.call('applyLibraryUpdate');

    if (!result.ok) {
      LIB_STATE.recheckBtn.disabled = false;
      libSetStatus('更新失败', '接口未就绪。');
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      LIB_STATE.recheckBtn.disabled = false;
      LIB_STATE.applyBtn.disabled = false;
      libSetStatus(String(data.message || '写入没能开始'), '');
      return;
    }
    //: 已受理 → 等 ``libraryApplied`` 事件
  }

  function libOnApplied(data) {
    LIB_STATE.recheckBtn.disabled = false;

    if (data.ok === false) {
      LIB_STATE.applyBtn.disabled = false;
      libSetStatus('更新失败', String(data.message || ''));
      return;
    }

    const done = Array.isArray(data.done) ? data.done : [];
    libSetStatus('更新完成', done.length ? done.join('\n') : '本地数据已写入。');

    //: 应用完就没有待应用的更新了
    LIB_STATE.report = null;
    LIB_STATE.hasSnapshot = false;
    LIB_STATE.applyBtn.disabled = true;

    //: 资源库页数据变旧 —— 清掉渲染标记，下次切过去会重新拉
    const librarySection = document.querySelector('.page[data-page="library"]');
    if (librarySection) librarySection.dataset.rendered = '0';
  }

  function libNormalizeReport(raw) {
    const r = raw || {};
    function arr() {
      for (let i = 0; i < arguments.length; i += 1) {
        if (Array.isArray(r[arguments[i]])) return r[arguments[i]];
      }
      return [];
    }
    const newSets = arr('newSets', 'new_sets');
    const effectChanged = arr('effectChanged', 'effect_changed');
    const newEchoes = arr('newEchoes', 'new_echoes');
    const newCharacters = arr('newCharacters', 'new_characters');
    return {
      newSets: newSets,
      effectChanged: effectChanged,
      newEchoes: newEchoes,
      newCharacters: newCharacters,
      remoteEmpty: !!(r.remoteEmpty || r.remote_empty),
      localEmpty: !!(r.localEmpty || r.local_empty),
      hasUpdates: r.hasUpdates != null ? !!r.hasUpdates
        : !!(newSets.length || effectChanged.length ||
             newEchoes.length || newCharacters.length),
      summary: r.summary || ''
    };
  }

  function libRenderReport(report) {
    if (!report) return;
    if (report.remoteEmpty) {
      libSetStatus('没能取到远端数据',
        '上次检查没能取到远端数据，建议重新检查。');
    } else if (report.hasUpdates) {
      libSetStatus('发现数据更新', report.summary || '');
      LIB_STATE.applyBtn.disabled = false;
    } else {
      libSetStatus('数据已是最新', report.summary || '数据已是最新。');
    }
  }

  //  ① 4C 自动战斗  auto_combat   （**照抄旧界面 5 张卡**）
  //
  //  ## ⚠ P6 重写：用户「不对啊，按照以前那个布局做啊」
  //
  //  旧界面 ``auto_combat/tool.py`` L429-468 的 ``layout.addWidget`` 顺序：
  //
  //  .. code:: python
  //
  //    L430  run_card = ConfigCard("4C 自动战斗", "战斗本体是 ok-ww 引擎…")
  //          row = [启动][停止]                    # 两个按钮各占一半宽
  //          run_card.add(state_label)             # "引擎：就绪 · 点「启动」…"
  //    L449  self._build_style_card(page)          # 战斗方式
  //    L452  self._build_shutdown_card(page)       # 定时关机
  //    L455  BattleReportCard(page)                # 战斗报告
  //    L468  history_card                          # 历史记录
  //
  //  **5 张卡，没有任何「运行前提」块** —— 那是 P5 我们自己加的，用户圈出「干掉」。
  //  前提写进了 run_card 的说明里（"引擎随程序启动已在后台加载"）。
  // ════════════════════════════════════════════════════════════════════════
  //  ② 声骸批量调频  echo_change   （**只有 1 张卡**）
  //
  //  ## ⚠ P6 重写：用户「其他的也是」+「对着旧界面的代码复刻」
  //
  //  旧界面 ``echo_change/tool.py`` L126-229 的 ``_build_run_card`` ——
  //  **全部内容都在这张卡里**：
  //
  //  .. code:: python
  //
  //    card = ConfigCard("声骸批量调频",
  //        "把过滤器筛出的声骸，主属性批量改成下面选的那一个。"
  //        "流程由 ok-ww 引擎执行（后台按键，不抢前台）。")
  //    row:  [目标属性]  [攻击 ▼]            ← 标签 60px、下拉 320px
  //    count_row: [数量] [−][数字][+]        ← 标签 60px、按钮 32x32
  //    hint:  数量最多**成功调频**多少个…（灰色说明，不渲染 markdown）
  //    buttons: [运行(主色)][停止]           ← 各占一半
  //    state_label: "引擎：…"               ← 卡内最后一行
  //
  //  P5 我把它拆成了 5 块（运行前提 / 参数卡 / 状态条 / 日志区…）—— **全错**。
  //
  //  ## 关于「数量」控件
  //
  //  旧界面 L164-167 的注释：
  //
  //    ★ 数量 = 〔−〕〔数字〕〔+〕，**左减右加**。
  //      用户 2026-09-27："左边-号按钮控制-1，右边+号按钮控制数量+1"。
  //      ⚠ **不能用 SpinBox**：它自带的是上下箭头（^ v），和"左右加减"不是一回事
  //
  //  所以这里是两个按钮夹一个居中数字框，**不是** number 输入的上下箭头。
  // ════════════════════════════════════════════════════════════════════════

  /** 目标属性列表 —— 逐字对齐 ``echo_change/okww_task.TARGET_STATS`` */
  const TARGET_STATS = [
    '攻击', '暴击伤害', '暴击', '生命', '防御', '共鸣效率',
    '冷凝伤害加成', '热熔伤害加成', '导电伤害加成',
    '气动伤害加成', '衍射伤害加成', '湮灭伤害加成'
  ];
  //: ``okww_task.DEFAULT_TARGET``
  const DEFAULT_TARGET = '攻击';
  //: ``tool.py`` 的 MAX_COUNT
  const MAX_COUNT = 999;
  //: ``tool.py`` 的 TARGET_BOX_WIDTH（用户 2026-09-27 要求"变短"）
  const TARGET_BOX_WIDTH = 320;
  //: ``tool.py`` 的 COUNT_BOX_WIDTH
  const COUNT_BOX_WIDTH = 90;

  const CHANGE_STATE = {
    handle: null,
    target: null,
    count: null,
    stateLabel: null,
    //: ★ 2026-11-03：「正在启动…」有效期（轮询不许清掉）——
    //: 引擎首次冷启动 ~20 秒，期间后端 state 还是 idle。见 COMBAT_STATE 的说明。
    pendingUntil: 0,
    runBtn: null,
    stopBtn: null,
    tracker: null,
    pollTimer: null,
    settings: null,
    choices: null
  };

  registerPanel('echo_change', function renderEchoChange(container, app, meta) {
    //: ★ 只有一张卡 —— 所有内容都在里面（旧界面 ``_build_run_card``）
    const built = cfgCard(
      '声骸批量调频',
      ''
    );

    // ── ① 目标属性行 ──
    const targetRow = P.el('div', { class: 'cfg-inline-row' });
    targetRow.appendChild(P.el('span', {
      class: 'cfg-label-fixed', text: '目标属性'
    }));
    CHANGE_STATE.target = Panels.select(TARGET_STATS, DEFAULT_TARGET);
    CHANGE_STATE.target.el.classList.add('cfg-select-wide');
    //: ★ 2026-11-03 宽度按**最长选项文字**算（``fit-content`` 在 select 上
    //: 会塌成 79px，见 CSS 里的说明）
    sizeSelectToLongestOption(CHANGE_STATE.target.el, TARGET_STATS);
    targetRow.appendChild(CHANGE_STATE.target.el);
    targetRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    built.body.appendChild(targetRow);

    // ── ② 数量行（〔−〕〔数字〕〔+〕，左减右加）──
    const countRow = P.el('div', { class: 'cfg-inline-row' });
    countRow.appendChild(P.el('span', {
      class: 'cfg-label-fixed', text: '数量'
    }));

    const minusBtn = P.el('button', {
      class: 'cfg-step', type: 'button', text: '−', title: '减 1',
      onClick: function () { changeStep(-1); }
    });
    countRow.appendChild(minusBtn);

    //: 居中数字框（不是 number 输入，避免上下箭头）
    CHANGE_STATE.count = P.el('input', {
      class: 'input cfg-count-box',
      type: 'text',
      value: '0',
      inputmode: 'numeric',
      title: '最多成功调频多少个；0 = 不限'
    });
    //: 只收 0~MAX 的整数（旧界面 ``QIntValidator(0, MAX_COUNT)``）
    CHANGE_STATE.count.addEventListener('input', function () {
      const cleaned = CHANGE_STATE.count.value.replace(/[^0-9]/g, '');
      if (cleaned !== CHANGE_STATE.count.value) {
        CHANGE_STATE.count.value = cleaned;
      }
    });
    CHANGE_STATE.count.addEventListener('change', function () {
      CHANGE_STATE.count.value = String(changeCountValue());
      changeSaveSettings();
    });
    countRow.appendChild(CHANGE_STATE.count);

    const plusBtn = P.el('button', {
      class: 'cfg-step', type: 'button', text: '＋', title: '加 1',
      onClick: function () { changeStep(1); }
    });
    countRow.appendChild(plusBtn);
    countRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    built.body.appendChild(countRow);

    //: ★★★ 2026-11-03 用户：「另外文字说明也去掉，再检查其他地方有没有类似情况」
    //:
    //: 这里删掉的是「数量最多**成功调频**多少个（点 −/+ 每次 1 个；填 0 = 不限）。
    //: 已经是目标属性的声骸会被**跳过**（不会中断任务）……」那整段灰字。
    //:
    //: ⚠ 旧界面确实有这段（``echo_change/tool.py`` L198-206），但用户
    //: 2026-11-02 起**反复要求「工具页的说明文字全删」**，之前几轮就
    //: 删过 7 个工具页的说明，只是这一段漏了 —— 属于「用户主动推翻
    //: 旧设计」，不是我们擅自修改。
    //:
    //: 上限仍然存在（后端夹 0~MAX），只是不再用一段话解释它。

    // ── ④ 运行 / 停止 ──
    const btnRow = P.el('div', { class: 'cfg-btn-row' });
    CHANGE_STATE.runBtn = P.el('button', {
      class: 'cfg-btn cfg-btn-primary', type: 'button', text: '运行',
      onClick: function () { changeAction('run'); }
    });
    CHANGE_STATE.stopBtn = P.el('button', {
      class: 'cfg-btn', type: 'button', text: '停止',
      onClick: function () { changeAction('stop'); }
    });
    btnRow.appendChild(CHANGE_STATE.runBtn);
    btnRow.appendChild(CHANGE_STATE.stopBtn);
    built.body.appendChild(btnRow);

    // ── ⑤ 状态行（旧界面 self.state_label）──
    //: ★ 2026-11-03 用户圈图「去掉」—— 常态不显示说明文字。
    //: 失败反馈仍会由 ``Panels.setStateLabel`` 显示出来（不能删元素）。
    CHANGE_STATE.stateLabel = P.el('div', {
      class: 'cfg-state',
      text: '',
      hidden: true
    });
    built.body.appendChild(CHANGE_STATE.stateLabel);

    container.appendChild(built.card);

    changeLoadSettings();
    void app; void meta;
  });

  /** 当前数量（夹到 0~MAX；旧界面 ``count()`` 的容错）*/
  function changeCountValue() {
    const raw = String((CHANGE_STATE.count && CHANGE_STATE.count.value) || '0');
    const n = parseInt(raw, 10);
    if (!isFinite(n) || isNaN(n)) return 0;
    return Math.max(0, Math.min(MAX_COUNT, n));
  }

  /** 数量 ±1（旧界面 ``_step_count``，夹边界在这做）*/
  function changeStep(delta) {
    const next = Math.max(0, Math.min(MAX_COUNT, changeCountValue() + delta));
    if (CHANGE_STATE.count) CHANGE_STATE.count.value = String(next);
    changeSaveSettings();
  }

  async function changeSaveSettings() {
    const payload = JSON.stringify({
      toolKey: 'echo_change',
      settings: {
        target_stat: CHANGE_STATE.target.get(),
        max_count: changeCountValue()
      }
    });
    await P.callMulti('setToolSettings', [payload]);
  }

  // ── 数据 ──────────────────────────────────────────────────────────────
  async function changeLoadSettings() {
    const result = await P.call('getToolSettings', 'echo_change');
    //: ★ 不能静默返回 —— 读不到设置时界面会显示「攻击 / 0」这种默认值，
    //: 用户会以为自己的设置丢了。在状态行说明原因。
    if (!result.ok) {
      if (CHANGE_STATE.stateLabel) {
        CHANGE_STATE.stateLabel.textContent =
          '引擎：设置读取失败（接口未就绪）—— 现在显示的是默认值';
      }
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      if (CHANGE_STATE.stateLabel) {
        CHANGE_STATE.stateLabel.textContent =
          '引擎：设置读取失败 —— 现在显示的是默认值';
      }
      return;
    }

    //: ★ 选项列表：后端 ``choices.targetStat`` 优先（工具模块直读，永不漂移）
    const choices = (data.choices || {}).targetStat;
    if (Array.isArray(choices) && choices.length) {
      CHANGE_STATE.choices = choices.slice();
      CHANGE_STATE.target.setOptions(choices, CHANGE_STATE.target.get());
    } else {
      CHANGE_STATE.choices = TARGET_STATS.slice();
    }
    const legal = CHANGE_STATE.choices;

    //: 上次保存的值（settings 是**下划线**命名：target_stat / max_count）
    const settings = data.settings || {};
    CHANGE_STATE.settings = settings;
    const saved = String(settings.target_stat || '');
    if (saved && legal.indexOf(saved) >= 0) {
      CHANGE_STATE.target.set(saved);
    } else if (saved) {
      //: 存了个不认识的值 —— 回落到 default（明说，不静默）
      const fallback = String((data.defaults && data.defaults.targetStat)
        || DEFAULT_TARGET);
      CHANGE_STATE.target.set(fallback);
    }
    const rawCount = settings.max_count;
    if (rawCount != null && rawCount !== '') {
      const n = Number(rawCount);
      if (isFinite(n) && n >= 0 && CHANGE_STATE.count) {
        CHANGE_STATE.count.value = String(Math.min(MAX_COUNT, Math.floor(n)));
      }
    }

    //: 引擎状态轮询
    changePoll();
    CHANGE_STATE.pollTimer = setInterval(changePoll, 1500);
  }

  async function changePoll() {
    const result = await P.call('getOkwwState');
    if (!result.ok || !result.data) return;
    const data = result.data;
    const state = String(data.state || 'idle');
    const running = String(data.runningTask || '');
    const pending = String(data.pendingStart || '');

    //: 本工具的 taskKey（名字就叫「声骸批量调频」）
    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    let myTask = '';
    for (const item of tasks) {
      if (item && item.key === 'echo_change') {
        myTask = String(item.taskKey || item.name || '');
        break;
      }
    }

    const label = CHANGE_STATE.stateLabel;
    if (label) {
      //: ★ 2026-11-03 与 4C / 扫荡 统一：
      //:   常态（就绪 / 后台加载）**不显示说明文字**（用户圈图要求删）；
      //:   失败 / 占用 / 运行中 / 启动中 是**反馈**，必须显示。
      if (state === 'error') {
        Panels.setStateLabel(label, '引擎：启动失败 —— ' +
          String(data.bootError || '详见日志'));
      } else if (running && myTask && running !== myTask) {
        Panels.setStateLabel(label, '引擎：被占用（正在跑 ' + running + '）');
      } else if (running) {
        Panels.setStateLabel(label,
          '引擎：运行中 —— ' + running + ' · 点「停止」结束');
      } else if (pending || state === 'booting') {
        Panels.setStateLabel(label, '引擎：正在启动…');
      } else if (!settlePendingStart(CHANGE_STATE, running, pending, state)) {
        //: 引擎冷启动 ~20 秒，期间后端可能还报 idle —— 别清掉反馈
        Panels.setStateLabel(label, '引擎：正在启动…');
      } else {
        Panels.setStateLabel(label, '');
      }
    }

    const isMine = running && myTask && running === myTask;
    if (CHANGE_STATE.runBtn) {
      CHANGE_STATE.runBtn.disabled = !!(running || pending);
    }
    if (CHANGE_STATE.stopBtn) {
      CHANGE_STATE.stopBtn.disabled = !(running || pending);
    }
    if (CHANGE_STATE.tracker) {
      CHANGE_STATE.tracker.observe({ running: !!isMine, engineState: state });
    }
  }

  /** 运行 / 停止（旧界面 ``_on_run`` / ``_on_stop``）*/
  async function changeAction(action) {
    if (action === 'run') {
      //: ★ 先给反馈，再做任何 await —— 点下去立刻有反应
      //: （``changeSaveSettings`` 也是排队异步的，前一个面板占着桥时会卡住）
      markPendingStart(CHANGE_STATE);
      Panels.setStateLabel(CHANGE_STATE.stateLabel, '引擎：正在启动…');

      //: 先把界面上的参数存盘（引擎跑的时候读 tool_settings）
      await changeSaveSettings();

      CHANGE_STATE.tracker = Panels.trackRun({
        timeoutMs: 12000,
        onFinish: function () {},
        onGiveUp: function () {}
      });
      CHANGE_STATE.tracker.reset();

      const result = await P.call('runOkwwTask', JSON.stringify({
        taskKey: 'echo_change',
        config: {
          '目标属性': CHANGE_STATE.target.get(),
          '数量上限': changeCountValue()
        }
      }));

      if (!result.ok) {
        clearPendingStart(CHANGE_STATE);
        Panels.setStateLabel(CHANGE_STATE.stateLabel,
          '引擎：启动请求失败（接口未就绪）');
        return;
      }
      const data = result.data || {};
      if (data.ok === false) {
        clearPendingStart(CHANGE_STATE);
        Panels.setStateLabel(CHANGE_STATE.stateLabel,
          '引擎：' + String(data.message || data.reason || '启动失败'));
        return;
      }
      //: ★★★ 2026-11-03 **受理成功也不能清掉 pending 标记**
      //:
      //: 踩到过：这里原本写着 ``clearPendingStart()`` —— 意思是
      //: 「后端受理了，交给轮询」。但引擎**冷启动要 ~20 秒**，
      //: 这期间 ``getOkwwState()`` 返回的还是 ``state:"idle"``，
      //: 轮询一看 idle、又没有 pending 标记 → 立刻把「正在启动…」清空。
      //:
      //: 实测时间线（探针）：
      //:
      //: .. code:: text
      //:
      //:     点完立刻    「引擎：正在启动…」   ← 对
      //:     点完 0.8s   （空，hidden）        ← 被轮询清了
      //:
      //: 用户视角就是「点了一下，然后就没了」。
      //:
      //: 正确做法：**保留标记**，让 ``isPendingStart()`` 一直撑到
      //: 轮询真的看到 ``running`` / ``booting`` 为止（或 30 秒超时）。
      if (CHANGE_STATE.tracker) CHANGE_STATE.tracker.accept();
      return;
    }

    // ── 停止 ──
    clearPendingStart(CHANGE_STATE);
    Panels.setStateLabel(CHANGE_STATE.stateLabel, '引擎：正在停止…');
    const r = await P.call('stopOkwwTask');
    if (!r.ok) {
      Panels.setStateLabel(CHANGE_STATE.stateLabel,
        '引擎：停止失败（接口未就绪）');
      return;
    }
    const d = r.data || {};
    if (d.ok === false) {
      Panels.setStateLabel(CHANGE_STATE.stateLabel,
        '引擎：' + String(d.message || d.reason || '没有正在运行的任务'));
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  ③ 扫荡残像聚落  nest_sweep   （**照抄旧界面 2 张卡**）
  //
  //  ## ⚠ P6 重写
  //
  //  旧界面 ``nest_sweep/tool.py`` L506-508：
  //
  //  .. code:: python
  //
  //    layout.addWidget(self._build_run_card(page))     # ①运行卡
  //    layout.addWidget(self._build_targets_card(page)) # ②「残像聚落」卡片墙
  //    layout.addStretch(1)
  //
  //  **只有 2 张卡**，没有「运行前提」，没有页面级标题。
  //
  //  ## 运行卡结构（L545-596）
  //
  //  .. code:: text
  //
  //    扫荡残像聚落
  //    勾选要刷的目标，点「运行」后**按下面的顺序一个一个刷**
  //    （顺序 = 卡片顺序 = **版本从新到旧**，同一版本内看 order）。
  //    [全选][全不选][反选]   已选 10 个        ← 勾选行（左右两段）
  //    [运行][停止]  引擎：就绪 · 点「运行」开始扫荡   ← 运行行（同一行）
  //    [进度文字]                                ← 跑起来才有内容
  //
  //  ## 目标卡结构（``TargetCard`` L202-345）
  //
  //  .. code:: text
  //
  //    ┌────────────────────────────────┐
  //    │    [图]套装A  [图]套装B          │   ← 套装在上（图标 + 名称）
  //    │    [图]套装C  [图]套装D          │      高度按**实际行数**
  //    │        复生丘原残像聚落           │   ← 名字**居中**
  //    │              ☑                 │   ← 勾选框在名字**下面**、单独居中
  //    └────────────────────────────────┘
  //
  //  ⚠ 网格 **3 列**（``CARD_COLUMNS = 3``）、卡最小宽 **260**（``CARD_MIN_WIDTH``）、
  //  卡片内边距 14/12/14/12、间距 8、**上下各一个 stretch**（内容垂直居中）。
  //
  //  ⚠ 卡片上**不再显示**「每日 48 · 3.7 版本」和「别名：…」——
  //  用户第 ④ 轮把这些整块划掉了。
  //
  //  ## 默认全选（L526-531）
  //
  //  .. code:: text
  //
  //    ★ 第一次打开（盘上什么都没存）时**默认全选**。
  //      ⚠ 只有"从来没存过"才默认全选；用户取消过就尊重他的选择。
  // ════════════════════════════════════════════════════════════════════════

  //: 旧界面 ``CARD_COLUMNS = 3``
  const SWEEP_COLUMNS = 3;
  //: 旧界面 ``CARD_MIN_WIDTH = 260``
  const SWEEP_CARD_MIN_WIDTH = 260;
  //: 旧界面 ``POLL_MS``（工具页轮询间隔）
  const SWEEP_POLL_MS = 1500;

  const SWEEP_STATE = {
    handle: null,
    targets: [],
    selected: null,          //: Set
    stateLabel: null,
    //: ★ 2026-11-03：「正在启动…」有效期（轮询不许清掉）——
    //: 引擎首次冷启动 ~20 秒，期间后端 state 还是 idle。见 COMBAT_STATE 的说明。
    pendingUntil: 0,
    progressLabel: null,
    selectionLabel: null,
    gridHost: null,
    runBtn: null,
    stopBtn: null,
    tracker: null,
    pollTimer: null,
    saveTimer: null
  };

  registerPanel('nest_sweep', function renderNestSweep(container, app, meta) {
    container.appendChild(buildSweepRunCard());
    container.appendChild(buildSweepTargetsCard());
    sweepLoad();
    void app; void meta;
  });

  // ── ① 运行卡（旧界面 L545-596）──────────────────────────────────────────
  function buildSweepRunCard() {
    const built = cfgCard(
      '扫荡残像聚落',
      //: ★ 2026-11-02 用户要求「这些说明都要删掉」
      ''
    );

    //: 勾选行：[全选][全不选][反选]  …  已选 10 个
    const pickRow = P.el('div', { class: 'cfg-inline-row' });
    pickRow.appendChild(P.button('全选', {
      size: 'sm',
      onClick: function () { sweepSelectMode('all'); }
    }));
    pickRow.appendChild(P.button('全不选', {
      size: 'sm',
      onClick: function () { sweepSelectMode('none'); }
    }));
    pickRow.appendChild(P.button('反选', {
      size: 'sm',
      onClick: function () { sweepSelectMode('invert'); }
    }));
    pickRow.appendChild(P.el('span', { style: 'width:10px;flex:0 0 auto' }));
    SWEEP_STATE.selectionLabel = P.el('span', {
      class: 'cfg-muted',
      text: '未勾选任何目标'
    });
    pickRow.appendChild(SWEEP_STATE.selectionLabel);
    built.body.appendChild(pickRow);

    //: 运行行：[运行][停止] 同一行 + 状态文字在右边
    const runRow = P.el('div', { class: 'cfg-inline-row' });
    SWEEP_STATE.runBtn = P.el('button', {
      class: 'cfg-btn cfg-btn-primary cfg-btn-auto',
      type: 'button',
      text: '运行',
      onClick: function () { sweepAction('run'); }
    });
    SWEEP_STATE.stopBtn = P.el('button', {
      class: 'cfg-btn cfg-btn-auto',
      type: 'button',
      text: '停止',
      onClick: function () { sweepAction('stop'); }
    });
    runRow.appendChild(SWEEP_STATE.runBtn);
    runRow.appendChild(SWEEP_STATE.stopBtn);
    SWEEP_STATE.stateLabel = P.el('span', {
      class: 'cfg-muted',
      style: 'margin-left:10px',
      text: '',
      //: ★ 2026-11-03 用户要求删说明文字 —— 常态不显示
      //: （失败/占用仍由 ``Panels.setStateLabel`` 显示出来）
      hidden: true
    });
    runRow.appendChild(SWEEP_STATE.stateLabel);
    built.body.appendChild(runRow);

    //: 进度行（跑起来才有内容）
    SWEEP_STATE.progressLabel = P.el('div', {
      class: 'cfg-muted',
      text: ''
    });
    built.body.appendChild(SWEEP_STATE.progressLabel);

    return built.card;
  }

  // ── ② 「残像聚落」卡片墙（旧界面 L598-618）──────────────────────────────
  function buildSweepTargetsCard() {
    //: 旧界面标题就叫「残像聚落」，**没有说明文字**
    const built = cfgCard('残像聚落', '');
    SWEEP_STATE.gridHost = P.el('div', { class: 'sweep-grid' });
    built.body.appendChild(SWEEP_STATE.gridHost);
    return built.card;
  }

  // ── 数据 ──────────────────────────────────────────────────────────────
  async function sweepLoad() {
    //: 套装图标映射（``getLibraryData().echoSets[].iconUrl``）——
    //: 旧界面 ``load_icon(set.icon)`` 读本地文件；Web 侧只能从资源库接口拿 URL。
    await sweepLoadSetIcons();

    const result = await P.call('getNestSweepData');
    if (!result.ok) {
      SWEEP_STATE.gridHost.appendChild(P.el('div', {
        class: 'cfg-muted', text: '目标清单接口未就绪。'
      }));
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      SWEEP_STATE.gridHost.appendChild(P.el('div', {
        class: 'cfg-muted',
        text: String(data.message || '读取清单失败。')
      }));
      return;
    }

    SWEEP_STATE.targets = Array.isArray(data.targets) ? data.targets : [];
    const saved = Array.isArray(data.selected) ? data.selected : [];

    //: ★ 默认全选（旧界面 L526-531）：只有"从来没存过"才默认全选
    SWEEP_STATE.selected = new Set(saved);

    sweepRenderCards();
    sweepUpdateSelectionLabel();
    sweepPoll();
    SWEEP_STATE.pollTimer = setInterval(sweepPoll, SWEEP_POLL_MS);
  }

  /** 套装名 → 图标 URL（旧界面读本地 png，Web 侧走资源库接口）*/
  async function sweepLoadSetIcons() {
    SWEEP_STATE.setIcons = {};
    const result = await P.call('getLibraryData');
    if (!result.ok || !result.data) return;
    const sets = Array.isArray(result.data.echoSets) ? result.data.echoSets : [];
    for (const item of sets) {
      if (item && item.name && item.iconUrl) {
        SWEEP_STATE.setIcons[String(item.name)] = String(item.iconUrl);
      }
    }
  }

  /**
   * 重建卡片墙。
   *
   * 旧界面 ``_rebuild_cards``（L620-639）：
   *   ``self.targets_grid.addWidget(card, index // 3, index % 3)`` —— 3 列。
   */
  function sweepRenderCards() {
    const host = SWEEP_STATE.gridHost;
    if (!host) return;
    P.fill(host, null);

    if (!SWEEP_STATE.targets.length) {
      host.appendChild(P.el('div', {
        class: 'cfg-muted', text: '清单里还没有可选目标。'
      }));
      return;
    }

    for (const target of SWEEP_STATE.targets) {
      host.appendChild(sweepCard(target));
    }
  }

  /** 一张目标卡（旧界面 ``TargetCard`` L258-345）*/
  function sweepCard(target) {
    const key = String(target.key || '');
    const checked = SWEEP_STATE.selected.has(key);

    const card = P.el('div', { class: 'sweep-card' });

    // ── 套装区（图标 + 名称，按**实际行数**）──
    const sets = Array.isArray(target.sets) ? target.sets : [];
    if (sets.length) {
      const block = P.el('div', { class: 'sweep-sets-block' });
      const rows = Math.ceil(sets.length / 2);   //: 每行 2 个（旧界面 ``_sets_rows``）
      for (let r = 0; r < rows; r += 1) {
        const row = P.el('div', { class: 'sweep-sets-row' });
        for (let c = 0; c < 2; c += 1) {
          const idx = r * 2 + c;
          if (idx >= sets.length) break;
          row.appendChild(sweepSetChip(sets[idx]));
        }
        block.appendChild(row);
      }
      card.appendChild(block);
    }

    // ── 聚落名（居中一行）──
    card.appendChild(P.el('div', {
      class: 'sweep-name',
      text: String(target.name || key)
    }));

    // ── 勾选框（名字**下面**、单独居中）──
    const checkRow = P.el('label', { class: 'sweep-check-row' });
    const cb = P.el('input', { type: 'checkbox' });
    cb.checked = checked;
    cb.addEventListener('change', function () {
      if (cb.checked) SWEEP_STATE.selected.add(key);
      else SWEEP_STATE.selected.delete(key);
      card.classList.toggle('is-checked', cb.checked);
      sweepUpdateSelectionLabel();
      sweepScheduleSave();
    });
    checkRow.appendChild(cb);
    card.appendChild(checkRow);

    card.classList.toggle('is-checked', checked);
    return card;
  }

  /** 一个套装小片（图标 + 名称）*/
  function sweepSetChip(name) {
    const chip = P.el('div', { class: 'sweep-set-chip' });
    const icon = P.el('div', { class: 'sweep-set-icon' });
    //: 图标来自资源库（``getLibraryData().echoSets[].iconUrl``）
    const url = SWEEP_STATE.setIcons && SWEEP_STATE.setIcons[String(name)];
    if (url) {
      const img = P.el('img', { src: url, alt: '', loading: 'lazy' });
      img.addEventListener('error', function () {
        P.fill(icon, null);
        icon.textContent = String(name).slice(0, 1);
      }, { once: true });
      icon.appendChild(img);
    } else {
      icon.textContent = String(name).slice(0, 1);
    }
    chip.appendChild(icon);
    chip.appendChild(P.el('span', {
      class: 'sweep-set-name',
      text: String(name),
      title: String(name)
    }));
    return chip;
  }

  /** 更新「已选 N 个」（旧界面 ``_refresh_selection_label``）*/
  function sweepUpdateSelectionLabel() {
    const el = SWEEP_STATE.selectionLabel;
    if (!el) return;
    const n = SWEEP_STATE.selected.size;
    el.textContent = n ? '已选 ' + n + ' 个' : '未勾选任何目标';
  }

  /** 全选 / 全不选 / 反选 */
  function sweepSelectMode(mode) {
    const all = SWEEP_STATE.targets.map(function (t) {
      return String(t.key || '');
    }).filter(Boolean);

    if (mode === 'all') {
      SWEEP_STATE.selected = new Set(all);
    } else if (mode === 'none') {
      SWEEP_STATE.selected = new Set();
    } else {
      const next = new Set();
      for (const k of all) {
        if (!SWEEP_STATE.selected.has(k)) next.add(k);
      }
      SWEEP_STATE.selected = next;
    }
    sweepRenderCards();
    sweepUpdateSelectionLabel();
    sweepScheduleSave();
  }

  /** 保存勾选（防抖 400ms —— 用户连点十几张卡不必要每次都发请求）*/
  function sweepScheduleSave() {
    if (SWEEP_STATE.saveTimer) clearTimeout(SWEEP_STATE.saveTimer);
    SWEEP_STATE.saveTimer = setTimeout(function () {
      SWEEP_STATE.saveTimer = null;
      sweepSaveSelection();
    }, 400);
  }

  async function sweepSaveSelection() {
    const payload = JSON.stringify({
      selected: Array.from(SWEEP_STATE.selected)
    });
    const result = await P.callMulti('setNestSweepSelection', [payload]);
    //: ★ 勾选保存失败必须说出来 —— 用户以为勾住了，重开工具就没了（数据丢失）。
    if (!result.ok) {
      if (SWEEP_STATE.stateLabel) {
        SWEEP_STATE.stateLabel.textContent =
          '引擎：勾选**没能保存**（接口未就绪）—— 重开页面会丢';
      }
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      if (SWEEP_STATE.stateLabel) {
        SWEEP_STATE.stateLabel.textContent =
          '引擎：勾选**没能保存** —— ' +
          String(data.message || data.reason || '后端拒绝');
      }
      return;
    }
    //: 后端会 clean_selection（丢失效 key）—— 以返回的为准
    if (Array.isArray(data.selected)) {
      const before = SWEEP_STATE.selected.size;
      SWEEP_STATE.selected = new Set(data.selected);
      if (before !== SWEEP_STATE.selected.size) sweepRenderCards();
      sweepUpdateSelectionLabel();
    }
  }

  // ── 运行 / 停止 ──────────────────────────────────────────────────────
  async function sweepAction(action) {
    if (action === 'run') {
      if (!SWEEP_STATE.selected.size) {
        if (SWEEP_STATE.stateLabel) {
          SWEEP_STATE.stateLabel.textContent =
            '引擎：一个目标都没勾选 —— 先勾上要刷的聚落';
        }
        return;
      }
      //: ★★★ 2026-11-03 **先给反馈，再做任何 await**
      //:
      //: 踩到过：反馈原来写在 ``await sweepSaveSelection()`` **之后** ——
      //: 而 QWebChannel 调用是异步排队的，前一个面板（比如 4C）还在
      //: 等 ``runOkwwTask`` 时，这里会卡住不返回 → 用户点完按钮
      //: **几秒钟毫无反应**，测试也读不到任何变化（实测 full-suite
      //: 里 nest_sweep.P5 一直失败）。
      //:
      //: 现在先写「正在启动…」再存盘，点下去立刻有反应。
      markPendingStart(SWEEP_STATE);
      Panels.setStateLabel(SWEEP_STATE.stateLabel, '引擎：正在启动…');

      //: 先把勾选存盘（ok-ww 的 MyToolsNestSweepTask 读的是 tool_settings）
      if (SWEEP_STATE.saveTimer) {
        clearTimeout(SWEEP_STATE.saveTimer);
        SWEEP_STATE.saveTimer = null;
      }
      await sweepSaveSelection();

      SWEEP_STATE.tracker = Panels.trackRun({
        timeoutMs: 20000,
        onFinish: function () {},
        onGiveUp: function () {}
      });
      SWEEP_STATE.tracker.reset();

      const result = await P.call('runOkwwTask', JSON.stringify({
        taskKey: 'nest_sweep'
      }));
      if (!result.ok) {
        clearPendingStart(SWEEP_STATE);
        Panels.setStateLabel(SWEEP_STATE.stateLabel,
          '引擎：启动请求失败（接口未就绪）');
        return;
      }
      const data = result.data || {};
      if (data.ok === false) {
        clearPendingStart(SWEEP_STATE);
        Panels.setStateLabel(SWEEP_STATE.stateLabel,
          '引擎：' + String(data.message || data.reason || '启动失败'));
        return;
      }
      //: ★ 受理成功也保留 pending 标记（引擎冷启动期间后端还报 idle，
      //: 立刻清掉会让轮询擦掉「正在启动…」）。见 CHANGE_STATE 处的说明。
      if (SWEEP_STATE.tracker) SWEEP_STATE.tracker.accept();
      return;
    }

    // ── 停止 ──
    clearPendingStart(SWEEP_STATE);
    Panels.setStateLabel(SWEEP_STATE.stateLabel, '引擎：正在停止…');
    const r = await P.call('stopOkwwTask');
    if (!r.ok) {
      Panels.setStateLabel(SWEEP_STATE.stateLabel,
        '引擎：停止失败（接口未就绪）');
      return;
    }
    const d = r.data || {};
    if (d.ok === false) {
      Panels.setStateLabel(SWEEP_STATE.stateLabel,
        '引擎：' + String(d.message || d.reason || '没有正在运行的任务'));
    }
  }

  async function sweepPoll() {
    const result = await P.call('getOkwwState');
    if (!result.ok || !result.data) return;
    const data = result.data;
    const state = String(data.state || 'idle');
    const running = String(data.runningTask || '');
    const pending = String(data.pendingStart || '');

    const tasks = Array.isArray(data.tasks) ? data.tasks : [];
    let myTask = '';
    for (const item of tasks) {
      if (item && item.key === 'nest_sweep') {
        myTask = String(item.taskKey || item.name || '');
        break;
      }
    }

    const label = SWEEP_STATE.stateLabel;
    if (label) {
      //: ★ 2026-11-03 用户要求删说明文字 —— 常态（就绪）不显示；
      //: **启动中 / 失败 / 占用 / 运行中**这些反馈仍然显示
      //: （引擎首次冷启动 ~20 秒，不给反馈用户会以为按钮坏了）。
      if (state === 'error') {
        Panels.setStateLabel(label, '引擎：启动失败 —— ' +
          String(data.bootError || '详见日志'));
      } else if (running && myTask && running !== myTask) {
        Panels.setStateLabel(label, '引擎：被占用（正在跑 ' + running + '）');
      } else if (running) {
        Panels.setStateLabel(label,
          '引擎：运行中 —— ' + running + ' · 点「停止」结束');
      } else if (pending || state === 'booting') {
        Panels.setStateLabel(label, '引擎：正在启动…');
      } else if (!settlePendingStart(SWEEP_STATE, running, pending, state)) {
        //: 引擎冷启动 ~20 秒，期间后端可能还报 idle —— 别清掉反馈
        Panels.setStateLabel(label, '引擎：正在启动…');
      } else {
        Panels.setStateLabel(label, '');
      }
    }

    const isMine = running && myTask && running === myTask;
    if (SWEEP_STATE.runBtn) {
      SWEEP_STATE.runBtn.disabled = !!(running || pending);
    }
    if (SWEEP_STATE.stopBtn) {
      SWEEP_STATE.stopBtn.disabled = !(running || pending);
    }
    if (SWEEP_STATE.tracker) {
      SWEEP_STATE.tracker.observe({ running: !!isMine, engineState: state });
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  ⑥ 查询角色练度  character_build   （只读缓存，不登录）
  // ════════════════════════════════════════════════════════════════════════

  const BUILD_STATE = {
    handle: null,
    data: null,
    filter: '',
    choice: '全部',
    selectedId: '',
    rolesHost: null,
    detailHost: null,
    summaryEl: null,
    //: ★ P6：① 登录卡（照抄旧界面外观）
    loginStatus: null,
    loginFields: null,
    //: ★ 2026-11-05：登录按钮 / 刷新按钮 / 是否已登录
    //: —— 「已登录」决定三个输入框和登录按钮是否置灰，
    //:    见 ``buildApplyEditable()``
    loginBtn: null,
    refreshBtn: null,
    //: ★ 2026-11-05：验证码行右边的「获取验证码」按钮 + 倒计时句柄
    codeBtn: null,
    codeLeft: 0,
    codeTimer: 0,
    //: ★ 2026-11-05：「重新登录」按钮（原来那颗「刷新数据」删了）
    reloginBtn: null,
    //: 「重新登录」进行中：三个框解锁 + 只等验证码。
    //: 已登录时正常是锁住的，但用户要换一个新的验证码 → 临时解锁。
    relogin: false,
    //: ★ 2026-11-05：「退出登录」按钮 —— 未登录时**整个隐藏**
    //: （用户圈图：「都没登录还能点退出登录」）
    logoutBtn: null,
    loggedIn: false,
    //: 登录 / 拉数据是否正在进行（防止连点，也用于页面切回来时恢复状态）
    busy: false
  };

  //: 旧界面 ``FILTER_CHOICES``（tool.py L96），逐字照抄
  const BUILD_FILTERS = ['全部', '未达标', '达标', '未练'];

  //: 旧界面 ``MAX_LEVEL`` = 90（``is_below_max_level`` 用它）
  const MAX_LEVEL = 90;

  /**
   * ⑥ 查询角色练度（**照抄旧界面 ``CharacterBuildPanel``**）
   *
   * ## ⚠ P5 重写：用户「图片6 跟原来完全不一样了，请恢复原来的样子」
   *
   * P4 做成了「左列表 | 右详情」两栏 —— **那是我自己设计的。**
   *
   * 旧界面 ``src/tools/game/character_build/tool.py`` L668-686 ``_build()``：
   *
   * .. code:: text
   *
   *   查询角色练度                       ← TitleLabel
   *   登录库街区后拉取…                   ← BodyLabel
   *   ① 登录库街区                       ← _build_login_card
   *   ② 账号概览                         ← _build_overview_card
   *   ③ 共鸣者                          ← _build_roles_card
   *   ④ 共鸣者详情                       ← _build_detail_card
   *   日志 [展开]                        ← _build_log_card
   *
   * **5 张卡垂直堆叠**，不是左右分栏。
   *
   * ## ① 登录卡 → Web 版换成「缓存说明卡」
   *
   * 登录要「手机号 + 短信验证码」，Web 端做不了（用户也定的是只读缓存）。
   * 所以这张卡改成说明「数据是几号的缓存、要更新怎么办」——
   * **保留卡位和编号**，用户看到的页面结构不变。
   *
   * ## ③ 共鸣者列表：**单行横向滚动**（关键细节）
   *
   * 旧界面 L792-815 的注释：
   *
   *     用户："一个就展示所有共鸣者，展示不全，可以滑动"
   *
   *     ⚠ 之前用 QGridLayout 换行 → 43 个角色铺了 6 行，
   *       把下面的详情区挤到屏幕外。现在改成
   *       QScrollArea(横向) + QHBoxLayout —— **永远只占一行**。
   *
   * 所以这里必须 ``flex-wrap: nowrap`` + ``overflow-x: auto``，
   * **不能**用网格换行。
   *
   * ## ④ 共鸣者详情：只做数据摘要
   *
   * 旧界面用 ``EchoDetailView``（``detail_view.py`` 1400 行）画官方风格的
   * 图文详情（属性雷达 / 武器立绘 / 声骸套装图 / 共鸣链图标）。
   * **那个不照抄** —— 等于重写一个新项目，而且旧界面还在。
   * 这里显示基础数值 + 一句「完整图文详情请用旧界面查看」。
   */
  registerPanel('character_build', function renderCharacterBuild(container, app, meta) {
    // ══════════════════════════════════════════════════════════════════════
    //  ★★★ 2026-11-03 **不再用 ``Panels.create()`` 骨架**
    //  （用户：「查询角色练度与原来页面区别太大，按照原来的样子改一下」）
    //
    //  ## 基准是**真跑旧界面截的图**（不是读代码猜的）
    //
    //  ``_oldbuild.py`` 直接实例化 ``CharacterBuildPanel`` 抓的控件树：
    //
    //  .. code:: text
    //
    //    TitleLabel   '查询角色练度'                      ← 页头标题（有！）
    //    BodyLabel    '登录库街区后拉取你账号里的角色与…'   ← 页头描述（有！）
    //    CardWidget   ① 登录库街区 / ② 账号概览 / ③ 共鸣者
    //                 ④ 共鸣者详情 / 日志                  ← 5 张卡
    //
    //  ## 之前错在哪
    //
    //  只有这一个面板用了 ``Panels.create()`` —— 它额外画出两块旧界面
    //  **根本没有**的东西：
    //
    //  .. code:: text
    //
    //    ..run-panel..  状态胶囊 + 进度条 + 步骤文字   ← 旧界面没有
    //    ..log-box ..   "日志 0 行 / 清空"             ← 旧界面只有一块日志
    //                     （而且这块是第二块，和⑤重复）
    //
    //  ## 现在的结构（和旧界面逐项对齐）
    //
    //  .. code:: text
    //
    //    .page-head   「查询角色练度」+ 描述            ← 保留（旧界面有）
    //    ① 登录库街区  ② 账号概览  ③ 共鸣者  ④ 详情  ⑤ 日志
    //
    //  ⚠ **没有**页面级「刷新」按钮 —— 旧界面的「刷新数据」在**①号卡片里**
    //    （``_build_login_card`` 的 btn_row），Web 版一直也在那儿，没丢。
    //
    //  ⚠ 下面的 ``panel`` 是个**极小的 shim**，只为了不改动 ``buildLoad()``
    //    里那些 ``panel.setState(...)`` / ``panel.setProgress(...)`` 调用 ——
    //    那些调用负责「读取中 / 读取失败 / 已加载 N 个角色」的反馈，
    //    是有用的（不能删）。
    //
    //    shim 把状态写到 **日志卡**里（旧界面 ``_say()`` 也是写日志），
    //    不再画那个旧界面没有的状态胶囊。``setProgress`` 是**空实现** ——
    //    这个页面是只读缓存读取，没有进度可言，旧界面也没有进度条。
    // ══════════════════════════════════════════════════════════════════════
    //: 页头（旧界面 ``_build`` L676-679：TitleLabel + BodyLabel）
    const buildHead = P.pageHead({
      title: (meta && meta.name) || '查询角色练度',
      subtitle: (meta && meta.desc)
        || '登录库街区后拉取你账号里的角色与声骸数据，'
        + '用来比对哪些角色的声骸属性需要重刷。'
    });
    container.appendChild(buildHead.head);

    const panel = {
      setState: function (state, text) {
        //: ★★★ 2026-11-03 日志卡删掉之后，**反馈必须换出口**
        //:
        //: 原来反馈只写 ``buildLog()``（写进⑤日志卡）。日志卡按用户要求
        //: 删了，``BUILD_STATE.logHost`` 恒为 null → ``buildLog`` 直接
        //: return → **所有失败提示静默消失**。
        //:
        //: 这正是交接文档点名的「静默失败」形态 ②：提示容器失效，
        //: ``if (!host) return`` 把话吞掉。
        //:
        //: 所以这里加一个**可见出口**：② 账号概览卡片顶部那行提示位
        //: （``BUILD_STATE.noticeEl``）。失败/警告都写到那儿，
        //: 常态（idle / preparing）不显示 —— 只有真有事才出现。
        if (!text) return;
        buildLog(String(text), state === 'blocked' ? 'warn' : 'info');
        if (state === 'blocked' || state === 'error') {
          setBuildNotice(String(text), state === 'error' ? 'error' : 'warn');
        }
      },
      setProgress: function () { /* 只读页面，没有进度条（旧界面也没有）*/ }
    };
    BUILD_STATE.handle = panel;


    // ══════════════════════════════════════════════════════════════════════
    //  ① 登录卡 —— **照抄旧界面外观**（``_build_login_card`` L690-748）
    //
    //  ## ⚠ P6 修正：用户要「布局一致」，不是「功能一致」
    //
    //  P5 我把这整块换成了「只读缓存」说明卡 —— 功能上诚实，但**长得不一样**。
    //u  Lead 决定（2026-11-02）：**照抄外观 + 置灰 + 提示**。
    //
    //  旧界面 L695-743 的结构：
    //
    //  .. code:: text
    //
    //    [① 登录库街区]  已登录（手机号 ****641)      [退出登录]
    //    特征码  [137856011       ]     ← 标签固定 48px、输入框 200px
    //    手机号  [19128896241     ]
    //    验证码  [短信验证码       ]
    //    [登录] [刷新数据]
    //    验证码在任意官方入口获取（库街区 App / 网页登录框）—— 两边通用。
    //    **登录后会自动拉取数据**；之后想重拉点「刷新数据」。
    //
    //  Web 版：三个输入框 **readonly + 置灰**（显示缓存里的值），
    //  「登录」「退出登录」**禁用**，「刷新数据」可用（= 重读缓存）。
    //
    //  ★★★ 2026-11-05 **上面那条改掉了**（Web 版现在真能登录）
    //
    //  用户圈图：「退出登录后，特征码、手机号、验证码怎么不能输入？」
    //
    //  P5 时 Web 版只做「读旧界面留下的缓存」，所以把控件写死禁用 ——
    //  但底层 ``core/kuro_account.app_login_with_code`` 一直是通的，
    //  旧界面也一直能登录，Web 版没理由拦着。现在的规则：
    //
    //    * **未登录** → 三个输入框可编辑、登录按钮可点
    //    * **已登录** → 三个输入框置灰、登录按钮置灰
    //      （登录后账号由令牌决定，改输入框不会生效 —— 旧界面
    //       ``_apply_inputs_editable`` 就是这么做的）
    //    * **退出登录成功后** → 恢复可编辑（原来这里漏了，就是本次 bug）
    // ══════════════════════════════════════════════════════════════════════
    const loginCard = P.el('div', { class: 'build-card card-glass' });

    const loginHead = P.el('div', { class: 'build-card-head' });
    loginHead.appendChild(P.el('div', {
      class: 'build-card-title', text: '① 登录库街区'
    }));
    //: 登录状态（旧界面 ``_login_status``）：已登录（手机号 ****641）
    BUILD_STATE.loginStatus = P.el('div', {
      class: 'build-login-status',
      id: 'build-login-status',
      text: '未登录'
    });
    loginHead.appendChild(BUILD_STATE.loginStatus);
    loginHead.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    //: 「退出登录」在**标题行最右**（旧界面 head.addWidget)
    //
    //: ★★★ 2026-11-03 用户：「退出登录怎么不能点？」
    //:
    //: 之前这里 ``disabled: true``，理由是"会破坏旧界面保存的登录态"——
    //: 那是**保守猜测，不是事实约束**。登出是用户的合法操作，
    //: 旧界面一直可点，Web 版没理由拦着。
    //:
    //: ## 二次确认
    //:
    //: 登出会**删掉令牌 + 练度缓存**（不可逆），所以点第一下变成
    //: 「确认退出？」，再点才真做 —— 和项目里其他危险按钮一致。
    const logoutBtn = P.button('退出登录', {
      size: 'sm',
      onClick: function () { buildLogout(logoutBtn); }
    });
    logoutBtn.dataset.action = 'logout';
    //: ★ 2026-11-05：记下来，交给 ``buildApplyEditable()`` 控制显隐
    //: （未登录时应该**整个不出现** —— 用户圈图「都没登录还能点退出登录」）。
    BUILD_STATE.logoutBtn = logoutBtn;
    loginHead.appendChild(logoutBtn);
    loginCard.appendChild(loginHead);

    //: 三个字段（旧界面 ``field()``：标签 48px + 输入框 200px）
    BUILD_STATE.loginFields = {};
    const FIELDS = [
      ['feature', '特征码', '留空 = 自动用绑定账号'],
      ['mobile', '手机号', '手机号'],
      ['code', '验证码', '短信验证码']
    ];
    for (const item of FIELDS) {
      const row = P.el('div', { class: 'build-login-row' });
      row.appendChild(P.el('span', {
        class: 'build-login-tag', text: item[1]
      }));
      const input = P.el('input', {
        class: 'input build-login-input',
        type: 'text',
        placeholder: item[2],
        autocomplete: 'off'
      });
      //: ★ 2026-11-05：**默认可编辑**（原来是 ``disabled = true``，
      //: 退出登录后也不恢复 —— 用户圈图就是这个）。已登录时才置灰，
      //: 见 ``buildApplyEditable()``。
      //:
      //: 验证码额外加 ``inputmode=numeric`` + 长度提示：手机号/验证码
      //: 都是纯数字，手机上该弹数字键盘。
      if (item[0] === 'mobile' || item[0] === 'code') {
        input.setAttribute('inputmode', 'numeric');
      }
      //: 手机号框**只留后四位可见**（``****6241``）—— 那是脱敏后的显示值，
      //: 真去编辑时先清成空，否则用户会在 ``****6241`` 后面接着打。
      if (item[0] === 'mobile') {
        input.addEventListener('focus', function () {
          if (input.value.indexOf('****') === 0) input.value = '';
        });
      }
      row.appendChild(input);

      //: ★★★ 2026-11-05 用户圈图：
      //:
      //:   > 验证码变成可输入，**右边**还有 60 倒计时输入提示
      //:
      //: 验证码框**右边**挂一颗「获取验证码」。点它：
      //:
      //:   1. **不真的发短信** —— 服务端要求先过极验（``NeedHumanVerify``），
      //:      纯 Python 做不到，实测点了只会拿到「人机验证」而不是短信。
      //:      所以按钮的作用是**开始 60 秒倒计时 + 把验证码框准备好**，
      //:      并提示用户去官方入口取（码在 APP / 网页通用）。
      //:   2. 倒计时期间按钮禁用并在文字里显示剩余秒数（``重发 58s``），
      //:      这是用户要的「倒计时输入提示」。
      //:
      //: ⚠ 顺序：**必须 append 在 input 之后**才是"右边"。
      //: 第一版写在了 ``row.appendChild(input)`` 前面，结果按钮跑到
      //: 标签和输入框中间（看着像"获取验证码"是第二个标签），已改。
      if (item[0] === 'code') {
        const codeBtn = P.button('获取验证码', {
          size: 'sm',
          title: '去库街区 App / 网页登录框点「获取验证码」，然后填到这里' +
            '（验证码两边通用；本机发不出去 —— 服务端要求人机验证）',
          onClick: function () { buildSendCode(codeBtn); }
        });
        codeBtn.dataset.action = 'send-code';
        codeBtn.classList.add('build-code-btn');
        BUILD_STATE.codeBtn = codeBtn;
        row.appendChild(codeBtn);
      }
      loginCard.appendChild(row);
      BUILD_STATE.loginFields[item[0]] = input;
    }

    //: 按钮行（旧界面 btn_row L732-743）
    const loginBtnRow = P.el('div', { class: 'build-login-btns' });
    //: ★ 2026-11-05：登录按钮**启用**并接上 ``kuroLogin``。
    //:
    //: 原来这里是 ``disabled: true`` 且**没有 onClick** —— 连同三个输入框
    //: 一起是 P5「只读缓存」时期的遗留。用户圈图问的正是这个。
    const loginBtn = P.button('登录', {
      size: 'sm',
      title: '手机号 + 短信验证码（验证码在库街区 App / 网页登录框获取）',
      onClick: function () { buildLogin(loginBtn); }
    });
    loginBtn.dataset.action = 'login';
    BUILD_STATE.loginBtn = loginBtn;
    loginBtnRow.appendChild(loginBtn);

    //: ★★★ 2026-11-05 用户第二条圈图：
    //:
    //:   > 刷新数据改成重新登录，重新登陆不会清除特征码和手机号信息
    //:   > （退出登陆会清除），验证码变成可输入，右边还有60倒计时输入提示
    //:
    //: 所以这里换成「重新登录」。它的语义**不是**「再拉一次数据」
    //: （那是 ``kuroFetchData``），而是：
    //:
    //:   1. 已登录状态下点它 → 三个框解锁（特征码/手机号**保持原值**）
    //:   2. 验证码框清空并聚焦，右边出现「60s」倒计时
    //:   3. 倒计时期间点「获取验证码」不重复发（服务端要求人机验证，
    //:      我们发不出去 —— 见下面 :func:`buildRelogin` 的说明）
    //:
    //: 保留旧的「刷新数据」能力但**不再挂在按钮上**：登录成功后会自动
    //: 拉一次数据，中途要重拉走 ``BUILD_STATE.relogin`` 里的「拉取」
    //: 分支（见 ``buildRelogin`` 的实现说明）。
    const reloginBtn = P.button('重新登录', {
      size: 'sm',
      title: '用同一个手机号重新登录（特征码 / 手机号会保留，只需重填验证码）',
      onClick: function () { buildRelogin(reloginBtn); }
    });
    reloginBtn.dataset.action = 'relogin';
    BUILD_STATE.reloginBtn = reloginBtn;
    loginBtnRow.appendChild(reloginBtn);

    //: ★★★ 2026-11-05：原来的「刷新数据」按钮**删掉**了 ——
    //: 用户要求「刷新数据改成重新登录」。
    //:
    //: 那个按钮原来调 ``kuroFetchData``（真的重拉数据）。现在数据拉取
    //: 挂在两处，不需要单独按钮了：
    //:
    //:   * 登录成功后**自动**拉一次（后端 ``kuroLogin.on_ok``）
    //:   * 「重新登录」走完后也会拉（同一段逻辑）
    //:
    //: ``BUILD_STATE.refreshBtn`` 保留为 ``null`` —— 事件回调里
    //: 还有几处 ``if (BUILD_STATE.refreshBtn)`` 的判空保护，
    //: 不删那些代码（删了要改三处，且判空本来就是对的）。
    BUILD_STATE.refreshBtn = null;
    loginCard.appendChild(loginBtnRow);

    //: ★★★ 2026-11-03 用户圈图：「干掉」——删掉两块说明文字：
    //:
    //:   ① 「验证码在任意官方入口获取（库街区 App / 网页登录框）——
    //:       两边通用。**登录后会自动拉取数据**；之后想重拉点「刷新数据」。」
    //:   ② 「Web 版不支持登录，字段来自上次在旧界面保存的缓存。
    //:       要更新请用旧界面：MYTOOLS_WEB_SHELL=0 python main.py」
    //:
    //: ## 为什么可以删
    //:
    //: * 第 ① 条是**旧界面的说明**（那里真能登录，需要教用户去哪拿验证码）。
    //:   Web 版登录按钮是**禁用的**，这段说明对用户毫无用处。
    //: * 第 ② 条是**开发者信息**（告诉你自己用旧界面刷新）。
    //:   用户已经知道 Web 版不支持登录（看「已登录」状态和禁用的按钮就明白）。
    //:
    //: ⚠ 保留了**功能性的状态显示**：「已登录（手机号 ****6241）」
    //:   和「最后更新：…」仍在——那些是数据状态，不是说明。
    //:   ``setBuildCacheNote()`` 函数**保留**（它还负责在出错时写提示位），
    //:   只是不再有常驻的说明 div 可写。
    container.appendChild(loginCard);

    // ══════════════════════════════════════════════════════════════════════
    //  ② 账号概览 —— **照抄旧界面 ``_format_base``**（L1300-1315）
    //
    //  .. code:: python
    //
    //    parts = [
    //        f"结晶波片 {base.get('energy','?')}/{base.get('maxEnergy','?')}",
    //        f"结晶单质 {base.get('storeEnergy','?')}/{base.get('storeEnergyLimit','?')}",
    //        f"活跃度 {base.get('liveness','?')}/{base.get('livenessMaxCount','?')}",
    //        f"游戏天数 {base.get('activeDays','?')}",
    //        f"联觉等级 {base.get('level','?')}",
    //        f"解锁角色 {base.get('roleNum','?')}",
    //    ]
    //    return "　|　".join(parts)
    //
    //  ⚠ 分隔符是**全角空格 + 竖线 + 全角空格**（``　|　``），不是普通 `` | ``。
    // ══════════════════════════════════════════════════════════════════════
    const overviewCard = P.el('div', { class: 'build-card card-glass' });
    overviewCard.appendChild(P.el('div', { class: 'build-card-head' }, [
      P.el('div', { class: 'build-card-title', text: '② 账号概览' })
    ]));
    BUILD_STATE.summaryEl = P.el('div', {
      class: 'build-overview',
      id: 'build-summary'
    }, [
      P.el('div', { class: 'build-overview-empty', text: '尚未拉取数据' })
    ]);
    overviewCard.appendChild(BUILD_STATE.summaryEl);

    //: ★ 2026-11-03 反馈提示位（日志卡删掉后的新出口 —— 见 ``panel.setState``）
    BUILD_STATE.noticeEl = P.el('div', { class: 'build-notice' });
    BUILD_STATE.noticeEl.hidden = true;
    BUILD_STATE.noticeEl.classList.add('hidden');
    overviewCard.appendChild(BUILD_STATE.noticeEl);

    container.appendChild(overviewCard);

    // ══════════════════════════════════════════════════════════════════════
    //  ③ 共鸣者（★ 单行横向滚动）
    // ══════════════════════════════════════════════════════════════════════
    const rolesCard = P.el('div', { class: 'build-card card-glass' });

    const rolesHead = P.el('div', { class: 'build-card-head' }, [
      P.el('div', { class: 'build-card-title', text: '③ 共鸣者' }),
      (function () {
        const hint = P.el('div', { class: 'build-card-badge', id: 'build-roles-hint' });
        return hint;
      })(),
      P.el('div', { class: 'build-card-actions' }, [
        //: ★★★ 2026-11-03 用户圈图：
        //:   「只搜索角色，也是下拉列表，也可输入搜索
        //:     检查其它地方的角色搜索是不是有图片吗，还有角色搜索都是这种
        //:     下拉列表+输入关键词模糊搜索」
        //:
        //: ## 旧界面本来就要的是这个
        //:
        //: ``tool.py`` L774 的注释写着用户原话：
        //:   「加个下拉列表搜索」
        //: 但实现成了一个**纯输入框**（``LineEdit``）—— 没有候选可点。
        //:
        //: ## 现在
        //:
        //: 做成「输入框 + 下拉候选」：
        //:   * 点输入框 → 展开候选（带**角色头像**，用户要"有图片"）
        //:   * 打字即过滤（模糊：名字 / 拼音首字母 / 属性 / 武器）
        //:   * 点候选 → 直接选中那个角色（= 筛选 + 切详情）
        //:
        //: ⚠ 和「筛选下拉」（全部/达标/未达标）是**两个独立控件** ——
        //:   那个筛状态，这个定位角色。
        (function () {
          const box = P.el('div', { class: 'search build-search build-char-search' });
          //: ★★★ 2026-11-03 用户圈图：「这个是什么？干掉」
          //:
          //: 原来这里有个 ``DOCUMENT``（文件）图标 —— 一张文档轮廓，在
          //: 搜索框里既不代表「搜索」也不代表「角色」，纯装饰还难看。
          //: 配置页同一个毛病一起删了（见 ``config.js`` 的同名注释）。

          const inp = P.el('input', {
            type: 'search',
            //: ★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
            //:   —— 和配置页同一个 placeholder（明说支持拼音，不然没人会试）
            placeholder: '搜索角色名（支持拼音，如 feixue / fx）',
            autocomplete: 'off'
          });
          box.appendChild(inp);

          //: ★★★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
          //:
          //: 配置页那里已经补了一个右侧下拉箭头（`.search-caret`，24×24 /
          //: 15px 的 ▼）。练度页这个搜索框是**同一个控件形态**，却没有
          //: 任何「这里能展开」的视觉线索 —— 用户只看到一条输入框。
          //: 这里补上，展开时也跟着翻转（`.search.is-open .search-caret`）。
          const caretBtn = P.el('button', {
            class: 'search-caret',
            type: 'button',
            title: '展开/收起候选角色',
            text: '▼',
            onMousedown: function (ev) {
              //: ⚠ 用 mousedown —— click 前 input 会先 blur，面板开了又关
              ev.preventDefault();
              ev.stopPropagation();
              if (panel.hidden) {
                inp.focus();
                open();
              } else {
                close();
              }
            }
          });
          box.appendChild(caretBtn);

          //: 候选面板
          const panel = P.el('div', { class: 'build-char-panel' });
          panel.hidden = true;
          panel.classList.add('hidden');
          box.appendChild(panel);

          /** 候选来源：当前缓存里的全部角色 */
          function pool() {
            const data = BUILD_STATE.data || {};
            const all = Array.isArray(data.characters) ? data.characters : [];
            return all.slice().reverse();
          }

          /**
           * 候选命中判定 —— ★★★ 2026-11-03 用户：「所有设计角色搜索的，
           * 都按照这个做」。
           *
           * 这里**照抄配置页** ``config.js`` 的 ``matchOption()``：
           * 只看**角色名子串** + **纯字母走拼音**（``role.pinyin`` 是后端
           * ``text_match.pinyin_keys`` 算的 ``[全拼, 首字母]``）。
           *
           * ## 之前错在哪
           *
           * .. code:: js
           *
           *     const hay = [role.name, role.attribute, role.weaponType,
           *                  role.level, role.acronym].join(' ');
           *
           * ① 打「冷凝」「长刃」能筛出一堆角色 —— 但用户**看不见**这个
           *    关键词在哪儿，只会觉得"怎么出来这些不相关的"（配置页
           *    同一个毛病，用户已经圈过图）。
           * ② ``role.acronym`` 后端从来不返回（恒 ``undefined``）—— 噪声。
           *
           * 现在唯一依据就是「用户看得见的东西」：名字 + 拼音。
           */
          function match(role, kw) {
            if (!kw) return true;
            if (String(role.name || '').toLowerCase().indexOf(kw) >= 0) return true;
            //: 只有**纯字母**才试拼音（打中文时子串已经够，硬算白费）
            if (!/^[a-z]+$/.test(kw)) return false;
            const keys = Array.isArray(role.pinyin) ? role.pinyin : [];
            const full = String(keys[0] || '').toLowerCase();
            const initial = String(keys[1] || '').toLowerCase();
            return (!!full && full.indexOf(kw) >= 0) ||
                   (!!initial && initial.indexOf(kw) >= 0);
          }

          function render() {
            P.fill(panel, null);
            const kw = inp.value.trim().toLowerCase();
            const all = pool();
            const list = all.filter(function (r) {
              return match(r, kw);
            }).slice(0, 120);
            //: ★ 和配置页一样，顶部钉一行汇总：候选池多大、当前筛出几个
            //:   —— 否则用户不知道「还没打全」和「就这么多」的区别。
            if (all.length) {
              let hint = '共 ' + all.length + ' 个角色';
              if (kw) hint += ' · 匹配 ' + list.length + ' 个';
              panel.appendChild(P.el('div', {
                class: 'build-char-hint', text: hint
              }));
            }
            if (!list.length) {
              panel.appendChild(P.el('div', {
                class: 'build-char-empty', text: '没有匹配的角色'
              }));
              return;
            }
            for (const role of list) {
              const row = P.el('div', {
                class: 'build-char-opt'
                  + (String(role.roleId || '') === BUILD_STATE.selectedId
                     ? ' is-current' : '')
              });
              //: 头像（用户明确要求「有图片」）
              const face = P.el('span', { class: 'build-char-face' });
              const pic = role.iconUrl || role.picUrl || '';
              if (pic) {
                const img = P.el('img', { src: pic, alt: '', loading: 'lazy' });
                img.addEventListener('error', function () {
                  P.fill(face, null);
                  face.textContent = String(role.name || '?').slice(0, 1);
                }, { once: true });
                face.appendChild(img);
              } else {
                face.textContent = String(role.name || '?').slice(0, 1);
              }
              row.appendChild(face);
              //: ★★★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
              //:
              //: 配置页的候选行已经改成**只有头像 + 角色名**（用户圈图
              //: 把类型标签「干掉」了）。这里原来还带着「Lv.90 冷凝」，
              //: 属同一类"看得见但筛不到"的多余信息 —— 一并去掉。
              row.appendChild(P.el('span', {
                class: 'build-char-name', text: String(role.name || '')
              }));
              //: ⚠ 用 mousedown —— click 会先触发 input 的 blur 把面板收掉
              row.addEventListener('mousedown', function (ev) {
                ev.preventDefault();
                selectRole(role);
              });
              panel.appendChild(row);
            }
          }

          function open() {
            render();
            panel.hidden = false;
            panel.classList.remove('hidden');
            box.classList.add('is-open');
          }
          function close() {
            panel.hidden = true;
            panel.classList.add('hidden');
            box.classList.remove('is-open');
          }

          /** 选中一个角色：切详情 + 清掉文字筛选 */
          function selectRole(role) {
            const id = String(role.roleId || '');
            inp.value = String(role.name || '');
            BUILD_STATE.filter = '';
            close();
            if (id) buildSelectRole(id);
            buildRenderRoles();
          }

          inp.addEventListener('focus', open);
          inp.addEventListener('click', function (ev) {
            ev.stopPropagation();
            open();
          });
          inp.addEventListener('input', function () {
            BUILD_STATE.filter = inp.value.trim().toLowerCase();
            buildRenderRoles();
            if (panel.hidden) open(); else render();
          });
          inp.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') { close(); inp.blur(); }
            if (ev.key === 'Enter') {
              const first = panel.querySelector('.build-char-opt');
              if (first) { ev.preventDefault(); first.dispatchEvent(
                new MouseEvent('mousedown', { bubbles: true })); }
            }
          });
          //: 点外部关闭
          document.addEventListener('click', function (ev) {
            if (!box.contains(ev.target)) close();
          });

          return box;
        })(),
        //: 「达标/未达标」筛选（旧界面 ``_filter_box``，宽 120）
        (function () {
          const sel = Panels.select(BUILD_FILTERS, '全部');
          sel.el.classList.add('build-filter');
          sel.el.addEventListener('change', function () {
            BUILD_STATE.choice = sel.get();
            buildRenderRoles();
          });
          return sel.el;
        })()
      ])
    ]);
    rolesCard.appendChild(rolesHead);

    //: ★★★ 2026-11-03 用户（**第三次**）：「滑动的拖动按钮呢？？这个说几次了」
    //:
    //: ## 为什么前两轮都没修好
    //:
    //: 第一轮只加 ``overflow-x: auto`` —— 属性上能滚，界面上**毫无痕迹**。
    //: 第二轮给滚动条加样式 —— 实测仍然看不见，因为
    //: ``.build-roles-scroll`` 的 ``height`` 写死 154、内容只有 142，
    //: 剩下的 12px 里塞 9px 滚动条，被 ``overflow-y: hidden`` **整个裁掉**。
    //:
    //: ## 现在
    //:
    //: 不再只依赖滚动条（太细、用户看不见），**加左右箭头按钮**：
    //:   * 浮在左右两端，鼠标进入时显现
    //:   * 点一下滚一屏（``scrollBy``）
    //:   * 到头了就自动禁用（视觉上消失）
    //:
    //: 滚动条本身也保留了（CSS 里改粗、改亮），两条路都能用。
    const rolesWrap = P.el('div', { class: 'build-roles-wrap' });
    BUILD_STATE.rolesHost = P.el('div', {
      class: 'build-roles-scroll',
      id: 'build-roles'
    });

    /** 造一个箭头按钮 */
    function makeNavBtn(dir) {
      const btn = P.el('button', {
        class: 'build-roles-nav ' + (dir < 0 ? 'is-left' : 'is-right'),
        type: 'button',
        text: dir < 0 ? '‹' : '›',
        title: dir < 0 ? '向前翻' : '向后翻',
        onClick: function () {
          const host = BUILD_STATE.rolesHost;
          if (!host) return;
          //: 一屏 = 可视宽度的 80%（留一点重叠，用户知道自己滚到哪了）
          const step = Math.max(200, Math.round(host.clientWidth * 0.8));
          host.scrollBy({ left: dir * step, behavior: 'smooth' });
        }
      });
      return btn;
    }
    const navLeft = makeNavBtn(-1);
    const navRight = makeNavBtn(1);
    rolesWrap.appendChild(navLeft);
    rolesWrap.appendChild(BUILD_STATE.rolesHost);
    rolesWrap.appendChild(navRight);

    //: ★★★ 2026-11-03 **自己画一条滚动指示条**（用户为"滑动按钮"说了三次）
    //:
    //: ## 为什么原生滚动条怎么改样式都不出现
    //:
    //: ``web_shell.py`` 里给 QWebEngineSetting 设了
    //: ``ShowScrollBars = False`` —— 那是为了让**内容区**不出现系统滚动条
    //: （页面自己用 ``.page { overflow-y: auto }`` 滚）。
    //:
    //: 副作用：这个开关是**全局**的，所以 ``::-webkit-scrollbar`` 系列
    //: 样式根本不绘制 —— 实测 ``clientHeight === offsetHeight``，
    //: 滚动条一点布局空间都没占。
    //:
    //: ## 现在
    //:
    //: 不跟浏览器的滚动条较劲了 —— **用 DOM 画一条**：
    //:   * 轨道在最底部（12px 高）
    //:   * 滑块宽度 = 可视宽 / 内容宽 的比例
    //:   * 位置跟着 ``scrollLeft`` 走
    //:   * 可以**拖动**（用户说的"拖动按钮"就是这个）
    const bar = P.el('div', { class: 'build-roles-bar' });
    const thumb = P.el('div', { class: 'build-roles-thumb' });
    bar.appendChild(thumb);
    rolesWrap.appendChild(bar);

    /** 按当前滚动位置刷新滑块 */
    function syncBar() {
      const host = BUILD_STATE.rolesHost;
      if (!host) return;
      const maxLeft = host.scrollWidth - host.clientWidth;
      if (maxLeft <= 4) {
        bar.style.display = 'none';
        return;
      }
      bar.style.display = '';
      const ratio = host.clientWidth / host.scrollWidth;
      const trackW = bar.clientWidth;
      const thumbW = Math.max(36, Math.round(trackW * ratio));
      const maxThumbLeft = trackW - thumbW;
      const progress = maxLeft > 0 ? (host.scrollLeft / maxLeft) : 0;
      thumb.style.width = thumbW + 'px';
      thumb.style.transform =
        'translateX(' + Math.round(maxThumbLeft * progress) + 'px)';
    }
    BUILD_STATE.syncRolesBar = syncBar;
    BUILD_STATE.rolesHost.addEventListener('scroll', syncBar);
    window.addEventListener('resize', syncBar);
    setTimeout(syncBar, 80);

    //: 拖动滑块 → 滚动内容
    (function () {
      let dragging = false;
      let startX = 0;
      let startLeft = 0;
      thumb.addEventListener('mousedown', function (ev) {
        ev.preventDefault();
        dragging = true;
        startX = ev.clientX;
        startLeft = BUILD_STATE.rolesHost.scrollLeft;
        document.body.style.userSelect = 'none';
      });
      document.addEventListener('mousemove', function (ev) {
        if (!dragging) return;
        const host = BUILD_STATE.rolesHost;
        const trackW = bar.clientWidth;
        const thumbW = thumb.offsetWidth;
        const movable = trackW - thumbW;
        if (movable <= 0) return;
        const maxLeft = host.scrollWidth - host.clientWidth;
        const dx = ev.clientX - startX;
        host.scrollLeft = startLeft + (dx / movable) * maxLeft;
      });
      document.addEventListener('mouseup', function () {
        if (!dragging) return;
        dragging = false;
        document.body.style.userSelect = '';
      });
      //: 点轨道空白处 → 翻页
      bar.addEventListener('mousedown', function (ev) {
        if (ev.target === thumb) return;
        const host = BUILD_STATE.rolesHost;
        const rect = bar.getBoundingClientRect();
        const toRight = ev.clientX > (rect.left + rect.width / 2);
        host.scrollBy({
          left: (toRight ? 1 : -1) * host.clientWidth * 0.8,
          behavior: 'smooth'
        });
      });
    })();

    rolesCard.appendChild(rolesWrap);

    /** 按滚动位置刷新两个箭头的可用状态 */
    function syncNav() {
      const host = BUILD_STATE.rolesHost;
      if (!host) return;
      const maxLeft = host.scrollWidth - host.clientWidth;
      const canScroll = maxLeft > 4;
      navLeft.disabled = !canScroll || host.scrollLeft <= 2;
      navRight.disabled = !canScroll || host.scrollLeft >= maxLeft - 2;
      //: ★ 同步自绘滚动条（它定义在下面，用 typeof 守卫避免时序问题）
      if (typeof BUILD_STATE.syncRolesBar === 'function') {
        BUILD_STATE.syncRolesBar();
      }
    }
    BUILD_STATE.syncRolesNav = syncNav;
    BUILD_STATE.rolesHost.addEventListener('scroll', syncNav);
    //: 窗口尺寸变了也要重算（可视宽变了，能滚的范围就变了）
    window.addEventListener('resize', syncNav);
    //: 初次渲染后算一次（角色卡片是异步填进来的，所以给个延迟）
    setTimeout(syncNav, 60);

    container.appendChild(rolesCard);

    // ══════════════════════════════════════════════════════════════════════
    //  ④ 共鸣者详情
    // ══════════════════════════════════════════════════════════════════════
    const detailCard = P.el('div', { class: 'build-card card-glass' });
    detailCard.appendChild(P.el('div', { class: 'build-card-head' }, [
      P.el('div', { class: 'build-card-title', text: '④ 共鸣者详情' })
    ]));
    BUILD_STATE.detailHost = P.el('div', {
      class: 'build-detail-body',
      id: 'build-detail'
    }, [
      P.el('div', {
        class: 'build-overview-empty',
        text: '在上面点一个共鸣者，这里显示他的练度。'
      })
    ]);
    detailCard.appendChild(BUILD_STATE.detailHost);
    container.appendChild(detailCard);

    // ══════════════════════════════════════════════════════════════════════
    //  ⑤ 日志 —— ★★★ 2026-11-03 **用户圈图：「干掉」**
    //
    //  整张日志卡片删掉了。理由：
    //
    //  * 这个页面是**只读缓存展示**，日志里只有「读取角色练度缓存…」
    //    「✓ 读到 21 个角色，缓存于 …」这两三行 —— 用户看一眼就够，
    //    不值得占一整张卡（而且默认还是折叠的，等于白占位）。
    //  * 旧界面确实有这块，但用户现在明确要求去掉。
    //
    //  ## ⚠ 保留了 ``buildLog()`` 函数
    //
    //  它还被 ``buildLoad`` / ``buildSelectRole`` / ``panel.setState``
    //  （shim）调用着 —— 那些调用是**失败反馈**的唯一出口
    //  （例如「✗ 接口未就绪」「✗ 读取缓存失败」），不能删。
    //
    //  ``buildLog`` 里第一行就是 ``if (!host) return;``，
    //  日志容器不再创建 → ``buildLog`` 只往控制台写。
    //
    //  ⚠ 但失败反馈不能就此消失！所以 ``panel.setState`` 的 shim 改成
    //    **同时**往「结果提示位」写（见上面 shim 的实现）。
    // ══════════════════════════════════════════════════════════════════════

    // ══════════════════════════════════════════════════════════════════════
    //  ★★★ 2026-11-05：订阅登录 / 拉数据事件
    //
    //  后端 ``kuroLogin`` 是**异步**的（立刻返回），结果全走事件：
    //
    //  * ``kuroLoginState``    —— state = logging_in / logged_in / failed
    //  * ``kuroDataProgress``  —— 拉数据时的每一行进度
    //  * ``kuroDataReady``     —— 数据到手（partial=True 表示拉到一半）
    //  * ``kuroDataFailed``    —— 拉数据失败
    //
    //  ## ⚠ 不能在这里 ``return`` 一个 off 数组
    //
    //  这个面板走的是 ``registerPanel``（不是 ``registerPage``），
    //  页面切走时**没有统一的卸载钩子** —— 所以监听器用
    //  ``window.Bridge.on`` 挂上后由 Bridge 自己持有。
    //  重建面板会再挂一次，但每个回调都只操作 ``BUILD_STATE`` 里
    //  **当前**那几个元素（旧的已被 GC），不会串到别的面板。
    const offs = [];
    offs.push(window.Bridge.on('kuroLoginState', function (data) {
      const d = data || {};
      const state = String(d.state || '');
      const msg = String(d.message || '');
      if (BUILD_STATE.loginStatus) {
        if (state === 'logged_in') {
          BUILD_STATE.loginStatus.textContent = '已登录';
        } else if (state === 'failed') {
          BUILD_STATE.loginStatus.textContent = '未登录';
        } else {
          BUILD_STATE.loginStatus.textContent = '登录中…';
        }
      }
      if (state === 'failed') {
        BUILD_STATE.busy = false;
        if (BUILD_STATE.loginBtn) BUILD_STATE.loginBtn.textContent = '登录';
        buildApplyEditable();
        setBuildNotice('登录失败：' + (msg || '未知原因'), 'error');
        return;
      }
      if (state === 'logged_in') {
        //: 登录成功 —— 后端紧接着会自动拉数据，这里保持 busy
        BUILD_STATE.loggedIn = true;
        BUILD_STATE.busy = true;
        if (BUILD_STATE.loginBtn) BUILD_STATE.loginBtn.textContent = '登录';
        buildApplyEditable();
        setBuildNotice(msg || '登录成功，开始拉取数据…', 'info');
        return;
      }
      setBuildNotice(msg || '正在登录…', 'info');
    }));

    offs.push(window.Bridge.on('kuroDataProgress', function (data) {
      const msg = String((data || {}).message || '');
      if (msg) setBuildNotice(msg, 'info');
    }));

    offs.push(window.Bridge.on('kuroDataReady', function (data) {
      const d = data || {};
      BUILD_STATE.busy = false;
      buildApplyEditable();
      if (BUILD_STATE.refreshBtn) BUILD_STATE.refreshBtn.textContent = '刷新数据';
      //: 收到完整数据才重读缓存重画；partial 只更新提示（43 个角色要几十秒，
      //: 每 5 个推一次 partial，重画整页会闪）
      if (d.partial) {
        setBuildNotice('数据拉取中…（已拉到一部分）', 'info');
        return;
      }
      setBuildNotice('数据已更新（' + String(d.updatedAt || '') + '）', 'ok');
      buildLoad();
    }));

    offs.push(window.Bridge.on('kuroDataFailed', function (data) {
      BUILD_STATE.busy = false;
      buildApplyEditable();
      if (BUILD_STATE.refreshBtn) BUILD_STATE.refreshBtn.textContent = '刷新数据';
      setBuildNotice('拉取失败：' + String((data || {}).message || '未知原因'),
        'error');
    }));
    BUILD_STATE._offs = offs;

    //: ★ 页面切回来时后端可能还在拉（线程不随页面销毁）——
    //: 问一句把按钮锁住，不然用户会连点。
    (async function () {
      try {
        const r = await P.call('kuroBusy');
        if (r.ok && r.data && r.data.busy) {
          BUILD_STATE.busy = true;
          buildApplyEditable();
          setBuildNotice('后台正在登录 / 拉取数据…', 'info');
        }
      } catch (err) {
        void err;
      }
    })();

    buildLoad();
    void app;
  });

  /**
   * ★ 退出登录 —— 2026-11-05 用户要求**改成弹出提示框确认**。
   *
   * ## 为什么不能再用「按钮变确认态」
   *
   * 原来点第一下按钮自己变成「确认退出？」、5 秒内再点一次才执行。
   * 用户圈图（m15330 图1 红框圈的就是那颗按钮）说：
   *
   *   > 退出登录点击后改成弹出提示框确认
   *
   * 两次点击之间没有别的视觉提示，用户容易以为「点一下没反应」而连点；
   * 而且按钮就在卡片标题行最右，旁边的状态文字完全没变。
   *
   * 现在用项目里统一的 ``.dlg-overlay`` / ``.dlg-box`` 弹框（CSS 是全局的，
   * ``config.js`` / ``tasks.js`` 也是这套），标题 + 说明 + 取消/退出 两个按钮。
   *
   * 弹框内容要**说清后果**：登出会删掉令牌 + ``kuro_练度.json`` 缓存，
   * 下次得重新拿验证码登录。这是不可逆操作，不能只写一句「确定吗」。
   *
   * @param {HTMLElement} btn - 「退出登录」按钮
   */
  function buildLogout(btn) {
    openConfirmDialog({
      title: '退出登录',
      message: '退出后会删掉登录令牌和本地练度缓存（data/kuro_练度.json）。' +
        '下次要用得重新获取验证码登录，拉一次数据大约 30~60 秒。',
      confirmLabel: '退出登录',
      danger: true
    }).then(function (ok) {
      if (ok) doLogout(btn);
    });
  }

  /** 真执行退出（弹框确认之后）。*/
  function doLogout(btn) {
    if (btn) btn.disabled = true;

    (async function () {
      const r = await P.call('kuroLogout');
      if (!r.ok) {
        if (btn) btn.disabled = false;
        setBuildNotice('退出登录失败（接口未就绪）', 'error');
        return;
      }
      const d = r.data || {};
      if (d.ok === false) {
        if (btn) btn.disabled = false;
        setBuildNotice('退出登录失败：' +
          String(d.message || d.reason || '后端拒绝'), 'error');
        return;
      }
      //: 清空页面上的数据（旧界面也是 ``self._render({})``）
      BUILD_STATE.data = null;
      BUILD_STATE.selectedId = '';
      if (BUILD_STATE.rolesHost) P.fill(BUILD_STATE.rolesHost, null);
      if (BUILD_STATE.detailHost) P.fill(BUILD_STATE.detailHost, null);
      if (BUILD_STATE.summaryEl) {
        P.fill(BUILD_STATE.summaryEl, [P.el('div', {
          class: 'build-overview-empty', text: '尚未拉取数据'
        })]);
      }
      if (BUILD_STATE.loginStatus) {
        BUILD_STATE.loginStatus.textContent = '未登录';
      }
      if (BUILD_STATE.loginFields) {
        for (const key of Object.keys(BUILD_STATE.loginFields)) {
          const el = BUILD_STATE.loginFields[key];
          if (el) el.value = '';
        }
      }
      //: ★★★ 2026-11-05 **这里原来漏了恢复可编辑**
      //:
      //: 用户圈图：「退出登录后，特征码、手机号、验证码怎么不能输入？」
      //: 三个输入框在建卡时就被写死 ``disabled = true``，
      //: 退出登录只清了 ``value``、没动 ``disabled`` ——
      //: 于是登出之后**再也输不进去**，只能重启程序（而重启后还是禁用）。
      BUILD_STATE.loggedIn = false;
      BUILD_STATE.busy = false;
      BUILD_STATE.relogin = false;
      buildApplyEditable();
      setBuildNotice(String(d.message ||
        '已退出登录（令牌 + 缓存都已删除）'), 'warn');
      //: 退出成功后按钮就该消失（没登录了）—— 交给状态函数统一处理，
      //: 别再在这里手写 ``style.display``（两处都改容易漏一处）
      if (btn) btn.disabled = false;
      buildApplyEditable();
    })();
  }

  // ════════════════════════════════════════════════════════════════════════
  //  通用确认弹框（tool-panels 里原来没有，config.js / tasks.js 各有一份）
  //
  //  ⚠ 为什么不去抽成公共的：``tool-panels.js`` 在 index.html 里
  //  **排在 tasks.js / config.js 之前**，那两个文件的 ``openDialog``
  //  是 IIFE 内部的局部函数，拿不到。真正要抽公共应当挪进 ``_shared.js``，
  //  但那要动三个文件的调用点（40+ 处）—— 为一个弹框不值得。
  //  这里只做「标题 + 一段话 + 取消/确定」，够用且不引额外依赖。
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 弹一个确认框，返回 ``Promise<boolean>``。
   *
   * @param {Object} opts
   * @param {string} opts.title 标题
   * @param {string} opts.message 正文（**不支持 Markdown**，
   *   ``**…**`` 和 ``` `` ``` 会原样显示 —— 写纯文本）
   * @param {string} [opts.confirmLabel] 确认按钮文字
   * @param {boolean} [opts.danger] 确认按钮是否红色
   */
  function openConfirmDialog(opts) {
    opts = opts || {};
    return new Promise(function (resolve) {
      let settled = false;

      const overlay = P.el('div', { class: 'dlg-overlay' });
      const box = P.el('div', {
        class: 'dlg-box',
        style: 'width:440px'
      });

      function close(value) {
        if (settled) return;
        settled = true;
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
        document.removeEventListener('keydown', onKey);
        resolve(value);
      }

      function onKey(ev) {
        if (ev.key === 'Escape') close(false);
      }

      const head = P.el('div', { class: 'dlg-head' }, [
        P.el('div', { class: 'dlg-title', text: opts.title || '确认' }),
        P.el('div', { style: 'flex:1 1 auto' }),
        P.el('button', {
          class: 'dlg-close', type: 'button', text: '×', title: '关闭',
          onClick: function () { close(false); }
        })
      ]);
      box.appendChild(head);

      const body = P.el('div', { class: 'dlg-body' });
      body.appendChild(P.el('div', {
        class: 'dlg-note',
        style: 'font-size:12.5px;line-height:1.75',
        text: String(opts.message || '')
      }));
      box.appendChild(body);

      const foot = P.el('div', { class: 'dlg-foot' });
      foot.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
      const cancelBtn = P.button('取消', {
        onClick: function () { close(false); }
      });
      cancelBtn.dataset.action = 'cancel';
      foot.appendChild(cancelBtn);
      const okBtn = P.button(opts.confirmLabel || '确定', {
        kind: opts.danger ? 'danger' : 'primary',
        onClick: function () { close(true); }
      });
      okBtn.dataset.action = 'confirm';
      foot.appendChild(okBtn);
      box.appendChild(foot);

      overlay.appendChild(box);
      //: 点遮罩关闭（点框内不关）
      overlay.addEventListener('mousedown', function (ev) {
        if (ev.target === overlay) close(false);
      });
      document.addEventListener('keydown', onKey);
      document.body.appendChild(overlay);
      //: 焦点给「取消」—— 危险操作默认不落在确认上
      try { cancelBtn.focus(); } catch (err) { void err; }
    });
  }

  /**
   * ★★★ 2026-11-05 用户圈图：「刷新数据改成重新登录，重新登陆不会清除
   * 特征码和手机号信息（退出登陆会清除），验证码变成可输入，
   * 右边还有 60 倒计时输入提示」。
   *
   * ## 三种状态别混
   *
   * ============  =====================================================
   * 操作           语义
   * ============  =====================================================
   * 登录           未登录时用手机号 + 验证码登进来
   * **重新登录**   **已登录**时换一个新验证码再登一次 —— 特征码/手机号
   *                保持原值，只重填验证码
   * 退出登录       清令牌 + 清缓存，三个框全部清空
   * ============  =====================================================
   *
   * 所以「重新登录」= 解锁输入框（但**不清**特征码/手机号）+ 聚焦验证码
   * + 把按钮文字改成「确认重登」，用户填完再点一次就真登录。
   *
   * ## 为什么不直接调 ``kuroFetchData``
   *
   * 那个是「已有令牌重拉数据」，不需要验证码。用户这次要的是**换新验证码
   * 重登**（令牌会过期，过期后只能重新登录，不能刷新）。
   *
   * @param {HTMLElement} btn - 「重新登录」按钮
   */
  function buildRelogin(btn) {
    if (!BUILD_STATE.loggedIn) {
      setBuildNotice('还没登录 —— 直接填手机号 + 验证码点「登录」', 'warn');
      return;
    }
    //: 已经在重登流程里 → 这次点击是「确认重登」
    if (BUILD_STATE.relogin) {
      buildLogin(BUILD_STATE.loginBtn || btn);
      return;
    }

    BUILD_STATE.relogin = true;
    BUILD_STATE.busy = false;
    buildApplyEditable();

    //: ★ 特征码 / 手机号**保持原值**（用户明确要求），只清验证码
    const fields = BUILD_STATE.loginFields || {};
    if (fields.code) {
      fields.code.value = '';
      try { fields.code.focus(); } catch (err) { void err; }
    }
    if (btn) btn.textContent = '确认重登';
    setBuildNotice(
      '重新登录：特征码和手机号已保留，填一个新验证码后点「确认重登」。' +
      '点「获取验证码」可以看到 60 秒倒计时提示。', 'info');
    //: 顺手起一个倒计时（用户要的「右边还有 60 倒计时输入提示」）
    buildStartCodeCountdown();
  }

  /**
   * ★ 验证码倒计时（用户：「右边还有 60 倒计时输入提示」）。
   *
   * ## ★★★ 为什么**不真发短信**
   *
   * ``kuro_account.send_sms_code`` 实测会抛 :class:`NeedHumanVerify` ——
   * 服务端返回 ``{"code":200, "data":{"geeTest":true}}``，
   * **code 是 200 但短信根本没发**（极验要跑 JS 采行为轨迹，纯 Python 做不到）。
   *
   * 好消息是**验证码在 APP 端与网页端通用**，用户自己去官方入口点一次
   * 「获取验证码」就能拿到，填到这里即可。所以这颗按钮的职责是
   * **倒计时 + 引导**，不是发短信。
   *
   * 倒计时结束（60 秒）后按钮恢复可点 —— 这时用户如果还没拿到码，
   * 说明官方那边的码可能也过期了，该再去点一次。
   */
  function buildSendCode(btn) {
    if (BUILD_STATE.codeLeft > 0) return;
    buildStartCodeCountdown(btn);
    setBuildNotice(
      '验证码需要去库街区 App / 网页登录框点「获取验证码」，' +
      '拿到后填到这个框里（两边通用，本机发不出去）。', 'info');
    const fields = BUILD_STATE.loginFields || {};
    if (fields.code) {
      try { fields.code.focus(); } catch (err) { void err; }
    }
  }

  /** 起 60 秒倒计时，按钮文字显示剩余秒数。 */
  function buildStartCodeCountdown(btn) {
    const codeBtn = btn || BUILD_STATE.codeBtn;
    if (!codeBtn) return;
    if (BUILD_STATE.codeTimer) {
      clearInterval(BUILD_STATE.codeTimer);
      BUILD_STATE.codeTimer = 0;
    }
    BUILD_STATE.codeLeft = 60;
    const paint = function () {
      if (BUILD_STATE.codeLeft > 0) {
        codeBtn.textContent = '重发 ' + BUILD_STATE.codeLeft + 's';
        codeBtn.disabled = true;
      } else {
        codeBtn.textContent = '获取验证码';
        codeBtn.disabled = false;
        if (BUILD_STATE.codeTimer) {
          clearInterval(BUILD_STATE.codeTimer);
          BUILD_STATE.codeTimer = 0;
        }
        buildApplyEditable();
      }
    };
    paint();
    BUILD_STATE.codeTimer = setInterval(function () {
      BUILD_STATE.codeLeft -= 1;
      paint();
    }, 1000);
  }


  /**
   * ★★★ 2026-11-05 同步「登录卡能不能编辑」。
   *
   * 照抄旧界面 ``_apply_inputs_editable(editable)`` 的语义：
   *
   * * **未登录** → 特征码 / 手机号 / 验证码可编辑，登录按钮可点
   * * **已登录** → 三者置灰 + tooltip「已登录 —— 想换号请先点「退出登录」」
   * * **正在登录 / 正在拉数据** → 全置灰（防止连点，也防止改到一半被覆盖）
   *
   * ## ⚠ 为什么必须集中成一个函数
   *
   * 原来「能不能编辑」散在三处（建卡时写死 ``disabled = true``、
   * 退出登录时只清 ``value`` 不动 ``disabled``、回填时也不动），
   * 于是**退出登录后再也输入不了** —— 用户圈图问的就是这个 bug。
   * 现在只有这里改 ``disabled``，谁改状态谁调它。
   */
  function buildApplyEditable() {
    const fields = BUILD_STATE.loginFields || {};
    //: ★ 2026-11-05：「重新登录」进行中时**即使已登录也要解锁** ——
    //: 用户要重填验证码，锁着就没法填（这是那条圈图的核心诉求）。
    const locked = (!!BUILD_STATE.loggedIn && !BUILD_STATE.relogin)
      || !!BUILD_STATE.busy;
    for (const key of Object.keys(fields)) {
      const el = fields[key];
      if (!el) continue;
      el.disabled = locked;
      //: 验证码框在**已登录且不在重登流程**时干脆留空
      //: （旧界面也不留旧验证码）。重登时不清 —— 用户马上就要填新的。
      if (key === 'code' && locked) el.value = '';
    }
    if (BUILD_STATE.loginBtn) {
      BUILD_STATE.loginBtn.disabled = locked;
      BUILD_STATE.loginBtn.title = BUILD_STATE.busy
        ? '正在处理，请稍候'
        : (BUILD_STATE.loggedIn && !BUILD_STATE.relogin
          ? '已登录 —— 想换号请先点「退出登录」；只想换验证码点「重新登录」'
          : '手机号 + 短信验证码（验证码在库街区 App / 网页登录框获取）');
    }
    //: 「获取验证码」跟着验证码框的可用性走（倒计时期间另有自己的禁用逻辑）
    if (BUILD_STATE.codeBtn) {
      BUILD_STATE.codeBtn.disabled = locked || BUILD_STATE.codeLeft > 0;
    }
    //: ★ 2026-11-05：「重新登录」在**已登录 + 不忙**时可用
    //: （没登录时它就是普通登录，不需要它）
    if (BUILD_STATE.reloginBtn) {
      BUILD_STATE.reloginBtn.disabled = !BUILD_STATE.loggedIn
        || !!BUILD_STATE.busy;
    }
    //: 旧的「刷新数据」按钮已经删了，``refreshBtn`` 恒为 null。
    //: 保留判空是因为事件回调里还有几处引用（删干净要改三处，
    //: 而且判空本身是对的）。
    if (BUILD_STATE.refreshBtn) {
      BUILD_STATE.refreshBtn.disabled = !BUILD_STATE.loggedIn
        || !!BUILD_STATE.busy;
    }
    //: ★★★ 2026-11-05 用户圈图：「都没登录还能点退出登录」。
    //:
    //: 没登录时哪来的登录态可退？点它只会在「确认退出？」和
    //: 删一个不存在的令牌之间来回 —— 纯属误导。
    //: 所以：**未登录时整个按钮隐藏**，已登录才显示。
    //:
    //: 放这里而不是 ``buildLogout()`` 里，是因为「显不显示」是**状态**，
    //: 而 ``buildApplyEditable()`` 就是这个状态函数 ——
    //: 上一轮「按钮文案散在两处」吃过亏，同理。
    //
    //: ⚠ 用 ``style.display`` 而不是 ``hidden`` 属性：``P.button`` 产出的
    //: 是普通 ``<button>``，``hidden`` 会被 `.btn { display: inline-flex }`
    //: 盖掉（和前面 ``.search-caret`` 踩过的是同一类坑）。
    if (BUILD_STATE.logoutBtn) {
      BUILD_STATE.logoutBtn.style.display =
        BUILD_STATE.loggedIn ? '' : 'none';
    }
  }

  /**
   * ★★★ 2026-11-05 点「登录」：校验 → 调 ``kuroLogin`` → 等事件。
   *
   * 后端 ``kuroLogin`` 是**异步**的（立刻返回 ``{ok:true}``），真正的结果
   * 走 ``kuroLoginState`` / ``kuroDataProgress`` / ``kuroDataReady`` 事件。
   * 所以这里只负责：拿输入 → 本地先校验一遍 → 置忙 → 发请求。
   */
  async function buildLogin(btn) {
    const fields = BUILD_STATE.loginFields || {};
    const mobileEl = fields.mobile;
    const codeEl = fields.code;
    const featureEl = fields.feature;
    const mobile = String((mobileEl && mobileEl.value) || '').trim();
    const code = String((codeEl && codeEl.value) || '').trim();
    const feature = String((featureEl && featureEl.value) || '').trim();

    //: 手机号框里可能还是脱敏值 ``****6241`` —— 那不是能提交的号码
    if (!/^\d{11}$/.test(mobile)) {
      setBuildNotice('请填写 11 位手机号（框里若是 ****xxxx，点一下重填）',
        'warn');
      if (mobileEl) mobileEl.focus();
      return;
    }
    if (!code) {
      setBuildNotice('请填写短信验证码（在库街区 App / 网页登录框点「获取验证码」）',
        'warn');
      if (codeEl) codeEl.focus();
      return;
    }

    BUILD_STATE.busy = true;
    buildApplyEditable();
    if (btn) btn.textContent = '登录中…';
    setBuildNotice('正在登录…', 'info');

    //: ★ 必须用 ``callMulti`` —— ``kuroLogin`` 是
    //: ``@Slot(str, str, str, result=str)`` 三个参数。QWebChannel 按
    //: **JS 实参个数**匹配签名，用单参的 ``P.call`` 会「找不到匹配」并
    //: 静默返回空数组（见 ``_shared.js`` 里那段长注释），
    //: 表现就是**一按登录立刻失败**、日志写着「接口未就绪」。
    const r = await P.callMulti('kuroLogin', [mobile, code, feature]);
    if (!r.ok) {
      BUILD_STATE.busy = false;
      buildApplyEditable();
      if (btn) btn.textContent = '登录';
      setBuildNotice('登录失败（接口未就绪）', 'error');
      return;
    }
    const d = r.data || {};
    if (d.ok === false) {
      BUILD_STATE.busy = false;
      buildApplyEditable();
      if (btn) btn.textContent = '登录';
      setBuildNotice('登录失败：' + String(d.message || d.reason || '未知原因'),
        d.reason === 'busy' ? 'warn' : 'error');
    }
    //: 成功 / 忙碌：等 ``kuroLoginState`` 事件收尾，这里不动按钮
  }

  /**
   * ★★★ 2026-11-05 点「刷新数据」：真的重新拉一次（不是只读缓存）。
   */
  async function buildRefresh(btn) {
    BUILD_STATE.busy = true;
    buildApplyEditable();
    if (btn) btn.textContent = '拉取中…';
    setBuildNotice('正在重新拉取账号数据…', 'info');
    const r = await P.call('kuroFetchData', '');
    if (!r.ok || (r.data && r.data.ok === false)) {
      BUILD_STATE.busy = false;
      buildApplyEditable();
      if (btn) btn.textContent = '刷新数据';
      const d = (r.data || {});
      setBuildNotice('拉取失败：' +
        String(d.message || d.reason || '接口未就绪'), 'error');
    }
  }

  /**
   * 记录一行日志（旧界面 ``_log`` 是只读 QTextEdit）。
   *
   * ## ★ 2026-11-03 日志卡删掉后，这里改成**只往控制台写**
   *
   * 用户圈图要求删掉「⑤ 日志」那张卡。卡没了，日志容器也就不再存在。
   *
   * ⚠ 这个函数**不能删** —— 十几处调用（读缓存 / 选角色 / 接口失败）
   * 都走它。而且它是**排查问题的唯一线索**（用户报"没数据"时，
   * 日志里那句「✓ 读到 21 个角色」是判断"接口没问题、是渲染问题"的关键）。
   *
   * 所以：保留调用点，实现改成 ``console.info`` —— 界面上不占地方，
   * 但 ``debug_js`` / 开发者工具里仍然查得到。
   *
   * **用户可见的失败反馈**走另一个出口 :func:`setBuildNotice`
   * （② 账号概览卡里那行提示），见 ``panel.setState``。
   *
   * ⚠ 老实现是「取容器 → 没容器就 return」，删卡后那段代码就成了
   *   「引用了但从未赋值的字段」，``js_sanity`` 的静默失败检查会
   *   （正确地）报出来 —— 所以整个实现换成控制台输出。
   */
  function buildLog(text, level) {
    const value = String(text == null ? '' : text);
    if (!value) return;
    try {
      if (level === 'error') console.error('[character_build]', value);
      else if (level === 'warn') console.warn('[character_build]', value);
      else console.info('[character_build]', value);
    } catch (err) {
      //: 控制台都不可用（极端环境）—— 不影响主流程，但留个痕
      void err;
    }
  }

  async function buildLoad() {
    const panel = BUILD_STATE.handle;
    if (!panel) return;

    panel.setState('preparing', '正在读取缓存…', { percent: 30 });
    buildLog('读取角色练度缓存…');

    const result = await P.call('getCharacterBuildCache');

    if (!result.ok) {
      panel.setState('blocked', '接口未就绪');
      buildLog('✗ 接口未就绪', 'error');
      setBuildCacheNote('接口未就绪（缺 getCharacterBuildCache）。');
      return;
    }

    const data = result.data || {};

    //: ★ 没有缓存 —— 明确告诉用户怎么办
    if (data.ok === false) {
      const reason = String(data.reason || '');
      panel.setState('blocked', reason === 'no_cache' ? '还没有缓存' : '读取失败');
      panel.setProgress(0, '');
      P.fill(BUILD_STATE.rolesHost, null);
      P.fill(BUILD_STATE.detailHost, null);
      setBuildCacheNote(String(data.message || '读取缓存失败。'));
      buildLog('✗ ' + String(data.message || '读取缓存失败。'), 'error');
      return;
    }

    BUILD_STATE.data = data;
    panel.setState('idle', '已加载 ' + (data.count || 0) + ' 个角色');
    panel.setProgress(0, '');
    buildLog('✓ 读到 ' + (data.count || 0) + ' 个角色，缓存于 ' +
      (data.updatedAt || '未知时间'));

    // ── ① 登录卡：登录状态 + 三个字段（显示缓存里保存的值）──
    //
    //: 后端 ``loginInfo``（web-shell-dev 2026-11-02 补）：
    //:   ``{gameId, roleId, nickname, phoneTail, phoneMasked, loggedIn, loginAt}``
    //:
    //: ⚠ **手机号本来就只有 4 位** —— ``kuro_account.json`` 存的是
    //:   ``mobile_tail: "6241"``，完整号码从来没落过盘。
    //:   所以直接用 ``phoneMasked``（``****6241``），不用自己脱敏。
    const login = data.loginInfo || data.account || {};
    //: ★ 2026-11-05：这里原来是照抄旧界面的
    //: ``login.loggedIn != null ? !!login.loggedIn : !!login.loggedIn``
    //: —— 两个分支一模一样，等于 ``!!login.loggedIn``，三元没意义。
    //: 直接写清楚：**没有 ``loginInfo``（没缓存）就当未登录**。
    const loggedIn = !!(login && login.loggedIn);

    //: ★ 2026-11-05：登录态决定输入框能不能编辑（见 buildApplyEditable）
    BUILD_STATE.loggedIn = loggedIn;

    if (BUILD_STATE.loginStatus) {
      //: 旧界面 ``_say`` L918：``f"已登录（手机号 ****{tail}）"``
      if (loggedIn) {
        const masked = String(login.phoneMasked || '');
        BUILD_STATE.loginStatus.textContent = masked
          ? '已登录（手机号 ' + masked + '）'
          : (login.loginAt ? '已登录（' + login.loginAt + '）' : '已登录');
      } else {
        BUILD_STATE.loginStatus.textContent = '未登录';
      }
    }
    if (BUILD_STATE.loginFields) {
      //: 特征码（旧界面 ``_feature_edit``）
      const feat = BUILD_STATE.loginFields.feature;
      const gameId = login.gameId || login.roleId || '';
      if (feat) feat.value = String(gameId || '');
      //: 手机号 —— 只有后四位，显示脱敏形式
      const mob = BUILD_STATE.loginFields.mobile;
      if (mob) {
        mob.value = String(login.phoneMasked ||
          (login.phoneTail ? '****' + login.phoneTail : ''));
      }
      //: 验证码 —— 缓存里从来没存过（旧界面也不存），留空
      const code = BUILD_STATE.loginFields.code;
      if (code) code.value = '';
    }
    //: ★ 2026-11-05：回填完再决定置灰 —— 顺序反了会把刚回填的值锁在外面
    buildApplyEditable();
    //: 缓存说明（时间）
    //
    //: ★ 2026-11-05 文案改掉：原来写「Web 版不支持登录…要更新请用旧界面」，
    //: 现在 Web 版能登录了，那句话会误导用户。
    setBuildCacheNote(
      '最后更新：' + String(data.updatedAt || '未知时间') +
      '（点「刷新数据」可重新拉取）'
    );

    // ── ② 账号概览 —— **照抄旧界面 ``_format_base`` 的 6 项** ──
    //
    //: ``base`` 字段目前后端还没给（等 web-shell-dev 补）。
    //: 拿不到时**照旧界面的容错**显示 ``?`` —— 不是空着、也不是"尚未拉取"。
    if (BUILD_STATE.summaryEl) {
      P.fill(BUILD_STATE.summaryEl, null);
      const base = data.base || {};

      function pick(key) {
        const value = base[key];
        return value != null && value !== '' ? String(value) : '?';
      }

      const parts = [
        '结晶波片 ' + pick('energy') + '/' + pick('maxEnergy'),
        '结晶单质 ' + pick('storeEnergy') + '/' + pick('storeEnergyLimit'),
        '活跃度 ' + pick('liveness') + '/' + pick('livenessMaxCount'),
        '游戏天数 ' + pick('activeDays'),
        '联觉等级 ' + pick('level'),
        '解锁角色 ' + pick('roleNum')
      ];
      //: ⚠ 分隔符是**全角空格 + 竖线 + 全角空格**（旧界面 ``"　|　".join()``）
      BUILD_STATE.summaryEl.appendChild(P.el('div', {
        class: 'build-overview-line',
        text: parts.join('　|　')
      }));
    }

    buildRenderRoles();

    //: ★★★ 2026-11-03 用户：「默认选择最近的一个角色」
    //:
    //: ## 之前
    //:
    //: ``BUILD_STATE.selectedId`` 一直是空串 → 打开页面时
    //: **没有任何角色被选中**，④ 详情区永远显示「在上面点一个共鸣者…」。
    //: 用户得先点一下才看得到东西。
    //:
    //: ## ⚠ 选谁？必须是**列表里第一个显示的**，不是 ``characters[0]``
    //:
    //: ``buildRenderRoles()`` 里有一句 ``all.slice().reverse()``
    //: ——「最新获得在前」（照抄旧界面）。所以页面**最左边**那个是
    //: ``characters[characters.length - 1]``。
    //:
    //: 踩到过：一开始按 ``characters[0]`` 选，结果默认选中的是「秧秧
    //: Lv.20」，而列表第一格明晃晃写着「千咲 Lv.90」——
    //: 选中态和看到的完全对不上，用户会以为点错了。
    //:
    //: 现在直接复用 ``buildRenderRoles`` 的同一套排序/筛选结果。
    if (!BUILD_STATE.selectedId) {
      const chars = Array.isArray(data.characters) ? data.characters : [];
      //: 和 ``buildRenderRoles`` 一致：反转后取第一个
      const ordered = chars.slice().reverse();
      const first = ordered.find(function (c) {
        return c && String(c.roleId || '') !== '';
      });
      if (first) {
        buildSelectRole(String(first.roleId));
      }
    }
  }

  function setBuildCacheNote(text) {
    const el = document.getElementById('build-cache-note');
    if (!el) return;
    //: ⚠ textContent（不是 innerHTML）—— 内容是用户可见的纯文本说明
    el.textContent = String(text);
  }

  /**
   * ★ 在「② 账号概览」卡片里显示一条**可见的**失败/警告提示（2026-11-03）。
   *
   * ## 为什么需要
   *
   * ⑤ 日志卡片按用户要求删掉了，而原来的失败反馈**只写日志** ——
   * 删了卡之后所有错误都会静默消失（交接文档点名的静默失败形态 ②）。
   *
   * 所以给一个常驻但默认隐藏的提示位：只有 ``state === 'blocked'/'error'``
   * 时才显示，常态不占视觉空间。
   *
   * @param {string} text - 提示内容
   * @param {string} [level] - ``warn`` / ``error``
   */
  function setBuildNotice(text, level) {
    const el = BUILD_STATE.noticeEl;
    if (!el) return;
    const value = String(text || '').trim();
    if (!value) {
      el.hidden = true;
      el.classList.add('hidden');
      el.textContent = '';
      return;
    }
    el.dataset.level = level || 'warn';
    el.textContent = value;
    el.hidden = false;
    el.classList.remove('hidden');
  }

  /**
   * 渲染 ③ 共鸣者列表（**单行横向滚动**）。
   *
   * ## 筛选三态规则（★ 照抄旧界面 tool.py L1107-1136）
   *
   * .. code:: python
   *
   *   unleveled = is_unleveled(role, has_data)   # 没声骸数据 或 未满 90 级
   *
   *   if choice == "未练":     if not unleveled: continue
   *   elif choice == "未达标":  if unleveled or not issues: continue
   *   elif choice == "达标":    if unleveled or issues: continue
   *
   * 关键：「没数据」**不等于**「达标」，那是「未练」。
   * （旧界面注释里记着用户报的 bug：「丽贝卡 Lv.40」出现在「达标」里）
   *
   * ## 排序（L1095-1101）
   *
   * ``ordered = list(reversed(role_list))`` —— 游戏返回的原始顺序反转
   * 就是「最新获得在前」。**别再按 level / 名字排**，那会打乱游戏顺序。
   */
  function buildRenderRoles() {
    const host = BUILD_STATE.rolesHost;
    if (!host || !BUILD_STATE.data) return;
    P.fill(host, null);

    const all = Array.isArray(BUILD_STATE.data.characters)
      ? BUILD_STATE.data.characters
      : [];
    const detailSet = {};
    for (const id of (BUILD_STATE.data.detailIds || [])) {
      detailSet[String(id)] = true;
    }

    //: ★ 反转（最新获得在前）—— 照抄旧界面
    const ordered = all.slice().reverse();

    const keyword = BUILD_STATE.filter;
    const choice = BUILD_STATE.choice;

    const shown = ordered.filter(function (role) {
      const id = String(role.roleId || '');
      const hasData = !!detailSet[id];
      const unleveled = !hasData || (Number(role.level) || 0) < MAX_LEVEL;

      //: ★★★ 2026-11-03 **筛选逻辑修正**（用户：「筛选逻辑有问题，
      //: 未达标，怎么进入达标里了？」）
      //:
      //: ## 之前错在哪
      //:
      //: .. code:: js
      //:
      //:     const issues = hasData ? false : true;   // ← 假的判定
      //:
      //: 「有数据」被当成「达标」。于是千咲（暴击 41.3% / 推荐 ≥75%）
      //: 明明是未达标，却出现在「达标」分类里 —— 用户截图圈的就是这个。
      //:
      //: ## 现在
      //:
      //: 用后端**真算出来的** ``role.flagged``（比对 standards.attrs 与
      //: roleAttributeList 得出）。语义照旧界面 ``tool.py`` L1123-1136：
      //:
      //:   * 未练   = 没数据 **或** 等级没满 90
      //:   * 未达标 = 有数据、满级、**且有问题**
      //:   * 达标   = 有数据、满级、**且没问题**
      //:
      //: ⚠ 「没数据」必须归到「未练」而不是「达标」—— 见旧代码注释
      //:   L1111-1115：那是用户 2026-10-05 报过的同一个 bug。
      const flagged = role.flagged === true
        || (Array.isArray(role.issues) && role.issues.length > 0);

      if (choice === '未练') {
        if (!unleveled) return false;
      } else if (choice === '未达标') {
        if (unleveled || !flagged) return false;
      } else if (choice === '达标') {
        if (unleveled || flagged) return false;
      }

      if (keyword) {
        //: ★★★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
        //:
        //: 和下拉候选的 ``match()`` **同一套规则** —— 只看**角色名** +
        //: **纯字母走拼音**。原来这里是
        //: ``[role.name, role.attribute, role.weaponType, role.level]``
        //: 拼起来子串匹配：打「冷凝」会把所有冷凝角色筛出来，但用户
        //: 看不见"冷凝"这两个字在哪儿（候选行已经不显示属性了）——
        //: 配置页就是因为这个被用户圈图抱怨的，这里对齐。
        let ok = String(role.name || '').toLowerCase().indexOf(keyword) >= 0;
        if (!ok && /^[a-z]+$/.test(keyword)) {
          const keys = Array.isArray(role.pinyin) ? role.pinyin : [];
          const full = String(keys[0] || '').toLowerCase();
          const initial = String(keys[1] || '').toLowerCase();
          ok = (!!full && full.indexOf(keyword) >= 0) ||
               (!!initial && initial.indexOf(keyword) >= 0);
        }
        if (!ok) return false;
      }
      return true;
    });

    //: 标题右边的计数（旧界面 ``_roles_hint`` L1160）
    //
    //: .. code:: python
    //:
    //:   f"共 {total} 个　声骸待优化 {bad_n} 个{extra}"
    //:
    //: ``bad_n`` = 没声骸数据 / 未满级的角色数。搜索时带「筛出 N 个」后缀。
    const hint = document.getElementById('build-roles-hint');
    if (hint) {
      const badN = all.filter(function (r) {
        const rid = String(r.roleId || '');
        const has = !!detailSet[rid];
        return !has || (Number(r.level) || 0) < MAX_LEVEL;
      }).length;
      let text = '共 ' + all.length + ' 个　声骸待优化 ' + badN + ' 个';
      if (shown.length !== all.length) {
        text += '（筛出 ' + shown.length + ' 个）';
      }
      hint.textContent = text;
    }

    if (!shown.length) {
      host.appendChild(P.el('div', {
        class: 'build-roles-empty',
        text: all.length ? '没有匹配的共鸣者。' : '缓存里没有角色数据。'
      }));
      return;
    }

    //: ★★★ 2026-11-03 **筛掉的选中角色要跟着换掉**
    //:
    //: 用户把筛选切到「达标」后，原来选中的千咲（未达标）**不在列表里了**，
    //: 但 ④ 共鸣者详情**还显示着千咲** —— 列表只剩漂泊者/清宵，
    //: 详情却讲千咲，看起来像"点错了"。
    //:
    //: 修法：选中的角色如果被当前筛选排除，自动改选**筛后第一个**。
    //: ⚠ 只在"选中的那个不在 shown 里"时切，否则用户的选择会被打断。
    const selectedStillShown = shown.some(function (role) {
      return String(role.roleId || '') === BUILD_STATE.selectedId;
    });
    if (!selectedStillShown) {
      const firstShown = shown[0];
      const firstId = String((firstShown && firstShown.roleId) || '');
      if (firstId) {
        //: 用 setTimeout 排到当前渲染之后，避免在 for 循环里重入
        setTimeout(function () { buildSelectRole(firstId); }, 0);
      }
    }

    for (const role of shown) {
      host.appendChild(buildRoleTile(role, detailSet[String(role.roleId || '')]));
    }
    //: ★ 2026-11-03 卡片重建后刷新左右箭头状态
    //: （卡片数变了 → 能滚的范围变了 → 箭头该亮还是该暗也变了）
    if (typeof BUILD_STATE.syncRolesNav === 'function') {
      setTimeout(BUILD_STATE.syncRolesNav, 30);
    }
  }

  /**
   * 一个共鸣者格子（旧界面 ``CharacterTile``，``TILE_W = 96``、``TILE_H = 132``）。
   *
   * ## ★ 用**立绘**不是头像（P6 修正）
   *
   * 旧界面每个角色有两个图字段：
   *
   *   ``roleIconUrl`` —— 方形**头像**（46×46 的小图）
   *   ``rolePicUrl``  —— **立绘**（竖长，全身）
   *
   * 卡片是 96×132（比例 0.73 = 竖长），用的正是**立绘** ``rolePicUrl``。
   * P5 我用的是头像 —— 尺寸对了但图画错了。
   *
   * 后台字段叫法不一样，这里按优先级找：
   *   ``picUrl`` / ``rolePicUrl`` / ``portraitUrl`` → 立绘
   *   找不到才退回 ``iconUrl``（头像），再找不到用首字。
   */
  function buildRoleTile(role, hasData) {
    const id = String(role.roleId || '');
    const selected = id === BUILD_STATE.selectedId;
    //: 没详情数据的角色 → 红框（旧界面 ``flagged`` 视觉）
    const flagged = !hasData;

    //: ★ 立绘优先（旧界面用 ``rolePicUrl``）
    const pic = role.picUrl || role.rolePicUrl || role.portraitUrl || '';
    const icon = role.iconUrl || role.roleIconUrl || '';

    const tile = P.el('div', {
      class: 'build-tile' +
        (selected ? ' is-selected' : '') +
        (flagged ? ' is-flagged' : ''),
      dataset: { roleId: id },
      style: 'width:96px;height:132px',
      title: (role.name || '') + ' Lv.' + (role.level || '?') +
        (hasData ? '' : '（无明显数据）'),
      onClick: function () { buildSelectRole(id); }
    });

    //: 立绘区（铺满卡片上部，**不是圆形**）
    const picBox = P.el('div', { class: 'build-tile-pic' });
    if (pic) {
      const img = P.el('img', {
        src: pic, alt: String(role.name || ''), loading: 'lazy'
      });
      img.addEventListener('error', function () {
        //: 立绘加载失败 → 退回头像
        P.fill(picBox, null);
        if (icon) {
          const fallback = P.el('img', {
            src: icon, alt: '', loading: 'lazy'
          });
          fallback.addEventListener('error', function () {
            P.fill(picBox, null);
            picBox.textContent = (role.name || '?').slice(0, 1);
            picBox.classList.add('has-initial-color');
          }, { once: true });
          picBox.appendChild(fallback);
        } else {
          picBox.textContent = (role.name || '?').slice(0, 1);
          picBox.classList.add('has-initial-color');
        }
      }, { once: true });
      picBox.appendChild(img);
    } else if (icon) {
      const img = P.el('img', { src: icon, alt: '', loading: 'lazy' });
      img.addEventListener('error', function () {
        P.fill(picBox, null);
        picBox.textContent = (role.name || '?').slice(0, 1);
        picBox.classList.add('has-initial-color');
      }, { once: true });
      picBox.appendChild(img);
    } else {
      picBox.textContent = (role.name || '?').slice(0, 1);
      picBox.classList.add('has-initial-color');
    }
    tile.appendChild(picBox);

    //: 名字 + 等级（在立绘**下方**，不覆盖在图上）
    tile.appendChild(P.el('div', {
      class: 'build-tile-name',
      text: String(role.name || '')
    }));
    tile.appendChild(P.el('div', {
      class: 'build-tile-level',
      text: 'Lv.' + String(role.level || '—')
    }));

    return tile;
  }

  async function buildSelectRole(roleId) {
    BUILD_STATE.selectedId = roleId;
    buildRenderRoles();

    const host = BUILD_STATE.detailHost;
    if (!host) return;
    P.fill(host, [
      P.el('div', { class: 'build-overview-empty', text: '正在读取详情…' })
    ]);

    const result = await P.call('getCharacterBuildDetail', roleId);
    if (!result.ok) {
      P.fill(host, [P.el('div', {
        class: 'build-overview-empty',
        text: '详情接口未就绪。'
      })]);
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      P.fill(host, [P.el('div', {
        class: 'build-overview-empty',
        text: String(data.message || '这个角色没有详细数据。')
      })]);
      return;
    }
    buildRenderDetail(host, data);
    buildLog('读取详情：' + roleId);
  }

  /**
   * ★★★ 2026-11-03 **彻底重写**（用户：「这个原查询角色练度的显示布局」）
   *
   * ## 之前是什么样（为什么被否）
   *
   * 旧实现只有：头像 + 名字 + 属性两行 + 共鸣链列表 + 一句
   * 「完整图文详情请在旧界面查看」—— **少了六块**。
   *
   * ## 现在照抄旧界面 ``detail_view.py`` 的 ``show_detail()``（L1317-1400）
   *
   * 顺序**逐块对齐**：
   *
   * .. code:: text
   *
   *    ① 待优化红字（issues）
   *    ② ✦ 属性推荐      当前 vs 官方推荐（超过/没到用颜色区分）
   *    ③ ✦ 共鸣者属性    两列网格（生命/攻击/防御/暴击…）
   *    ④ ✦ 武器          图标 + 名称 + 等级/谐振/星级 + 主属性
   *    ⑤ ✦ 属性展示      声骸提供的加成（equipPhantomAddPropList）
   *    ⑥ ✦ 声骸 COST n/12  套装名 + 每个声骸的主/副词条
   *    ⑦ ✦ 技能          7 个技能图标 + 等级
   *    ⑧ ✦ 共鸣链        已解锁/未解锁
   *
   * ## 数据从哪来
   *
   * ``getCharacterBuildDetail(roleId)`` 返回 ``{detail, standard}``：
   *
   * * ``detail`` —— 官方库街区的原始 ``details[roleId]``
   * * ``standard`` —— 官方推荐标准（``standards[roleId]``），
   *   含 ``attrs``（推荐属性）/ ``echo``（推荐套装）/ ``weapon`` / ``role_skill``
   *
   * @param {HTMLElement} host - 详情容器（④ 卡片内部）
   * @param {object} data - ``{detail, standard, roleId}``
   */
  function buildRenderDetail(host, data) {
    P.fill(host, null);
    const detail = data.detail || {};
    const standard = data.standard || {};
    const role = detail.role || {};

    const name = String(role.roleName || role.name || '');
    const level = role.level || detail.level || '';
    const attrName = String(role.attributeName || '');
    const weaponType = String(role.weaponTypeName || '');

    // ══════════════════════════════════════════════════════════════════════
    //  标题行（旧界面 ``self._title``）
    //
    //  .. code:: text
    //
    //    千咲　Lv90　湮灭　长刃
    //
    //  ⚠ 分隔符是**全角空格** ``　``（旧界面 L1329-1332 用的就是它）
    // ══════════════════════════════════════════════════════════════════════
    const titleBits = [name || '?'];
    if (level) titleBits.push('Lv' + level);
    if (attrName) titleBits.push(attrName);
    if (weaponType) titleBits.push(weaponType);
    host.appendChild(P.el('div', {
      class: 'build-detail-headline',
      text: titleBits.join('\u3000')
    }));

    // ══════════════════════════════════════════════════════════════════════
    //  ① 待优化红字（旧界面 L1339-1343）
    //
    //  ``issues`` 是一串**已经组织好的句子**，用「；」连接。
    //  例：「暴击 41.3% 没到 ≥75%；暴击伤害 192.6% 没到 ≥260%；
    //       套装搭配不符（现在 轻云出月×5，推荐 命理崩毁之弦×3 + 幽夜隐匿之帷×2）」
    // ══════════════════════════════════════════════════════════════════════
    const issues = Array.isArray(data.issues) ? data.issues : [];
    if (issues.length) {
      host.appendChild(P.el('div', {
        class: 'build-detail-issues',
        text: '⚠ ' + issues.join('；')
      }));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ② ✦ 属性推荐（旧界面 L1345-1356 ``_standard_block``）
    //
    //  这是**核心判据**：把「当前值」和「官方推荐值」并排，
    //  没达标的整行标红 + 末尾 ✗，达标标绿 + ✓。
    // ══════════════════════════════════════════════════════════════════════
    // ══════════════════════════════════════════════════════════════════════
    //  当前属性表（detail.roleAttributeList → {名字: 数值}）
    //
    //  ★★★ 2026-11-03 踩到：``attributeValue`` 是**带百分号的字符串**
    //
    //  .. code:: text
    //
    //      '生命'     = '19500'      → Number 19500  ✅
    //      '暴击'     = '43.2%'      → Number **NaN**  ❌
    //      '共鸣效率' = '170.2%'     → Number **NaN**  ❌
    //
    //  直接 ``Number('170.2%')`` 得 NaN，后面 ``have >= need`` 全是 false
    //  → **明明达标（170.2% ≥ 115%）也被标成 ✗**。
    //
    //  实测症状：属性推荐里「共鸣效率 170.2% ≥115.0%」挂着红 ✗。
    //
    //  修法：剥掉非数字后缀再转换（``parseFloat`` 天然只吃到数字为止，
    //  但为了明确表达意图、并且处理全角符号，这里先清一遍）。
    // ══════════════════════════════════════════════════════════════════════
    const parseAttrNum = function (raw) {
      if (raw == null) return NaN;
      if (typeof raw === 'number') return raw;
      const cleaned = String(raw).replace(/[^0-9.\-]/g, '');
      if (!cleaned) return NaN;
      const n = parseFloat(cleaned);
      return isFinite(n) ? n : NaN;
    };
    const currentMap = {};
    for (const item of (detail.roleAttributeList || [])) {
      if (!item || typeof item !== 'object') continue;
      const nm = String(item.attributeName || '').trim();
      if (nm) currentMap[nm] = parseAttrNum(item.attributeValue);
    }
    const stdAttrs = (standard && Array.isArray(standard.attrs))
      ? standard.attrs : [];
    if (stdAttrs.length) {
      const sec = buildDetailSection('✦ 属性推荐', [
        P.el('div', {
          class: 'build-std-head'
        }, [
          P.el('span', { class: 'build-std-head-name', text: '属性' }),
          P.el('span', { class: 'build-std-head-cur', text: '当前数值' }),
          P.el('span', { class: 'build-std-head-want', text: '推荐数值' })
        ])
      ]);
      const body = sec.contentEl;
      for (const attr of stdAttrs) {
        if (!attr || typeof attr !== 'object') continue;
        const label = String(attr.name || '');
        if (!label) continue;
        const wantRaw = String(attr.recommend != null ? attr.recommend : '');
        const symbol = String(attr.symbol || '≥');

        // ══════════════════════════════════════════════════════════════
        //  ★★★ 当前值**必须从 ``roleAttributeList`` 取**，不能用
        //  ``attr.current``（2026-11-03 实测踩到）
        //
        //  ## 坑
        //
        //  ``standard.attrs[].current`` 在后端**恒为 ``"0"`` / ``"0.0%"``**
        //  —— 那是 ```` 的原始字段，没人回填。直接用的话：
        //
        //  .. code:: text
        //
        //      暴击      0.0%   ≥70.0%   ✗      ← 全是 0，全员"没达标"
        //      暴击伤害  0.0%   ≥250.0%  ✗
        //
        //  用户看到的是一条全红的表，**判据完全失效**。
        //
        //  ## 旧界面怎么做的（``detail_view.py`` L884-893）
        //
        //  .. code:: python
        //
        //      current = {}
        //      for item in detail.get("roleAttributeList") or []:
        //          current[item["attributeName"]] = _num(...)
        //      ...
        //      for a in standard["attrs"]:
        //          have = current.get(a["name"])      # ← 从当前属性表取
        //          ok = _meets(have, need, symbol)    # ← 自己算，不信 is_finished
        //
        //  **两个要点**：
        //    ① 当前值从 ``roleAttributeList`` 取（那里是真数据）
        //    ② 达标与否**自己比**，不信 ``is_finished``
        //       （它同样没人回填，恒为 false）
        // ══════════════════════════════════════════════════════════════
        const haveRaw = (label in currentMap) ? currentMap[label] : null;
        const needNum = Number(attr.value);
        const haveUnit = (label in currentMap)
          ? String((function () {
            for (const it of (detail.roleAttributeList || [])) {
              if (it && String(it.attributeName || '').trim() === label) {
                return String(it.attributeValue || '');
              }
            }
            return '';
          })())
          : '';

        //: ⚠ 面板里没这个属性 → 显示「—」，**不标红**（不是"不达标"）
        const missing = (haveRaw === null) || !isFinite(needNum);

        //: 自己算达标（照旧界面 ``_meets``：≥ / ≤ / = 三种符号）
        let okFlag = true;
        if (!missing) {
          if (symbol === '≤') okFlag = haveRaw <= needNum;
          else if (symbol === '=') okFlag = Math.abs(haveRaw - needNum) < 1e-9;
          else okFlag = haveRaw >= needNum;
        }

        //: 当前值显示：优先用原始字符串（带 % 单位），否则用数值
        const cur = missing ? '—' : haveUnit;

        //: 差值文案（旧界面 ``_gap_label``）—— 「（差 33.7%）」
        let gap = '';
        if (!missing && !okFlag) {
          const diff = needNum - haveRaw;
          if (diff > 0) {
            const unit = String(wantRaw).indexOf('%') >= 0 ? '%' : '';
            gap = '（差 ' + (Math.round(diff * 10) / 10) + unit + '）';
          }
        }
        body.appendChild(P.el('div', {
          class: 'build-std-row' +
            (missing ? ' is-missing' : (okFlag ? ' is-ok' : ' is-bad'))
        }, [
          P.el('span', { class: 'build-std-name', text: label }),
          P.el('span', { class: 'build-std-cur', text: cur }),
          P.el('span', {
            class: 'build-std-want',
            text: symbol + wantRaw + ' ' + gap
          }),
          P.el('span', {
            class: 'build-std-mark',
            //: 缺属性用灰色「—」，不误导成"没达标"
            text: missing ? '—' : (okFlag ? '✓' : '✗')
          })
        ]));
      }
      host.appendChild(sec.card);
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ③ ✦ 共鸣者属性（旧界面 L1358-1363 ``_prop_grid(cols=2)``）
    // ══════════════════════════════════════════════════════════════════════
    const attrs = Array.isArray(detail.roleAttributeList)
      ? detail.roleAttributeList : [];
    if (attrs.length) {
      host.appendChild(buildDetailPropGrid('✦ 共鸣者属性', attrs));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ④ ✦ 武器（旧界面 L1365-1370 ``_weapon_block``）
    // ══════════════════════════════════════════════════════════════════════
    const wd = detail.weaponData || {};
    if (wd.weapon && (wd.weapon.weaponName || wd.weapon.name)) {
      host.appendChild(buildDetailWeapon(wd));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ⑤ ✦ 属性展示（旧界面 L1372-1377）—— 声骸提供的加成
    //
    //  ⚠ 字段名是 ``equipPhantomAddPropList``（**不在** phantomData 里，
    //    和 detail 同级）—— 读错位置就永远画不出来。
    // ══════════════════════════════════════════════════════════════════════
    const adds = Array.isArray(detail.equipPhantomAddPropList)
      ? detail.equipPhantomAddPropList : [];
    if (adds.length) {
      host.appendChild(buildDetailPropGrid('✦ 属性展示', adds));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ⑥ ✦ 声骸（旧界面 L1379-1386 ``_echoes_block``）
    // ══════════════════════════════════════════════════════════════════════
    const ph = detail.phantomData || {};
    if (Array.isArray(ph.equipPhantomList) && ph.equipPhantomList.length) {
      host.appendChild(buildDetailEchoes(ph));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ⑦ ✦ 技能（旧界面 L1388-1393 ``_skills_block``）
    // ══════════════════════════════════════════════════════════════════════
    const skills = Array.isArray(detail.skillList) ? detail.skillList : [];
    if (skills.length) {
      host.appendChild(buildDetailSkills(skills));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  ⑧ ✦ 共鸣链（旧界面 L1395-1400 ``_chains_block``）
    // ══════════════════════════════════════════════════════════════════════
    const chains = Array.isArray(detail.chainList) ? detail.chainList : [];
    if (chains.length) {
      host.appendChild(buildDetailChains(chains, role));
    }
  }

  /**
   * 造一个「✦ 标题」区块（旧界面 ``_section``）。
   *
   * @param {string} title
   * @param {Array} children - 初始内容
   * @returns {{card: HTMLElement, contentEl: HTMLElement}}
   */
  function buildDetailSection(title, children) {
    const card = P.el('div', { class: 'build-section' });
    card.appendChild(P.el('div', {
      class: 'build-section-title', text: title
    }));
    const contentEl = P.el('div', { class: 'build-section-body' });
    for (const child of (children || [])) {
      if (child) contentEl.appendChild(child);
    }
    card.appendChild(contentEl);
    return { card: card, contentEl: contentEl };
  }

  /**
   * 两列属性网格（旧界面 ``_prop_grid(cols=2)``）。
   *
   * ## 布局
   *
   * .. code:: text
   *
   *    生命      15335      攻击        1185
   *    防御       1483      暴击        41.3%
   *
   * 用 CSS ``grid-template-columns: repeat(2, 1fr)``，每格内部
   * 「图标 + 名字 …… 数值」（``justify-content: space-between``）。
   */
  function buildDetailPropGrid(title, items) {
    const rows = [];
    for (const item of items) {
      if (!item || typeof item !== 'object') continue;
      const nm = String(item.attributeName || item.name || '');
      if (!nm) continue;
      const val = item.attributeValue != null
        ? String(item.attributeValue) : '';
      const iconUrl = String(item.iconUrl || '');
      rows.push(P.el('div', { class: 'build-prop-cell' }, [
        (function () {
          const icon = P.el('span', { class: 'build-prop-icon' });
          if (iconUrl) {
            const img = P.el('img', { src: iconUrl, alt: '' });
            //: 图标挂了一律隐藏（不留破图）—— 官方 CDN 有时会拒
            img.addEventListener('error', function () {
              icon.style.display = 'none';
            }, { once: true });
            icon.appendChild(img);
          } else {
            icon.style.display = 'none';
          }
          return icon;
        })(),
        P.el('span', { class: 'build-prop-name', text: nm }),
        P.el('span', { class: 'build-prop-value', text: val })
      ]));
    }
    if (!rows.length) return buildDetailSection(title, []).card;
    const grid = P.el('div', { class: 'build-prop-grid' });
    for (const row of rows) grid.appendChild(row);
    return buildDetailSection(title, [grid]).card;
  }

  /** ④ ✦ 武器（旧界面 ``_weapon_block`` L665-694）*/
  function buildDetailWeapon(wd) {
    const weapon = wd.weapon || {};
    const box = P.el('div', { class: 'build-weapon' });

    //: 左侧立绘 / 图标
    const iconWrap = P.el('div', { class: 'build-weapon-icon' });
    const iconUrl = String(weapon.weaponIcon || '');
    if (iconUrl) {
      const img = P.el('img', { src: iconUrl, alt: '' });
      img.addEventListener('error', function () {
        iconWrap.style.display = 'none';
      }, { once: true });
      iconWrap.appendChild(img);
    } else {
      iconWrap.style.display = 'none';
    }
    box.appendChild(iconWrap);

    //: 右侧信息
    const info = P.el('div', { class: 'build-weapon-info' });
    info.appendChild(P.el('div', {
      class: 'build-weapon-name',
      text: String(weapon.weaponName || weapon.name || '')
    }));
    const bits = [];
    if (wd.level != null) bits.push('Lv.' + wd.level);
    if (wd.resonLevel != null) bits.push('谐振' + wd.resonLevel + '阶');
    if (weapon.weaponStarLevel != null) {
      bits.push('★' + weapon.weaponStarLevel);
    }
    if (bits.length) {
      info.appendChild(P.el('div', {
        class: 'build-weapon-sub', text: bits.join('　')
      }));
    }
    //: 主属性（旧界面 ``mainPropList``）
    const mains = Array.isArray(wd.mainPropList) ? wd.mainPropList : [];
    if (mains.length) {
      const mrow = P.el('div', { class: 'build-weapon-props' });
      for (const mp of mains) {
        if (!mp || typeof mp !== 'object') continue;
        mrow.appendChild(P.el('div', { class: 'build-weapon-prop' }, [
          P.el('span', {
            class: 'build-prop-name',
            text: String(mp.attributeName || '')
          }),
          P.el('span', {
            class: 'build-prop-value',
            text: String(mp.attributeValue != null ? mp.attributeValue : '')
          })
        ]));
      }
      info.appendChild(mrow);
    }
    box.appendChild(info);

    //: 武器特效说明（``effectDescription``）—— 旧界面折叠区里，这里直接给
    if (weapon.weaponEffectName || weapon.effectDescription) {
      box.appendChild(P.el('div', { class: 'build-weapon-effect' }, [
        P.el('div', {
          class: 'build-weapon-effect-name',
          text: String(weapon.weaponEffectName || '')
        }),
        P.el('div', {
          class: 'build-weapon-effect-desc',
          text: String(weapon.effectDescription || '')
        })
      ]));
    }
    return buildDetailSection('✦ 武器', [box]).card;
  }

  /**
   * ⑥ ✦ 声骸（旧界面 ``_echoes_block`` L624-664）
   *
   * 结构：
   *   * 顶部：套装统计「推荐辅音词条命中 11」+ 词条计数（旧界面那个
   *     大圆圈数字）
   *   * 每个声骸一张小卡：图标 + 名字 + COST + 等级 + 套装名
   *     + 主属性（金）+ 副词条（白）
   */
  function buildDetailEchoes(ph) {
    const list = Array.isArray(ph.equipPhantomList) ? ph.equipPhantomList : [];
    const wrap = P.el('div', { class: 'build-echoes' });

    //: 套装统计（旧界面 ``_echoes_block`` 开头的 fetter 汇总）
    const setCount = {};
    for (const item of list) {
      const fd = (item && item.fetterDetail) || {};
      const nm = String(fd.name || '');
      if (nm) setCount[nm] = (setCount[nm] || 0) + 1;
    }
    const setNames = Object.keys(setCount);
    if (setNames.length) {
      wrap.appendChild(P.el('div', { class: 'build-echo-sets' }, [
        P.el('span', { class: 'build-echo-sets-label', text: '套装' }),
        P.el('span', {
          class: 'build-echo-sets-value',
          text: setNames.map(function (n) {
            return n + ' ×' + setCount[n];
          }).join(' + ')
        })
      ]));
    }

    const grid = P.el('div', { class: 'build-echo-grid' });
    for (const item of list) {
      if (!item || typeof item !== 'object') continue;
      const prop = item.phantomProp || {};
      const fd = item.fetterDetail || {};
      const card = P.el('div', { class: 'build-echo-card' });

      //: 图标 + 名字 + COST/等级
      const head = P.el('div', { class: 'build-echo-head' });
      const iconWrap = P.el('div', { class: 'build-echo-icon' });
      const iconUrl = String(prop.iconUrl || '');
      if (iconUrl) {
        const img = P.el('img', { src: iconUrl, alt: '' });
        img.addEventListener('error', function () {
          iconWrap.textContent = '?';
        }, { once: true });
        iconWrap.appendChild(img);
      } else {
        iconWrap.textContent = '?';
      }
      head.appendChild(iconWrap);

      const headText = P.el('div', { class: 'build-echo-headtext' });
      headText.appendChild(P.el('div', {
        class: 'build-echo-name',
        text: String(prop.name || '')
      }));
      const sub = [];
      if (prop.cost != null) sub.push('COST ' + prop.cost);
      if (item.level != null) sub.push('+' + item.level);
      if (fd.name) sub.push('[' + fd.name + ']');
      if (sub.length) {
        headText.appendChild(P.el('div', {
          class: 'build-echo-sub', text: sub.join('　')
        }));
      }
      head.appendChild(headText);
      card.appendChild(head);

      //: 主属性（金色，旧界面 ``mainProps``）
      const mains = Array.isArray(item.mainProps) ? item.mainProps : [];
      if (mains.length) {
        const body = P.el('div', { class: 'build-echo-props' });
        for (const mp of mains) {
          if (!mp || typeof mp !== 'object') continue;
          body.appendChild(P.el('div', { class: 'build-echo-prop is-main' }, [
            P.el('span', {
              class: 'build-prop-name',
              text: String(mp.attributeName || '')
            }),
            P.el('span', {
              class: 'build-prop-value',
              text: String(mp.attributeValue != null ? mp.attributeValue : '')
            })
          ]));
        }
        card.appendChild(body);
      }
      //: 副词条（``subProps``；``valid: true`` 的标色 —— 旧界面也这么区分）
      const subs = Array.isArray(item.subProps) ? item.subProps : [];
      if (subs.length) {
        const body = P.el('div', { class: 'build-echo-props' });
        for (const sp of subs) {
          if (!sp || typeof sp !== 'object') continue;
          body.appendChild(P.el('div', {
            class: 'build-echo-prop' + (sp.valid ? ' is-valid' : '')
          }, [
            P.el('span', {
              class: 'build-prop-name',
              text: String(sp.attributeName || '')
            }),
            P.el('span', {
              class: 'build-prop-value',
              text: String(sp.attributeValue != null ? sp.attributeValue : '')
            })
          ]));
        }
        card.appendChild(body);
      }
      grid.appendChild(card);
    }
    wrap.appendChild(grid);
    return buildDetailSection(
      '✦ 声骸　COST ' + (ph.cost != null ? ph.cost : '?') + '/12',
      [wrap]
    ).card;
  }

  /**
   * ⑦ ✦ 技能（旧界面 ``_skills_block`` L960-1029）
   *
   * 一行 7 个：图标 + 名字 + 等级（``Lv.x/10``）。
   * 旧界面用 ``skill.iconUrl`` 画图标，没有就用占位。
   */
  /**
   * ★ 造一块**共用**的说明面板（旧界面 ``_expand_panel`` L743-792）。
   *
   * ## 交互要求（用户原话，``detail_view.py`` L746-750）
   *
   * > 这里点到哪个技能，展示哪个，占满整个红框，
   * > 再次点击该技能就是关闭展开
   * > 共鸣链这里也是跟上面一样
   *
   * → **不是每条一个框**，而是**共用一块**：点谁就把内容换上去；
   *   再点同一个就关掉（互斥展开）。
   *
   * @returns {{panel: HTMLElement, titleEl: HTMLElement,
   *            bodyEl: HTMLElement, set: Function, hide: Function}}
   */
  function buildExpandPanel() {
    const panel = P.el('div', { class: 'build-expand-panel' });
    panel.hidden = true;
    panel.classList.add('hidden');

    const titleEl = P.el('div', { class: 'build-expand-title' });
    const bodyEl = P.el('div', { class: 'build-expand-body' });
    panel.appendChild(titleEl);
    panel.appendChild(bodyEl);

    const api = {
      panel: panel,
      titleEl: titleEl,
      bodyEl: bodyEl,
      //: 当前展开的是哪一条（用来做「再点一次关闭」）
      currentKey: '',
      set: function (key, title, text) {
        api.currentKey = key;
        titleEl.textContent = String(title || '');
        bodyEl.textContent = String(text || '');
        panel.hidden = false;
        panel.classList.remove('hidden');
      },
      hide: function () {
        api.currentKey = '';
        panel.hidden = true;
        panel.classList.add('hidden');
      }
    };
    return api;
  }

  /**
   * ★ 把「点图标 → 在共用面板里展开/收起」接上（旧界面 ``_bind_exclusive``）。
   *
   * 互斥语义：
   *   * 点 A   → 面板显示 A
   *   * 点 B   → 面板换成 B
   *   * 再点 B → 面板关闭（``currentKey === key`` 就 hide）
   *
   * @param {HTMLElement} clickable - 可点的元素（图标 / 整格）
   * @param {object} expand - ``buildExpandPanel()`` 的返回值
   * @param {string} key - 这一条的唯一标识
   * @param {string} title - 面板标题
   * @param {string} text - 面板正文
   */
  function bindExclusiveExpand(clickable, expand, key, title, text) {
    if (!clickable || !expand) return;
    if (!String(text || '').trim()) return;   //: 没说明就不给点（不制造空面板）
    clickable.classList.add('is-clickable');
    clickable.setAttribute('role', 'button');
    clickable.setAttribute('tabindex', '0');
    clickable.title = '点击展开说明';

    const toggle = function () {
      if (expand.currentKey === key) {
        expand.hide();
        clickable.classList.remove('is-active');
        return;
      }
      //: 互斥：先把别的格子取消高亮
      const host = clickable.ownerDocument;
      if (host) {
        for (const el of host.querySelectorAll('.build-skill.is-active,'
          + ' .build-chain-node.is-active')) {
          el.classList.remove('is-active');
        }
      }
      clickable.classList.add('is-active');
      expand.set(key, title, text);
    };

    clickable.addEventListener('click', toggle);
    //: 键盘可达（无障碍；也方便自动化测试）
    clickable.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        toggle();
      }
    });
  }

  /**
   * ⑦ ✦ 技能（旧界面 ``_skills_block`` L960-1027）
   *
   * ==========  ========================================================
   * 元素         说明
   * ==========  ========================================================
   * 图标行       一排 7 个：图标 + 名字 + ``Lv.x/10``
   * 共用面板     点图标 → 在**下面**展开该技能的说明；再点同一格 → 收起
   * ==========  ========================================================
   *
   * ⚠ 标题格式照旧界面 ``f"{name}（{type}）"`` ——
   *   例「砰砰（常态攻击）」。
   */
  function buildDetailSkills(skills) {
    const wrap = P.el('div', { class: 'build-skills' });
    const row = P.el('div', { class: 'build-skill-row' });

    //: ★ 共用面板 —— 必须在图标行**之后**插进 DOM（下面展开）
    const expand = buildExpandPanel();

    let idx = 0;
    for (const item of skills) {
      if (!item || typeof item !== 'object') continue;
      const skill = item.skill || {};
      const nm = String(skill.name || skill.skillName || '');
      if (!nm) continue;
      idx += 1;

      const type = String(skill.type || '');
      const desc = String(skill.description || '').trim();
      const title = type ? (nm + '（' + type + '）') : nm;

      const cell = P.el('div', { class: 'build-skill' });
      const iconWrap = P.el('div', { class: 'build-skill-icon' });
      const iconUrl = String(skill.iconUrl || '');
      if (iconUrl) {
        const img = P.el('img', { src: iconUrl, alt: '' });
        img.addEventListener('error', function () {
          iconWrap.textContent = '✦';
        }, { once: true });
        iconWrap.appendChild(img);
      } else {
        iconWrap.textContent = '✦';
      }
      cell.appendChild(iconWrap);
      cell.appendChild(P.el('div', {
        class: 'build-skill-name', text: nm
      }));
      if (item.level != null) {
        cell.appendChild(P.el('div', {
          class: 'build-skill-level',
          text: 'Lv.' + item.level + '/10'
        }));
      }
      //: 点整格（图标更好点）→ 展开说明
      bindExclusiveExpand(cell, expand, 'skill-' + idx, title, desc);
      row.appendChild(cell);
    }

    wrap.appendChild(row);
    wrap.appendChild(expand.panel);
    return buildDetailSection('✦ 技能', [wrap]).card;
  }

  /**
   * ⑧ ✦ 共鸣链（旧界面 ``_chains_block`` L1054-1135）
   *
   * ## 交互和技能**完全一样**（用户：「共鸣链这里也是跟上面一样」）
   *
   * 一排图标（解锁的亮 / 没解的压暗），点一个 → 下面共用面板展开说明，
   * 再点同一个 → 收起。
   *
   * ⚠ 旧界面用 ``_dim()`` 把未解锁的压暗（**不能用 CSS ``opacity``**，
   *   那个在 QLabel 上无效）。网页里 ``opacity`` 正常，所以直接 CSS。
   */
  function buildDetailChains(chains, role) {
    const wrap = P.el('div', { class: 'build-chains' });
    const row = P.el('div', { class: 'build-chain-row' });
    const expand = buildExpandPanel();

    const unlockedNum = role && role.chainUnlockNum != null
      ? Number(role.chainUnlockNum) : -1;
    let idx = 0;
    for (const item of chains) {
      if (!item || typeof item !== 'object') continue;
      idx += 1;
      //: 判定解锁：优先用 ``unlocked`` 字段，退回 ``order <= chainUnlockNum``
      const order = item.order != null ? Number(item.order) : idx;
      const unlocked = (item.unlocked != null)
        ? !!item.unlocked
        : (unlockedNum >= 0 && order <= unlockedNum);

      const nm = String(item.name || '');
      const desc = String(item.description || '').trim();
      //: ★★★ 2026-11-03 用户圈图：「这里有没有激活该共鸣链，要打个括号说明」
      //:
      //: 问题：面板标题只写「共鸣链 1　穿行于荒芜长廊」，
      //: **看不出这条到底解锁没有** —— 用户可能以为已经生效了。
      //:
      //: 现在标题末尾加状态括号，和官方库街区一致：
      //:
      //: .. code:: text
      //:
      //:     共鸣链 1　穿行于荒芜长廊（已激活）
      //:     共鸣链 4　xxx（未激活）
      //:
      //: ⚠ 标题里也要带，不只是靠图标的明暗 ——
      //:   用户是**点开面板看说明**的，那一眼必须能判断有没有生效。
      const stateText = unlocked ? '（已激活）' : '（未激活）';
      const title = (nm ? ('共鸣链 ' + order + '　' + nm) : ('共鸣链 ' + order))
        + stateText;

      const cell = P.el('div', {
        class: 'build-chain-node'
          + (unlocked ? ' is-unlocked' : ' is-locked')
      });
      const iconUrl = String(item.iconUrl || item.icon || '');
      if (iconUrl) {
        const img = P.el('img', { src: iconUrl, alt: '' });
        img.addEventListener('error', function () {
          cell.textContent = String(order);
        }, { once: true });
        cell.appendChild(img);
      } else {
        cell.textContent = String(order);
      }
      //: 未解锁的也**可以看说明**（用户可能想知道后面解锁什么）
      bindExclusiveExpand(cell, expand, 'chain-' + idx, title, desc);
      row.appendChild(cell);
    }

    wrap.appendChild(row);
    wrap.appendChild(expand.panel);
    return buildDetailSection('✦ 共鸣链', [wrap]).card;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  ⑤ 抽卡记录分析  gacha   （**照抄旧界面 12 块**）
  //
  //  ## ⚠ P6 重写：用户「我的抽卡分析记录呢」
  //
  //  P5 我只做了「粘贴链接 + 状态条 + 日志区」—— 旧界面根本不是这样。
  //
  //  旧界面 ``gacha/tool.py`` L606-771 ``_build`` 的顺序：
  //
  //  .. code:: text
  //
  //    L606  TitleLabel("抽卡记录分析")
  //    L608  note          "点「获取抽卡记录」自动读取本机游戏记录的链接…"
  //    L620  howto         "怎么获取：① … ② … ⚠ 链接有时效…"
  //    L636  link_row      [获取抽卡记录] [链接输入框] [分析]   ← 按钮在**左**
  //    L659  status        "显示的是本地累计的 N 抽（…）（N 条记录）…"
  //    L665  overview_card 欧皇卡：6 个大数字（两排）
  //    L698  summary_title "抽卡总结"
  //    L700  summary_note  "共获得限定五星 4 个，常驻五星 5 个。（常驻：…）"
  //    L704  cards_host    角色头像网格（带 ×N 角标）
  //    L717  pools_title   "分卡池记录"
  //    L727  pool_tabs_host [角色活动唤取][武器活动唤取][角色常驻唤取][武器常驻唤取]
  //    L740  pools_host    当前选中卡池的详情
  //    L750  history_row   "历史记录"          [清空历史]
  //    L763  history_host  历史卡片列表
  //
  //  ## 欧皇卡的 6 个数字（``_BigStat``）
  //
  //  第一排：总抽卡数 / 平均出金
  //  第二排：小保底不歪 / 五星数 / 每UP角色需 / 每UP武器需
  //
  //  ⚠ 旧界面注释（L634-635）：
  //    「这里**不能写 Markdown 星号** —— Qt 的 QLabel 不解析 markdown」
  //  所以文案里没有 `**`，我也不加。
  // ════════════════════════════════════════════════════════════════════════

  const GACHA_STATE = {
    linkInput: null,
    grabBtn: null,
    fetchBtn: null,
    statusEl: null,
    overviewHost: null,
    summaryNote: null,
    cardsHost: null,
    poolTabsHost: null,
    poolsHost: null,
    historyHost: null,
    data: null,
    //: 卡池汇总（``getGachaOverview().pools``）+ 逐条五星（``getGachaPoolDetail``）
    //: 按 poolType 合并成同一个对象，渲染时一次取
    pools: {},
    selectedPool: '',
    history: [],
    //: ★ 2026-11-05：``gachaLinkGrabbed`` 只订一次（重复订阅会让
    //: 同一个事件触发多次回调、输入框被连续写几次）
    grabBound: false
  };

  registerPanel('gacha', function renderGacha(container, app, meta) {
    // ══════════════════════════════════════════════════════════════════════
    //  标题 + 两段说明（旧界面 L606-631，逐字照抄）
    // ══════════════════════════════════════════════════════════════════════
    container.appendChild(P.el('div', {
      class: 'gk-title', text: '抽卡记录分析'
    }));
    container.appendChild(P.el('div', {
      class: 'gk-note',
      text: '点「获取抽卡记录」自动读取本机游戏记录的链接，也可以自己粘贴。\n' +
        '拿到链接后发给库洛官方接口做分析（需要联网）。'
    }));
    container.appendChild(P.el('div', {
      class: 'gk-howto',
      text: '怎么获取：\n' +
        '① 点下面「获取抽卡记录」—— 自动从本机游戏日志里读出链接并填好；\n' +
        '② 如果没读到，就手动取：游戏里　唤取 → 唤取记录 → ' +
        '打开页面后多翻几页 → 复制页面链接 → 粘到输入框。\n' +
        '⚠ 链接有时效：取完尽快粘过来；放久了会提示「请求游戏获取日志异常」，' +
        '那时回游戏重新打开一次唤取记录页再复制即可。'
    }));

    // ══════════════════════════════════════════════════════════════════════
    //  取链接行：[获取抽卡记录] [输入框] [分析]   ← 按钮在**左**（L636-657）
    // ══════════════════════════════════════════════════════════════════════
    const linkRow = P.el('div', { class: 'gk-link-row' });
    GACHA_STATE.grabBtn = P.button('获取抽卡记录', {
      kind: 'primary',
      title: '从本机游戏的日志里读出抽卡记录链接（需要先在本机登录过游戏）',
      onClick: function () { gachaGrab(); }
    });
    //: ★ 2026-11-05：给按钮一个稳定的选择器 —— 验证脚本 / 探针要能点到它。
    //: 按文案找太脆（改了措辞就断），按 ``data-action`` 找才稳。
    GACHA_STATE.grabBtn.dataset.action = 'grab';
    linkRow.appendChild(GACHA_STATE.grabBtn);

    GACHA_STATE.linkInput = P.el('input', {
      class: 'input gk-link-input',
      type: 'text',
      placeholder: '抽卡记录链接（点左边按钮自动获取，也可手动粘贴）'
    });
    linkRow.appendChild(GACHA_STATE.linkInput);

    GACHA_STATE.fetchBtn = P.button('分析', {
      title: '把链接发给库洛官方接口分析',
      onClick: function () { gachaAnalyze(); }
    });
    linkRow.appendChild(GACHA_STATE.fetchBtn);
    container.appendChild(linkRow);

    //: 状态行（旧界面 L659-662）
    GACHA_STATE.statusEl = P.el('div', { class: 'gk-status' });
    container.appendChild(GACHA_STATE.statusEl);

    // ══════════════════════════════════════════════════════════════════════
    //  欧皇卡（旧界面 L665-695）—— 6 个大数字
    // ══════════════════════════════════════════════════════════════════════
    const overview = P.el('div', { class: 'gk-overview card-glass' });
    GACHA_STATE.overviewHost = overview;
    container.appendChild(overview);
    gachaRenderOverview(null);

    // ══════════════════════════════════════════════════════════════════════
    //  抽卡总结（L698-703）+ 头像网格（L704-714）
    // ══════════════════════════════════════════════════════════════════════
    container.appendChild(P.el('div', {
      class: 'gk-section-title', text: '抽卡总结'
    }));
    GACHA_STATE.summaryNote = P.el('div', { class: 'gk-note' });
    container.appendChild(GACHA_STATE.summaryNote);
    GACHA_STATE.cardsHost = P.el('div', { class: 'gk-cards' });
    container.appendChild(GACHA_STATE.cardsHost);

    // ══════════════════════════════════════════════════════════════════════
    //  分卡池记录（L717-744）
    // ══════════════════════════════════════════════════════════════════════
    container.appendChild(P.el('div', {
      class: 'gk-section-title', text: '分卡池记录'
    }));
    GACHA_STATE.poolTabsHost = P.el('div', { class: 'gk-pool-tabs' });
    container.appendChild(GACHA_STATE.poolTabsHost);
    GACHA_STATE.poolsHost = P.el('div', { class: 'gk-pools' });
    container.appendChild(GACHA_STATE.poolsHost);

    // ══════════════════════════════════════════════════════════════════════
    //  历史记录（L746-767）
    // ══════════════════════════════════════════════════════════════════════
    const histRow = P.el('div', { class: 'gk-history-head' });
    histRow.appendChild(P.el('div', {
      class: 'gk-section-title', style: 'margin:0', text: '历史记录'
    }));
    histRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    histRow.appendChild(P.button('清空历史', {
      size: 'sm',
      title: '删掉本地累积的全部抽卡记录（不可撤销）',
      onClick: function (ev) { gachaClearHistory(ev.target); }
    }));
    container.appendChild(histRow);
    GACHA_STATE.historyHost = P.el('div', { class: 'gk-history' });
    container.appendChild(GACHA_STATE.historyHost);

    //: ★ 打开页面就把**已累积的历史**显示出来（旧界面 L772-777 的教训：
    //: 原来只有点「分析」成功才渲染，一旦链接过期界面就一直是空的）
    gachaLoadHistory();
    //: ★ 欧皇卡 / 抽卡总结 / 头像墙 / 分卡池 —— 后端起就渲染（不依赖点「分析」）
    gachaLoadOverview();
    //: ★ 2026-11-05：``gachaAnalyzed`` 必须**建面板时就订阅**。
    //:
    //: 原来只在 ``gachaAnalyze()`` 末尾（点完「分析」、后端已受理之后）
    //: 才 ``gachaBindAnalyzed()`` —— 于是这些场景事件全丢：
    //:   * 点了分析、又在结果回来前切走页面再切回来（面板重建 →
    //:     监听器随旧 DOM 一起没了）；
    //:   * 用户在旧界面/Qt 版点了分析，Web 页面这边想跟着更新；
    //:   * 探针从 Python 侧 emit（模拟后端推送）时页面根本没订阅。
    //: 事件监听和"谁会触发它"无关，订阅应该跟面板生命周期绑定。
    gachaBindAnalyzed();
    void app; void meta;
  });

  // ── 欧皇卡（6 个大数字）───────────────────────────────────────────────
  //
  //  ## 字段来自后端 ``getGachaOverview()``（web-shell-dev 2026-11-02）
  //
  //  .. code:: jsonc
  //
  //    {"total": 1131, "avgFive": 47.1, "noLoseRate": 66.7, "five": 24,
  //     "perChar": 71.8, "perWeapon": 63.3, "rank": "欧皇"}
  //
  //  ## ⚠ 三个格式化细节，照抄旧界面
  //
  //  ==============  ==========================  ==========================
  //  字段            旧界面显示                   Web 侧
  //  ==============  ==========================  ==========================
  //  ``avgFive``     ``f"{average:.0f}"`` → ``47`` ``toFixed(0)``
  //  ``noLoseRate``  ``f"{not_up:.1f}%"`` → ``66.7%`` ``toFixed(1) + '%'``
  //  ``perChar``     ``f"{x:.1f}"`` → ``71.8``   ``toFixed(1)``
  //  ==============  ==========================  ==========================
  //
  //  ## ⚠⚠ ``null`` 必须显示成 ``—``，**不能显示 0**
  //
  //  ``noLoseRate`` / ``perChar`` / ``perWeapon`` / ``avgFive`` 在
  //  「没抽过限定池 / 没出过五星」时是 **``null`` 而不是 0**。
  //  旧界面那时候显示 ``—``。
  //  **``0`` 会被用户误读成「每次都歪」—— 这是语义错误，不是显示问题。**
  function gachaRenderOverview(data) {
    const host = GACHA_STATE.overviewHost;
    if (!host) return;
    P.fill(host, null);

    //: 左上角评价（旧界面 ``luck_label``，例如「欧皇」）
    host.appendChild(P.el('div', {
      class: 'gk-luck',
      text: (data && data.rank) ? String(data.rank) : '—'
    }));

    //: 第一排：总抽卡数 / 平均出金
    const row1 = P.el('div', { class: 'gk-stat-row' });
    row1.appendChild(gachaBigStat(
      data && data.total != null ? String(data.total) : null, '总抽卡数'));
    row1.appendChild(gachaBigStat(
      gachaFixed(data && data.avgFive, 0), '平均出金'));
    host.appendChild(row1);

    //: 第二排：小保底不歪 / 五星数 / 每UP角色需 / 每UP武器需
    const row2 = P.el('div', { class: 'gk-stat-row' });
    row2.appendChild(gachaBigStat(
      gachaFixed(data && data.noLoseRate, 1, '%'), '小保底不歪'));
    row2.appendChild(gachaBigStat(
      data && data.five != null ? String(data.five) : null, '五星数'));
    row2.appendChild(gachaBigStat(
      gachaFixed(data && data.perChar, 1), '每UP角色需'));
    row2.appendChild(gachaBigStat(
      gachaFixed(data && data.perWeapon, 1), '每UP武器需'));
    host.appendChild(row2);
  }

  /**
   * 数字格式化 —— ``null`` / ``undefined`` → 返回 ``null``（由 ``gachaBigStat`` 画 ``—``）。
   *
   * @param {*} value - 后端给的值（可能是 null）
   * @param {number} digits - 小数位（0 = 整数，1 = 一位小数）
   * @param {string} [suffix] - 后缀（如 ``%``）
   * @returns {string|null}
   */
  function gachaFixed(value, digits, suffix) {
    if (value == null || value === '') return null;
    const n = Number(value);
    if (!isFinite(n)) return null;
    return n.toFixed(digits) + (suffix || '');
  }

  /**
   * 一个大数字（旧界面 ``_BigStat``：值在上、标签在下）。
   *
   * @param {string|null} text - 已经格式化好的文字；``null`` 画成 ``—``
   * @param {string} label
   */
  function gachaBigStat(text, label) {
    const box = P.el('div', { class: 'gk-big-stat' });
    box.appendChild(P.el('div', {
      class: 'gk-big-value',
      text: text == null ? '—' : String(text)
    }));
    box.appendChild(P.el('div', { class: 'gk-big-label', text: label }));
    return box;
  }

  /** 拉欧皇卡数据（挂到面板初始化 + 分析成功后）*/
  async function gachaLoadOverview() {
    //: ⚠ ``@Slot(str, result=str)`` —— **必须传一个字符串**，
    //: 不传会静默返回 ``[]``（QWebChannel 的坑：参数个数不匹配不报错）。
    //: 空串 = 用默认 playerId（后端 ``player_id: str = ""``）。
    const result = await P.call('getGachaOverview', '');
    if (!result.ok) {
      //: 接口没就绪 → 画出 6 个「—」的骨架（不是空白）
      gachaRenderOverview(null);
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      gachaRenderOverview(null);
      return;
    }
    GACHA_STATE.overview = data;
    gachaRenderOverview(data);

    //: 抽卡总结（旧界面 ``summary_note``）
    if (GACHA_STATE.summaryNote && data.summary) {
      GACHA_STATE.summaryNote.textContent =
        String(data.summary.note || '');
    }

    //: 五星头像墙（带 ×N 角标）
    if (GACHA_STATE.cardsHost) {
      P.fill(GACHA_STATE.cardsHost, null);
      const cards = Array.isArray(data.cards) ? data.cards : [];
      for (const item of cards) {
        GACHA_STATE.cardsHost.appendChild(gachaAvatarCard(item));
      }
      if (!cards.length) {
        GACHA_STATE.cardsHost.appendChild(P.el('div', {
          class: 'gk-note', text: '还没有五星记录。'
        }));
      }
    }

    //: 分卡池（``pools[].{name, pulls, five, rate, pity, rank}``）
    if (Array.isArray(data.pools) && data.pools.length) {
      //: 先记下汇总（逐条五星由 ``gachaLoadPoolDetail`` 补进来）
      for (const p of data.pools) {
        const key = String(p.poolType || p.name || '');
        if (key) GACHA_STATE.pools[key] = p;
      }
      gachaRenderPools(data.pools);
    }

    //: ★ 再拉逐条五星（接口可能还没就绪 —— 那样只有汇总，不崩）
    await gachaLoadPoolDetail();
  }

  /**
   * 拉 4 个卡池的**逐条五星记录**（``getGachaPoolDetail()``）。
   *
   * ## 后端已经算好了三样东西，**直接用，不要自己实现阈值**
   *
   * .. code:: jsonc
   *
   *   {"name":"心", "span":50, "cumulative":50,
   *    "barColor":"#7fae72",     // ← 条色（5 档，按 span）
   *    "verdict":"欧",           // ← 评价（"歪"/"欧"/"非"/""）
   *    "verdictColor":"#2e8b57"} // ← 评价色
   *
   * ## ⚠ 颜色和评价是**两套独立阈值**
   *
   * 实测反例：``安可 span=24 isLost=true``
   * → ``barColor`` 绿（按 span 分档）、``verdict`` 歪（按 isLost）。
   *
   * 抽数少就是绿条，但歪了照样标「歪」—— **不能写成一个 if-else 链**。
   *
   * ## ⚠ ``span`` 不是 ``cumulative``
   *
   * 实测：``心 span=25 cumulative=49`` —— 用了 25 抽出金，
   * 但距上次 UP 已经 49 抽（上次歪了）。条长看 ``span``。
   */
  async function gachaLoadPoolDetail() {
    //: ⚠ ``@Slot(str, result=str)`` —— 必须传**字符串**（不传会静默返回 ``[]``）。
    //: 空串 = 用默认 playerId。
    const result = await P.call('getGachaPoolDetail', '');
    if (!result.ok) {
      //: ★ 不静默 —— 汇总还在，但要让用户知道「逐条记录」没加载出来
      if (GACHA_STATE.poolsHost) {
        const host = GACHA_STATE.poolsHost;
        const note = P.el('div', {
          class: 'gk-note',
          text: '逐条出金记录接口（getGachaPoolDetail）未就绪 —— ' +
            '上面只有汇总数字。'
        });
        host.appendChild(note);
      }
      return;
    }
    const data = result.data || {};
    if (data.ok === false) return;

    //: ⚠ Slot 不存在时返回 ``{ok:true, data:{}}``（不是失败）——
    //: 只判 ``data.ok !== false`` 会拿到空对象然后渲染出空列表
    const pools = Array.isArray(data.pools) ? data.pools : null;
    if (!pools) return;

    //: 按 poolType 把 ``fives`` 合并进已有的汇总对象
    for (const detail of pools) {
      const key = String(detail.poolType || detail.name || '');
      if (!key) continue;
      const existing = GACHA_STATE.pools[key] || {};
      GACHA_STATE.pools[key] = Object.assign({}, existing, {
        //: 汇总字段以 detail 为准（它也有 pulls/five/rate/pity/rank）
        pulls: detail.pulls != null ? detail.pulls : existing.pulls,
        five: detail.five != null ? detail.five : existing.five,
        rate: detail.rate != null ? detail.rate : existing.rate,
        pity: detail.pity != null ? detail.pity : existing.pity,
        rank: detail.rank || existing.rank,
        name: detail.name || existing.name,
        sixesUnused: undefined,
        fives: Array.isArray(detail.fives) ? detail.fives : []
      });
    }
    //: 重渲染当前选中的池
    gachaRenderSelectedPool();
  }

  // ── 取链接 / 分析 ─────────────────────────────────────────────────────
  async function gachaGrab() {
    if (GACHA_STATE.grabBtn) GACHA_STATE.grabBtn.disabled = true;
    if (GACHA_STATE.statusEl) {
      GACHA_STATE.statusEl.textContent = '正在从本机游戏日志里读取链接…';
    }
    //: ★ 2026-11-05：``grabGachaLink`` 补上了（后端真去读 Client.log，
    //: 主日志没有还会往回翻滚动备份 —— 游戏重启一次就把记录滚走了）。
    //: 它是**异步**的：Slot 立即返回 ``{ok:true}``，结果走 ``gachaLinkGrabbed``
    //: 事件。不能在等返回值的地方填输入框，否则永远是空的。
    gachaBindGrabbed();
    const result = await P.call('grabGachaLink');

    if (!result.ok) {
      if (GACHA_STATE.grabBtn) GACHA_STATE.grabBtn.disabled = false;
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent =
          '读不了游戏日志（接口未就绪）—— 请按上面的②手动复制粘贴链接。';
      }
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      //: 后端忙（上一次还没结束）之类的同步拒绝
      if (GACHA_STATE.grabBtn) GACHA_STATE.grabBtn.disabled = false;
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent = String(
          data.message || '没从本机日志里读到链接 —— 请按上面的②手动复制粘贴。');
      }
    }
    //: 已受理 → 等 ``gachaLinkGrabbed`` 事件（按钮在那里复位）
  }

  /** 订阅「读到链接」事件（只订一次）。*/
  function gachaBindGrabbed() {
    if (GACHA_STATE.grabBound) return;
    GACHA_STATE.grabBound = true;
    window.Bridge.on('gachaLinkGrabbed', function (data) {
      if (!data) return;
      if (GACHA_STATE.grabBtn) GACHA_STATE.grabBtn.disabled = false;
      if (data.ok === false) {
        if (GACHA_STATE.statusEl) {
          GACHA_STATE.statusEl.textContent = String(
            data.message || '没从本机日志里读到链接 —— 请按上面的②手动复制粘贴。');
        }
        return;
      }
      const link = String(data.link || '');
      if (!link) return;
      if (GACHA_STATE.linkInput) GACHA_STATE.linkInput.value = link;
      if (GACHA_STATE.statusEl) {
        //: 链接常来自滚动备份 —— 说清来源，免得用户以为读的是旧数据
        const src = String(data.source || '');
        GACHA_STATE.statusEl.textContent =
          '已读到链接（来源：' + (src || 'Client.log') + '），点「分析」开始。';
      }
    });
  }

  async function gachaAnalyze() {
    const link = ((GACHA_STATE.linkInput && GACHA_STATE.linkInput.value) || '').trim();
    if (!link) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent =
          '请先粘贴抽卡记录链接（或点左边的「获取抽卡记录」）。';
      }
      return;
    }
    if (GACHA_STATE.fetchBtn) GACHA_STATE.fetchBtn.disabled = true;
    if (GACHA_STATE.statusEl) {
      GACHA_STATE.statusEl.textContent = '正在分析（拉取记录中，可能要一会儿）…';
    }

    const result = await P.call('analyzeGacha', link);
    if (GACHA_STATE.fetchBtn) GACHA_STATE.fetchBtn.disabled = false;

    if (!result.ok) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent = '分析失败（接口未就绪）';
      }
      return;
    }
    const data = result.data || {};
    //: ★ 链接错误是**同步返回**的 —— 立刻告诉用户缺哪一项
    if (data.ok === false) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent = String(data.message ||
          data.reason || '分析没能开始');
      }
      return;
    }
    //: 已受理 → 等 ``gachaAnalyzed`` 事件
    gachaBindAnalyzed();
  }

  function gachaBindAnalyzed() {
    if (GACHA_STATE.bound) return;
    GACHA_STATE.bound = true;
    window.Bridge.on('gachaAnalyzed', function (data) {
      if (!data) return;
      if (GACHA_STATE.fetchBtn) GACHA_STATE.fetchBtn.disabled = false;
      if (data.ok === false) {
        if (GACHA_STATE.statusEl) {
          GACHA_STATE.statusEl.textContent = String(data.message || '分析失败');
        }
        return;
      }
      gachaRenderResult(data);
      gachaLoadHistory();
    });
  }

  /** 渲染分析结果（欧皇卡 + 总结 + 头像墙 + 分卡池）*/
  function gachaRenderResult(data) {
    GACHA_STATE.data = data;

    if (GACHA_STATE.statusEl) {
      const pid = String(data.playerId || '');
      const tail = pid.length > 6 ? '…' + pid.slice(-6) : pid;
      const merged = (data.merge && data.merge.added) || 0;
      GACHA_STATE.statusEl.textContent =
        '本次拉到 ' + (data.fetchedTotal != null ? data.fetchedTotal : 0) +
        ' 抽，' +
        '本地累计 ' + (data.total != null ? data.total : 0) + ' 抽' +
        (tail ? '（' + tail + '）' : '') +
        (merged ? '，新增 ' + merged + ' 条记录。' : '。');
    }

    //: ★★★ 2026-11-05 修：这里原来手工拼了一个字段名完全对不上的对象。
    //
    //: ``gachaRenderOverview()`` 读的是 ``getGachaOverview`` 的字段名
    //: （``avgFive``/``noLoseRate``/``five``/``perChar``/``perWeapon``/
    //: ``rank``），而这里传的是分析接口的
    //: （``average``/``notUpRate``/``fiveCount``/…）——
    //: **一个都不认**，所以用户 m15107 看到「有数据但标记处全是 —」。
    //
    //: 现在**不再手工拼**：直接调 ``gachaLoadOverview()`` 重拉一次。
    //: 那一刻 ``GachaStore`` 已经把新记录合并落盘，``getGachaOverview``
    //: 读到的就是最新全量，字段也天然对得上（同一个函数、同一套口径）。
    //: 两套字段各自维护一次就是上一轮踩的坑，别再拆开。
    gachaLoadOverview();

    //: 抽卡总结（旧界面 ``summary_note``）
    if (GACHA_STATE.summaryNote) {
      GACHA_STATE.summaryNote.textContent = String(data.summary || '');
    }

    //: 头像墙 / 分卡池**不在这里画** —— ``gachaLoadOverview()`` 会连
    //: ``cards`` 和 ``pools`` 一起重新渲染（它读的是合并后的全量）。
    //: 原来这里还画了一遍，而且用的是分析接口的 ``fiveStarCards``
    //: （后端实际叫 ``fiveStars``）→ 永远空 → 页面显示
    //: 「这次分析没有五星记录」（用户 m15107 截图里那句），
    //: 然后又被异步回来的 overview 覆盖掉，闪一下。
  }

  /**
   * 一个五星头像卡（旧界面 ``_FiveStarCard``，右上角 ×N 角标）。
   *
   * 后端字段（``getGachaOverview().cards[]``）：
   *   ``{name, count, iconUrl, avatarHue, initial, isLimited}``
   *
   *  ⚠ ``iconUrl`` 是**远程 CDN**（``web-static.kurobbs.com``）——
   *  断网会裂图，所以 ``onerror`` 要回落到首字圆图
   *  （用 ``initial`` + ``avatarHue``，和配置页头像同一套逻辑）。
   */
  function gachaAvatarCard(item) {
    const card = P.el('div', {
      class: 'gk-avatar-card',
      title: (item.name || '') + ' ×' + (item.count || 1) +
        (item.isLimited ? '（限定）' : '')
    });
    const avatar = P.el('div', { class: 'gk-avatar' });

    /** 首字圆图兜底（后端给了 initial / avatarHue 就用）*/
    function useInitial() {
      P.fill(avatar, null);
      const name = String(item.name || '?');
      //: ``initial`` 是后端算好的首字（大多数情况就是 name[0]）
      const letter = String(item.initial || name.slice(0, 1) || '?');
      avatar.textContent = letter;
      const hue = Number(item.avatarHue);
      if (isFinite(hue)) {
        avatar.style.backgroundColor = 'hsl(' + hue + ', 42%, 30%)';
        avatar.style.color = 'rgba(255,255,255,0.92)';
      }
    }

    if (item.iconUrl || item.avatarUrl) {
      const img = P.el('img', {
        src: String(item.iconUrl || item.avatarUrl), alt: '', loading: 'lazy'
      });
      img.addEventListener('error', useInitial, { once: true });
      avatar.appendChild(img);
    } else {
      useInitial();
    }
    card.appendChild(avatar);

    //: ★ 右上角 ×N（只在 >= 2 时显示，旧界面也是这样）
    if (item.count && item.count > 1) {
      card.appendChild(P.el('span', {
        class: 'gk-avatar-count', text: '×' + item.count
      }));
    }
    card.appendChild(P.el('div', {
      class: 'gk-avatar-name', text: String(item.name || '')
    }));
    return card;
  }

  /** 分卡池：[4 个页签] + 当前池详情（旧界面 L727-744）*/
  function gachaRenderPools(pools) {
    //: ⚠ 这里**不能** ``GACHA_STATE.pools = {}`` 重置 ——
    //: ``gachaLoadPoolDetail`` 已经把 ``fives`` 合并进来了，
    //: 清空会把逐条五星记录冲掉（2026-11-02 实测：页签能切但列表永远空）。
    //: 改成逐项合并：已有对象保留 ``fives``，新对象直接用。
    GACHA_STATE.pools = GACHA_STATE.pools || {};
    for (const pool of pools) {
      const key = String(pool.poolType || pool.key || pool.name || '');
      if (!key) continue;
      const existing = GACHA_STATE.pools[key] || {};
      GACHA_STATE.pools[key] = Object.assign({}, existing, pool);
    }
    const keys = Object.keys(GACHA_STATE.pools);

    const tabsHost = GACHA_STATE.poolTabsHost;
    if (tabsHost) {
      P.fill(tabsHost, null);
      if (!keys.length) {
        tabsHost.appendChild(P.el('div', {
          class: 'gk-note', text: '还没有分卡池数据。'
        }));
      } else {
        //: 默认选中第一个
        if (!GACHA_STATE.selectedPool || keys.indexOf(GACHA_STATE.selectedPool) < 0) {
          GACHA_STATE.selectedPool = keys[0];
        }
        for (const key of keys) {
          const pool = GACHA_STATE.pools[key];
          const tab = P.el('button', {
            class: 'gk-pool-tab' +
              (key === GACHA_STATE.selectedPool ? ' is-active' : ''),
            type: 'button',
            text: String(pool.name || key),
            dataset: { poolKey: key },
            onClick: function () { gachaSelectPool(key); }
          });
          tabsHost.appendChild(tab);
        }
      }
    }
    gachaRenderSelectedPool();
  }

  function gachaSelectPool(key) {
    GACHA_STATE.selectedPool = key;
    const tabs = document.querySelectorAll('.gk-pool-tab');
    for (const tab of tabs) {
      tab.classList.toggle('is-active', tab.dataset.poolKey === key);
    }
    gachaRenderSelectedPool();
  }

  /**
   * 渲染选中的卡池 —— **汇总行 + 逐条五星列表**。
   *
   * ## ★ 逐条五星（2026-11-02 补，用户「记录数据在，为什么不展示」）
   *
   * 旧界面 ``_pool_block`` 的注释写着：
   *
   * .. code:: text
   *
   *   ★ 这是工坊那条列表的核心视觉（用户 2026-09-30："差在逐条抽数条列表"）：
   *
   *       [头像] ████████████ 68抽                    (歪)
   *       [头像] ██████ 33抽
   *       [头像] ███████████████ 81抽                 (歪)
   *
   *   条的**长度**按抽数走、**颜色**按欧非分级（绿→黄→红）。
   *
   * ## ⚠⚠ 颜色和评价是**两套独立阈值**，别写成一个 if-else 链
   *
   * 后端 ``getGachaPoolDetail()`` 已经算好 ``barColor`` / ``verdict`` /
   * ``verdictColor`` —— **直接用，别自己实现阈值**（抄一遍必然对不上）。
   *
   * 实测反例：
   *
   * .. code:: text
   *
   *   安可  span=24  isLost=true
   *         → barColor=绿（按 span 分档）、verdict=歪（按 isLost）
   *
   * 两个逻辑**独立**：抽数少就是绿条，但歪了照样标「歪」。
   *
   * ## ⚠ ``span`` 不是 ``cumulative``
   *
   * ``span``       = 距上一个**五星**（条长看这个）
   * ``cumulative`` = 距上一次 **UP**（歪了累加）
   *
   * 旧代码踩过：混用会显示「124 抽」这种累计值。
   *
   * ## ⚠ 顺序：**最新在最上面**（后端已排好，别再 reverse）
   *
   * ## ⚠ 不显示时间（用户明确不要）
   */
  function gachaRenderSelectedPool() {
    const host = GACHA_STATE.poolsHost;
    if (!host) return;
    P.fill(host, null);
    const pool = GACHA_STATE.pools[GACHA_STATE.selectedPool];
    if (!pool) return;

    const card = P.el('div', { class: 'gk-pool-card card-glass' });

    // ── 汇总行 ──
    const row = P.el('div', { class: 'gk-pool-row' });
    const bits = [];
    if (pool.pulls != null) bits.push(pool.pulls + ' 抽');
    if (pool.five != null) bits.push('五星 ' + pool.five);
    const rate = gachaFixed(pool.rate, 1, '%');
    if (rate != null) bits.push('出货率 ' + rate);
    //: 旧界面：只有 total 非 0 才显示「已垫 N 抽」（L1133-1134）
    if (pool.pity != null && pool.pulls) bits.push('已垫 ' + pool.pity + ' 抽');
    row.appendChild(P.el('div', {
      class: 'gk-pool-stat', text: bits.join('   ')
    }));
    if (pool.rank) {
      row.appendChild(P.el('span', {
        class: 'gk-pool-luck', text: String(pool.rank)
      }));
    }
    card.appendChild(row);

    //: 分隔线（旧界面 L1150-1154）
    card.appendChild(P.el('div', { class: 'gk-pool-divider' }));

    // ── 逐条五星 ──
    const fives = Array.isArray(pool.fives) ? pool.fives : [];
    if (!fives.length) {
      //: 抽过但没出金（池 4 就是这种：pulls=1, five=0）
      card.appendChild(P.el('div', {
        class: 'gk-pool-empty',
        text: pool.pulls ? '这个卡池还没有出过五星。' : '这个卡池还没抽过。'
      }));
      host.appendChild(card);
      return;
    }

    const list = P.el('div', { class: 'gk-five-list' });
    for (const five of fives) {
      list.appendChild(gachaFiveRow(five));
    }
    card.appendChild(list);
    host.appendChild(card);
  }

  //: 抽数条的几何 —— **逐字照抄**旧界面 ``gacha/tool.py`` L79-91
  //
  //: .. code:: python
  //:
  //:   BAR_UNIT = 3.2     #: 每抽 3.2px（60 抽 ≈ 192px，接近头像宽度）
  //:   BAR_MAX  = 300     #: 最长
  //:   BAR_MIN  = 76      #: 最短 —— 否则「1抽」的条只有几像素，数字都写不下
  //:   BAR_HEIGHT = 34    #: 条高，接近头像 48（原来是 18，太细）
  //:
  //:   def bar_width(span): return min(BAR_MAX, max(BAR_MIN, span * BAR_UNIT))
  //:
  //: ⚠ **不是**按 max(span) 归一化 —— 我一开始那么写是错的：
  //:   旧界面是**绝对像素**（3.2px/抽，夹 76~300），
  //:   所以「30 抽」和「90 抽」的条长差 3 倍，不管这一池最大多少抽。
  const BAR_UNIT = 3.2;
  const BAR_MAX = 300;
  const BAR_MIN = 76;
  const BAR_HEIGHT = 34;

  /** 抽数 → 条的像素宽度（旧界面 ``bar_width``）*/
  function gachaBarWidth(span) {
    const n = Number(span);
    const safe = isFinite(n) ? Math.max(0, n) : 0;
    return Math.round(Math.min(BAR_MAX, Math.max(BAR_MIN, safe * BAR_UNIT)));
  }

  /** 一行五星（旧界面 ``_five_row`` L1180+）：头像 + 抽数条 + 抽数 + 评价 */
  function gachaFiveRow(five) {
    const row = P.el('div', { class: 'gk-five-row' });

    // ── 头像 48px（旧界面 ``AVATAR_SIZE = 48``）──
    const avatar = P.el('div', { class: 'gk-five-avatar' });
    function useInitial() {
      P.fill(avatar, null);
      const name = String(five.name || '?');
      const init = five.initial || {};
      avatar.textContent = String(init.initial || name.slice(0, 1) || '?');
      const hue = Number(five.avatarHue != null ? five.avatarHue : init.hue);
      if (isFinite(hue)) {
        avatar.style.backgroundColor = 'hsl(' + hue + ', 42%, 30%)';
        avatar.style.color = 'rgba(255,255,255,0.92)';
      }
    }
    if (five.iconUrl) {
      const img = P.el('img', { src: five.iconUrl, alt: '', loading: 'lazy' });
      img.addEventListener('error', useInitial, { once: true });
      avatar.appendChild(img);
    } else {
      useInitial();
    }
    row.appendChild(avatar);

    // ── 抽数条 ──
    //
    //: ★ 长度用 ``span``（距上一个五星），**不是** ``cumulative``（距上次 UP）。
    //:   实测例：``心 span=25 cumulative=49`` —— 用了 25 抽出金，
    //:   但距上次 UP 已 49 抽（上次歪了）。混用会显示「49抽」。
    const span = Number(five.span);
    const safeSpan = isFinite(span) ? span : 0;
    const bar = P.el('div', { class: 'gk-five-bar' });
    bar.style.width = gachaBarWidth(safeSpan) + 'px';
    bar.style.height = BAR_HEIGHT + 'px';
    //: ★ **直接用后端的 barColor**（5 档阈值，别自己实现）
    if (five.barColor) bar.style.backgroundColor = String(five.barColor);
    row.appendChild(bar);

    // ── 抽数文字（紧跟条后面，旧界面不用 stretch 顶到最右）──
    row.appendChild(P.el('span', {
      class: 'gk-five-span', text: safeSpan + '抽'
    }));

    // ── 评价（歪 / 欧 / 非 / 空串）──
    //
    //: ★ 评价和颜色是**两套独立阈值**（旧界面 ``_verdict``）：
    //:   isLost → 歪；span≤60 → 欧；span≥74 → 非；61~73 → **空串不标**
    //:
    //: 实测反例：``安可 span=24 isLost=true`` → 条是**绿**的但标「歪」。
    //: 所以不能写成一个 if-else 链，直接用后端给的两个字段。
    const verdict = String(five.verdict || '');
    if (verdict) {
      const tag = P.el('span', {
        class: 'gk-five-verdict', text: verdict
      });
      if (five.verdictColor) tag.style.color = String(five.verdictColor);
      row.appendChild(tag);
    }

    //: ⚠ 不显示时间（``at`` 字段后端有，但用户明确不要）
    return row;
  }

  // ── 历史记录 ─────────────────────────────────────────────────────────
  async function gachaLoadHistory() {
    const host = GACHA_STATE.historyHost;
    if (!host) return;
    const result = await P.call('getGachaHistory');
    if (!result.ok) {
      P.fill(host, [P.el('div', {
        class: 'gk-note', text: '历史记录接口未就绪。'
      })]);
      return;
    }
    const data = result.data || {};
    const items = Array.isArray(data.items) ? data.items : [];
    GACHA_STATE.history = items;
    P.fill(host, null);
    if (!items.length) {
      //: 旧界面 L875 原话
      host.appendChild(P.el('div', {
        class: 'gk-note', text: '还没有历史 —— 点「分析」后会按时间记下来。'
      }));
      return;
    }
    for (const item of items) {
      host.appendChild(gachaHistoryCard(item));
    }
  }

  /** 一张历史卡（旧界面 ``HistoryCard`` 168x92，三行）*/
  function gachaHistoryCard(item) {
    const card = P.el('div', { class: 'gk-history-card' });
    card.appendChild(P.el('div', {
      class: 'gk-history-account',
      text: gachaAccountLabel(item.playerId)
    }));
    card.appendChild(P.el('div', {
      class: 'gk-history-month',
      text: String(item.monthText || item.yearMonth || '')
    }));
    card.appendChild(P.el('div', {
      class: 'gk-history-stat',
      text: (item.total || 0) + ' 抽 / ' + (item.five || 0) + ' 金'
    }));
    return card;
  }

  /** 账号显示：后 6 位（旧界面 ``gacha_store.account_label``）*/
  function gachaAccountLabel(playerId) {
    const text = String(playerId || '');
    if (!text) return '未知账号';
    return text.length > 6 ? '…' + text.slice(-6) : text;
  }

  /**
   * 清空历史 —— **必须二次确认**。
   *
   * 抽卡历史**不可逆**（旧界面 ``store.save(GachaHistory())`` 直接覆盖成空）。
   * 两道防线：① 前端点两次 ② 后端 ``confirm_token: "YES"``。
   */
  async function gachaClearHistory(btn) {
    if (!btn) return;
    if (btn.dataset.confirming !== '1') {
      btn.dataset.confirming = '1';
      btn.textContent = '确认清空？';
      btn.classList.add('is-confirming');
      if (btn._timer) clearTimeout(btn._timer);
      btn._timer = setTimeout(function () {
        btn.dataset.confirming = '';
        btn.textContent = '清空历史';
        btn.classList.remove('is-confirming');
      }, 3000);
      return;
    }
    if (btn._timer) clearTimeout(btn._timer);
    btn.dataset.confirming = '';
    btn.textContent = '清空中…';
    btn.disabled = true;

    const result = await P.call('clearGachaHistory', 'YES');
    btn.textContent = '清空历史';
    btn.disabled = false;
    btn.classList.remove('is-confirming');

    if (!result.ok) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent = '清空失败（接口未就绪）';
      }
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent =
          '清空失败：' + String(data.message || data.reason || '');
      }
      return;
    }
    await gachaLoadHistory();
  }

  // ════════════════════════════════════════════════════════════════════════
  //  ④ 声骸自动强化  echo_enhance   （**照抄旧界面 EchoEnhanceWidget**）
  //
  //  ## ⚠ P6 重写：用户「请不要擅自修改原先的布局内容」
  //
  //  旧界面 ``echo_enhance/tool.py`` L487-528 的 ``_build``：
  //
  //  .. code:: python
  //
  //    layout.addWidget(self._build_title_row(view))   # 标题 + 5 按钮（同一行）
  //    layout.addWidget(intro)                          # 说明（含日志路径）
  //    layout.addWidget(self.editor)                    # 6 张可折叠卡
  //    layout.addWidget(self._build_report_card(view))  # 结果报告
  //    layout.addWidget(self._build_history_card(view)) # 历史记录
  //
  //  **没有页面级标题** —— 标题和按钮在同一行（``_build_title_row`` L862-928）：
  //
  //  .. code:: python
  //
  //    row.addWidget(StrongBodyLabel("声骸自动强化"))
  //    self.run_button    = PrimaryPushButton(FluentIcon.PLAY, "运行")
  //    self.resume_button = PushButton(FluentIcon.PLAY, "继续")
  //    self.stop_button   = PushButton(FluentIcon.CANCEL, "停止")
  //    self.skip_button   = ... "跳过"   ← 2026-11-04 删掉，换成「指定强化」
  //    self.reset_button  = ... "恢复默认"
  //
  //  ## 可折叠卡（``gui/widgets.py`` L591-645 ``CollapsibleCard``）
  //
  //  .. code:: python
  //
  //    root.setContentsMargins(20, 14, 20, 16)
  //    header: [SubtitleLabel(title)]  stretch  [▼按钮 28x28]
  //    hint_label  （灰色）
  //    summary_label  ← ★ **收起时也一直可见**（能看出"当前选了什么"）
  //    content      ← 默认收起
  //
  //  ## 双爆下限那行**没有卡片包裹**
  //
  //  旧界面 ``_build_crit_card`` 用的是裸 ``CardWidget`` + 一行三个控件
  //  （暴击不低于 / 爆伤不低于 / 启用开关），没有折叠、没有标题。
  //
  //  ## 🔴 必须删掉「运行前提」+「使用哪条配置」
  //
  //  前者用户圈出「干掉」；后者是用户 2026-09-26 明确否掉过的错误设计
  //  （``tool.py`` L530-535 注释：故意没有配置选择器）。已全部删除。
  // ════════════════════════════════════════════════════════════════════════

  //: 旧界面 ``settings.ALL_STATS`` —— 逐字照抄（顺序也一致）
  const ENHANCE_ALL_STATS = [
    '暴击', '暴击伤害', '攻击', '攻击百分比', '生命', '生命百分比',
    '防御', '防御百分比', '共鸣效率',
    '普攻伤害加成', '重击伤害加成', '共鸣技能伤害加成', '共鸣解放伤害加成'
  ];
  const ENHANCE_CRIT = '暴击';
  const ENHANCE_CRIT_DMG = '暴击伤害';
  const ENHANCE_MAX_CORE = 5;
  const ENHANCE_DEFAULT_CRIT_MIN = 7.5;
  const ENHANCE_DEFAULT_CRIT_DMG_MIN = 15.0;
  const ENHANCE_DEFAULT_VALID = 2;

  const ENHANCE_STATE = {
    coreBoxes: {},
    optionalBoxes: {},
    critField: null,
    critDmgField: null,
    critSwitch: null,
    maxrollSwitch: null,
    autostopSwitch: null,
    //: ★ 2026-11-04「指定强化」开关（同款 `.enh-switch-card`，默认开）——
    //: 开着时「运行」走 `runTaskWith` + `{designated:true}`
    designatedSwitch: null,
    validStepper: null,
    coreSummary: null,
    optionalSummary: null,
    reportHost: null,
    historyHost: null,
    btnRun: null,
    btnResume: null,
    btnStop: null,
    //: ★ 2026-11-04 「跳过」→「指定强化」（用户要求删掉跳过）。
    //: 语义是"只强化玩家鼠标点中的那个声骸，处理完就停"。
    btnDesignated: null,
    watchTimer: null
  };

  /**
   * 可折叠卡（旧界面 ``CollapsibleCard``）。
   *
   * @param {string} title
   * @param {object} opts - {hint, summary, expanded, headerRight}
   * @returns {{card, body, summaryEl, contentEl, setSummary, setExpanded}}
   */
  function collapsibleCard(title, opts) {
    opts = opts || {};
    let expanded = !!opts.expanded;

    const card = P.el('div', { class: 'coll-card card-glass' });

    // ── 标题行：[标题] stretch [headerRight] [▼] ──
    const head = P.el('div', { class: 'coll-head' });
    head.appendChild(P.el('div', { class: 'coll-title', text: title }));
    head.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    if (opts.headerRight) head.appendChild(opts.headerRight);

    const toggle = P.el('button', {
      class: 'coll-toggle',
      type: 'button',
      title: '展开 / 收起',
      text: '▼'
    });
    head.appendChild(toggle);
    card.appendChild(head);

    // ── hint（灰色，一直可见）──
    if (opts.hint) {
      card.appendChild(P.el('div', { class: 'coll-hint', text: opts.hint }));
    }

    // ── summary（★ 收起时也可见）──
    const summaryEl = P.el('div', {
      class: 'coll-summary',
      text: opts.summary || ''
    });
    card.appendChild(summaryEl);

    // ── 内容区（默认收起）──
    const contentEl = P.el('div', { class: 'coll-content' });
    contentEl.hidden = !expanded;
    card.appendChild(contentEl);

    function sync() {
      toggle.classList.toggle('is-expanded', expanded);
      contentEl.hidden = !expanded;
    }
    toggle.addEventListener('click', function () {
      expanded = !expanded;
      sync();
    });
    sync();

    return {
      card: card,
      contentEl: contentEl,
      summaryEl: summaryEl,
      setSummary: function (text) { summaryEl.textContent = text || ''; },
      setExpanded: function (v) { expanded = !!v; sync(); }
    };
  }

  registerPanel('echo_enhance', function renderEchoEnhance(container, app, meta) {
    // ══════════════════════════════════════════════════════════════════════
    //  标题行 + 5 个按钮（旧界面 ``_build_title_row`` L862-928）
    // ══════════════════════════════════════════════════════════════════════
    const titleRow = P.el('div', { class: 'enh-title-row' });
    titleRow.appendChild(P.el('div', {
      class: 'enh-title', text: '声骸自动强化'
    }));
    ENHANCE_STATE.btnRun = P.button('运行', {
      kind: 'primary', size: 'sm',
      onClick: function () { enhanceAction('run'); }
    });
    ENHANCE_STATE.btnResume = P.button('继续', {
      size: 'sm', disabled: true,
      onClick: function () { enhanceAction('resume'); }
    });
    ENHANCE_STATE.btnStop = P.button('停止', {
      size: 'sm', disabled: true,
      onClick: function () { enhanceAction('stop'); }
    });
    //: ★★★ 2026-11-04 用户：「【指定强化】功能放在下面，与自动停止一样
    //: 启用与不启用，默认启用」
    //:
    //: 所以「指定强化」**不是标题行按钮**，而是设置区里的一个开关卡
    //: （和「自动停止」同款 `.enh-switch-card`），默认开着；开着时点
    //: 「运行」就走指定强化。
    //:
    //: 历史：这里原本是「跳过」（强化途中换下一个），2026-11-04 上午按
    //: 用户要求换成「指定强化」按钮并删掉 `enhanceAction('skip')` +
    //: 后端 `okwwSkipEcho` Slot；现在按钮也撤了，改成开关。
    const btnReset = P.button('恢复默认', {
      size: 'sm',
      onClick: function () { enhanceResetSettings(); }
    });
    for (const b of [ENHANCE_STATE.btnRun, ENHANCE_STATE.btnResume,
                     ENHANCE_STATE.btnStop, btnReset]) {
      titleRow.appendChild(b);
    }
    container.appendChild(titleRow);

    //: ★★★ 2026-11-03 用户：「另外文字说明也去掉，再检查其他地方有没有类似情况」
    //:
    //: 删掉的是这一整段（旧界面 ``echo_enhance/tool.py`` L494-504 逐字照抄的）：
    //:
    //:   「在背包 → 声骸界面用过滤器筛好、按等级升序排序，再点运行。
    //:     强化流程由 ok-ww 引擎执行（与「4C 自动战斗」同一个引擎，
    //:     后台按键不抢前台）：符合条件的上锁保留，不符合条件的自动弃置。
    //:     运行日志按日期落盘：data/okww/logs（出问题把当天那个文件发过来即可）」
    //:
    //: ⚠ 全站只有这一段是「逐字照抄旧界面」的说明，其他工具页早在
    //: P5~P8 就按用户要求删掉了 —— 这里漏了，用户圈图点名。
    //:
    //: 日志路径信息仍有价值，但它属于「出问题时才需要」的东西，
    //: 需要的时候在 ``data/okww/logs`` 找即可，不必常驻在页面上。

    // ══════════════════════════════════════════════════════════════════════
    //  设置编辑器（6 张卡，``settings_editor.EchoSettingsEditor``）
    // ══════════════════════════════════════════════════════════════════════
    const editor = P.el('div', { class: 'enh-editor' });
    editor.appendChild(buildEnhanceCoreCard());
    editor.appendChild(buildEnhanceCritRow());      // ★ 裸行，没有卡片包裹
    editor.appendChild(buildEnhanceMaxrollCard());
    //: ★★★ 2026-11-04 用户：「【指定强化】功能放在下面，与自动停止一样
    //: 启用与不启用，默认启用」→ 排在「自动停止」上面一格（"放在下面"指的
    //: 是从标题行挪到设置区，不是排到最后一格）。
    editor.appendChild(buildEnhanceDesignatedCard());
    editor.appendChild(buildEnhanceAutostopCard());
    editor.appendChild(buildEnhanceOptionalCard());
    editor.appendChild(buildEnhanceValidCard());
    container.appendChild(editor);

    // ══════════════════════════════════════════════════════════════════════
    //  结果报告（旧界面 ``_build_report_card`` L542-575）
    // ══════════════════════════════════════════════════════════════════════
    const report = cfgCard('结果报告', '');
    ENHANCE_STATE.reportHost = P.el('div', { class: 'cfg-report' });
    report.body.appendChild(ENHANCE_STATE.reportHost);
    container.appendChild(report.card);
    enhanceRenderReport(null);

    // ══════════════════════════════════════════════════════════════════════
    //  历史记录（旧界面 ``_build_history_card`` L577-680）
    // ══════════════════════════════════════════════════════════════════════
    const history = cfgCard('历史记录', '');
    const histHead = P.el('div', { class: 'cfg-inline-row' });
    histHead.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    histHead.appendChild(P.button('刷新', {
      size: 'sm',
      onClick: function () { enhanceLoadHistory(); }
    }));
    history.body.appendChild(histHead);
    ENHANCE_STATE.historyHost = P.el('div', { class: 'cfg-history' });
    history.body.appendChild(ENHANCE_STATE.historyHost);
    container.appendChild(history.card);

    //: ★★★ 2026-11-03 **把「改动即存盘」接上**（旧界面 L509 的
    //: ``self.editor.changed.connect(self._save_settings)``）
    //:
    //: 旧界面语义（``tool.py`` L478-485 的注释）：
    //:
    //: * **界面**每次进入都是出厂默认 —— 不回填存盘值
    //: * **改动照样存盘** —— 任务运行读的是存盘那份
    //:
    //: 两条同时成立才是对的。原来 Web 版只做了"读回来回填"（错），
    //: 完全没有"存"（也错）—— 结果界面上改的判定条件**从来没生效过**，
    //: 引擎跑的是上一次存盘的值。这是会毁结果的静默 bug。
    enhanceBindSave();
    //: ★ 2026-11-03 初始化互斥状态（核心 ↔ 可选）+ 两份摘要。
    //: 必须在**所有卡片都建好之后**调 —— 它要同时读两组 checkbox。
    enhanceRefresh();
    enhanceLoadSettings();
    enhanceLoadHistory();
    void app; void meta;
  });

  /**
   * 给所有设置控件挂「变更就存盘」监听（旧界面 ``editor.changed``）。
   *
   * ⚠ 用 ``change`` 而不是 ``input``：数字框在用户还在一半输入时
   * （比如敲了 "1" 准备敲 "13"）不该存盘 —— ``change`` 在失焦/回车时
   * 才触发，和 Qt 的 ``textChanged``+``editingFinished`` 语义接近。
   */
  function enhanceBindSave() {
    const save = function () { enhanceSaveSettings(); };
    for (const stat of ENHANCE_ALL_STATS) {
      const cb = ENHANCE_STATE.coreBoxes[stat];
      if (cb) cb.addEventListener('change', save);
      const opt = ENHANCE_STATE.optionalBoxes[stat];
      if (opt) opt.addEventListener('change', save);
    }
    const fields = [ENHANCE_STATE.critField, ENHANCE_STATE.critDmgField,
                    ENHANCE_STATE.validStepper];
    for (const f of fields) {
      //: ``Panels.numberInput`` 暴露 ``.input``（真正的 <input>）+
      //: ``.el``（外壳，含 −/+ 按钮）。按钮点完会触发 input 的 change，
      //: 所以只监听 input 就够。
      if (f && f.input) f.input.addEventListener('change', save);
      if (f && f.el) {
        f.el.addEventListener('click', function (ev) {
          //: 兜底：±按钮改值时不一定冒泡 change，这里再存一次
          if (ev.target && ev.target.closest
            && ev.target.closest('button')) {
            setTimeout(save, 0);
          }
        });
      }
    }
    const toggles = [ENHANCE_STATE.critSwitch, ENHANCE_STATE.maxrollSwitch,
                     ENHANCE_STATE.autostopSwitch,
                     //: ★ 2026-11-04 指定强化开关也要「一改就存」
                     ENHANCE_STATE.designatedSwitch];
    for (const t of toggles) {
      if (t) t.addEventListener('change', save);
    }
  }

  // ── 核心属性（CollapsibleCard，默认收起）──────────────────────────────
  //
  //  ★ 复选框是 **4 列网格、按列填充**（旧界面 ``settings_editor.py`` L151-166）：
  //
  //  .. code:: python
  //
  //    grid = QGridLayout()
  //    columns = 4
  //    rows = (len(ALL_STATS) + columns - 1) // columns      # 13 项 → 4 行
  //    for index, stat in enumerate(ALL_STATS):
  //        grid.addWidget(box, index % rows, index // rows)  # ← 按**列**填
  //
  //  13 项 → 4 行 × 4 列（最后一列只有 1 个）。按列填的意思是第 1 列放 4 个，
  //  第 2 列再放 4 个…… 视觉上是从上往下读的。
  //
  //  ⚠ CSS ``grid-auto-flow: column`` + ``grid-template-rows: repeat(4, auto)``
  //    就是「按列填充」。P5 我用的是默认的按行填充，和旧界面读法不一样。
  function buildEnhanceCoreCard() {
    const coll = collapsibleCard('核心属性', {
      //: ★ 2026-11-02 用户要求「这些说明都要删掉」—— 说明文字全删，
      //:   只留标题 + 摘要行 + 复选框网格。
      summary: '已勾选 2 / ' + ENHANCE_MAX_CORE + ' 条：暴击、暴击伤害',
      expanded: false
    });
    ENHANCE_STATE.coreSummary = coll;

    const grid = P.el('div', { class: 'enh-core-grid' });
    for (const stat of ENHANCE_ALL_STATS) {
      const forced = stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG;
      const lbl = P.el('label', { class: 'enh-check' });
      const cb = P.el('input', { type: 'checkbox' });
      cb.checked = forced;
      cb.disabled = forced;
      if (forced) cb.title = '必须保留，不可取消';
      cb.addEventListener('change', enhanceOnCoreChange);
      lbl.appendChild(cb);
      lbl.appendChild(P.el('span', { text: stat }));
      if (forced) lbl.classList.add('is-forced');
      grid.appendChild(lbl);
      ENHANCE_STATE.coreBoxes[stat] = cb;
    }
    coll.contentEl.appendChild(grid);
    return coll.card;
  }

  function enhanceOnCoreChange() {
    enhanceRefresh();
  }

  /**
   * 可选属性那侧任何一格变动后走这里。
   *
   * ★ 2026-11-03 用户圈图：「这里属性是互斥的，上面先选了，下面就不能选，
   * 下面先选了，上面就不能选」—— 两个方向都要生效，所以两侧的
   * ``change`` 事件最后都汇到同一个 ``enhanceRefresh()``。
   */
  function enhanceSyncOptional() {
    enhanceRefresh();
  }

  /**
   * 核心属性 ↔ 可选属性的**互斥 + 置灰 + 摘要**唯一真源。
   *
   * ## 两条独立规则，取或
   *
   * ① **互斥**（用户 2026-11-03 圈图）：除暴击 / 暴击伤害外，11 项属性
   *    同一时间只能待在一侧 —— 可选勾了，核心同名项灰掉；核心勾了，
   *    可选同名项灰掉。
   * ② **核心上限**：暴击 + 爆伤已强制占 2 条，自选最多再 3 条；
   *    勾满后其余核心自选框置灰（已勾的仍可取消）。
   *
   * ## 为什么拆成「一个函数」而不是两边各写一半
   *
   * 原来核心里那句 ``cb.disabled = (custom >= limit) && !cb.checked``
   * 只在**核心**变动时重算 —— 可选那侧一动，核心的置灰状态就过期了。
   * 现在两侧的 change 都调这一个函数，一次性重算**两边的** disabled
   * 和两份摘要，不可能出现一边新一边旧。
   *
   * ## 冲突时以核心为准
   *
   * 后端 ``EchoSettings.from_dict`` **不过滤交集**（``settings.py:148-162``
   * 只做去重保序），存盘数据里可能两侧都有同一项。走到这里一律按
   * 「核心保留、可选摘掉」处理 —— 核心是主要求，可选是补充项。
   */
  function enhanceRefresh() {
    //: ① 互斥 + 摘掉冲突项（以核心为准）
    for (const stat of ENHANCE_ALL_STATS) {
      if (stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG) continue;
      const opt = ENHANCE_STATE.optionalBoxes[stat];
      if (!opt) continue;
      const core = ENHANCE_STATE.coreBoxes[stat];
      const takenByCore = !!(core && core.checked);
      if (takenByCore && opt.checked) opt.checked = false;
      opt.disabled = takenByCore;
    }
    //: ② 核心侧置灰 = 被可选占了 或 已达自选上限（两条取或）
    let checked = 0;
    for (const stat of ENHANCE_ALL_STATS) {
      const cb = ENHANCE_STATE.coreBoxes[stat];
      if (cb && cb.checked) checked += 1;
    }
    const custom = checked - 2;                    //: 暴击 + 爆伤 强制占 2
    const limit = ENHANCE_MAX_CORE - 2;
    for (const stat of ENHANCE_ALL_STATS) {
      const cb = ENHANCE_STATE.coreBoxes[stat];
      if (!cb) continue;
      if (stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG) continue;
      const optBox = ENHANCE_STATE.optionalBoxes[stat];
      const takenByOptional = !!(optBox && optBox.checked);
      cb.disabled = takenByOptional || ((custom >= limit) && !cb.checked);
    }
    //: ③ 两份摘要（收起也可见）—— 旧界面 ``summary_label``
    if (ENHANCE_STATE.coreSummary) {
      const names = ENHANCE_ALL_STATS.filter(function (s) {
        const cb = ENHANCE_STATE.coreBoxes[s];
        return cb && cb.checked;
      });
      ENHANCE_STATE.coreSummary.setSummary(
        '已勾选 ' + checked + ' / ' + ENHANCE_MAX_CORE + ' 条：' +
        (names.join('、') || '（无）'));
    }
    if (ENHANCE_STATE.optionalSummary) {
      const picked = ENHANCE_ALL_STATS.filter(function (s) {
        const box = ENHANCE_STATE.optionalBoxes[s];
        return box && box.checked;
      });
      ENHANCE_STATE.optionalSummary.setSummary(picked.length
        ? '已选 ' + picked.length + ' 条：' + picked.join('、')
        : '未选');
    }
  }

  // ── 双爆下限（★ 2026-11-03 加了玻璃卡底 —— 用户圈图「这个卡片怎么没了」）──
  //
  //  旧界面 ``_build_crit_card`` 这一行**确实没有** CardWidget 包裹
  //  （见 ``settings_editor.py``：它直接 ``layout.addWidget(row)``）。
  //
  //  ⚠ 但网页里上下文不一样：上下五块全是玻璃卡，中间突然来一条裸行，
  //  用户看到的就是「**少了一张卡**」—— 而且那行里还有三个控件
  //  （两个数字输入 + 一个开关），info 密度远高于其他裸行。
  //
  //  所以这里套 ``.enh-crit-card``（同样的玻璃底 + 内边距），
  //  开关 ``margin-left:auto`` 靠右 —— 和下面「满值锁定 / 自动停止」
  //  两张卡的开关**左右对齐**（用户：「这个启用要对齐」）。
  function buildEnhanceCritRow() {
    const card = P.el('div', { class: 'enh-crit-card card-glass' });
    const row = P.el('div', { class: 'enh-crit-row' });
    row.appendChild(P.el('span', { class: 'enh-inline-label', text: '暴击不低于' }));
    ENHANCE_STATE.critField = Panels.numberInput(ENHANCE_DEFAULT_CRIT_MIN, {
      min: 0, max: 100
    });
    ENHANCE_STATE.critField.el.classList.add('cfg-number');
      ENHANCE_STATE.critField.input.classList.add('cfg-number-input');
    row.appendChild(ENHANCE_STATE.critField.el);
    row.appendChild(P.el('span', { style: 'width:22px;flex:0 0 auto' }));
    row.appendChild(P.el('span', { class: 'enh-inline-label', text: '爆伤不低于' }));
    ENHANCE_STATE.critDmgField = Panels.numberInput(ENHANCE_DEFAULT_CRIT_DMG_MIN, {
      min: 0, max: 300
    });
    ENHANCE_STATE.critDmgField.el.classList.add('cfg-number');
      ENHANCE_STATE.critDmgField.input.classList.add('cfg-number-input');
    row.appendChild(ENHANCE_STATE.critDmgField.el);
    //: 开关（旧界面 SwitchButton，圆角药丸形）—— 靠右对齐由 CSS 负责
    const sw = P.toggle('启用', true, function (on) { enhanceOnCritToggle(on); },
      { onText: '启用', offText: '不启用' });
    row.appendChild(sw);
    ENHANCE_STATE.critSwitch = sw.querySelector('input[type="checkbox"]');

    card.appendChild(row);
    return card;
  }

  function enhanceOnCritToggle(on) {
    const disabled = !on;
    if (ENHANCE_STATE.critField) ENHANCE_STATE.critField.input.disabled = disabled;
    if (ENHANCE_STATE.critDmgField) {
      ENHANCE_STATE.critDmgField.input.disabled = disabled;
    }
  }

  // ── 满值锁定（旧界面 ``_build_maxroll_card`` L204-237）────────────────
  //
  //  ★ 用的是**普通 ``CardWidget``**（不是 CollapsibleCard）：
  //
  //  .. code:: python
  //
  //    card = CardWidget(parent)
  //    row = QHBoxLayout(card)
  //    row.setContentsMargins(20, 15, 20, 15)
  //    box = QVBoxLayout()                        # 左：标题 + 说明
  //    box.addWidget(StrongBodyLabel("满暴击 / 满爆伤 自动锁定"))
  //    box.addWidget(hint)
  //    row.addWidget(box, 1)
  //    row.addWidget(self.maxroll_switch, 0, AlignTop)   # ★ 开关**顶部对齐**
  //
  //  ⚠ 开关是 ``AlignTop``（不是垂直居中）—— 说明文字有两三行时，
  //    开关贴着标题那行，不跟着文字往下漂。
  function buildEnhanceMaxrollCard() {
    const card = P.el('div', { class: 'enh-switch-card card-glass' });
    const row = P.el('div', { class: 'enh-switch-row' });

    const left = P.el('div', { class: 'enh-switch-left' });
    left.appendChild(P.el('div', {
      class: 'enh-switch-title',
      text: '满' + ENHANCE_CRIT + ' / 满爆伤 自动锁定'
    }));
    //: ★ 2026-11-02 用户要求「这些说明都要删掉」—— 说明文字不再渲染
    row.appendChild(left);

    //: ★ 开关顶部对齐
    //: 旧界面 ``setOnText("启用") / setOffText("不启用")``
    const sw = P.toggle('启用', true, function () { /* 状态即可 */ },
      { onText: '启用', offText: '不启用' });
    sw.classList.add('enh-switch-top');
    ENHANCE_STATE.maxrollSwitch = sw.querySelector('input[type="checkbox"]');
    row.appendChild(sw);

    card.appendChild(row);
    return card;
  }

  // ── 指定强化（P9：用户要求做成和「自动停止」同款的开关）──────────────
  //
  //  ## 用户 2026-11-04
  //
  //  >「【指定强化】功能放在下面，与自动停止一样启用与不启用，默认启用」
  //
  //  上午刚按他的要求把「跳过」按钮换成「指定强化」按钮，下午他又要求挪
  //  到设置区做开关 —— 因为**它其实是运行模式，不是一次性动作**：
  //
  //    * 按钮形态：每次想指定强化都得先点一下，忘了点就按普通模式跑
  //    * 开关形态：开着就一直按指定强化跑，直到自己关掉
  //
  //  对「专门强化我选中的这个」这个用法，开关更省事。
  //
  //  ⚠ 开关只管**「运行」按钮走哪条路**（`runTask` 还是 `runTaskWith`），
  //    不自己发起运行。
  function buildEnhanceDesignatedCard() {
    const card = P.el('div', { class: 'enh-switch-card card-glass' });
    const row = P.el('div', { class: 'enh-switch-row' });

    const left = P.el('div', { class: 'enh-switch-left' });
    left.appendChild(P.el('div', {
      class: 'enh-switch-title',
      text: '指定强化'
    }));
    //: 说明只在这张卡写（用户对别的卡要求删说明，但这是新功能，
    //: 不说明用户不知道「先在背包里点中声骸」这个前提）。
    left.appendChild(P.el('div', {
      class: 'enh-switch-hint',
      text: '先在背包里用鼠标点中要强化的声骸，再点运行 —— 只强化它一个，处理完就停'
    }));
    row.appendChild(left);

    const sw = P.toggle('启用', true, function () { /* 状态即可 */ },
      { onText: '启用', offText: '不启用' });
    sw.classList.add('enh-switch-top');
    ENHANCE_STATE.designatedSwitch = sw.querySelector('input[type="checkbox"]');
    row.appendChild(sw);

    card.appendChild(row);
    return card;
  }

  // ── 自动停止（P8：用户要求简写 + 删说明）─────────────────────────────
  //
  //  ## ⚠ 这一处**故意偏离旧界面**（用户 2026-11-02 明确要求）
  //
  //  旧界面 ``_build_autostop_card`` L239-287 是**长标题 + 三大段说明**：
  //
  //  .. code:: python
  //
  //    col.addWidget(StrongBodyLabel("出现符合条件的声骸就自动停止", box))
  //    ... '⚠ **不算**这一条：只因为出了满暴击/满爆伤而被上锁…'
  //    ... 'ℹ **在任务流程里不暂停**：跑「任务」页的流程时…'
  //
  //  而且旧代码注释里记着用户当年的话：
  //
  //  > ⚠ 文案里必须把**排除项**写清楚。用户原话：
  //  > "出现符合条件声骸自动停止（不包括出现满爆击/满暴伤，
  //  >   但是词条数不符合的）"
  //
  //  **但用户 2026-11-02 又明确要求「简写成自动停止」+ 说明全删。**
  //  以最新要求为准 —— 这是**用户主动推翻旧设计**，不是我们擅自修改。
  //  只留「标题 + 开关」。
  function buildEnhanceAutostopCard() {
    const card = P.el('div', { class: 'enh-switch-card card-glass' });
    const row = P.el('div', { class: 'enh-switch-row' });

    const left = P.el('div', { class: 'enh-switch-left' });
    left.appendChild(P.el('div', {
      class: 'enh-switch-title',
      text: '自动停止'
    }));
    row.appendChild(left);

    //: 旧界面 ``setOnText("启用") / setOffText("不启用")``
    const sw = P.toggle('启用', true, function () { /* 状态即可 */ },
      { onText: '启用', offText: '不启用' });
    sw.classList.add('enh-switch-top');
    ENHANCE_STATE.autostopSwitch = sw.querySelector('input[type="checkbox"]');
    row.appendChild(sw);

    card.appendChild(row);
    return card;
  }

  // ── 可选属性（CollapsibleCard）────────────────────────────────────────
  function buildEnhanceOptionalCard() {
    const coll = collapsibleCard('可选属性', {
      //: ★ 2026-11-02 用户要求「这些说明都要删掉」
      summary: '未选',
      expanded: false
    });
    //: ★ 2026-11-03 互斥联动要用到摘要（``enhanceSyncOptional`` 里刷新）
    ENHANCE_STATE.optionalSummary = coll;
    const grid = P.el('div', { class: 'enh-core-grid' });
    for (const stat of ENHANCE_ALL_STATS) {
      if (stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG) continue;
      const lbl = P.el('label', { class: 'enh-check' });
      const cb = P.el('input', { type: 'checkbox' });
      //: ★★★ 2026-11-03 用户圈图「上面先选了，下面就不能选，反过来也一样」
      //: —— 这里只挂 ``enhanceSyncOptional``（刷新摘要 + 摘掉与核心冲突的
      //: 项），核心那侧的置灰由它内部回写；**不要**在这里再写一遍摘要逻辑，
      //: 否则两处会各算一套、摘要和实际勾选对不上。
      cb.addEventListener('change', enhanceSyncOptional);
      lbl.appendChild(cb);
      lbl.appendChild(P.el('span', { text: stat }));
      grid.appendChild(lbl);
      ENHANCE_STATE.optionalBoxes[stat] = cb;
    }
    coll.contentEl.appendChild(grid);
    return coll.card;
  }

  // ── 有效词条（★ 2026-11-03 加玻璃卡底 —— 用户圈图「这里也是」）──
  //
  //  旧界面这一行同样**没有** CardWidget 包裹（``_build_valid_card``
  //  直接 ``layout.addWidget``）。但它在网页里夹在「可选属性」卡片和
  //  「结果报告」卡片之间，**裸行夹在两块玻璃中间**看起来像少了一张卡
  //  —— 和双爆下限那行是同一个问题。
  function buildEnhanceValidCard() {
    const card = P.el('div', { class: 'enh-crit-card card-glass' });
    const row = P.el('div', { class: 'enh-crit-row' });
    row.appendChild(P.el('span', { class: 'enh-inline-label', text: '有效词条' }));
    row.appendChild(P.el('span', { class: 'enh-inline-label', text: '至少' }));
    ENHANCE_STATE.validStepper = Panels.numberInput(ENHANCE_DEFAULT_VALID, {
      min: 2, max: 5
    });
    ENHANCE_STATE.validStepper.el.classList.add('cfg-number');
      ENHANCE_STATE.validStepper.input.classList.add('cfg-number-input');
    row.appendChild(ENHANCE_STATE.validStepper.el);
    row.appendChild(P.el('span', { class: 'enh-inline-label', text: '条' }));
    card.appendChild(row);
    return card;
  }

  // ── 结果报告 ─────────────────────────────────────────────────────────
  function enhanceRenderReport(stats) {
    const host = ENHANCE_STATE.reportHost;
    if (!host) return;
    P.fill(host, null);
    if (!stats) {
      host.appendChild(P.el('div', {
        class: 'cfg-muted',
        text: '还没跑过 —— 点「运行」后这里实时显示本次的统计'
      }));
      return;
    }
    const rows = [
      ['判定', stats.checked],
      ['符合条件', stats.kept],
      ['弃置', stats.dropped],
      ['满属性', stats.perfect]
    ];
    for (const pair of rows) {
      const row = P.el('div', { class: 'cfg-report-row' });
      row.appendChild(P.el('span', {
        class: 'cfg-report-key', text: pair[0]
      }));
      row.appendChild(P.el('span', {
        class: 'cfg-report-val',
        text: pair[1] != null ? String(pair[1]) : '—'
      }));
      host.appendChild(row);
    }
  }

  // ── 数据 ─────────────────────────────────────────────────────────────
  async function enhanceLoadSettings() {
    //: ★★★ 2026-11-03 **不把存盘值回填到界面**（用户：「可选属性默认是空的」）
    //:
    //: ## 旧界面怎么做的（``echo_enhance/tool.py`` L478-485）
    //:
    //: .. code:: python
    //:
    //:     #: 本页当前的一套设置。**每次打开页面都是出厂默认**（用户 2026-09-24
    //:     #: 明确要求："不要遗留上次的东西，每次进入都是默认配置"）——
    //:     #: 所以这里不用 ``EchoSettings.load()``。改动仍然存盘，任务流程
    //:     #: 读的就是存下来那份。
    //:     self._settings = EchoSettings()
    //:
    //: **关键区别**：
    //:   * **界面**永远从出厂默认开始（核心=双爆 / 可选=空 / 有效词条=3）
    //:   * **改动照样存盘**，任务运行读的是存盘那份
    //:
    //: 也就是说"界面显示"和"存盘值"是**故意分开的** —— 用户要的是
    //: 每次进来干净的一块白纸。
    //:
    //: ## 之前错在哪
    //:
    //: Web 版读 ``getToolSettings('echo_enhance')`` 然后全量回填，
    //: 于是打开就显示上次（甚至是 10-09 那次）的勾选状态 ——
    //: 用户看到的「可选属性里勾了 攻击百分比 / 共鸣效率」就是这么来的。
    //:
    //: ## 现在
    //:
    //: 什么都不回填 —— 界面用 HTML 里写死的出厂默认值
    //: （``DEFAULT_ENHANCE_*`` / ``DEFAULT_CORE`` ...）。
    //: ``changeSaveSettings`` 仍然照常存盘，任务流程不受影响。
    //:
    //: ⚠ 只保留一个"读"的用途：确认后端接口在不在（失败要能说出来，
    //:   不能静默）。但**不写回控件**。
    const result = await P.call('getToolSettings', 'echo_enhance');
    if (!result.ok) {
      //: 读不到设置**不影响界面可用性**（界面本来就是出厂默认），
      //: 但要说出来 —— 否则用户以为自己的设置被吞了。
      //: 这个面板没有 ``stateLabel``，失败出口是「结果报告」区。
      const host = ENHANCE_STATE.reportHost;
      if (host) {
        P.fill(host, null);
        host.appendChild(P.el('div', {
          class: 'cfg-state',
          style: 'color:#ff8f88',
          text: '设置接口未就绪 —— 界面显示的是出厂默认值'
        }));
      }
      return;
    }
    //: 注意：**到此为止**。不 setSettings / 不回填任何控件。
    void result;
  }

  /**
   * 收集界面上当前这套判定条件（旧界面 ``self.editor.settings()``）。
   *
   * @returns {object} ``{core_stats, optional_stats, crit_min, ...}``
   *
   * ⚠ 字段名用**下划线**（``core_stats``），和 ``EchoSettings.from_dict``
   * 一致 —— 它只认下划线，写驼峰会被静默丢掉（交接文档第五节 C
   * 「写操作要验往返一致」就是踩的这个）。
   */
  function enhanceCollectSettings() {
    const core = [];
    const optional = [];
    for (const stat of ENHANCE_ALL_STATS) {
      const coreBox = ENHANCE_STATE.coreBoxes[stat];
      if (coreBox && coreBox.checked) core.push(stat);
      const optBox = ENHANCE_STATE.optionalBoxes[stat];
      if (optBox && optBox.checked) optional.push(stat);
    }
    const num = function (field, fallback) {
      if (!field) return fallback;
      const v = parseFloat(String(field.get()));
      return isFinite(v) ? v : fallback;
    };
    return {
      core_stats: core,
      optional_stats: optional,
      crit_min: num(ENHANCE_STATE.critField, ENHANCE_DEFAULT_CRIT_MIN),
      crit_dmg_min: num(ENHANCE_STATE.critDmgField,
                        ENHANCE_DEFAULT_CRIT_DMG_MIN),
      min_valid_count: parseInt(
        String(ENHANCE_STATE.validStepper ? ENHANCE_STATE.validStepper.get()
                                          : ENHANCE_DEFAULT_VALID), 10)
        || ENHANCE_DEFAULT_VALID,
      enable_crit_check: !!(ENHANCE_STATE.critSwitch
        && ENHANCE_STATE.critSwitch.checked),
      enable_max_roll_lock: !!(ENHANCE_STATE.maxrollSwitch
        && ENHANCE_STATE.maxrollSwitch.checked),
      enable_auto_stop: !!(ENHANCE_STATE.autostopSwitch
        && ENHANCE_STATE.autostopSwitch.checked)
    };
  }

  /**
   * 把「界面当前值」存盘（旧界面 ``_save_settings``）。
   *
   * ## 为什么必须有（2026-11-03 发现缺失）
   *
   * 旧界面 ``tool.py`` L509：``self.editor.changed.connect(self._save_settings)``
   * —— 控件一动就存盘，**任务流程运行时读的就是存盘那份**
   * （``okww_task`` 里走 ``EchoSettings.load()``）。
   *
   * Web 版原来**只读不写**：界面上改了判定条件，存盘的还是旧值，
   * 一点「运行」引擎读到的和你看到的**不是同一套条件** ——
   * 这是会毁结果的静默 bug（而且完全看不出来）。
   *
   * ## 和 ``enhanceLoadSettings`` 的分工
   *
   * | 方向 | 规则 |
   * |---|---|
   * | 读（打开页面）| **不回填** —— 永远出厂默认（用户 2026-09-24 要求）|
   * | 写（改动控件）| **必须存** —— 任务流程读的是这份 |
   *
   * 这两条同时成立才是旧界面的语义：界面是干净的白纸，
   * 但你这次勾的条件会生效。
   */
  async function enhanceSaveSettings() {
    const settings = enhanceCollectSettings();
    if (!settings) return;
    const r = await P.callMulti('setToolSettings', [JSON.stringify({
      toolKey: 'echo_enhance', settings: settings
    })]);
    if (!r.ok) {
      //: 存不下来要说出来 —— 否则用户以为条件生效了，实际引擎用的是旧值
      const host = ENHANCE_STATE.reportHost;
      if (host) {
        P.fill(host, null);
        host.appendChild(P.el('div', {
          class: 'cfg-state',
          style: 'color:#ff8f88',
          text: '判定条件**没能保存**（接口未就绪）—— 运行时会用旧条件'
        }));
      }
    }
  }

  async function enhanceLoadHistory() {
    const host = ENHANCE_STATE.historyHost;
    if (!host) return;
    //: ⚠ ``@Slot(str, result=str)`` —— 必须传**字符串**（不是数字）。
    //: 传数字或什么都不传都会静默返回 ``[]``。
    const result = await P.call('getEchoEnhanceHistory', '10');
    if (!result.ok) {
      P.fill(host, [P.el('div', {
        class: 'cfg-muted', text: '历史记录接口未就绪。'
      })]);
      return;
    }
    const data = result.data || {};
    const items = Array.isArray(data.items) ? data.items : [];
    P.fill(host, null);
    if (!items.length) {
      host.appendChild(P.el('div', {
        class: 'cfg-muted', text: '还没有历史 —— 跑过一轮后这里会记录。'
      }));
      return;
    }
    for (const rec of items) {
      const row = P.el('div', { class: 'cfg-history-row' });
      row.appendChild(P.el('span', {
        class: 'cfg-history-when', text: String(rec.when || '')
      }));
      const bits = [];
      if (rec.duration) bits.push(String(rec.duration));
      const st = rec.stats || {};
      if (st.checked != null) bits.push('判定 ' + st.checked);
      if (st.kept != null) bits.push('符合 ' + st.kept);
      if (st.dropped != null) bits.push('弃置 ' + st.dropped);
      row.appendChild(P.el('span', {
        class: 'cfg-history-stat', text: bits.join(' · ')
      }));
      host.appendChild(row);
    }
  }

  /** 恢复默认（旧界面 CollapsibleCard 的「恢复默认」）*/
  function enhanceResetSettings() {
    for (const stat of ENHANCE_ALL_STATS) {
      const cb = ENHANCE_STATE.coreBoxes[stat];
      if (cb) cb.checked = (stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG);
      const opt = ENHANCE_STATE.optionalBoxes[stat];
      if (opt) opt.checked = false;
    }
    if (ENHANCE_STATE.critField) {
      ENHANCE_STATE.critField.set(ENHANCE_DEFAULT_CRIT_MIN);
    }
    if (ENHANCE_STATE.critDmgField) {
      ENHANCE_STATE.critDmgField.set(ENHANCE_DEFAULT_CRIT_DMG_MIN);
    }
    if (ENHANCE_STATE.validStepper) {
      ENHANCE_STATE.validStepper.set(ENHANCE_DEFAULT_VALID);
    }
    if (ENHANCE_STATE.critSwitch) {
      ENHANCE_STATE.critSwitch.checked = true;
      enhanceOnCritToggle(true);
    }
    if (ENHANCE_STATE.maxrollSwitch) ENHANCE_STATE.maxrollSwitch.checked = true;
    if (ENHANCE_STATE.autostopSwitch) {
      ENHANCE_STATE.autostopSwitch.checked = true;
    }
    //: ★ 2026-11-04「指定强化」默认**启用**（用户明确要求）
    if (ENHANCE_STATE.designatedSwitch) {
      ENHANCE_STATE.designatedSwitch.checked = true;
    }
    enhanceOnCoreChange();
  }

  /** 运行 / 指定强化 / 继续 / 停止 */
  async function enhanceAction(action) {
    // ══════════════════════════════════════════════════════════════════════
    //  ★ 所有失败都要**看得见**
    //
    //  ⚠ 2026-11-02 修的静默失败：原来这些分支写的是
    //  ``if (ENHANCE_STATE.stateLabel) { ... }``，但 ``stateLabel``
    //  **从头到尾没被赋值过**（永远是 null）——
    //  于是「跳过失败」「继续失败」「停止失败」「运行失败」
    //  四种情况**全都不显示任何东西**，用户只看到按钮闪了一下。
    //
    //  现在用**真实存在的**出口：「结果报告」区（``reportHost``）。
    //  ④ 没有 ``Panels.create`` 骨架（旧界面就是纯卡片堆），
    //  所以没有 ``notice()`` 可用 —— 报告区那块一直在，够用。
    // ══════════════════════════════════════════════════════════════════════

    /** 让失败可见：写到「结果报告」区（那块一直都在）*/
    function fail(message) {
      const host = ENHANCE_STATE.reportHost;
      if (!host) return;
      P.fill(host, null);
      host.appendChild(P.el('div', {
        class: 'cfg-state',
        style: 'color:#ff8f88',
        text: String(message)
      }));
    }

    if (action === 'resume') {
      const r = await P.call('okwwResumeTask');
      if (!r.ok) {
        fail('继续失败（接口未就绪）');
        return;
      }
      const d = r.data || {};
      if (d.ok === false) {
        fail('继续失败：' + String(d.message || d.reason || '没有暂停中的任务'));
      }
      return;
    }

    if (action === 'stop') {
      const r = await P.call('stopTask');
      if (!r.ok) {
        fail('停止失败（接口未就绪）');
        return;
      }
      const d = r.data || {};
      if (d.ok === false) {
        fail('停止失败：' + String(d.message || d.reason || '没有正在运行的任务'));
        return;
      }
      //: 停止成功 → 四个按钮统一回「未运行」态
      setEnhanceRunning(false, '');
      return;
    }

    // ── 运行 ──
    //: 统一走 setEnhanceRunning（它同时管 停止 / 继续）
    setEnhanceRunning(true, '强化');

    //: ★★★ 2026-11-04 「指定强化」开关决定走哪条路（用户要求做成开关，
    //: 默认启用）：
    //:
    //:   * 关 → `runTask`（老路，引擎自己找 0 级声骸、按白名单/成套筛）
    //:   * 开 → `runTaskWith` + `{designated:true}`（只强化玩家鼠标选中的那个）
    //:
    //: ⚠ `runTaskWith` 是 `@Slot(str, str, result=str)` —— **两个参数**，
    //: 必须走 `P.callMulti`（QWebChannel 按 JS 实参个数匹配 Slot，
    //: 用 `P.call` 只传一个必然 No candidates found，而且静默失败）。
    //:
    //: ⚠⚠ 实参**必须写在同一个物理行**：`js_sanity.py` 的 `check_call_arity`
    //: 是逐行正则解析的，换行会让它数出 0 个参数并报假失败。
    const designatedOn = !!(ENHANCE_STATE.designatedSwitch
      && ENHANCE_STATE.designatedSwitch.checked);
    let result;
    if (designatedOn) {
      const armed = JSON.stringify({ designated: true });
      result = await P.callMulti('runTaskWith', ['echo_enhance', armed]);
    } else {
      result = await P.call('runTask', 'echo_enhance');
    }
    const revert = function () { setEnhanceRunning(false, ''); };

    if (!result.ok) {
      revert();
      fail(designatedOn ? '指定强化失败（接口未就绪）' : '运行失败（接口未就绪）');
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      revert();
      fail((designatedOn ? '指定强化失败：' : '运行失败：')
        + String(data.message || data.reason || '后端拒绝'));
      return;
    }
    enhanceStartWatch();
  }

  function enhanceStartWatch() {
    if (ENHANCE_STATE.watchTimer) clearInterval(ENHANCE_STATE.watchTimer);
    const startedAt = Date.now();
    ENHANCE_STATE.watchTimer = setInterval(async function () {
      if (Date.now() - startedAt > 60000) {
        clearInterval(ENHANCE_STATE.watchTimer);
        ENHANCE_STATE.watchTimer = null;
        return;
      }
      const r = await P.call('getStatus');
      if (!r.ok || !r.data) return;
      const running = String(r.data.running || '');
      //: 用 ``setEnhanceRunning()`` 统一改四处 disabled，避免各写一份走偏。
      setEnhanceRunning(!!running, running);
      if (!running) {
        clearInterval(ENHANCE_STATE.watchTimer);
        ENHANCE_STATE.watchTimer = null;
      }
    }, 1500);
  }

  /**
   * ★ 统一维护「运行 / 停止 / 继续」三个按钮的可点状态。
   *
   * ## 为什么要一个函数
   *
   * 之前这是**四处各写一份** ``btnXxx.disabled = ...``：
   * ``enhanceAction`` 里两处、``enhanceStartWatch`` 里一处、
   * 别处还有 —— 漏一个就是"某个按钮状态不对"。
   *
   * ## 2026-11-04：「跳过」→「指定强化」→ 又改成开关
   *
   * 上午按用户要求把「跳过」按钮换成「指定强化」按钮；下午用户又要求
   * 「【指定强化】功能放在下面，与自动停止一样启用与不启用，默认启用」
   * —— 它成了设置区里的开关，标题行不再有它，所以这里也不用管它了。
   *
   * @param {boolean} running - 引擎是否在跑
   * @param {string} [taskName] - 正在跑的任务名（暂时没用，留着给将来细分）
   */
  function setEnhanceRunning(running, taskName) {
    running = !!running;
    if (ENHANCE_STATE.btnRun) {
      ENHANCE_STATE.btnRun.disabled = running;
    }
    if (ENHANCE_STATE.btnStop) {
      ENHANCE_STATE.btnStop.disabled = !running;
    }
    //: 「继续」只在**暂停**时出现（引擎那边自动停止会暂停任务）——
    //: 这里没有暂停态的可靠信号，保守起见保持"运行中可点，
    //: 真实是否可继续由后端拒绝并回报错误"。见 enhanceAction('resume')。
    if (ENHANCE_STATE.btnResume) {
      ENHANCE_STATE.btnResume.disabled = !running;
    }
    void taskName;
  }

  //  导出（调试用）
  // ========================================================================

  window.ToolPanels = {
    TARGET_STATS: TARGET_STATS,
    DEFAULT_TARGET: DEFAULT_TARGET,
    MAX_COUNT: MAX_COUNT,
    COMBAT_STYLES: COMBAT_STYLES_FALLBACK,
    DEFAULT_COMBAT_STYLE: DEFAULT_COMBAT_STYLE,
    lib: LIB_STATE,
    change: CHANGE_STATE,
    combat: COMBAT_STATE,
    sweep: SWEEP_STATE,
    enhance: ENHANCE_STATE,
    build: BUILD_STATE,
    gacha: GACHA_STATE,

    // ══════════════════════════════════════════════════════════════════
    //  ★ 卡片构件 —— **配置页的「新增/编辑」弹框要用**（P7）
    //
    //  ``config.js`` 和这个文件是**两个独立的 IIFE 作用域**。
    //  不导出的话，``config.js`` 里调它们会报 ``xxx is not defined``；
    //  而且因为弹框是 async 打开的，这个异常**不会进 ``window.onerror``**
    //  —— 表现只是「点了「下一步」什么都没发生」。2026-11-02 真踩到。
    //
    //  旧界面本来就是共用的：``EchoProfileDialog`` 的设置区
    //  **就是** ``EchoSettingsEditor``（工具页那一份）。
    //  所以这里导出完全是照抄旧界面的依赖关系，不是新设计。
    // ══════════════════════════════════════════════════════════════════
    cfgCard: cfgCard,
    collapsibleCard: collapsibleCard,
    ENHANCE_ALL_STATS: ENHANCE_ALL_STATS,
    ENHANCE_CRIT: ENHANCE_CRIT,
    ENHANCE_CRIT_DMG: ENHANCE_CRIT_DMG,
    ENHANCE_MAX_CORE: ENHANCE_MAX_CORE,
    ENHANCE_DEFAULT_CRIT_MIN: ENHANCE_DEFAULT_CRIT_MIN,
    ENHANCE_DEFAULT_CRIT_DMG_MIN: ENHANCE_DEFAULT_CRIT_DMG_MIN,
    ENHANCE_DEFAULT_VALID: ENHANCE_DEFAULT_VALID
  };
})();
