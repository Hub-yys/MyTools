/* ══════════════════════════════════════════════════════════════════════════
   pages/tasks.js —— 任务页

   **P2 重写**。P1 版本只是「工具列表 + 运行」，而且有 bug：
   点一次运行之后按钮永久 disabled（``taskFinished`` 到来也不恢复）。

   ## Qt 版是什么

   ``src/gui/tasks_interface.py``（702 行）不是「7 个工具列表」，而是
   **任务流程（TaskFlow）编排 + 运行**：

   .. code:: text

     一条流程 = 开始步 → [配置步...] → 工具步 → [配置步...] → 工具步 ...

     · 每个步骤有 type（start / config / tool）、key、name
     · 运行时一条流程一个 QThread，按顺序跑各步骤
     · 同一时刻只允许跑一条流程（要抢游戏窗口，两条并行只会互相干扰）
     · 日志：self._emit() 同时进界面和日志文件

   数据在 ``core/tasks.TaskStore``（``data/tasks.json``），目前有 1 条流程。

   ## 这个页面的三个区域

   1. **运行面板** —— 正在跑哪条、进度条、当前步骤、停止按钮
   2. **流程列表** —— 每条流程：名字 / 类型 / 步骤链 / 运行、编辑、删除
   3. **日志流** —— 实时日志，等宽字体，自动滚动（可关），可清空

   ## ⚠ 「双态」设计（P2 阶段的关键取舍）

   ``web_bridge.py`` 目前**没有**读 TaskFlow 的方法（只有 runTask/stopTask，
   而且 runTask 还是模拟的）。所以本页面这样处理：

   * 有 ``getFlowList()`` → 渲染**真实流程**（含步骤链）
   * 没有 → 退回渲染**工具列表**，并在顶部明确说明「任务流程接口未接入，
     当前显示的是工具快捷运行」—— 而不是白板或谎报成功

   逻辑集中在 :func:`loadFlows`，接口一到位就自动切到真实数据，页面不用改。

   ## 日志为什么自己维护一份

   ``app.js`` 的 ``App.appendLog`` 只往 ``#task-log`` 里塞一行，没有时间戳、
   不维护计数、也不管自动滚动开关。任务页要的东西比它多，所以这里接管
   ``#task-log`` 的内容（元素 id 保持一致，``App.appendLog`` 仍然可用）。
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

  //: 日志最多留多少行（超出丢最老的，防长时间运行把内存吃满）
  const MAX_LOG_LINES = 800;

  //: 页面级状态（模块作用域 —— 一个页面实例一份）
  const state = {
    /** 当前运行的流程 key（空 = 空闲）*/
    running: '',
    /** 当前进度 0~100 */
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
    source: 'tools',
    /** 各个 DOM 引用 */
    dom: {}
  };

  P.ready(function () {
    App.registerPage('tasks', renderTasks);
  });

  // ════════════════════════════════════════════════════════════════════════
  //  渲染
  // ════════════════════════════════════════════════════════════════════════
  async function renderTasks(section, app) {
    // ── 页头 ──
    const head = P.pageHead({
      title: '任务',
      subtitle: '运行任务流程，实时查看日志'
    });

    const refreshBtn = P.button('刷新', {
      icon: 'HISTORY',
      size: 'sm',
      onClick: function () { reload(section, app, refreshBtn); }
    });
    const clearBtn = P.button('清空日志', {
      size: 'sm',
      onClick: function () { clearLog(); }
    });
    head.actions.appendChild(refreshBtn);
    head.actions.appendChild(clearBtn);
    section.appendChild(head.head);

    //: 运行引擎说明
    //
    //: ★ 2026-11-02 改：以前这里写「引擎还在接入中，点运行不会真的调用工具」。
    //: 现在真引擎接上了（FlowRunThread → create_task_runner().run()），
    //: 那句话会误导用户以为点了没用 —— 必须删。
    //: 但**游戏必须开着**这个前提不能少说：前置检查不过会立刻返回，
    //: 用户不知道的话会以为按钮坏了。
    section.appendChild(P.notice(
      '<b>点「运行」会真的操作游戏</b>（走和 Qt 版相同的执行器）。' +
      '⚠ 前提：<b>鸣潮客户端必须已经在运行</b>，否则会立刻前置检查失败并提示你；' +
      '游戏类工具还需要以管理员权限启动本程序（否则点击会被系统静默丢弃）。' +
      '同一时刻只允许跑一条流程。',
      'info'
    ));

    // ── ① 运行面板 ──
    const runCard = P.panel({
      padding: '15px 18px',
      body: buildRunPanel(app)
    });
    runCard.classList.add('run-panel');
    section.appendChild(runCard);

    // ── ② 流程 / 工具列表 ──
    const listHost = P.el('div', { class: 'section' });
    section.appendChild(listHost);

    // ── ③ 日志 ──
    section.appendChild(buildLogPanel());

    //: DOM 引用集中存起来（事件回调里要用）
    state.dom.listHost = listHost;
    state.dom.stopBtn = runCard.querySelector('#task-stop');
    state.dom.progressBar = runCard.querySelector('#task-progress-bar');
    state.dom.progressText = runCard.querySelector('#task-progress-text');
    state.dom.runName = runCard.querySelector('#task-run-name');
    state.dom.runStep = runCard.querySelector('#task-run-step');
    state.dom.statePill = runCard.querySelector('#task-run-state');
    state.dom.logBox = section.querySelector('#task-log');
    state.dom.logCount = section.querySelector('#task-log-count');

    //: ★ 把 app.js 的日志入口接到本页的实现上（见 hookGlobalLog 的说明）
    hookGlobalLog();

    //: 从 app 的全局状态恢复（比如在别处点了运行再切过来）
    restoreState(app);

    // ── 事件订阅 ──
    bindEvents(section, app);

    // ── 拉数据 ──
    await reload(section, app, refreshBtn);

    //: 页面刚渲染完，给一条定位提示（用户至少知道日志在等什么）
    if (!state.logCount) {
      appendLog('就绪 —— 选择一条流程点「运行」，日志会实时出现在这里', 'debug');
    }
  }

  // ────────────────────────────────────────────────────────────────────────
  //  运行面板
  // ────────────────────────────────────────────────────────────────────────
  function buildRunPanel(app) {
    const box = P.el('div');

    // 第一行：状态 + 名字 + 百分比 + 停止
    const headRow = P.el('div', { class: 'run-head' }, [
      P.el('span', {
        class: 'flow-state',
        id: 'task-run-state',
        text: '空闲'
      }),
      P.el('div', { class: 'run-name', id: 'task-run-name', text: '没有正在运行的任务' }),
      //: 百分比只在运行时才有意义 —— 空闲时留空，避免和状态胶囊重复说「空闲」
      P.el('div', { class: 'run-percent', id: 'task-progress-text', text: '' }),
      (function () {
        //: ★ id 必须是 task-progress-bar —— app.js 的 setProgress 也找它
        const stopBtn = P.button('停止', {
          kind: 'danger',
          size: 'sm',
          onClick: function () { stopTask(app); }
        });
        stopBtn.id = 'task-stop';
        stopBtn.disabled = true;
        return stopBtn;
      })()
    ]);
    box.appendChild(headRow);

    // 第二行：进度条
    box.appendChild(P.el('div', { class: 'progress' }, [
      P.el('div', { class: 'progress-bar', id: 'task-progress-bar' })
    ]));

    // 第三行：当前步骤
    box.appendChild(P.el('div', {
      class: 'run-step',
      id: 'task-run-step',
      text: '等待开始'
    }));

    return box;
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
  //  数据加载（双态）
  // ────────────────────────────────────────────────────────────────────────
  async function reload(section, app, refreshBtn) {
    if (refreshBtn) refreshBtn.disabled = true;

    const flows = await loadFlows();
    state.source = flows.available ? 'flows' : 'tools';
    state.flows = flows.available ? flows.list : [];

    renderList(app);

    if (refreshBtn) refreshBtn.disabled = false;
    void section;
  }

  /**
   * 拉流程列表。
   *
   * @returns {Promise<{available:boolean, list:Array}>}
   */
  async function loadFlows() {
    //: 优先真流程接口
    const flows = await P.fetchList('getFlowList', 'flows');
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
      host.appendChild(P.el('div', { class: 'section-title', text: '任务流程（0）' }));
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty(
          '还没有任务流程',
          '在 Qt 版的任务页里点「新增任务流程」编排一条（开始 → 配置 → 工具），' +
          '它就会出现在这里。',
          'TASK'
        )
      }));
      return;
    }

    host.appendChild(P.el('div', {
      class: 'section-title',
      text: '任务流程（' + state.flows.length + '）'
    }));

    const list = P.el('div', { class: 'flow-list' });
    for (const flow of state.flows) {
      list.appendChild(buildFlowCard(flow, app));
    }
    host.appendChild(list);
  }

  function buildFlowCard(flow, app) {
    const key = flow.id || flow.key || flow.name || '';
    const card = P.el('div', { class: 'card flow-card', dataset: { flowKey: key } });

    // ── 主区 ──
    const main = P.el('div', { class: 'flow-main' });

    const titleRow = P.el('div', { class: 'flow-title-row' }, [
      P.el('div', { class: 'flow-name', text: flow.name || '(未命名流程)' }),
      P.el('span', {
        class: 'flow-state',
        dataset: { state: state.running === key ? 'running' : 'idle' },
        text: state.running === key ? '运行中' : '空闲'
      })
    ]);
    main.appendChild(titleRow);

    // 步骤链（getFlowList 的 steps: [{type,key,name,config_kind}]）
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
          title: type + ' · ' + (step.key || ''),
          text: step.name || step.key || '?'
        }));
      });
      main.appendChild(chain);
    }

    // 元信息：类型 + 步骤数 + 更新时间 + 校验错误
    const meta = P.el('div', { class: 'flow-meta' });
    if (flow.typeText) meta.appendChild(P.el('span', { text: flow.typeText }));
    const stepCount = Number(flow.stepCount || steps.length);
    if (stepCount) meta.appendChild(P.el('span', { text: stepCount + ' 个步骤' }));
    if (flow.updatedAt) {
      meta.appendChild(P.el('span', { text: '更新于 ' + P.timeAgo(flow.updatedAt) }));
    }
    main.appendChild(meta);

    //: 校验错误 —— 这条流程有问题的话，运行前就该看见
    const errors = Array.isArray(flow.errors) ? flow.errors : [];
    if (errors.length) {
      main.appendChild(P.el('div', {
        class: 'run-step',
        style: 'margin-top:6px;color:#fca5a5',
        text: '⚠ ' + errors.join('；')
      }));
    }

    card.appendChild(main);

    // ── 操作 ──
    const actions = P.el('div', { class: 'flow-actions' });

    const isRunning = state.running === key;
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

    actions.appendChild(P.button('详情', {
      size: 'sm',
      onClick: function () { showFlowDetail(flow, app); }
    }));

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

    main.appendChild(P.el('div', { class: 'flow-title-row' }, [
      P.el('div', { class: 'flow-name', text: tool.name }),
      P.el('span', {
        class: 'flow-state',
        dataset: { state: state.running === tool.key ? 'running' : 'idle' },
        text: state.running === tool.key ? '运行中' : '空闲'
      })
    ]));

    if (tool.desc) {
      main.appendChild(P.el('div', {
        class: 'run-step',
        style: 'margin-top:5px;color:var(--dim)',
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
  //  启动 / 停止
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
   * .. code:: text
   *
   *   kind === 'flow'  →  runFlow(flow.id)
   *   否则（工具列表） →  runTask(tool.key)
   *
   * ## ★ 错误文案一律用后端给的 message
   *
   * ``web_bridge`` 的所有失败分支都带 ``message``，而且那是**写给用户看的**
   * （不带异常类名前缀）。自己编文案会丢失真正的原因 ——
   * 前置检查（游戏没开）的说明就只存在于 ``data.message`` 里。
   */
  async function startFlow(flow, app, kind) {
    const isTool = kind === 'tool';
    const key = isTool ? flow.key : (flow.id || flow.key || '');
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
      //: 顺手把状态面板重置成空闲，别让它停在奇怪的状态
      if (data.reason === 'precheck') {
        applyIdle(app);
      }
      return;
    }

    //: 成功 → 状态交给 taskStarted 事件统一处理（Python 那边一定会发）
    void app;
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
      })
      //: ⚠ 这里**故意不订阅 logLine** —— 见 hookGlobalLog 的说明
    ];
    //: 页面常驻 DOM，不需要退订；记录一下便于将来支持重建
    section._offs = (section._offs || []).concat(offs);
  }

  /**
   * ★ 接管 ``app.js`` 的日志入口。
   *
   * ## 为什么必须接管
   *
   * ``app.js`` 的 ``boot()`` 里 ``Bridge.subscribe(handleEvent)``，
   * 收到 ``logLine`` 就调 ``App.appendLog(text)`` —— 直接往 ``#task-log``
   * 里塞一行**没有时间戳**的纯文本。
   *
   * 如果本页**也**订阅 ``logLine`` 再写一遍，用户看到的就是**每条日志两份**：
   *
   * .. code:: text
   *
   *    [骨架] echo_enhance 已接收运行请求（尚未接入真实任务）      ← app.js 写的
   *    23:58:41  [骨架] echo_enhance 已接收运行请求（尚未接入真实任务）  ← 本页写的
   *
   * DSH 项目里这类「两个订阅者各写一次」是日志重复的经典原因。
   *
   * ## 做法
   *
   * 把 ``App.appendLog`` **替换**成解析 ``#task-log`` 的通用版本：
   *
   * * 目标不是 ``#task-log``（比如将来的别处日志）→ 走原来那套
   * * 目标是 ``#task-log`` → 走本页的 :func:`appendLog`（时间戳 / 级别色 / 计数）
   *
   * 这样两条路径都只有**一个**写入点，且其它页面调 ``App.appendLog`` 也不受影响。
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

    if (state.dom.statePill) {
      state.dom.statePill.dataset.state = 'running';
      state.dom.statePill.textContent = '运行中';
    }
    if (state.dom.runName) {
      state.dom.runName.textContent = nameOf(key) || key || '任务';
    }
    if (state.dom.progressText) state.dom.progressText.textContent = '开始';
    if (state.dom.runStep) state.dom.runStep.textContent = '正在启动…';
    if (state.dom.stopBtn) state.dom.stopBtn.disabled = false;

    setProgress(0);
    app.setStatus('running', '运行中');
    syncRowStates();

    //: 日志由 Python 的 logLine 推，这里不再重复写一条
  }

  function applyFinished(app, data) {
    const ok = data.ok !== false;
    const name = nameOf(data.key || state.running) || data.key || '任务';

    state.running = '';
    state.step = '';

    if (state.dom.statePill) {
      state.dom.statePill.dataset.state = ok ? 'idle' : 'failed';
      state.dom.statePill.textContent = ok ? '已完成' : '已停止';
    }
    if (state.dom.runName) {
      state.dom.runName.textContent = ok
        ? name + ' 已完成'
        : name + ' 已结束' + (data.summary ? '：' + data.summary : '');
    }
    if (state.dom.runStep) state.dom.runStep.textContent = data.summary || '';
    if (state.dom.stopBtn) state.dom.stopBtn.disabled = true;

    setProgress(ok ? 100 : state.progress);

    app.setStatus('idle', '就绪');
    syncRowStates();

    //: app.js 已经会写一条「■ 结束」，这里补上成败语气（它那条只说 summary）
    if (!ok && data.summary) {
      appendLog('■ 已停止：' + data.summary, 'warn');
    }
  }

  function applyProgress(data) {
    const value = Number(data.value);
    const text = data.text || '';
    if (isFinite(value)) {
      state.progress = Math.max(0, Math.min(100, value));
      setProgress(state.progress);
    }
    if (text) {
      state.step = text;
      if (state.dom.runStep) state.dom.runStep.textContent = text;
    }
  }

  function setProgress(value) {
    const v = Math.max(0, Math.min(100, Number(value) || 0));
    if (state.dom.progressBar) state.dom.progressBar.style.width = v + '%';
    if (state.dom.progressText) {
      //: 0% 时不显示「空闲」—— 状态胶囊已经在说这件事了，重复反而吵
      state.dom.progressText.textContent = v > 0 ? Math.round(v) + '%' : '';
    }
  }

  /** 恢复外部设置过的状态（app.status / app 里的全局 progress）*/
  function restoreState(app) {
    const running = app.status && app.status.running;
    const progress = (app.status && app.status.progress) || 0;
    if (running) {
      applyRunning(app, running);
      if (progress) {
        state.progress = progress;
        setProgress(progress);
      }
    } else {
      applyIdle(app);
    }
  }

  function applyIdle(app) {
    state.running = '';
    if (state.dom.statePill) {
      state.dom.statePill.dataset.state = 'idle';
      state.dom.statePill.textContent = '空闲';
    }
    if (state.dom.runName) state.dom.runName.textContent = '没有正在运行的任务';
    if (state.dom.runStep) state.dom.runStep.textContent = '等待开始';
    if (state.dom.stopBtn) state.dom.stopBtn.disabled = true;
    setProgress(0);
    syncRowStates();
    void app;
  }

  /** 刷新列表行上的运行态（徽标 + 运行按钮 disabled）*/
  function syncRowStates() {
    const host = state.dom.listHost;
    if (!host) return;
    const busy = !!state.running;
    for (const card of host.querySelectorAll('.flow-card')) {
      const key = card.dataset.flowKey || card.dataset.toolKey || '';
      const pill = card.querySelector('.flow-state');
      const isRunning = busy && key === state.running;
      if (pill) {
        pill.dataset.state = isRunning ? 'running' : 'idle';
        pill.textContent = isRunning ? '运行中' : '空闲';
      }
      const runBtn = card.querySelector('[data-action="run"]');
      if (runBtn) {
        runBtn.disabled = busy;
        runBtn.textContent = isRunning ? '运行中' : '运行';
      }
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
   * 追加一行日志。
   *
   * ## 和 ``App.appendLog`` 的分工
   *
   * ``app.js`` 的版本在收到 ``logLine`` 事件时也会往 ``#task-log`` 里塞一行
   * （只有正文，没有时间戳）。如果这里也塞一条，用户会看到**每条日志两份**。
   *
   * 所以：:func:`bindEvents` **不**订阅 ``logLine`` 让 app.js 写，
   * 而是本页自己订阅 renderer —— 见 :func:`hookGlobalLog`。
   * 这样日志带时间戳 / 带级别色 / 带计数 / 受自动滚动开关控制。
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
  //  详情
  // ════════════════════════════════════════════════════════════════════════
  function showFlowDetail(flow, app) {
    const steps = Array.isArray(flow.steps) ? flow.steps : [];
    const body = P.el('div');

    //: 已有详情就不再叠一层（避免点两次出两个）
    const existing = document.getElementById('flow-detail-host');
    if (existing) existing.parentNode.removeChild(existing);

    const host = P.el('div', { id: 'flow-detail-host' });
    host.appendChild(P.panel({
      title: flow.name || '(未命名流程)',
      subtitle: (flow.typeText || '') + (steps.length ? ' · ' + steps.length + ' 个步骤' : ''),
      padding: '18px 20px',
      actions: [
        P.button('关闭', {
          size: 'sm',
          onClick: function () { host.parentNode && host.parentNode.removeChild(host); }
        })
      ],
      body: body
    }));

    if (steps.length) {
      const sectionEl = P.el('div', { class: 'detail-section' });
      sectionEl.appendChild(P.el('div', { class: 'detail-title', text: '步骤' }));
      const grid = P.el('div', { class: 'detail-grid' });
      steps.forEach(function (step, index) {
        grid.appendChild(P.el('div', {
          class: 'detail-key',
          text: String(index + 1) + '. ' + (step.type || '')
        }));
        grid.appendChild(P.el('div', {
          class: 'detail-val',
          text: (step.name || step.key || '?')
        }));
      });
      sectionEl.appendChild(grid);
      body.appendChild(sectionEl);
    }

    const info = P.el('div', { class: 'detail-section' });
    info.appendChild(P.el('div', { class: 'detail-title', text: '信息' }));
    const infoGrid = P.el('div', { class: 'detail-grid' });
    for (const pair of [
      ['ID', flow.id || flow.key || ''],
      ['名称', flow.name || ''],
      ['摘要', flow.summary || ''],
      ['类型', flow.typeText || ''],
      ['步骤数', String(flow.stepCount || steps.length)],
      ['工具步骤', flow.toolCount != null ? String(flow.toolCount) : ''],
      ['更新时间', flow.updatedAt || '']
    ]) {
      if (!pair[1]) continue;
      infoGrid.appendChild(P.el('div', { class: 'detail-key', text: pair[0] }));
      infoGrid.appendChild(P.el('div', { class: 'detail-val', text: pair[1] }));
    }
    info.appendChild(infoGrid);
    body.appendChild(info);

    //: 校验错误
    const errors = Array.isArray(flow.errors) ? flow.errors : [];
    if (errors.length) {
      const errSection = P.el('div', { class: 'detail-section' });
      errSection.appendChild(P.el('div', { class: 'detail-title', text: '校验问题' }));
      for (const err of errors) {
        errSection.appendChild(P.el('div', {
          class: 'detail-val',
          style: 'color:#fca5a5',
          text: '· ' + err
        }));
      }
      body.appendChild(errSection);
    }

    //: 插在列表下面
    if (state.dom.listHost && state.dom.listHost.parentNode) {
      state.dom.listHost.parentNode.insertBefore(host, state.dom.listHost.nextSibling);
    } else {
      app.go('tasks');
    }
  }
})();
