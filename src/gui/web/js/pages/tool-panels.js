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

  const COMBAT_STATE = {
    style: null,
    styleHint: null,
    styles: null,
    shutdownCheck: null,
    shutdownEdit: null,
    shutdownState: null,
    reportHost: null,
    historyHost: null,
    stateLabel: null,
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
      text: '引擎：后台加载中 · 就绪后点「启动」开跑'
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
    const row = P.el('div', { class: 'cfg-inline-row' });
    COMBAT_STATE.style = Panels.select(
      COMBAT_STYLES_FALLBACK.map(function (s) {
        return { value: s.value, label: s.label };
      }),
      DEFAULT_COMBAT_STYLE
    );
    COMBAT_STATE.style.el.classList.add('cfg-select');
    row.appendChild(COMBAT_STATE.style.el);
    COMBAT_STATE.styleHint = P.el('div', { class: 'cfg-hint-inline' });
    row.appendChild(COMBAT_STATE.styleHint);
    COMBAT_STATE.style.el.addEventListener('change', combatUpdateStyleHint);
    built.body.appendChild(row);
    combatUpdateStyleHint();
    return built.card;
  }

  function combatUpdateStyleHint() {
    const hint = COMBAT_STATE.styleHint;
    const selected = COMBAT_STATE.style.get();
    const styles = COMBAT_STATE.styles || COMBAT_STYLES_FALLBACK;
    const hit = styles.find(function (s) { return s.value === selected; });
    if (hint) hint.textContent = hit && hit.desc ? hit.desc : '';
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
    if (!COMBAT_STATE.shutdownCheck.checked) {
      el.textContent = '未启用（不勾选就不会关机）。';
      return;
    }
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
      combatUpdateStyleHint();
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
      if (state === 'error') {
        label.textContent = '引擎：启动失败 —— ' +
          String(data.bootError || '详见日志');
      } else if (running && myTask && running !== myTask) {
        label.textContent = '引擎：被占用（正在跑 ' + running + '）';
      } else if (pending) {
        label.textContent = '引擎：启动中…（就绪后自动开始）';
      } else if (running) {
        label.textContent = '引擎：运行中 —— ' + running + ' · 点「停止」结束';
      } else if (state === 'booting') {
        label.textContent = '引擎：后台加载中…';
      } else {
        label.textContent = '引擎：就绪 · 点「启动」开始 4C 刷声骸';
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
      if (COMBAT_STATE.stateLabel) {
        COMBAT_STATE.stateLabel.textContent = '引擎：正在启动…';
      }
      const result = await P.call('runOkwwTask', JSON.stringify({
        taskKey: 'auto_combat'
      }));
      if (!result.ok) {
        if (COMBAT_STATE.stateLabel) {
          COMBAT_STATE.stateLabel.textContent = '引擎：启动请求失败（接口未就绪）';
        }
        return;
      }
      const data = result.data || {};
      if (data.ok === false) {
        if (COMBAT_STATE.stateLabel) {
          COMBAT_STATE.stateLabel.textContent = '引擎：' +
            String(data.message || data.reason || '启动失败');
        }
        return;
      }
      if (COMBAT_STATE.tracker) COMBAT_STATE.tracker.accept();
      return;
    }

    if (COMBAT_STATE.stateLabel) {
      COMBAT_STATE.stateLabel.textContent = '引擎：正在停止…';
    }
    const r = await P.call('stopOkwwTask');
    if (!r.ok) {
      if (COMBAT_STATE.stateLabel) {
        COMBAT_STATE.stateLabel.textContent = '引擎：停止失败（接口未就绪）';
      }
      return;
    }
    const d = r.data || {};
    if (d.ok === false && COMBAT_STATE.stateLabel) {
      COMBAT_STATE.stateLabel.textContent = '引擎：' +
        String(d.message || d.reason || '没有正在运行的任务');
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

    // ── ③ 数量说明（旧界面 L198-206，灰色、不渲染 markdown）──
    built.body.appendChild(P.el('div', {
      class: 'cfg-muted',
      text: '数量最多**成功调频**多少个（点 −/+ 每次 1 个；填 0 = 不限）。' +
        '已经是目标属性的声骸会被**跳过**（不会中断任务），' +
        '跳过的**不计入**数量；但如果过滤器里一直有它，' +
        '工具会停下来提醒你收紧过滤条件。'
    }));

    // ── ④ 运行 / 停止（各占一半）──
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
    CHANGE_STATE.stateLabel = P.el('div', {
      class: 'cfg-state',
      text: '引擎：后台加载中 · 就绪后点「运行」开始调频'
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
      if (state === 'error') {
        label.textContent = '引擎：启动失败 —— ' +
          String(data.bootError || '详见日志');
      } else if (running && myTask && running !== myTask) {
        label.textContent = '引擎：被占用（正在跑 ' + running + '）';
      } else if (pending) {
        label.textContent = '引擎：启动中…（就绪后自动开始）';
      } else if (running) {
        label.textContent = '引擎：运行中 —— ' + running + ' · 点「停止」结束';
      } else if (state === 'booting') {
        label.textContent = '引擎：后台加载中…';
      } else {
        label.textContent = '引擎：就绪 · 点「运行」开始调频';
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
      //: 先把界面上的参数存盘（引擎跑的时候读 tool_settings）
      await changeSaveSettings();

      CHANGE_STATE.tracker = Panels.trackRun({
        timeoutMs: 12000,
        onFinish: function () {},
        onGiveUp: function () {}
      });
      CHANGE_STATE.tracker.reset();

      if (CHANGE_STATE.stateLabel) {
        CHANGE_STATE.stateLabel.textContent = '引擎：正在启动…';
      }

      const result = await P.call('runOkwwTask', JSON.stringify({
        taskKey: 'echo_change',
        config: {
          '目标属性': CHANGE_STATE.target.get(),
          '数量上限': changeCountValue()
        }
      }));

      if (!result.ok) {
        if (CHANGE_STATE.stateLabel) {
          CHANGE_STATE.stateLabel.textContent =
            '引擎：启动请求失败（接口未就绪）';
        }
        return;
      }
      const data = result.data || {};
      if (data.ok === false) {
        if (CHANGE_STATE.stateLabel) {
          CHANGE_STATE.stateLabel.textContent = '引擎：' +
            String(data.message || data.reason || '启动失败');
        }
        return;
      }
      if (CHANGE_STATE.tracker) CHANGE_STATE.tracker.accept();
      return;
    }

    // ── 停止 ──
    if (CHANGE_STATE.stateLabel) {
      CHANGE_STATE.stateLabel.textContent = '引擎：正在停止…';
    }
    const r = await P.call('stopOkwwTask');
    if (!r.ok) {
      if (CHANGE_STATE.stateLabel) {
        CHANGE_STATE.stateLabel.textContent = '引擎：停止失败（接口未就绪）';
      }
      return;
    }
    const d = r.data || {};
    if (d.ok === false && CHANGE_STATE.stateLabel) {
      CHANGE_STATE.stateLabel.textContent = '引擎：' +
        String(d.message || d.reason || '没有正在运行的任务');
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
      text: '引擎：未启动 · 点「运行」会先加载引擎再开跑'
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

      if (SWEEP_STATE.stateLabel) {
        SWEEP_STATE.stateLabel.textContent = '引擎：正在启动…';
      }
      const result = await P.call('runOkwwTask', JSON.stringify({
        taskKey: 'nest_sweep'
      }));
      if (!result.ok) {
        if (SWEEP_STATE.stateLabel) {
          SWEEP_STATE.stateLabel.textContent =
            '引擎：启动请求失败（接口未就绪）';
        }
        return;
      }
      const data = result.data || {};
      if (data.ok === false) {
        if (SWEEP_STATE.stateLabel) {
          SWEEP_STATE.stateLabel.textContent = '引擎：' +
            String(data.message || data.reason || '启动失败');
        }
        return;
      }
      if (SWEEP_STATE.tracker) SWEEP_STATE.tracker.accept();
      return;
    }

    // ── 停止 ──
    if (SWEEP_STATE.stateLabel) {
      SWEEP_STATE.stateLabel.textContent = '引擎：正在停止…';
    }
    const r = await P.call('stopOkwwTask');
    if (!r.ok) {
      if (SWEEP_STATE.stateLabel) {
        SWEEP_STATE.stateLabel.textContent = '引擎：停止失败（接口未就绪）';
      }
      return;
    }
    const d = r.data || {};
    if (d.ok === false && SWEEP_STATE.stateLabel) {
      SWEEP_STATE.stateLabel.textContent = '引擎：' +
        String(d.message || d.reason || '没有正在运行的任务');
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
      if (state === 'error') {
        label.textContent = '引擎：启动失败 —— ' +
          String(data.bootError || '详见日志');
      } else if (running && myTask && running !== myTask) {
        label.textContent = '引擎：被占用（正在跑 ' + running + '）';
      } else if (pending) {
        label.textContent = '引擎：启动中…（就绪后自动开始）';
      } else if (running) {
        label.textContent = '引擎：运行中 —— ' + running + ' · 点「停止」结束';
      } else if (state === 'booting') {
        label.textContent = '引擎：后台加载中…';
      } else {
        label.textContent = '引擎：就绪 · 点「运行」开始扫荡';
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
    logHost: null,
    logOpen: false,
    //: ★ P6：① 登录卡（照抄旧界面外观）
    loginStatus: null,
    loginFields: null
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
    const panel = Panels.create(container, {
      key: 'character_build',
      title: nameOf(meta, '查询角色练度'),
      desc: (meta && meta.desc)
        || '登录库街区后拉取你账号里的角色与声骸数据，用来比对哪些角色的声骸属性需要重刷。',
      runLabel: '刷新',
      stopLabel: '',
      onRun: function () { buildLoad(); },
      onStop: function () { /* 只读页面，没有停止语义 */ }
    });
    BUILD_STATE.handle = panel;
    panel.stopBtn.style.display = 'none';

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
    //: ⚠ Web 版禁用 —— 登出会破坏旧界面保存的登录态
    const logoutBtn = P.button('退出登录', {
      size: 'sm',
      disabled: true,
      title: 'Web 版不支持登录/登出（会破坏旧界面保存的登录态）'
    });
    logoutBtn.dataset.action = 'logout';
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
        readonly: 'readonly'
      });
      //: ★ Web 版：只显示缓存值，不可编辑
      input.disabled = true;
      row.appendChild(input);
      loginCard.appendChild(row);
      BUILD_STATE.loginFields[item[0]] = input;
    }

    //: 按钮行（旧界面 btn_row L732-743）
    const loginBtnRow = P.el('div', { class: 'build-login-btns' });
    const loginBtn = P.button('登录', {
      size: 'sm',
      disabled: true,
      title: 'Web 版不支持登录（需要手机号 + 短信验证码）'
    });
    loginBtn.dataset.action = 'login';
    loginBtnRow.appendChild(loginBtn);

    const refreshBtn = P.button('刷新数据', {
      size: 'sm',
      title: '重新读取缓存',
      onClick: function () { buildLoad(true); }
    });
    refreshBtn.dataset.action = 'refresh';
    loginBtnRow.appendChild(refreshBtn);
    loginCard.appendChild(loginBtnRow);

    //: 说明（旧界面 L745-747，**逐字照抄**）
    loginCard.appendChild(P.el('div', {
      class: 'build-card-hint',
      text: '验证码在任意官方入口获取（库街区 App / 网页登录框）—— 两边通用。' +
        '　**登录后会自动拉取数据**；之后想重拉点「刷新数据」。'
    }));
    //: ★ Web 版补充说明（用户需要知道为什么不能登录）
    loginCard.appendChild(P.el('div', {
      class: 'build-card-hint build-cache-note',
      id: 'build-cache-note',
      text: 'Web 版不支持登录，字段来自上次在旧界面保存的缓存。' +
        '要更新请用旧界面：MYTOOLS_WEB_SHELL=0 python main.py'
    }));
    panel.body.appendChild(loginCard);

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
    panel.body.appendChild(overviewCard);

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
        //: 搜索框（旧界面 ``_search_edit``，宽 200）
        (function () {
          const box = P.el('div', { class: 'search build-search' });
          const icon = P.el('span', { class: 'nav-icon' });
          const m = App.icon('DOCUMENT');
          icon.style.maskImage = m;
          icon.style.webkitMaskImage = m;
          icon.style.backgroundColor = 'currentColor';
          box.appendChild(icon);
          const inp = P.el('input', {
            type: 'search',
            placeholder: '搜索角色名 / 属性 / 武器',
            onInput: function () {
              BUILD_STATE.filter = inp.value.trim().toLowerCase();
              buildRenderRoles();
            }
          });
          box.appendChild(inp);
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

    //: ★ 单行横向滚动（旧界面 L799-815）
    BUILD_STATE.rolesHost = P.el('div', {
      class: 'build-roles-scroll',
      id: 'build-roles'
    });
    rolesCard.appendChild(BUILD_STATE.rolesHost);
    panel.body.appendChild(rolesCard);

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
    panel.body.appendChild(detailCard);

    // ══════════════════════════════════════════════════════════════════════
    //  ⑤ 日志（默认折叠，旧界面 ``_log_toggle``）
    // ══════════════════════════════════════════════════════════════════════
    const logCard = P.el('div', { class: 'build-card card-glass' });
    const logHead = P.el('div', { class: 'build-card-head' }, [
      P.el('div', { class: 'build-card-title', text: '日志' }),
      P.el('div', { class: 'build-card-actions' }, [
        (function () {
          const btn = P.button('展开', {
            size: 'sm',
            onClick: function () {
              BUILD_STATE.logOpen = !BUILD_STATE.logOpen;
              if (BUILD_STATE.logHost) {
                BUILD_STATE.logHost.hidden = !BUILD_STATE.logOpen;
              }
              btn.textContent = BUILD_STATE.logOpen ? '收起' : '展开';
            }
          });
          return btn;
        })()
      ])
    ]);
    logCard.appendChild(logHead);
    BUILD_STATE.logHost = P.el('div', {
      class: 'log-box',
      id: 'build-log',
      style: 'height:120px;max-height:22vh',
      hidden: true
    });
    logCard.appendChild(BUILD_STATE.logHost);
    panel.body.appendChild(logCard);

    buildLoad();
    void app;
  });

  /** 往日志区写一行（旧界面 ``_log`` 是只读 QTextEdit）*/
  function buildLog(text, level) {
    const host = BUILD_STATE.logHost;
    if (!host) return;
    host.appendChild(P.el('div', {
      class: 'log-line',
      dataset: { level: level || 'info' }
    }, [
      P.el('span', { class: 'log-time', text: '' }),
      P.el('span', { class: 'log-text', text: String(text) })
    ]));
    while (host.childElementCount > 300) host.removeChild(host.firstElementChild);
    host.scrollTop = host.scrollHeight;
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
    const loggedIn = login.loggedIn != null ? !!login.loggedIn : !!login.loggedIn;

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
      //: 验证码 —— Web 版永远空着（登录做不了）
      const code = BUILD_STATE.loginFields.code;
      if (code) code.value = '';
    }
    //: 缓存说明（时间）
    setBuildCacheNote(
      'Web 版不支持登录，字段来自上次在旧界面保存的缓存。最后更新：' +
      String(data.updatedAt || '未知时间') +
      '；要更新请用旧界面：MYTOOLS_WEB_SHELL=0 python main.py'
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
  }

  function setBuildCacheNote(text) {
    const el = document.getElementById('build-cache-note');
    if (!el) return;
    //: ⚠ textContent（不是 innerHTML）—— 内容是用户可见的纯文本说明
    el.textContent = String(text);
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
      //: ⚠ 「有没有 issue」需要详情；缓存接口没给逐条 issues，
      //: 所以「达标/未达标」只能按「有没有详情数据」粗判 —— 见下方说明
      const issues = hasData ? false : true;

      if (choice === '未练') {
        if (!unleveled) return false;
      } else if (choice === '未达标') {
        if (unleveled || !issues) return false;
      } else if (choice === '达标') {
        if (unleveled || issues) return false;
      }

      if (keyword) {
        const hay = [role.name, role.attribute, role.weaponType, role.level]
          .join(' ').toLowerCase();
        if (hay.indexOf(keyword) < 0) return false;
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

    for (const role of shown) {
      host.appendChild(buildRoleTile(role, detailSet[String(role.roleId || '')]));
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

  function buildRenderDetail(host, data) {
    P.fill(host, null);
    const detail = data.detail || {};
    const standard = data.standard || {};

    const role = detail.role || {};
    const name = String(role.roleName || role.name || '');
    const level = role.level || detail.level || '';
    const chainList = Array.isArray(detail.chainList) ? detail.chainList : [];
    const unlocked = chainList.filter(function (c) { return c && c.unlocked; });
    const weapon = detail.weaponData || {};

    // ── 顶部：头像 + 名字 + 等级 / 共鸣链 ──
    const headRow = P.el('div', { class: 'build-detail-head' });
    const avatar = P.el('div', { class: 'build-tile-avatar' });
    if (role.roleIconUrl) {
      const img = P.el('img', { src: role.roleIconUrl, alt: '' });
      img.addEventListener('error', function () {
        P.fill(avatar, null);
        avatar.textContent = (name || '?').slice(0, 1);
        avatar.classList.add('has-initial-color');
      }, { once: true });
      avatar.appendChild(img);
    } else {
      avatar.textContent = (name || '?').slice(0, 1);
      avatar.classList.add('has-initial-color');
    }
    headRow.appendChild(avatar);

    const headText = P.el('div', { class: 'build-detail-headtext' });
    headText.appendChild(P.el('div', {
      class: 'build-detail-name',
      text: name || String(data.roleId || '')
    }));
    const subBits = [];
    if (level) subBits.push('Lv.' + level);
    if (chainList.length) {
      subBits.push('共鸣链 ' + unlocked.length + '/' + chainList.length);
    }
    if (weapon.weaponName || weapon.name) {
      subBits.push(String(weapon.weaponName || weapon.name));
    }
    if (subBits.length) {
      headText.appendChild(P.el('div', {
        class: 'build-detail-sub',
        text: subBits.join(' · ')
      }));
    }
    headRow.appendChild(headText);
    host.appendChild(headRow);

    // ── 养成标准（`standard`）—— 旧界面在这块画雷达图，这里给数值 ──
    if (standard && typeof standard === 'object' && Object.keys(standard).length) {
      const attrs = Array.isArray(standard.attrs) ? standard.attrs : [];
      if (attrs.length) {
        const grid = P.el('div', { class: 'build-attr-grid' });
        for (const attr of attrs) {
          if (!attr || typeof attr !== 'object') continue;
          const label = String(attr.name || attr.key || '');
          const want = attr.value != null ? String(attr.value) : '';
          const got = attr.current != null ? String(attr.current) : '';
          if (!label) continue;
          grid.appendChild(P.el('div', { class: 'build-attr-key', text: label }));
          grid.appendChild(P.el('div', {
            class: 'build-attr-val',
            text: got ? got + ' / 推荐 ' + want : (want ? '推荐 ' + want : '')
          }));
        }
        if (grid.childElementCount) host.appendChild(grid);
      }
    }

    // ── 共鸣链（已解锁的逐条列出）──
    if (unlocked.length) {
      host.appendChild(P.el('div', {
        class: 'build-detail-section-title',
        text: '共鸣链（已解锁 ' + unlocked.length + '/' + chainList.length + '）'
      }));
      const list = P.el('div', { class: 'build-chain-list' });
      for (const chain of unlocked) {
        list.appendChild(P.el('div', { class: 'build-chain' }, [
          P.el('span', {
            class: 'sweep-tag',
            dataset: { kind: 'nest' },
            text: String(chain.order || '')
          }),
          P.el('div', { class: 'build-chain-body' }, [
            P.el('div', { class: 'build-chain-name', text: chain.name || '' }),
            P.el('div', {
              class: 'build-chain-desc',
              text: chain.description || ''
            })
          ])
        ]));
      }
      host.appendChild(list);
    }

    // ── ★ 明确留的缺口：图文详情不做 ──
    host.appendChild(P.el('div', {
      class: 'build-detail-missing',
      text: '完整图文详情（属性雷达 / 武器立绘 / 声骸套装图 / 技能说明）' +
            '请在旧界面查看：MYTOOLS_WEB_SHELL=0'
    }));
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
    history: []
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
    //: ⚠ 后端**还没有** ``grabGachaLink``（旧界面是 ``GrabLinkThread``，
    //: 读本机日志 + 可能全盘扫，要几十秒，必须在 Python 线程里跑）。
    //: 这里如实告诉用户，不假装在读。
    const result = await P.call('grabGachaLink');
    if (GACHA_STATE.grabBtn) GACHA_STATE.grabBtn.disabled = false;

    if (!result.ok) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent =
          '自动获取还没做（缺 grabGachaLink 接口）—— ' +
          '请按上面的②手动复制粘贴链接，或回旧界面点「获取抽卡记录」。';
      }
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      if (GACHA_STATE.statusEl) {
        GACHA_STATE.statusEl.textContent = String(data.message ||
          '没从本机日志里读到链接 —— 请按上面的②手动复制粘贴。');
      }
      return;
    }
    if (data.link && GACHA_STATE.linkInput) {
      GACHA_STATE.linkInput.value = String(data.link);
    }
    if (GACHA_STATE.statusEl) {
      GACHA_STATE.statusEl.textContent = '已读到链接，点「分析」开始。';
    }
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
      GACHA_STATE.statusEl.textContent =
        '显示的是本地累计的 ' + (data.total != null ? data.total : 0) +
        ' 抽' + (tail ? '（' + tail + '）' : '') + '。' +
        '点「分析」可以把最新记录并进来。';
    }

    gachaRenderOverview({
      luck: data.luck,
      total: data.total,
      average: data.average,
      notUpRate: data.notUpRate,
      fiveCount: data.fiveCount,
      upCharAverage: data.upCharAverage,
      upWeaponAverage: data.upWeaponAverage
    });

    //: 抽卡总结（旧界面 ``summary_note``）
    if (GACHA_STATE.summaryNote) {
      GACHA_STATE.summaryNote.textContent = String(data.summary || '');
    }

    //: 头像网格（带 ×N 角标）
    const cards = GACHA_STATE.cardsHost;
    if (cards) {
      P.fill(cards, null);
      const list = Array.isArray(data.fiveStarCards) ? data.fiveStarCards : [];
      for (const item of list) {
        cards.appendChild(gachaAvatarCard(item));
      }
      if (!list.length) {
        cards.appendChild(P.el('div', {
          class: 'gk-note', text: '这次分析没有五星记录。'
        }));
      }
    }

    //: 分卡池
    gachaRenderPools(Array.isArray(data.pools) ? data.pools : []);
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
  //    self.skip_button   = ... "跳过"
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
    validStepper: null,
    coreSummary: null,
    reportHost: null,
    historyHost: null,
    btnRun: null,
    btnResume: null,
    btnStop: null,
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
    const btnSkip = P.button('跳过', {
      size: 'sm',
      title: '强化途中遇到不想要的声骸，按一下换下一个',
      onClick: function () { enhanceAction('skip'); }
    });
    const btnReset = P.button('恢复默认', {
      size: 'sm',
      onClick: function () { enhanceResetSettings(); }
    });
    for (const b of [ENHANCE_STATE.btnRun, ENHANCE_STATE.btnResume,
                     ENHANCE_STATE.btnStop, btnSkip, btnReset]) {
      titleRow.appendChild(b);
    }
    container.appendChild(titleRow);

    // ══════════════════════════════════════════════════════════════════════
    //  说明（旧界面 L494-504，**逐字照抄**，含日志路径）
    // ══════════════════════════════════════════════════════════════════════
    container.appendChild(P.el('div', {
      class: 'enh-intro',
      text: '在背包 → 声骸界面用过滤器筛好、按等级升序排序，再点运行。' +
        '强化流程由 ok-ww 引擎执行（与「4C 自动战斗」同一个引擎，' +
        '后台按键不抢前台）：符合条件的上锁保留，不符合条件的自动弃置。\n' +
        '运行日志按日期落盘：data/okww/logs' +
        '（出问题把当天那个文件发过来即可）'
    }));

    // ══════════════════════════════════════════════════════════════════════
    //  设置编辑器（6 张卡，``settings_editor.EchoSettingsEditor``）
    // ══════════════════════════════════════════════════════════════════════
    const editor = P.el('div', { class: 'enh-editor' });
    editor.appendChild(buildEnhanceCoreCard());
    editor.appendChild(buildEnhanceCritRow());      // ★ 裸行，没有卡片包裹
    editor.appendChild(buildEnhanceMaxrollCard());
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

    enhanceLoadSettings();
    enhanceLoadHistory();
    void app; void meta;
  });

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
      cb.disabled = (custom >= limit) && !cb.checked;
    }
    //: ★ 摘要行（收起也可见）—— 旧界面 ``summary_label``
    const names = ENHANCE_ALL_STATS.filter(function (s) {
      const cb = ENHANCE_STATE.coreBoxes[s];
      return cb && cb.checked;
    });
    if (ENHANCE_STATE.coreSummary) {
      ENHANCE_STATE.coreSummary.setSummary(
        '已勾选 ' + checked + ' / ' + ENHANCE_MAX_CORE + ' 条：' +
        (names.join('、') || '（无）'));
    }
  }

  // ── 双爆下限（★ **裸行**，没有卡片包裹 —— 旧界面 ``_build_crit_card``）──
  function buildEnhanceCritRow() {
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
    row.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    //: 开关（旧界面 SwitchButton，圆角药丸形）
    const sw = P.toggle('启用', true, function (on) { enhanceOnCritToggle(on); },
      { onText: '启用', offText: '不启用' });
    row.appendChild(sw);
    ENHANCE_STATE.critSwitch = sw.querySelector('input[type="checkbox"]');
    return row;
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
    left.appendChild(P.el('div', {
      class: 'enh-switch-hint',
      text: '出现满值词条（暴击 10.5 / 爆伤 21）时：不看别的条件，' +
        '一律强化到满级并上锁，不弃置。判定排在双爆下限与有效词条之前 —— ' +
        '出了满值就保住。'
    }));
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
    const grid = P.el('div', { class: 'enh-core-grid' });
    for (const stat of ENHANCE_ALL_STATS) {
      if (stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG) continue;
      const lbl = P.el('label', { class: 'enh-check' });
      const cb = P.el('input', { type: 'checkbox' });
      cb.addEventListener('change', function () {
        const picked = ENHANCE_ALL_STATS.filter(function (s) {
          const box = ENHANCE_STATE.optionalBoxes[s];
          return box && box.checked;
        });
        coll.setSummary(picked.length
          ? '已选 ' + picked.length + ' 条：' + picked.join('、')
          : '未选');
      });
      lbl.appendChild(cb);
      lbl.appendChild(P.el('span', { text: stat }));
      grid.appendChild(lbl);
      ENHANCE_STATE.optionalBoxes[stat] = cb;
    }
    coll.contentEl.appendChild(grid);
    return coll.card;
  }

  // ── 有效词条（裸行）──────────────────────────────────────────────────
  function buildEnhanceValidCard() {
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
    row.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    return row;
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
    const result = await P.call('getToolSettings', 'echo_enhance');
    if (!result.ok || !result.data || result.data.ok === false) return;
    const s = result.data.settings || {};

    //: 核心属性
    const core = Array.isArray(s.core_stats) ? s.core_stats : null;
    if (core) {
      for (const stat of ENHANCE_ALL_STATS) {
        const cb = ENHANCE_STATE.coreBoxes[stat];
        if (!cb) continue;
        const forced = stat === ENHANCE_CRIT || stat === ENHANCE_CRIT_DMG;
        cb.checked = forced || core.indexOf(stat) >= 0;
      }
      enhanceOnCoreChange();
    }
    //: 可选属性
    const optional = Array.isArray(s.optional_stats) ? s.optional_stats : [];
    for (const stat of ENHANCE_ALL_STATS) {
      const cb = ENHANCE_STATE.optionalBoxes[stat];
      if (cb) cb.checked = optional.indexOf(stat) >= 0;
    }
    //: 双爆下限
    if (ENHANCE_STATE.critField && s.crit_min != null) {
      ENHANCE_STATE.critField.set(s.crit_min);
    }
    if (ENHANCE_STATE.critDmgField && s.crit_dmg_min != null) {
      ENHANCE_STATE.critDmgField.set(s.crit_dmg_min);
    }
    const critOn = s.enable_crit_check !== false;
    if (ENHANCE_STATE.critSwitch) {
      ENHANCE_STATE.critSwitch.checked = critOn;
      enhanceOnCritToggle(critOn);
    }
    if (ENHANCE_STATE.maxrollSwitch) {
      ENHANCE_STATE.maxrollSwitch.checked = s.enable_max_roll_lock !== false;
    }
    if (ENHANCE_STATE.autostopSwitch) {
      ENHANCE_STATE.autostopSwitch.checked = s.enable_auto_stop !== false;
    }
    if (ENHANCE_STATE.validStepper && s.min_valid_count != null) {
      ENHANCE_STATE.validStepper.set(s.min_valid_count);
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
    enhanceOnCoreChange();
  }

  /** 运行 / 继续 / 停止 / 跳过 */
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

    if (action === 'skip') {
      const r = await P.call('okwwSkipEcho');
      if (!r.ok) {
        fail('跳过失败（接口未就绪）');
        return;
      }
      const d = r.data || {};
      if (d.ok === false) {
        fail('跳过失败：' + String(d.message || d.reason || '引擎没有在跑'));
      }
      return;
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
      if (ENHANCE_STATE.btnStop) ENHANCE_STATE.btnStop.disabled = true;
      return;
    }

    // ── 运行 ──
    if (ENHANCE_STATE.btnRun) ENHANCE_STATE.btnRun.disabled = true;
    if (ENHANCE_STATE.btnStop) ENHANCE_STATE.btnStop.disabled = false;

    const result = await P.call('runTask', 'echo_enhance');
    const revert = function () {
      if (ENHANCE_STATE.btnRun) ENHANCE_STATE.btnRun.disabled = false;
      if (ENHANCE_STATE.btnStop) ENHANCE_STATE.btnStop.disabled = true;
    };

    if (!result.ok) {
      revert();
      fail('运行失败（接口未就绪）');
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      revert();
      fail('运行失败：' + String(data.message || data.reason || '后端拒绝'));
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
      if (ENHANCE_STATE.btnRun) {
        ENHANCE_STATE.btnRun.disabled = !!running;
      }
      if (ENHANCE_STATE.btnStop) {
        ENHANCE_STATE.btnStop.disabled = !running;
      }
      if (!running) {
        clearInterval(ENHANCE_STATE.watchTimer);
        ENHANCE_STATE.watchTimer = null;
      }
    }, 1500);
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
