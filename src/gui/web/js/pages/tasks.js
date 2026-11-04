/* ══════════════════════════════════════════════════════════════════════════
   pages/tasks.js —— 任务页（2026-11-03 按 main 分支重做）

   ## 为什么重做

   用户圈了页面顶部两块（蓝色提示条 + 深色「运行面板」大卡）并写：
   「**删掉，任务请按main分支那样做**」。

   原来的 web 版是「顶部一条说明 + 一个全局运行面板 + 下面一列卡片」，
   而 main 分支（``src/gui/tasks_interface.py``）是：

   .. code:: text

     任务流程                                       [＋ 新增任务流程]
     把工具和配置编成一条流程，按顺序自动跑。点「新增任务流程」开始编排。

     ┌──────────────────────────────────────────────────────────────┐
     │ (头像48) 秧秧·玄翎-声骸自动强化（小毕业 43311）                │
     │          开始 → 配置 → 配置 → 工具 → 结束                      │
     │          空闲                              [删除][运行][停止]   │
     └──────────────────────────────────────────────────────────────┘

     运行报告
     ┌─ 本轮报告 ───────────────────────────────────────────────────┐
     └──────────────────────────────────────────────────────────────┘
     ┌─ 所有任务累计 ────────────────────────────────[清零]─────────┐
     └──────────────────────────────────────────────────────────────┘

     运行日志（web 版独有，main 的日志在后台/消息里）

   **状态在每一行里**（main 的 ``status_label``），没有全局运行面板 ——
   因为同一时刻只允许跑一条流程，一个面板也表达不了"哪条在跑"。

   ## ★ 2026-11-04 用户第二次圈图（两处改动）

   图 A 圈住整行批注「**任务改成只有运行、停止、删除**」：
   行卡按钮从五个砍成三个，去掉「详情」和「修改」。

   图 B 圈住「可用组件（点一下加到下面 →）」批注「**增加任务类型 ...
   还有选择是否成套，44111、43311 这些都东西呢？**」：
   「＋ 新增任务流程」改成**选项式**（任务类型 + 角色 + 属性级别 +
   是否成套，保存后自动生成整条流程），手动编排编辑器整个删掉。

   所以下面的对照表只剩「新增」，没有「修改 / 详情」了。

   ## 和 main 的对应关系

   ==============================  ==================================
   main（Qt）                       这里（HTML）
   ==============================  ==================================
   ``TaskRowCard``                 :func:`buildFlowCard`
   ``_run`` / ``_stop``            :func:`startFlow` / :func:`stopTask`
   ``_delete``                     :func:`deleteFlow`
   ``NewFlowDialog``               :func:`openNewFlowDialog`
   ``_build_report_section``       :func:`buildReportSection`
   ``note_running``（互斥）         :func:`syncRowStates`
   ==============================  ==================================

   ## 日志区为什么留着

   main 分支没有页面内日志（日志进 ``notify`` 和文件），但 web 版一直是
   「跑的时候能看见每一步」，而且 ``pages_verify`` 的 T3/T4/T5 就靠这块
   做回归。所以保留，样式不变。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  if (!window.App) {
    console.error('[tasks] app.js 没先加载');
    return;
  }
  if (!window.Pages) {
    console.error('[tasks] _shared.js 没先加载');
    return;
  }

  const P = window.Pages;
  const App = window.App;

  /** 日志最多留多少行（超出丢最老的，防长时间运行把内存吃满）*/
  const MAX_LOG_LINES = 800;

  /** 流程名自动后缀 —— 和 ``src/gui/config_names.FLOW_NAME_SUFFIX`` 一致 */
  const FLOW_NAME_SUFFIX = '-声骸自动强化';

  /** 配置类型名 —— 和 ``src/gui/config_names`` 一致 */
  const TYPE_LOADOUT = '角色声骸筛选';
  const TYPE_ECHO_PROFILE = '角色声骸强化';

  /** 步骤类型 —— 和 ``src/core/tasks.py`` 一致 */
  const STEP_TOOL = 'tool';
  const STEP_CONFIG = 'config';
  const STEP_START = 'start';
  const STEP_END = 'end';

  /** 名字末尾的级别括号（「（小毕业 43311）」这种），剥角色名时要先去掉 */
  const LEVEL_RE = /（(?:小毕业|大毕业|完美毕业)(?:\s*(?:43311|44111))?）\s*$/;

  //: ★ 2026-11-04 用户：「任务完成后自动关机」
  //:
  //: 设置**分开存**（后端 ``TASK_SHUTDOWN_KEY = 'tasks'``），不复用 4C 页的
  //: ``auto_combat`` 那套 —— 两个页面各有各的开关，混在一起会出现
  //: 「在任务页关了，4C 工具页的定时关机也跟着没了」。
  /** 默认多少分钟后关机（与后端 ``getTaskShutdown`` 的 defaultMinutes 同值）*/
  const SHUTDOWN_DEFAULT_MINUTES = 30;

  const state = {
    /** 当前运行的 key（空 = 空闲）*/
    running: '',
    /** 当前进度 0~100（日志区不再画进度条，仍保留给状态行用）*/
    progress: 0,
    /** 当前步骤描述 */
    step: '',
    /** 日志行数 */
    logCount: 0,
    /** 是否自动滚动到底 */
    autoScroll: true,
    /** 流程列表数据 */
    flows: [],
    /** 数据来源：'flows'（真流程）| 'tools'（降级）*/
    source: 'flows',
    /** 运行报告：{round, total} */
    report: { round: null, total: null },
    /**
     * 任务完成后自动关机：{enabled, minutes, active, remainingText, flowName}。
     *
     * ``active`` 为真时表示「某条流程刚跑完，正在倒计时关机」——
     * 这时卡片上要出现「取消关机」按钮和倒计时文本。
     */
    shutdown: null,
    /** 角色候选缓存（编辑器用；null = 还没拉过）*/
    characterPool: null,
    /** 各个 DOM 引用 */
    dom: {}
  };

  /** 弹框的临时状态（新增任务用；options/newFlow 在拿到后端选项后填）*/
  const EDITOR = {
    root: null,
    flow: null,
    steps: [],
    character: '',
    escHandler: null,
    /** getNewFlowOptions 的返回体*/
    options: null,
    /** 新增弹框里的四个控件引用（别靠行序号去 DOM 里翻）*/
    newFlow: null
  };

  P.ready(function () {
    App.registerPage('tasks', renderTasks);
  });

  // ════════════════════════════════════════════════════════════════════════
  //  小工具：名字 / 类型
  // ════════════════════════════════════════════════════════════════════════

  /** 类型名 → 名字后缀（「角色声骸强化」→ ``-声骸强化``，照抄 config_names）*/
  function typeSuffix(typeName) {
    const name = String(typeName || '').trim();
    if (!name) return '';
    const head = name.indexOf('角色') === 0 ? name.slice(2) : name;
    return '-' + head;
  }

  /** 配置的显示名（``绯雪-声骸强化``）—— 和配置页一个字不差 */
  function configDisplayName(typeName, character) {
    const who = String(character || '').trim();
    if (!who) return '(未填角色)';
    return who + typeSuffix(typeName);
  }

  /** 流程名 → 角色名（剥级别括号 + 剥后缀），照抄 ``flow_character_of`` */
  function flowCharacterOf(name) {
    let text = String(name || '').trim();
    if (!text) return '';
    text = text.replace(LEVEL_RE, '').trim();
    if (!text) return '';
    if (text.length > FLOW_NAME_SUFFIX.length &&
        text.slice(-FLOW_NAME_SUFFIX.length) === FLOW_NAME_SUFFIX) {
      return text.slice(0, -FLOW_NAME_SUFFIX.length);
    }
    //: 老式后缀（没有连字符）—— 存量流程名大多是手打的这种
    const legacy = ['声骸自动强化', '声骸强化'];
    for (let i = 0; i < legacy.length; i += 1) {
      const tail = legacy[i];
      if (text.length > tail.length && text.slice(-tail.length) === tail) {
        return text.slice(0, -tail.length);
      }
    }
    return text;
  }

  /** 角色名 → 流程名（已经带后缀就原样返回，幂等），照抄 ``flow_name_for`` */
  function flowNameFor(character) {
    const who = String(character || '').trim();
    if (!who) return '';
    if (flowCharacterOf(who) !== who) return who;
    return who + FLOW_NAME_SUFFIX;
  }

  /** 步骤的中文类型（编辑区、详情里显示用）*/
  function stepTypeText(type) {
    if (type === STEP_TOOL) return '工具';
    if (type === STEP_CONFIG) return '配置';
    if (type === STEP_START) return '开始';
    if (type === STEP_END) return '结束';
    return '步骤';
  }

  function rowKey(flow) {
    return String(flow.id || flow.key || flow.name || '');
  }

  // ════════════════════════════════════════════════════════════════════════
  //  页面渲染
  // ════════════════════════════════════════════════════════════════════════

  async function renderTasks(section, app) {
    // ── 页头（照 main：标题 + 说明 + 右上「＋ 新增任务流程」）──
    const head = P.pageHead({
      title: '任务流程',
      subtitle: '把工具和配置编成一条流程，按顺序自动跑。点「新增任务流程」开始编排。'
    });

    const addBtn = P.button('＋ 新增任务流程', {
      kind: 'primary',
      size: 'sm',
      onClick: function () { openNewFlowDialog(app); }
    });
    addBtn.dataset.action = 'add-flow';

    const refreshBtn = P.button('刷新', {
      icon: 'HISTORY',
      size: 'sm',
      onClick: function () { reload(app, refreshBtn); }
    });

    head.actions.appendChild(addBtn);
    head.actions.appendChild(refreshBtn);
    section.appendChild(head.head);

    // ── ① 流程列表（状态在每一行里，没有全局运行面板）──
    const listHost = P.el('div', { class: 'section' });
    section.appendChild(listHost);

    // ── ② 运行报告（照 main：紧跟在流程列表下面，两块卡）──
    //
    //: ⚠ 顺序是**流程列表 → 运行报告 → 运行日志**。
    //: main 分支没有页面内日志，报告直接贴着行卡；如果日志排在前面，
    //: 那 300px 高的日志窗会把报告整个推到折叠线以下 —— 用户看不到
    //: 刚跑完的结果，等于白做。日志仍然留在最后（回归脚本要靠它）。
    section.appendChild(buildReportSection(app));

    // ── ②b 任务完成后自动关机（用户 2026-11-04）──
    section.appendChild(buildShutdownCard(app));

    // ── ③ 运行日志（web 版独有；页面既有能力，回归脚本也依赖）──
    section.appendChild(buildLogPanel());

    state.dom.listHost = listHost;
    state.dom.logBox = section.querySelector('#task-log');
    state.dom.logCount = section.querySelector('#task-log-count');

    //: ★ 把 app.js 的日志入口接到本页的实现上（见 hookGlobalLog 的说明）
    hookGlobalLog();

    //: 从 app 的全局状态恢复（比如在别处点了运行再切过来）
    restoreState(app);

    // ── 事件订阅 ──
    bindEvents(section, app);

    // ── 拉数据 ──
    await reload(app, refreshBtn);
    await refreshReport(true);
    await refreshShutdown(true);

    //: 页面刚渲染完，给一条定位提示（用户至少知道日志在等什么）
    if (!state.logCount) {
      appendLog('就绪 —— 随便点一条流程的「运行」，日志会实时出现在这里', 'debug');
    }
  }

  // ────────────────────────────────────────────────────────────────────────
  //  运行报告（main: _build_report_section）
  // ────────────────────────────────────────────────────────────────────────
  function buildReportSection(app) {
    const holder = P.el('div', { class: 'section task-report' });
    holder.appendChild(P.el('div', { class: 'section-title', text: '运行报告' }));

    // ── 本轮报告 ──
    const round = buildReportCard('本轮报告', null);
    state.dom.roundBody = round.body;
    holder.appendChild(round.card);

    // ── 所有任务累计（右上角「清零」）──
    const resetBtn = P.button('清零', {
      size: 'sm',
      title: '把所有任务的累计统计归零（本轮报告不受影响）',
      onClick: function () { resetTotal(app); }
    });
    resetBtn.dataset.action = 'reset-report';
    const total = buildReportCard('所有任务累计', resetBtn);
    state.dom.totalBody = total.body;
    holder.appendChild(total.card);

    return holder;
  }

  function buildReportCard(title, action) {
    const card = P.el('div', { class: 'card task-report-card' });
    const head = P.el('div', { class: 'task-report-head' }, [
      P.el('div', { class: 'task-report-title', text: title }),
      P.el('div', { style: 'flex:1 1 auto' }),
      action || null
    ]);
    card.appendChild(head);
    const body = P.el('div', { class: 'task-report-body' });
    card.appendChild(body);
    return { card: card, body: body };
  }

  /**
   * 读并重画两块报告卡。
   *
   * 文案照抄 main 的 ``_refresh_report``，只有一处**故意不同**：
   * 本轮报告 ``items`` 为空（比如前置检查没过）时，Qt 版显示「还没有跑过」
   * —— 那会让用户以为按钮没生效。这里如果有 ``note`` 就照实说出来。
   */
  async function refreshReport(quiet) {
    const result = await P.call('getRunReport');
    if (!result.ok) {
      if (!quiet) appendLog('✗ 读取运行报告失败（接口未就绪）', 'warn');
      return;
    }
    const data = result.data || {};
    state.report = {
      round: data.round || null,
      total: data.total || null
    };
    paintReport();
  }

  function paintReport() {
    const round = state.report.round || null;
    const roundBody = state.dom.roundBody;
    if (roundBody) {
      let text;
      if (!round) {
        text = '还没有跑过。点某条流程的「运行」后，这里显示本轮结果。';
      } else if (round.empty) {
        text = (round.note
          ? '这一轮没有跑出结果：' + round.note
          : '还没有跑过。点某条流程的「运行」后，这里显示本轮结果。');
      } else {
        text = String(round.flowName || '（未命名）') + '：' + String(round.summary || '');
        const lines = Array.isArray(round.lines) ? round.lines : [];
        if (lines.length) text += '\n' + lines.join('\n');
        if (round.ok === false && round.note) text += '\n（' + round.note + '）';
      }
      roundBody.textContent = text;
    }

    const total = state.report.total || null;
    const totalBody = state.dom.totalBody;
    if (totalBody) {
      if (!total || total.empty) {
        totalBody.textContent = '还没有累计数据。';
      } else {
        let text = String(total.summary || '') + ' · 共 ' + (total.rounds || 0) + ' 轮';
        if (total.updatedAt) text += ' · 最后一次 ' + total.updatedAt;
        totalBody.textContent = text;
      }
    }
  }

  async function resetTotal(app) {
    const answer = await confirmDialog({
      title: '清零累计统计',
      message: '把所有任务的累计锁定 / 弃置数量归零？这一步不可撤销。',
      confirmLabel: '清零',
      danger: false
    });
    if (!answer) return;
    const result = await P.call('resetRunReport');
    if (!result.ok || (result.data && result.data.ok === false)) {
      const msg = (result.data && result.data.message) ||
        (result.missing ? '桥接缺少 resetRunReport 方法' : '清零失败');
      appendLog('✗ ' + msg, 'error');
      return;
    }
    appendLog('✔ 累计统计已清零', 'ok');
    await refreshReport(true);
    void app;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  日志面板
  // ────────────────────────────────────────────────────────────────────────
  function buildLogPanel() {
    const panel = P.el('div', { class: 'section' });

    const titleRow = P.el('div', {
      style: 'display:flex;align-items:center;gap:10px;margin-bottom:9px'
    }, [
      P.el('div', { class: 'section-title', style: 'margin:0', text: '运行日志' }),
      P.el('div', { class: 'log-count', id: 'task-log-count', text: '0 行' }),
      P.el('div', { style: 'margin-left:auto;display:flex;gap:7px;align-items:center' }, [
        P.el('label', {
          class: 'sw',
          for: 'task-autoscroll'
        }, [
          (function () {
            const input = P.el('input', {
              type: 'checkbox',
              id: 'task-autoscroll',
              class: 'sw-input'
            });
            input.checked = true;
            input.addEventListener('change', function () {
              state.autoScroll = input.checked;
              if (state.autoScroll) scrollLogToEnd();
            });
            return input;
          })(),
          P.el('span', { class: 'sw-track' }, [P.el('span', { class: 'sw-thumb' })]),
          P.el('span', { class: 'sw-label', text: '自动滚动' })
        ])
      ])
    ]);
    panel.appendChild(titleRow);

    //: ★ id 必须叫 task-log —— app.js 的 App.appendLog 也是找这个 id
    panel.appendChild(P.el('div', { class: 'log-box', id: 'task-log' }));
    return panel;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  任务完成后自动关机（用户 2026-11-04「任务完成后自动关机」）
  // ────────────────────────────────────────────────────────────────────────

  /**
   * 建「完成后自动关机」卡。
   *
   * ## 为什么不做成 main 那种「运行时才开始倒计时」
   *
   * Qt 版 AutoCombat 工具页是「点启动 → 立刻开始倒计时 N 分钟关机」。
   * 任务页要的是另一回事：**流程跑完**才开始倒计时 —— 「我挂机让它跑，
   * 跑完把电脑关了」。所以计时器在**后端**（流程结束的那一刻起算），
   * 页面只负责显示剩余时间和「取消关机」。
   *
   * 后端为什么不用页面来计时：用户随时会切走页面（``App.go`` 只切显示，
   * JS 定时器还在，但页面被删掉重建就没人了），而关机必须按时发生。
   */
  function buildShutdownCard(app) {
    const holder = P.el('div', { class: 'section task-shutdown' });
    holder.appendChild(P.el('div', { class: 'section-title', text: '完成后自动关机' }));

    const card = P.el('div', { class: 'card task-report-card task-shutdown-card' });
    const head = P.el('div', { class: 'task-report-head' }, [
      P.el('div', { class: 'task-report-title', text: '流程跑完后自动关机' })
    ]);
    card.appendChild(head);

    //: 开关 + 分钟输入 + 说明，一行摆开
    const row = P.el('div', { class: 'task-shutdown-row' });

    const toggleEl = P.toggle('启用', false, function (checked) {
      state.shutdown = Object.assign({}, state.shutdown || {}, {
        enabled: checked,
        minutes: shutdownMinutes()
      });
      //: 打开时把分钟框也叫醒，否则用户点了开关却改不了数字
      if (state.dom.shutdownMinutes) {
        state.dom.shutdownMinutes.input.disabled = !checked;
      }
      saveShutdown(app, false);
    }, { onText: '启用', offText: '不启用' });
    toggleEl.dataset.action = 'toggle-shutdown';
    row.appendChild(toggleEl);

    //: 分钟数用 numberInput（和项目其它数字框一致：− N ＋）
    const minutesInput = window.Panels.numberInput(
      SHUTDOWN_DEFAULT_MINUTES,
      { min: 1, max: 1440, clampOnBlur: true }
    );
    minutesInput.input.id = 'task-shutdown-minutes';
    minutesInput.input.classList.add('task-shutdown-minutes');
    minutesInput.input.disabled = true;
    //: change 才存盘 —— 每敲一个数字就写一次文件太吵
    minutesInput.input.addEventListener('change', function () {
      if (state.shutdown && state.shutdown.enabled) saveShutdown(app, true);
    });
    row.appendChild(minutesInput.el);

    row.appendChild(P.el('div', { class: 'task-shutdown-unit', text: '分钟后关机' }));
    card.appendChild(row);

    const hint = P.el('div', { class: 'task-shutdown-hint' });
    card.appendChild(hint);

    //: 倒计时行（没有在倒计时就藏起来）
    const countdown = P.el('div', { class: 'task-shutdown-countdown hidden' });
    const countdownText = P.el('div', { class: 'task-shutdown-countdown-text' });
    countdown.appendChild(countdownText);
    const cancelBtn = P.button('取消关机', {
      size: 'sm',
      kind: 'danger',
      onClick: function () { cancelShutdown(app); }
    });
    cancelBtn.dataset.action = 'cancel-shutdown';
    countdown.appendChild(cancelBtn);
    card.appendChild(countdown);

    holder.appendChild(card);

    state.dom.shutdownToggle = toggleEl;
    state.dom.shutdownMinutes = minutesInput;
    state.dom.shutdownHint = hint;
    state.dom.shutdownCountdown = countdown;
    state.dom.shutdownCountdownText = countdownText;

    //: 先画成「读取中」，``refreshShutdown`` 回来后覆盖
    hint.textContent = '正在读取设置…';
    return holder;
  }

  /** 分钟框当前值（夹 1~1440，非法给默认值）*/
  function shutdownMinutes() {
    const input = state.dom.shutdownMinutes && state.dom.shutdownMinutes.input;
    const raw = input ? String(input.value || '').trim() : '';
    const n = parseInt(raw, 10);
    if (!isFinite(n) || n <= 0) return SHUTDOWN_DEFAULT_MINUTES;
    return Math.max(1, Math.min(1440, n));
  }

  /** 读后端设置 + 当前倒计时状态，重画卡片 */
  async function refreshShutdown(quiet) {
    const result = await P.call('getTaskShutdown');
    if (!result.ok) {
      if (!quiet) appendLog('✗ 读取关机设置失败（接口未就绪）', 'warn');
      return;
    }
    const data = result.data || {};
    state.shutdown = {
      enabled: !!data.enabled,
      minutes: Number(data.minutes) || SHUTDOWN_DEFAULT_MINUTES,
      minMinutes: Number(data.minMinutes) || 1,
      maxMinutes: Number(data.maxMinutes) || 1440,
      warnSeconds: Number(data.warnSeconds) || 60,
      active: !!data.active,
      remainingText: String(data.remainingText || ''),
      flowName: String(data.flowName || '')
    };
    paintShutdown();
  }

  /** 按 ``state.shutdown`` 重画开关 / 分钟 / 提示 / 倒计时 */
  function paintShutdown() {
    const info = state.shutdown || {};
    const toggleEl = state.dom.shutdownToggle;
    const minutesInput = state.dom.shutdownMinutes;

    if (toggleEl) {
      const input = toggleEl.querySelector('input');
      if (input && input.checked !== !!info.enabled) {
        input.checked = !!info.enabled;
        if (typeof toggleEl.syncText === 'function') toggleEl.syncText();
      }
    }
    if (minutesInput && minutesInput.input) {
      const want = String(info.minutes || SHUTDOWN_DEFAULT_MINUTES);
      //: 正在编辑的时候别抢输入框（用户敲到一半被改回去最恼人）
      if (document.activeElement !== minutesInput.input) {
        minutesInput.set(Number(want));
      }
      minutesInput.input.disabled = !info.enabled;
    }

    if (state.dom.shutdownHint) {
      state.dom.shutdownHint.textContent = info.enabled
        ? '流程成功跑完后开始倒计时，关机前 ' + (info.warnSeconds || 60) +
          ' 秒会提醒你，想反悔可以点「取消关机」。手动按「停止」也会取消。'
        : '开启后，流程成功跑完会自动关机（跑失败不关，免得白关）。';
    }

    if (state.dom.shutdownCountdown && state.dom.shutdownCountdownText) {
      if (info.active) {
        state.dom.shutdownCountdown.classList.remove('hidden');
        state.dom.shutdownCountdownText.textContent =
          '⏻ ' + (info.flowName ? '「' + info.flowName + '」跑完了 —— ' : '') +
          '还有 ' + (info.remainingText || '') + ' 关机';
      } else {
        state.dom.shutdownCountdown.classList.add('hidden');
        state.dom.shutdownCountdownText.textContent = '';
      }
    }
  }

  /** 存设置（``fromInput``=true 时读分钟框，否则用 state 里的）*/
  async function saveShutdown(app, fromInput) {
    const enabled = !!(state.shutdown && state.shutdown.enabled);
    const minutes = fromInput ? shutdownMinutes() : (state.shutdown || {}).minutes ||
      SHUTDOWN_DEFAULT_MINUTES;
    if (state.shutdown) state.shutdown.minutes = minutes;

    const result = await P.call('setTaskShutdown',
      JSON.stringify({ enabled: enabled, minutes: minutes }));
    if (!result.ok) {
      appendLog('✗ 保存关机设置失败：' + (result.missing
        ? '桥接缺少 setTaskShutdown 方法'
        : String(result.error && result.error.message || result.error)), 'error');
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      appendLog('✗ ' + (data.message || '保存关机设置失败'), 'warn');
      //: 后端拒绝了 → 重读一次，把界面拉回真实状态（别让开关停在假的 ON）
      await refreshShutdown(true);
      return;
    }
    if (state.shutdown) state.shutdown.enabled = !!data.enabled;
    paintShutdown();
    appendLog(enabled
      ? '✔ 已开启：流程跑完后 ' + minutes + ' 分钟自动关机'
      : '✔ 已关闭「完成后自动关机」', 'ok');
    void app;
  }

  /** 用户点「取消关机」*/
  async function cancelShutdown(app) {
    const result = await P.call('cancelTaskShutdown');
    if (!result.ok) {
      appendLog('✗ 取消失败：' + (result.missing
        ? '桥接缺少 cancelTaskShutdown 方法'
        : String(result.error && result.error.message || result.error)), 'error');
      return;
    }
    appendLog('✔ 已取消自动关机', 'ok');
    await refreshShutdown(true);
    void app;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  数据加载
  // ────────────────────────────────────────────────────────────────────────
  async function reload(app, refreshBtn) {
    if (refreshBtn) refreshBtn.disabled = true;

    const flows = await loadFlows();
    state.source = flows.available ? 'flows' : 'tools';
    state.flows = flows.available ? flows.list : [];

    renderList(app);

    if (refreshBtn) refreshBtn.disabled = false;
  }

  /**
   * 拉流程列表。
   *
   * @returns {Promise<{available:boolean, list:Array}>}
   *
   * ## ⚠ 为什么不直接用 ``P.fetchList('getFlowList', 'flows')``
   *
   * ``P.call`` 里有一条启发式：**返回值是空数组**就当成「QWebChannel
   * 没找到匹配的 Slot」（实参个数不对时它会静默返回 ``[]``）。
   *
   * 但 ``getFlowList`` 正常返回的就是**裸数组** —— 用户把流程删光之后
   * 它合法地返回 ``[]``，于是被误判成「接口没接」，页面降级成工具列表
   * 并弹一条「任务流程接口未接入」的警告。删掉最后一条流程就看见这句，
   * 会以为把功能删坏了。
   *
   * 所以这里绕过那个启发式，自己认响应形状：
   * 裸数组 / ``{flows:[...]}`` / ``{tasks:[...]}`` 都算成功。
   */
  async function fetchFlowList() {
    if (!window.Bridge) {
      return { available: false, list: [], error: new Error('bridge.js 未加载') };
    }
    try {
      const value = await window.Bridge.call('getFlowList');
      if (Array.isArray(value)) return { available: true, list: value };
      if (value && Array.isArray(value.flows)) {
        return { available: true, list: value.flows };
      }
      if (value && Array.isArray(value.tasks)) {
        return { available: true, list: value.tasks };
      }
      //: 抓到了响应但形状不认识 —— 仍然算「接口在」，只是没内容
      return { available: true, list: [], raw: value };
    } catch (err) {
      return { available: false, list: [], error: err };
    }
  }

  async function loadFlows() {
    //: 优先真流程接口
    const flows = await fetchFlowList();
    if (flows.available) return flows;

    //: 退一步：有些后端可能把流程叫 tasks
    const tasks = await P.fetchList('getTaskList', 'tasks');
    if (tasks.available) return tasks;

    return { available: false, list: [] };
  }

  // ────────────────────────────────────────────────────────────────────────
  //  列表渲染（真实流程 / 降级工具列表）
  // ────────────────────────────────────────────────────────────────────────
  function renderList(app) {
    const host = state.dom.listHost;
    if (!host) return;

    P.fill(host, null);

    if (state.source === 'flows') {
      renderFlowList(host, app);
    } else {
      renderToolFallback(host, app);
    }
  }

  // ── 真实流程列表 ──
  function renderFlowList(host, app) {
    if (!state.flows.length) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty(
          '还没有任务流程',
          '点右上角「＋ 新增任务流程」创建一条：选角色 → 加入工具和配置 → 保存。',
          'TASK'
        )
      }));
      return;
    }

    const list = P.el('div', { class: 'flow-list' });
    for (const flow of state.flows) {
      list.appendChild(buildFlowCard(flow, app));
    }
    host.appendChild(list);
  }

  /**
   * 一条流程的行卡 —— 对应 main 的 ``TaskRowCard``。
   *
   * 布局：``[头像 48px] 名字 / 步骤链 / 状态    [详情][修改][删除][运行][停止]``
   *
   * ⚠ 保留 ``.flow-card`` / ``.flow-name`` / ``.step-chip`` / ``.step-arrow``
   * 这些类名 —— ``pages_verify.py`` 的 T2/T2b/T2c/T2d 靠它们做回归。
   */
  function buildFlowCard(flow, app) {
    const key = rowKey(flow);
    const card = P.el('div', {
      class: 'card flow-card task-row',
      dataset: { flowKey: key }
    });

    // ── 行首头像（48px，取不到就留同样大的空位，保持左缘对齐）──
    const avatar = P.el('div', { class: 'task-avatar' });
    const avatarUrl = String(flow.avatarUrl || '');
    if (avatarUrl) {
      const img = P.el('img', { src: avatarUrl, alt: '' });
      img.addEventListener('error', function () {
        P.fill(avatar, null);
        avatar.textContent = String(flow.name || '?').slice(0, 1);
        avatar.classList.add('is-fallback');
      }, { once: true });
      avatar.appendChild(img);
    }
    card.appendChild(avatar);

    // ── 中间：名字 / 步骤链 / 状态 ──
    const main = P.el('div', { class: 'flow-main task-main' });

    main.appendChild(P.el('div', { class: 'flow-name', text: flow.name || '(未命名流程)' }));

    const steps = Array.isArray(flow.steps) ? flow.steps : [];
    if (steps.length) {
      const chain = P.el('div', { class: 'flow-steps' });
      steps.forEach(function (step, index) {
        if (index > 0) {
          chain.appendChild(P.el('span', { class: 'step-arrow', text: '›' }));
        }
        const type = step.type || 'step';
        chain.appendChild(P.el('span', {
          class: 'step-chip',
          dataset: { type: type },
          title: stepTypeText(type) + ' · ' + (step.key || ''),
          text: step.name || step.key || '?'
        }));
      });
      main.appendChild(chain);
    }

    //: 状态行（main 的 status_label）—— 运行态由 syncRowStates 刷新
    const isRunning = state.running === key;
    main.appendChild(P.el('div', {
      class: 'task-status',
      dataset: { state: isRunning ? 'running' : 'idle' },
      text: isRunning ? '运行中' : '空闲'
    }));

    //: 校验错误 —— 这条流程有问题的话，运行前就该看见
    const errors = Array.isArray(flow.errors) ? flow.errors : [];
    if (errors.length) {
      main.appendChild(P.el('div', {
        class: 'task-error',
        text: '⚠ ' + errors.join('；')
      }));
    }

    card.appendChild(main);

    // ── 右侧按钮：只有 运行 / 停止 / 删除 ──
    //
    //: ★ 2026-11-04 用户圈住整行批注：「任务改成只有运行、停止、删除」。
    //:
    //: 之前照 main 分支做的是五个（详情 / 修改 / 删除 / 运行 / 停止）。
    //: 用户看过之后要去掉「详情」和「修改」—— 因为"新增"已经改成
    //: 选选项自动生成（见 openNewFlowDialog），步骤不再手动编辑，
    //: 想换配置就删掉重建，留着「修改」反而是两条会打架的路径。
    const actions = P.el('div', { class: 'flow-actions task-actions' });

    const delBtn = P.button('删除', {
      size: 'sm',
      title: '删除这条流程',
      onClick: function () { deleteFlow(app, flow); }
    });
    delBtn.dataset.action = 'delete';
    actions.appendChild(delBtn);

    const runBtn = P.button(isRunning ? '运行中' : '运行', {
      kind: 'primary',
      size: 'sm',
      disabled: isRunning || !!state.running || errors.length > 0,
      title: errors.length
        ? '流程校验未通过：' + errors.join('；')
        : (state.running && !isRunning
          ? '已有任务在运行（同一时刻只允许一条流程）'
          : '运行这条流程'),
      onClick: function () { startFlow(flow, app); }
    });
    runBtn.dataset.action = 'run';
    actions.appendChild(runBtn);

    const stopBtn = P.button('停止', {
      size: 'sm',
      disabled: !isRunning,
      title: '停止这条流程',
      onClick: function () { stopTask(app); }
    });
    stopBtn.dataset.action = 'stop';
    actions.appendChild(stopBtn);

    card.appendChild(actions);
    return card;
  }

  // ── 降级：工具列表 ──
  function renderToolFallback(host, app) {
    const tools = (app.tools || []).filter(function (t) {
      return !t.comingSoon && t.supportsTaskRun !== false;
    });

    //: 把「为什么是工具列表」说清楚 —— 不谎报、不留白板
    host.appendChild(P.notice(
      '<b>任务流程接口未接入</b>，当前显示的是<b>工具快捷运行</b>。' +
      'Qt 版的「任务流程」（开始 → 配置 → 工具 的编排）数据在 ' +
      '<code>core/tasks.TaskStore</code>，需要 Python 侧暴露 ' +
      '<code>getFlowList()</code> 才能显示。',
      'warn'
    ));

    host.appendChild(P.el('div', {
      class: 'section-title',
      text: '可运行的工具（' + tools.length + '）'
    }));

    if (!tools.length) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty('没有可运行的工具',
          '所有工具当前都标记为「即将到来」。', 'TASK')
      }));
      return;
    }

    const list = P.el('div', { class: 'flow-list' });
    for (const tool of tools) {
      list.appendChild(buildToolCard(tool, app));
    }
    host.appendChild(list);
  }

  function buildToolCard(tool, app) {
    const card = P.el('div', {
      class: 'card flow-card',
      dataset: { toolKey: tool.key }
    });

    const main = P.el('div', { class: 'flow-main' });
    main.appendChild(P.el('div', { class: 'flow-name', text: tool.name }));

    if (tool.desc) {
      main.appendChild(P.el('div', {
        class: 'task-error',
        style: 'color:var(--dim)',
        text: tool.desc
      }));
    }

    if (tool.categoryName) {
      main.appendChild(P.el('div', { class: 'flow-meta' }, [
        P.el('span', { text: tool.categoryName })
      ]));
    }

    card.appendChild(main);

    const actions = P.el('div', { class: 'flow-actions' });
    const runBtn = P.button('运行', {
      kind: 'primary',
      size: 'sm',
      disabled: !!state.running,
      onClick: function () { startFlow(tool, app, 'tool'); }
    });
    runBtn.dataset.action = 'run';
    actions.appendChild(runBtn);

    actions.appendChild(P.button('打开', {
      size: 'sm',
      onClick: function () { app.go('tool:' + tool.key); }
    }));

    card.appendChild(actions);
    return card;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  启动 / 停止 / 删除
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 启动运行。
   *
   * ## ★ 方法分流（2026-11-02，和 web_bridge 对齐）
   *
   * 桥接层把「跑一条流程」和「跑一个工具」拆成了**两个方法**，因为底层路径
   * 完全不同（``TaskStore.get`` + 按步骤跑 vs ``ToolRegistry.make`` 单工具）。
   * 混用会**静默失败** —— 拿 flow id 去 ``ToolRegistry.make()`` 查不到工具，
   * 返回 None，什么都没发生。
   *
   * ## ★ 错误文案一律用后端给的 message
   *
   * ``web_bridge`` 的所有失败分支都带 ``message``，而且那是**写给用户看的**
   * （不带异常类名前缀）。自己编文案会丢失真正的原因 ——
   * 前置检查（游戏没开）的说明就只存在于 ``data.message`` 里。
   */
  async function startFlow(flow, app, kind) {
    const isTool = kind === 'tool';
    const key = isTool ? flow.key : rowKey(flow);
    const name = flow.name || flow.key || key;
    const method = isTool ? 'runTask' : 'runFlow';

    if (state.running) {
      appendLog('✗ 已有任务在运行（' + state.running + '），请先停止', 'warn');
      return;
    }

    appendLog('▶ 请求运行：' + name, 'info');

    const result = await P.call(method, key);

    // ── 桥接层调用本身失败（方法不存在 / 通道断了）──
    if (!result.ok) {
      appendLog('✗ 无法运行：' + (result.missing
        ? '桥接缺少 ' + method + ' 方法'
        : String(result.error && result.error.message || result.error)), 'error');
      return;
    }

    const data = result.data || {};

    // ── 后端明确拒绝 ──
    if (!data.ok) {
      appendLog('✗ ' + describeFailure(data, name), 'warn');

      //: 前置检查失败（游戏没开）不是"错误"，是"还没准备好" ——
      //: 顺手把状态重置成空闲，别让它停在奇怪的状态
      if (data.reason === 'precheck') {
        applyIdle(app);
      }
      return;
    }

    //: 成功 → 状态交给 taskStarted 事件统一处理（Python 那边一定会发）
  }

  /**
   * 把后端的失败 dict 翻成一行给用户看的文字。
   *
   * 优先用 ``message``（后端专门写的用户文案），没有才按 reason 兜底。
   */
  function describeFailure(data, fallbackName) {
    const reason = data.reason || '';
    const backendMessage = data.message || data.hint || '';

    switch (reason) {
      case 'precheck':
        //: 「鸣潮客户端没在运行。先把游戏打开再点运行。」
        return backendMessage || '前置检查未通过：游戏客户端没在运行';
      case 'busy':
        return '已有任务在运行（' + (data.running || '未知') + '），请先停止';
      case 'not_found':
        return backendMessage || '找不到这条任务流程';
      case 'invalid':
        //: 校验错误是数组，逐条列出来才看得懂
        return (backendMessage || '流程校验未通过') +
          (Array.isArray(data.errors) && data.errors.length
            ? '：' + data.errors.join('；') : '');
      case 'unknown_tool':
        return backendMessage || ('没有这个工具：' + (data.key || fallbackName));
      case 'not_runnable':
        return backendMessage || ('「' + fallbackName + '」没有实现自动运行');
      case 'empty':
        return '没有指定要运行的目标';
      default:
        return backendMessage ||
          ('无法运行 ' + (fallbackName || '') +
           (reason ? '（' + reason + '）' : ''));
    }
  }

  async function stopTask(app) {
    if (!state.running) return;
    appendLog('⏹ 正在停止 ' + state.running + '…', 'warn');
    const result = await P.call('stopTask');
    if (!result.ok) {
      appendLog('✗ 停止失败：' + String(result.error && result.error.message || result.error),
        'error');
      return;
    }
    if (result.data && !result.data.ok && result.data.reason === 'idle') {
      //: 已经不跑了 —— 状态可能不同步，自己纠正一下
      appendLog('（任务已经不在运行）', 'debug');
      applyIdle(app);
    }
  }

  /** 删除一条流程（main 的 ``_delete``：运行中不让删）*/
  async function deleteFlow(app, flow) {
    const key = rowKey(flow);
    if (state.running === key) {
      appendLog('✗ 正在运行，先停止再删除这条流程。', 'warn');
      return;
    }
    const answer = await confirmDialog({
      title: '删除任务流程',
      message: '删除「' + (flow.name || '(未命名流程)') + '」？这一步不可撤销。',
      confirmLabel: '删除',
      danger: true
    });
    if (!answer) return;

    const result = await P.call('deleteFlow', key);
    if (!result.ok) {
      appendLog('✗ 删除失败：' + (result.missing
        ? '桥接缺少 deleteFlow 方法'
        : String(result.error && result.error.message || result.error)), 'error');
      return;
    }
    const data = result.data || {};
    if (data.ok === false) {
      appendLog('✗ ' + (data.message || '删除失败'), 'warn');
      //: 已经不在了 —— 列表也该跟着刷新，别留着一条删掉的
      if (data.reason === 'not_found') await reload(app);
      return;
    }
    appendLog('✔ 已删除「' + (data.name || flow.name || '') + '」', 'ok');
    await reload(app);
  }

  // ════════════════════════════════════════════════════════════════════════
  //  事件订阅
  // ════════════════════════════════════════════════════════════════════════
  function bindEvents(section, app) {
    const offs = [
      window.Bridge.on('taskStarted', function (data) {
        applyRunning(app, data && data.key);
      }),
      window.Bridge.on('taskFinished', function (data) {
        applyFinished(app, data || {});
      }),
      window.Bridge.on('progress', function (data) {
        applyProgress(data || {});
      }),
      //: ★ 2026-11-04「任务完成后自动关机」的后端事件。
      //:
      //: 计时器在后端（页面切走也得按时关机），这些事件只是让界面跟上：
      //: 起倒计时 / 60 秒警告 / 已关机 / 已取消。
      window.Bridge.on('shutdownArmed', function (data) {
        applyShutdownArmed(data || {});
      }),
      window.Bridge.on('shutdownWarning', function (data) {
        const seconds = Number((data || {}).seconds) || 0;
        appendLog('⚠ ' + seconds + ' 秒后自动关机！要取消就点任务页的「取消关机」。', 'warn');
        refreshShutdown(true);
      }),
      window.Bridge.on('shutdownFired', function (data) {
        const info = data || {};
        appendLog(info.ok === false
          ? '✗ 关机失败：' + String(info.message || '')
          : '⏻ 已安排关机（' + String(info.message || '') + '）', info.ok === false ? 'error' : 'warn');
        refreshShutdown(true);
      }),
      window.Bridge.on('shutdownCancelled', function () {
        appendLog('✔ 自动关机已取消', 'ok');
        refreshShutdown(true);
      })
      //: ⚠ 这里**故意不订阅 logLine** —— 见 hookGlobalLog 的说明
    ];
    //: 页面常驻 DOM，不需要退订；记录一下便于将来支持重建
    section._offs = (section._offs || []).concat(offs);
  }

  /**
   * ★ 接管 ``app.js`` 的日志入口。
   *
   * ``app.js`` 的 ``boot()`` 里 ``Bridge.subscribe(handleEvent)``，
   * 收到 ``logLine`` 就调 ``App.appendLog(text)`` —— 直接往 ``#task-log``
   * 里塞一行**没有时间戳**的纯文本。本页再写一遍就会**每条两份**。
   *
   * 所以把 ``App.appendLog`` **替换**成解析 ``#task-log`` 的通用版本：
   * 目标是 ``#task-log`` → 走本页的 :func:`appendLog`；否则走原来的。
   */
  function hookGlobalLog() {
    if (!App || typeof App.appendLog !== 'function') return;
    if (App.appendLog._hookedByTasks) return;

    const original = App.appendLog.bind(App);

    const patched = function (text, level) {
      const box = document.getElementById('task-log');
      if (box) {
        //: 任务页存在 → 用带时间戳的版本
        appendLog(text, level);
        return;
      }
      //: 任务页还没渲染 → 退回 app.js 原实现（它自己会判断 #task-log 在不在）
      original(text, level);
    };
    patched._hookedByTasks = true;
    App.appendLog = patched;
  }

  // ── 状态变更 ──
  function applyRunning(app, key) {
    state.running = key || '';
    state.progress = 0;
    state.step = '';

    app.setStatus('running', '运行中');
    syncRowStates();
    appendLog('● 开始运行', 'info');
  }

  function applyFinished(app, data) {
    const ok = data.ok !== false;
    const name = nameOf(data.key || state.running) || data.key || '任务';
    const summary = data.summary ? String(data.summary) : '';

    state.running = '';
    state.step = '';

    app.setStatus('idle', '就绪');
    syncRowStates();

    //: 状态行由 syncRowStates 复位成「空闲」；这里把结果补进日志和状态行
    const row = findRowCard(data.key);
    const status = row && row.querySelector('.task-status');
    if (status) {
      status.dataset.state = ok ? 'idle' : 'failed';
      status.textContent = ok ? '完成' : '已停止';
    }

    if (!ok && summary) {
      appendLog('■ 已停止：' + summary, 'warn');
    } else if (ok) {
      appendLog('✔ ' + name + ' 完成' + (summary ? '：' + summary : ''), 'ok');
    }

    //: 跑完一轮 → 刷新「运行报告」（后端在 taskFinished 之后已有本轮报告）
    refreshReport(true);
  }

  function applyProgress(data) {
    const value = Number(data.value);
    const text = data.text || '';
    if (isFinite(value)) {
      state.progress = Math.max(0, Math.min(100, value));
    }
    if (text) {
      state.step = text;
    }
  }

  /**
   * 后端起了「跑完关机」倒计时。
   *
   * 这里**不自己算剩余时间** —— 后端每秒 tick 一次，页面只在收到事件时
   * 拉一次状态。两边各算一份一定会漂（页面切走再切回、标签页被节流），
   * 而关机是**不可撤销**的操作，宁可少显示也不要显示错。
   */
  function applyShutdownArmed(data) {
    const info = state.shutdown || {};
    state.shutdown = Object.assign({}, info, {
      active: true,
      minutes: Number(data.minutes) || info.minutes || SHUTDOWN_DEFAULT_MINUTES,
      flowName: String(data.flowName || ''),
      remainingText: String(data.remainingText || '')
    });
    paintShutdown();
    appendLog('⏻ 「' + (data.flowName || '任务') + '」跑完了 —— ' +
      (data.remainingText || '') + ' 后自动关机（可点「取消关机」）', 'warn');
    //: 剩余时间是后端算的，隔一会儿再对齐一次（倒计时在走）
    window.setTimeout(function () { refreshShutdown(true); }, 1200);
  }

  /** 恢复外部设置过的状态（app.status / app 里的全局 progress）*/
  function restoreState(app) {
    const running = app.status && app.status.running;
    const progress = (app.status && app.status.progress) || 0;
    if (running) {
      applyRunning(app, running);
      if (progress) state.progress = progress;
    } else {
      applyIdle(app);
    }
  }

  function applyIdle(app) {
    state.running = '';
    setStatusAll('idle', '空闲');
    syncRowStates();
    void app;
  }

  /** 把所有行的状态行统一设成某文案（不含"完成/已停止"这类一次性结果）*/
  function setStatusAll(tone, text) {
    const host = state.dom.listHost;
    if (!host) return;
    for (const node of host.querySelectorAll('.task-status')) {
      node.dataset.state = tone;
      node.textContent = text;
    }
  }

  function findRowCard(key) {
    const host = state.dom.listHost;
    if (!host || !key) return null;
    for (const card of host.querySelectorAll('[data-flow-key]')) {
      if (card.dataset.flowKey === key) return card;
    }
    return null;
  }

  /**
   * 刷新每一行的运行态（徽标 + 五个按钮的 disabled）。
   *
   * 对应 main 的 ``_set_running`` + ``note_running``：
   * 正在跑的那行 → 停止可用、其余禁用；其它行 → 运行禁用（同一时刻只能一条）。
   */
  function syncRowStates() {
    const host = state.dom.listHost;
    if (!host) return;
    const busy = !!state.running;

    for (const card of host.querySelectorAll('.flow-card')) {
      const key = card.dataset.flowKey || card.dataset.toolKey || '';
      const isRunning = busy && key === state.running;
      const status = card.querySelector('.task-status');
      if (status && (busy || status.dataset.state !== 'failed')) {
        status.dataset.state = isRunning ? 'running' : 'idle';
        status.textContent = isRunning ? '运行中' : '空闲';
      }
      const runBtn = card.querySelector('[data-action="run"]');
      if (runBtn) {
        runBtn.disabled = busy;
        runBtn.textContent = isRunning ? '运行中' : '运行';
      }
      const stopBtn = card.querySelector('[data-action="stop"]');
      if (stopBtn) stopBtn.disabled = !isRunning;
      //: 跑的时候不让删（main 同一条规则）
      const delBtn = card.querySelector('[data-action="delete"]');
      if (delBtn) delBtn.disabled = busy;
    }
  }

  function nameOf(key) {
    if (!key) return '';
    const flow = state.flows.find(function (f) {
      return (f.id || f.key || '') === key;
    });
    if (flow && flow.name) return flow.name;
    const tool = (App.tools || []).find(function (t) { return t.key === key; });
    return tool ? tool.name : '';
  }

  // ════════════════════════════════════════════════════════════════════════
  //  日志
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 追加一行日志（带时间戳 / 级别色 / 计数 / 受自动滚动开关控制）。
   *
   * @param {string} text
   * @param {string} [level] - info | warn | error | ok | debug
   */
  function appendLog(text, level) {
    const box = state.dom.logBox || document.getElementById('task-log');
    if (!box) return;

    const content = String(text == null ? '' : text);
    if (!content) return;

    const line = P.el('div', {
      class: 'log-line',
      dataset: { level: level || 'info' }
    }, [
      P.el('span', { class: 'log-time', text: clock() }),
      P.el('span', { class: 'log-text', text: content })
    ]);

    box.appendChild(line);
    state.logCount += 1;

    //: 超出上限丢最老的
    while (box.childElementCount > MAX_LOG_LINES) {
      box.removeChild(box.firstElementChild);
      state.logCount -= 1;
    }

    updateLogCount();

    if (state.autoScroll) scrollLogToEnd();
  }

  function clock() {
    const now = new Date();
    function pad(n) { return n < 10 ? '0' + n : String(n); }
    return pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':' + pad(now.getSeconds());
  }

  function scrollLogToEnd() {
    const box = state.dom.logBox || document.getElementById('task-log');
    if (box) box.scrollTop = box.scrollHeight;
  }

  function updateLogCount() {
    const label = state.dom.logCount || document.getElementById('task-log-count');
    if (label) label.textContent = state.logCount + ' 行';
  }

  function clearLog() {
    const box = state.dom.logBox || document.getElementById('task-log');
    if (box) box.innerHTML = '';
    state.logCount = 0;
    updateLogCount();
  }

  // ════════════════════════════════════════════════════════════════════════
  //  通用弹框（页面级，和 config.js 的那套视觉一致）
  // ════════════════════════════════════════════════════════════════════════
  function openDialog(opts) {
    opts = opts || {};
    closeDialog();

    const overlay = P.el('div', { class: 'dlg-overlay' });
    const box = P.el('div', {
      class: 'dlg-box',
      style: 'width:' + (opts.width || 520) + 'px'
    });

    const head = P.el('div', { class: 'dlg-head' }, [
      P.el('div', { class: 'dlg-title', text: opts.title || '' }),
      P.el('div', { style: 'flex:1 1 auto' }),
      P.el('button', {
        class: 'dlg-close', type: 'button', text: '×', title: '关闭',
        onClick: function () { closeDialog(); }
      })
    ]);
    box.appendChild(head);

    const body = P.el('div', { class: 'dlg-body' });
    if (opts.body) body.appendChild(opts.body);
    box.appendChild(body);

    if (Array.isArray(opts.actions) && opts.actions.length) {
      const foot = P.el('div', { class: 'dlg-foot' });
      foot.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
      for (const action of opts.actions) {
        const btn = P.button(action.label, {
          kind: action.kind || '',
          disabled: !!action.disabled,
          onClick: action.onClick
        });
        if (action.name) btn.dataset.action = action.name;
        foot.appendChild(btn);
      }
      box.appendChild(foot);
    }

    overlay.appendChild(box);

    //: 点遮罩关闭（点框内不关）
    overlay.addEventListener('mousedown', function (ev) {
      if (ev.target === overlay) closeDialog();
    });
    EDITOR.escHandler = function (ev) {
      if (ev.key === 'Escape') closeDialog();
    };
    document.addEventListener('keydown', EDITOR.escHandler);

    document.body.appendChild(overlay);
    EDITOR.root = overlay;
    if (typeof opts.onClose === 'function') EDITOR.onClose = opts.onClose;
    return { el: box, body: body, close: closeDialog };
  }

  function closeDialog() {
    if (EDITOR.escHandler) {
      document.removeEventListener('keydown', EDITOR.escHandler);
      EDITOR.escHandler = null;
    }
    if (EDITOR.root && EDITOR.root.parentNode) {
      EDITOR.root.parentNode.removeChild(EDITOR.root);
    }
    EDITOR.root = null;
    const cb = EDITOR.onClose;
    EDITOR.onClose = null;
    if (typeof cb === 'function') cb();
  }

  /**
   * 确认弹框。返回 ``Promise<boolean>``。
   *
   * @param {object} opts - {title, message, confirmLabel, danger}
   */
  function confirmDialog(opts) {
    return new Promise(function (resolve) {
      let settled = false;
      function done(value) {
        if (settled) return;
        settled = true;
        closeDialog();
        resolve(value);
      }
      openDialog({
        title: opts.title || '确认',
        width: 420,
        body: P.el('div', { class: 'task-confirm-text', text: opts.message || '' }),
        actions: [
          { label: '取消', name: 'cancel', onClick: function () { done(false); } },
          {
            label: opts.confirmLabel || '确定',
            kind: opts.danger ? 'danger' : 'primary',
            name: 'confirm',
            onClick: function () { done(true); }
          }
        ],
        onClose: function () { if (!settled) { settled = true; resolve(false); } }
      });
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  新增任务弹框（main：NewFlowDialog）—— 选类型 + 角色 + 级别 + 成套
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 「＋ 新增任务流程」走**选项式**弹框，不再是完整编排编辑器。
   *
   * ## 用户 2026-11-04 圈图
   *
   * 圈住「可用组件（点一下加到下面 →）」批注：
   *
   * > 增加任务类型，任务类型，目前有，声骸自动强化，
   * > 而且还有选择是否成套，44111、43311 这些都东西呢？
   *
   * 也就是要 main 分支 ``new_flow_dialog.NewFlowDialog`` 那套：
   * 选**任务类型 + 角色 + 属性级别 + 是否成套**，保存后自动生成
   * ``开始 → 筛选 → 强化 → 工具 → 结束`` 五步，不用手动挑组件。
   *
   * ## 为什么选项和判定都在后端算
   *
   * 「这角色齐不齐两类配置」「这条强化配置最多能要几条有效词条」
   * 「同角色同级别是不是已经有一条了」——这三条规则 main 分支写在
   * ``new_flow_dialog`` 里（有单测）。抄到 JS 就是两份会漂的规则，
   * 所以走 ``getNewFlowOptions`` / ``createFlowFromOptions``。
   */
  async function openNewFlowDialog(app) {
    EDITOR.flow = null;
    EDITOR.character = '';

    const body = P.el('div', { class: 'task-editor' });

    //: 先把弹框画出来（数据在下面异步拉，拉回来再填控件）
    const loading = P.el('div', { class: 'task-palette-empty', text: '正在读取角色和配置…' });
    body.appendChild(loading);

    const errorEl = P.el('div', { class: 'task-editor-error' });
    body.appendChild(errorEl);

    const dlg = openDialog({
      title: '新增任务',
      width: 560,
      body: body,
      actions: [
        { label: '取消', name: 'cancel', onClick: function () { closeDialog(); } },
        {
          label: '保存',
          kind: 'primary',
          name: 'save-flow',
          onClick: function () { submitNewFlow(app, dlg, errorEl); }
        }
      ]
    });

    let options = null;
    try {
      const result = await P.call('getNewFlowOptions');
      if (result.ok && result.data && result.data.ok) options = result.data;
    } catch (err) {
      console.error('[tasks] 读取新增任务选项失败', err);
    }
    if (!EDITOR.root) return;   //: 加载期间用户关了弹框

    P.fill(body, null);

    if (!options) {
      body.appendChild(P.el('div', {
        class: 'task-stale-hint',
        text: '⚠ 读不到角色和配置列表 —— 请稍后重试，或到「配置」页确认配置还在。'
      }));
      body.appendChild(errorEl);
      return;
    }

    EDITOR.options = options;
    EDITOR.newFlow = {};

    /** 简易下拉（``<select>``）—— main 的 ComboBox */
    function localSelect(labels, current) {
      const box = P.el('select', { class: 'input' });
      for (const label of labels) {
        const opt = P.el('option', { value: label, text: label });
        if (label === current) opt.selected = true;
        box.appendChild(opt);
      }
      return {
        el: box,
        get: function () { return String(box.value || ''); }
      };
    }

    // ── 任务类型 ──
    const typeRow = P.el('div', { class: 'task-editor-row' });
    typeRow.appendChild(P.el('div', { class: 'task-label', text: '任务类型' }));
    const typeSel = localSelect(
      (options.taskTypes || []).map(function (t) { return t.name; }),
      (options.taskTypes && options.taskTypes[0] || {}).name
    );
    typeSel.el.classList.add('task-select');
    typeRow.appendChild(typeSel.el);
    body.appendChild(typeRow);
    body.appendChild(P.el('div', {
      class: 'task-suffix-hint task-type-hint',
      text: '选好类型后会自动生成整条流程（开始 → 筛选 → 强化 → 工具 → 结束），不用再手动排步骤。'
    }));

    // ── 角色 ──
    const charRow = P.el('div', { class: 'task-editor-row' });
    charRow.appendChild(P.el('div', { class: 'task-label', text: '角色' }));
    const charPicker = buildCharacterPicker(function (name) {
      EDITOR.character = name;
      syncLevelAvailability();
    });
    charPicker.set(EDITOR.character);
    charRow.appendChild(charPicker.el);
    body.appendChild(charRow);

    const charHint = P.el('div', { class: 'task-suffix-hint task-char-hint' });
    body.appendChild(charHint);

    // ── 声骸属性级别 ──
    const levelRow = P.el('div', { class: 'task-editor-row' });
    levelRow.appendChild(P.el('div', { class: 'task-label', text: '声骸属性级别' }));
    const levelNames = (options.attrLevels || []).map(function (lv) {
      return lv.name + '（有效词条=' + lv.count + '）';
    });
    const defaultLevelLabel = (function () {
      const lv = options.defaultLevel || '';
      const found = (options.attrLevels || []).find(function (x) { return x.name === lv; });
      return found ? found.name + '（有效词条=' + found.count + '）' : (levelNames[0] || '');
    })();
    const levelSel = localSelect(levelNames, defaultLevelLabel);
    levelSel.el.classList.add('task-select');
    levelRow.appendChild(levelSel.el);
    body.appendChild(levelRow);

    const levelHint = P.el('div', { class: 'task-suffix-hint task-level-hint' });
    body.appendChild(levelHint);

    // ── 是否成套声骸 ──
    const setRow = P.el('div', { class: 'task-editor-row' });
    setRow.appendChild(P.el('div', { class: 'task-label', text: '是否成套' }));
    const setSel = localSelect(
      options.setChoices || ['不成套', '成套'],
      options.defaultSetBonus || '不成套'
    );
    setSel.el.classList.add('task-select');
    setRow.appendChild(setSel.el);

    const planSel = localSelect(options.setPlans || ['43311', '44111'], '43311');
    //: ⚠ classList.add 不接受带空格的字符串（会抛 DOMException 把整段渲染打断），
    //: 两个类必须分开加
    planSel.el.classList.add('task-select');
    planSel.el.classList.add('task-select-plan');
    setRow.appendChild(planSel.el);
    body.appendChild(setRow);

    const setHint = P.el('div', { class: 'task-suffix-hint task-set-hint' });
    body.appendChild(setHint);

    body.appendChild(errorEl);

    //: 把控件引用留给 submitNewFlow 读（别再靠行序号去 DOM 里翻）
    EDITOR.newFlow = {
      typeSel: typeSel,
      levelSel: levelSel,
      setSel: setSel,
      planSel: planSel,
      charPicker: charPicker
    };

    function currentLevelName() {
      const raw = String(levelSel.get() || '');
      const cut = raw.indexOf('（');
      return (cut > 0 ? raw.slice(0, cut) : raw).trim();
    }

    function currentCharacter() {
      const who = String(charPicker.get() || '').trim();
      if (!who) return null;
      const pool = options.characters || [];
      return pool.find(function (c) { return c.name === who; }) || null;
    }

    function syncSetVisibility() {
      const isSet = String(setSel.get() || '') === '成套';
      planSel.el.style.display = isSet ? '' : 'none';
      setHint.textContent = isSet
        ? (String(planSel.get() || '43311') === '44111'
          ? '44111 = 4C×2 + 1C×3（两种声骸）'
          : '43311 = 4C×1 + 3C×2 + 1C×2（三种声骸）')
        : '不成套 = 按配置里勾选的所有声骸逐个强化';
    }

    function syncLevelAvailability() {
      const item = currentCharacter();
      if (!item) {
        charHint.textContent = '点上面的角色框选一个角色（可打拼音）。';
        charHint.classList.remove('is-bad');
        levelHint.textContent = '';
        levelHint.classList.remove('is-bad');
        return;
      }
      if (!item.ready) {
        charHint.textContent = '⚠ 「' + item.name + '」还缺「' +
          (item.missing || []).join('」「') + '」配置 —— 请先到「配置」页建好。';
        charHint.classList.add('is-bad');
      } else {
        charHint.textContent = '将自动生成：开始 → ' + item.name + '-声骸筛选 → ' +
          item.name + '-声骸强化 → 声骸自动强化 → 结束';
        charHint.classList.remove('is-bad');
      }
      const lv = currentLevelName();
      const need = levelCountOf(lv);
      const cap = Number(item.levelCap || 0);
      if (need && cap && need > cap) {
        levelHint.textContent = '⚠ 「' + lv + '」要 ' + need + ' 条有效词条，' +
          '但这条强化配置只有 ' + cap + ' 条可用属性 —— 保存会被拒绝，' +
          '请先到「配置」页补属性或换低一级。';
        levelHint.classList.add('is-bad');
      } else if (need && cap) {
        levelHint.textContent = '有效词条数：' + need + '（配置上限 ' + cap + '）';
        levelHint.classList.remove('is-bad');
      } else {
        levelHint.textContent = '';
        levelHint.classList.remove('is-bad');
      }
    }

    function levelCountOf(name) {
      const found = (options.attrLevels || []).find(function (x) {
        return x.name === name;
      });
      return found ? Number(found.count) : 0;
    }

    levelSel.el.addEventListener('change', syncLevelAvailability);
    setSel.el.addEventListener('change', syncSetVisibility);
    planSel.el.addEventListener('change', syncSetVisibility);

    syncSetVisibility();
    syncLevelAvailability();

    //: 角色候选（下拉面板要全量 61 个；这里拉不到就只能手打，保存时会被拦）
    await loadCharacters();
    if (!EDITOR.root) return;
    charPicker.refresh();
    syncLevelAvailability();
  }

  /**
   * 保存「新增任务」—— 后端按选项生成流程。
   *
   * 失败一律把后端的 ``message`` 显示在弹框里（后端已经把这些话写成人话了：
   * 缺配置、级别做不到、重名……），**不在这里再判一遍** —— 判两遍就有两套规则。
   */
  async function submitNewFlow(app, dlg, errorEl) {
    const ctl = EDITOR.newFlow || {};
    const who = String(EDITOR.character || '').trim();

    const levelRaw = ctl.levelSel ? ctl.levelSel.get() : '';
    const cut = levelRaw.indexOf('（');
    const level = (cut > 0 ? levelRaw.slice(0, cut) : levelRaw).trim();

    function fail(text) {
      errorEl.textContent = '⚠ ' + text;
      errorEl.classList.add('is-visible');
    }

    if (!who) {
      fail('请先选一个角色');
      return;
    }

    const payload = JSON.stringify({
      character: who,
      taskType: ctl.typeSel ? ctl.typeSel.get() : '',
      level: level,
      setBonus: ctl.setSel ? ctl.setSel.get() : '',
      setPlan: ctl.planSel ? ctl.planSel.get() : ''
    });

    const btn = dlg.el.querySelector('.dlg-foot [data-action="save-flow"]');
    if (btn) { btn.disabled = true; btn.textContent = '保存中…'; }

    const result = await P.call('createFlowFromOptions', payload);
    const data = (result && result.ok && result.data) ? result.data : null;

    if (!data || !data.ok) {
      if (btn) { btn.disabled = false; btn.textContent = '保存'; }
      const message = data && data.message
        ? data.message
        : (result && result.error
          ? String(result.error.message || result.error)
          : '新建任务失败');
      fail(message);
      return;
    }

    appendLog('✔ 已新建任务「' + (data.name || '') + '」', 'ok');
    closeDialog();
    await reload(app);
  }

  /** 拉角色候选（全量；编辑器里选角色用）*/
  async function loadCharacters() {
    if (Array.isArray(state.characterPool)) return state.characterPool;
    const result = await P.call('getCharacterOptions', '');
    if (!result.ok || !result.data || !Array.isArray(result.data.items)) {
      state.characterPool = [];
      return state.characterPool;
    }
    state.characterPool = result.data.items
      .filter(function (item) { return item && item.name; })
      .map(function (item) {
        return {
          name: String(item.name),
          avatarUrl: String(item.avatarUrl || ''),
          pinyin: Array.isArray(item.pinyin) ? item.pinyin : []
        };
      });
    return state.characterPool;
  }

  /** 按名字/拼音匹配角色（和配置页同一套规则）*/
  function matchCharacter(item, kw) {
    if (!kw) return true;
    if (String(item.name || '').toLowerCase().indexOf(kw) >= 0) return true;
    if (!/^[a-z]+$/.test(kw)) return false;
    const keys = Array.isArray(item.pinyin) ? item.pinyin : [];
    const full = String(keys[0] || '').toLowerCase();
    const initial = String(keys[1] || '').toLowerCase();
    return (!!full && full.indexOf(kw) >= 0) || (!!initial && initial.indexOf(kw) >= 0);
  }

  /**
   * 弹框里的角色下拉：输入框 + 候选面板（和配置页同一套视觉）。
   * @returns {{el, set, get, refresh}}
   */
  function buildCharacterPicker(onPick) {
    let value = '';
    let open = false;

    const wrap = P.el('div', { class: 'task-char' });
    const input = P.el('input', {
      class: 'input task-char-input',
      type: 'text',
      placeholder: '点击展开，可输入过滤（支持拼音）',
      autocomplete: 'off'
    });
    wrap.appendChild(input);

    const caret = P.el('button', {
      class: 'search-caret', type: 'button', text: '▼', title: '展开候选',
      onMousedown: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (open) close(); else { input.focus(); show(); }
      }
    });
    wrap.appendChild(caret);

    const panel = P.el('div', { class: 'config-search-panel task-char-panel' });
    panel.hidden = true;
    panel.classList.add('hidden');
    wrap.appendChild(panel);

    function matches(item, kw) { return matchCharacter(item, kw); }

    function paint() {
      P.fill(panel, null);
      const kw = String(input.value || '').trim().toLowerCase();
      const pool = Array.isArray(state.characterPool) ? state.characterPool : [];
      const list = pool.filter(function (item) { return matches(item, kw); }).slice(0, 120);
      panel.appendChild(P.el('div', {
        class: 'config-search-hint',
        text: '全部 ' + pool.length + ' 个角色' +
          (kw ? ' · 匹配 ' + list.length + ' 个' : '')
      }));
      if (!list.length) {
        panel.appendChild(P.el('div', {
          class: 'config-search-empty',
          text: pool.length ? '没有匹配的角色' : '角色候选还没加载好 —— 可以直接输入名字'
        }));
        return;
      }
      for (const item of list) {
        const row = P.el('div', {
          class: 'config-search-opt',
          onMousedown: function (ev) {
            ev.preventDefault();
            choose(item.name);
          }
        });
        const face = P.el('span', { class: 'config-search-face' });
        if (item.avatarUrl) {
          const img = P.el('img', { src: item.avatarUrl, alt: '' });
          img.addEventListener('error', function () {
            P.fill(face, null);
            face.textContent = String(item.name || '?').slice(0, 1);
          }, { once: true });
          face.appendChild(img);
        } else {
          face.textContent = String(item.name || '?').slice(0, 1);
        }
        row.appendChild(face);
        row.appendChild(P.el('span', { class: 'config-search-name', text: item.name }));
        panel.appendChild(row);
      }
    }

    function show() {
      paint();
      panel.hidden = false;
      panel.classList.remove('hidden');
      wrap.classList.add('is-open');
      open = true;
    }

    function close() {
      panel.hidden = true;
      panel.classList.add('hidden');
      wrap.classList.remove('is-open');
      open = false;
    }

    function choose(name) {
      value = String(name || '');
      input.value = value;
      close();
      if (typeof onPick === 'function') onPick(value);
    }

    input.addEventListener('focus', function () { if (!open) show(); });
    input.addEventListener('mousedown', function () { if (!open) show(); });
    input.addEventListener('blur', function () {
      setTimeout(function () { if (open) close(); }, 120);
    });
    input.addEventListener('input', function () {
      value = input.value;
      if (typeof onPick === 'function') onPick(value);
      if (!open) show(); else paint();
    });
    input.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { close(); input.blur(); }
      if (ev.key === 'Enter') {
        const first = panel.querySelector('.config-search-opt .config-search-name');
        if (first) {
          ev.preventDefault();
          choose(first.textContent);
        }
      }
    });

    return {
      el: wrap,
      set: function (v) { value = String(v || ''); input.value = value; },
      get: function () { return String(input.value || value || '').trim(); },
      refresh: function () { if (open) paint(); }
    };
  }

})();
