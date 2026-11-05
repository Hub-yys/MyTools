/* ══════════════════════════════════════════════════════════════════════════
   pages/_panels.js —— ★ 工具面板公共层（P4 新增）

   ## 为什么需要它

   7 个工具面板长得不一样，但**骨架高度相似**：

   .. code:: text

     ┌─ 页头（名字 / 说明 / 运行·停止 按钮）───────┐
     ├─ 参数区（每个工具自己画）───────────────────┤
     ├─ 状态条（空闲 / 运行中 / 完成 / 失败）──────┤
     ├─ 进度条 ────────────────────────────────────┤
     └─ 日志区（等宽字体，滚动）───────────────────┘

   如果把「状态条的四种形态」「日志追加 + 自动滚动」「按钮启用/禁用联动」
   在每个面板里各写一遍，7 份就会长出 7 种不一致的行为 ——
   这正是 P1→P2 阶段「任务页按钮永久 disabled」那类 bug 的温床。

   所以这里抽出三样东西：

   * :func:`createPanel` —— 画骨架，返回一个带 ``setState`` / ``log`` 的句柄
   * :func:`stateText` / :func:`stateTone` —— 状态 → 文案 / 色调的统一映射
   * :func:`runGuard` —— 「同一时刻只能跑一个」的通用守卫

   ## 和 ``_shared.js`` 的分工

   ``_shared.js`` 是**页面级**公共层（DOM 构造、bridge 调用、格式化）；
   本文件是**工具面板级**（状态机、日志区、运行守卫）。
   面板模块两个都 use。

   ## ⚠ 加载顺序

   本文件**必须在 ``_shared.js`` 之后**（它用 ``Pages.el`` 等）。
   所以同样由 index.html 的 script 清单保证 —— 见该文件的说明。
   如果顺序错了，这里的 ``P.ready`` 会在 DOM 就绪后才跑，
   而 ``_shared.js`` 那时一定已经执行完（它同步执行），所以仍然安全。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  const P = window.Pages;
  if (!P) {
    console.error('[panels] _shared.js 没先加载');
    return;
  }

  //: 日志上限（和任务页一致，防长时间运行吃内存）
  const MAX_LOG_LINES = 500;

  // ════════════════════════════════════════════════════════════════════════
  //  状态机：7 个工具共用同一套状态语义
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 状态取值（全部小写，和 CSS 的 ``[data-state]`` 对应）。
   *
   * .. code:: text
   *
   *   idle       空闲（可以点运行）
   *   preparing  准备中（引擎在 boot / 请求已发出但还没开始）
   *   running    运行中（可以点停止）
   *   done       完成（可以再点运行）
   *   failed     失败 / 被拒（显示原因）
   *   blocked    被前置条件拦下（游戏没开 / 没权限）—— 和 failed 分开，
   *              因为它不是"出错"，是"还没准备好"
   */
  const STATES = ['idle', 'preparing', 'running', 'done', 'failed', 'blocked'];

  /** 状态 → 中文文案 */
  function stateText(state) {
    switch (state) {
      case 'preparing': return '准备中';
      case 'running': return '运行中';
      case 'done': return '已完成';
      case 'failed': return '失败';
      case 'blocked': return '未就绪';
      default: return '空闲';
    }
  }

  /** 状态 → 色调（喂给 data-tone，CSS 据此上色） */
  function stateTone(state) {
    switch (state) {
      case 'preparing': return 'warn';
      case 'running': return 'run';
      case 'done': return 'ok';
      case 'failed': return 'error';
      case 'blocked': return 'warn';
      default: return 'idle';
    }
  }

  /** 这个状态下，运行按钮该不该可点 */
  function canRun(state) {
    return state === 'idle' || state === 'done' || state === 'failed'
        || state === 'blocked';
  }

  /** 这个状态下，停止按钮该不该可点 */
  function canStop(state) {
    return state === 'running' || state === 'preparing';
  }

  // ════════════════════════════════════════════════════════════════════════
  //  面板骨架
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 画一个工具面板的骨架，返回句柄。
   *
   * ## 用法
   *
   * .. code:: js
   *
   *   const panel = Panels.create(container, {
   *     key: 'wuwa_library_update',
   *     title: '资源库更新',
   *     desc: '从库街区拉取最新图鉴数据',
   *     onRun: () => doCheck(),
   *     onStop: () => doStop()
   *   });
   *
   *   panel.body.appendChild(myControls);   // 参数区
   *   panel.setState('running', '正在检查更新…');
   *   panel.log('拉到 37 套套装', 'ok');
   *   panel.setProgress(42, '对比差异');
   *
   * @param {HTMLElement} container
   * @param {object} spec - {key, title, desc, onRun, onStop, runLabel, stopLabel}
   * @returns {object} 面板句柄
   */
  function createPanel(container, spec) {
    spec = spec || {};

    // ── 页头 ──
    const head = P.pageHead({
      title: spec.title || '工具',
      subtitle: spec.desc || ''
    });

    const stopBtn = P.button(spec.stopLabel || '停止', {
      kind: 'danger',
      size: 'sm',
      onClick: function () {
        if (typeof spec.onStop === 'function') spec.onStop();
      }
    });
    stopBtn.disabled = true;

    const runBtn = P.button(spec.runLabel || '运行', {
      kind: 'primary',
      size: 'sm',
      onClick: function () {
        if (typeof spec.onRun === 'function') spec.onRun();
      }
    });

    head.actions.appendChild(stopBtn);
    head.actions.appendChild(runBtn);
    container.appendChild(head.head);

    // ── 提示条槽（警告 / 降级说明 / 前置条件都插这儿）──
    const noticeHost = P.el('div');
    container.appendChild(noticeHost);

    // ── 参数区（由各工具自己填）──
    const body = P.el('div', { class: 'tool-panel-body' });
    container.appendChild(body);

    // ── 状态卡 ──
    const statusPill = P.el('span', {
      class: 'flow-state',
      dataset: { state: 'idle' },
      text: stateText('idle')
    });
    const statusText_ = P.el('div', {
      class: 'run-name',
      text: '尚未开始'
    });
    const statusPct = P.el('div', { class: 'run-percent', text: '' });

    const statusCard = P.el('div', { class: 'card-glass run-panel' }, [
      P.el('div', {
        class: 'run-head',
        style: 'padding:15px 18px 0'
      }, [statusPill, statusText_, statusPct]),
      P.el('div', { style: 'padding:10px 18px 15px' }, [
        P.el('div', { class: 'progress' }, [
          P.el('div', { class: 'progress-bar' })
        ]),
        P.el('div', { class: 'run-step', text: '' })
      ])
    ]);
    const progressBar = statusCard.querySelector('.progress-bar');
    const stepLine = statusCard.querySelector('.run-step');
    container.appendChild(statusCard);

    // ── 日志区 ──
    const logCard = P.el('div', { class: 'card-glass', style: 'padding:15px 18px' });
    const logHead = P.el('div', {
      style: 'display:flex;align-items:center;gap:10px;margin-bottom:9px'
    }, [
      P.el('div', { class: 'panel-title', text: '日志' }),
      P.el('div', { class: 'log-count', text: '0 行' }),
      P.el('div', { style: 'margin-left:auto' }, [
        P.button('清空', {
          size: 'sm',
          onClick: function () { handle.clearLog(); }
        })
      ])
    ]);
    const logBox = P.el('div', {
      class: 'log-box',
      id: 'tool-log-' + (spec.key || 'x'),
      style: 'height:220px;max-height:32vh'
    });
    logCard.appendChild(logHead);
    logCard.appendChild(logBox);
    container.appendChild(logCard);

    const logCount = logHead.querySelector('.log-count');

    // ════════════════════════════════════════════════════════════════════
    //  句柄
    // ════════════════════════════════════════════════════════════════════
    const state = { value: 'idle', lines: 0, autoScroll: true };

    const handle = {
      key: spec.key || '',
      head: head.head,
      actions: head.actions,
      noticeHost: noticeHost,
      body: body,
      runBtn: runBtn,
      stopBtn: stopBtn,
      logBox: logBox,

      /** 当前状态值 */
      get state() { return state.value; },

      /**
       * 设置状态。
       *
       * @param {string} value - idle / preparing / running / done / failed / blocked
       * @param {string} [text] - 状态行文案
       * @param {object} [opts] - {step, percent, runDisabled}
       */
      setState: function (value, text, opts) {
        opts = opts || {};
        if (STATES.indexOf(value) < 0) {
          console.warn('[panels] 未知状态:', value);
          value = 'idle';
        }
        state.value = value;

        //: ★ ``data-state`` 必须**如实**写状态机的值。
        //:
        //: 第一版这里写的是 ``value === 'preparing' ? 'idle' : value``，
        //: 理由是「preparing 没有对应的 CSS」。结果是：
        //: 面板确实显示"准备中"，但 DOM 里 ``data-state`` 是 ``idle`` ——
        //: 任何靠 data-state 判断状态的代码（验证脚本、将来的自动化）
        //: 都会把"引擎正在启动"读成"空闲"，进而误判成"已经结束"。
        //:
        //: 视觉差异改用 ``data-tone`` 表达（CSS 按 tone 上色），
        //: 这样"状态语义"和"视觉呈现"各走各的，互不污染。
        statusPill.dataset.state = value;
        statusPill.dataset.tone = stateTone(value);
        statusPill.textContent = stateText(value);

        if (text != null) statusText_.textContent = text;

        //: 按钮联动 —— 这是最容易写错的地方（P1 的按钮永久 disabled 就是漏了恢复）
        runBtn.disabled = !canRun(value);
        stopBtn.disabled = !canStop(value);

        if (opts.percent != null) {
          handle.setProgress(opts.percent, opts.step);
        } else if (opts.step != null) {
          stepLine.textContent = opts.step;
        }

        //: 完成 / 空闲时把进度条归零，别留着上一次的 100%
        if (value === 'idle' && opts.percent == null) {
          handle.setProgress(0, '');
        }
      },

      /** 进度（0~100）+ 当前动作说明 */
      setProgress: function (percent, stepText) {
        const v = Math.max(0, Math.min(100, Number(percent) || 0));
        if (progressBar) progressBar.style.width = v + '%';
        if (statusPct) statusPct.textContent = v > 0 ? Math.round(v) + '%' : '';
        if (stepText != null && stepLine) stepLine.textContent = stepText;
      },

      /**
       * 追加一行日志。
       *
       * @param {string} text
       * @param {string} [level] - info / ok / warn / error / debug
       */
      log: function (text, level) {
        const content = String(text == null ? '' : text);
        if (!content) return;

        const line = P.el('div', {
          class: 'log-line',
          dataset: { level: level || 'info' }
        }, [
          P.el('span', { class: 'log-time', text: clock() }),
          P.el('span', { class: 'log-text', text: content })
        ]);
        logBox.appendChild(line);
        state.lines += 1;

        while (logBox.childElementCount > MAX_LOG_LINES) {
          logBox.removeChild(logBox.firstElementChild);
          state.lines -= 1;
        }
        logCount.textContent = state.lines + ' 行';

        if (state.autoScroll) logBox.scrollTop = logBox.scrollHeight;
      },

      /** 清空日志 */
      clearLog: function () {
        logBox.innerHTML = '';
        state.lines = 0;
        logCount.textContent = '0 行';
      },

      /**
       * 在提示区显示一条说明（降级 / 前置条件 / 错误）。
       *
       * @param {string} html
       * @param {string} [level] - info / warn / error / ok
       * @param {string} [tag] - 同 tag 的旧提示会被替换（避免堆叠）
       */
      notice: function (html, level, tag) {
        const selector = tag
          ? '.notice[data-tag="' + tag + '"]'
          : '.notice';
        const old = noticeHost.querySelector(selector);
        if (old) old.remove();
        const box = P.notice(html, level || 'info');
        if (tag) box.dataset.tag = tag;
        noticeHost.appendChild(box);
        return box;
      },

      /** 移除某个 tag 的提示 */
      clearNotice: function (tag) {
        const old = noticeHost.querySelector('.notice[data-tag="' + tag + '"]');
        if (old) old.remove();
      },

      /** 便捷：绑定一个事件源，自动在面板销毁时退订（这里不销毁，只记录）*/
      track: function (offs) {
        (container._offs || (container._offs = [])).push(offs);
      }
    };

    return handle;
  }

  function clock() {
    const now = new Date();
    function pad(n) { return n < 10 ? '0' + n : String(n); }
    return pad(now.getHours()) + ':' + pad(now.getMinutes()) + ':'
         + pad(now.getSeconds());
  }

  // ════════════════════════════════════════════════════════════════════════
  //  运行守卫：同一时刻只能跑一个（7 个工具共用）
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 把一个后端的「运行结果」翻译成面板状态 + 日志。
   *
   * ## 为什么统一处理
   *
   * 7 个工具的后端返回结构**本该一致**（``{ok, reason, message}``），
   * 但历史原因各不相同。这个函数把已知的 reason 都吃下来，
   * 保证用户在任何面板上看到的失败原因**格式一致**。
   *
   * @param {object} panel - createPanel 的句柄
   * @param {object} result - P.call 的返回值
   * @param {string} label - 工具名（拼日志用）
   * @returns {boolean} 是否成功开始
   */
  function handleRunResult(panel, result, label) {
    // ── 桥接层调用失败 ──
    if (!result || !result.ok) {
      const detail = result && result.missing
        ? '桥接缺少对应接口'
        : String((result && result.error && result.error.message)
                 || (result && result.error) || '未知错误');
      panel.setState('failed', '调用失败');
      panel.log('✗ ' + detail, 'error');
      panel.notice(P.esc(detail), 'error', 'runfail');
      return false;
    }

    const data = result.data || {};

    // ── 后端明确拒绝 ──
    if (data.ok === false) {
      const reason = data.reason || '';
      //: 后端 message 是写给用户看的，优先用
      const message = data.message || data.hint || '';

      // ── 忙 ──
      if (reason === 'busy') {
        panel.setState('failed', '已有任务在运行');
        panel.log('✗ ' + (message || '已有任务在运行（' + (data.running || '?') + '）'),
          'warn');
        //: ★ 也要弹出来 —— 否则用户只看到一个"失败"徽标，不知道是被谁占着
        panel.notice(
          P.esc(message) ||
          ('已有任务在运行（<b>' + P.esc(data.running || '未知') + '</b>）— ' +
           '同一时刻只能跑一个任务，请先停止它。'),
          'warn', 'runfail'
        );
        return false;
      }

      // ── 前置条件没满足 ──
      if (reason === 'precheck' || reason === 'blocked'
          || reason === 'permission' || reason === 'not_ready') {
        //: 这不是"出错"，是"还没准备好"
        panel.setState('blocked', '前置条件未满足');
        panel.log('⚠ ' + (message || '前置检查未通过'), 'warn');
        if (message) panel.notice(P.esc(message), 'warn', 'runfail');
        return false;
      }

      // ── 其它启动失败（含 start_failed）──
      //
      //: ★ 这类 message 往往**带排查线索**（日志路径、具体原因），
      //: 只写进日志区是不够的 —— 日志区可能已经滚上去了，用户看不见。
      //: 必须同时弹到提示区。
      panel.setState('failed', '启动失败');
      const text = message || (label + ' 启动失败：' + (reason || '未知原因'));
      panel.log('✗ ' + text, 'error');
      panel.notice(P.esc(text), 'error', 'runfail');
      return false;
    }

    // ── 成功受理 ──
    panel.clearNotice('runfail');
    panel.setState('running', label + ' 运行中');
    return true;
  }

  // ════════════════════════════════════════════════════════════════════════
  //  参数控件（几个面板共用的表单件）
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 一行表单：标签 + 控件 + 说明。
   *
   * @returns {object} {row, controlHost}
   */
  function field(label, control, hint) {
    const row = P.el('div', { class: 'field' });
    const labelEl = P.el('div', { class: 'field-label', text: label });
    const controlHost = P.el('div', { class: 'field-control' });
    if (control) controlHost.appendChild(control);
    row.appendChild(labelEl);
    row.appendChild(controlHost);
    if (hint) {
      row.appendChild(P.el('div', { class: 'field-hint', text: hint }));
    }
    return row;
  }

  /** 下拉框 → {el, get(), set(value)} */
  function select(options, current) {
    const box = P.el('select', { class: 'input' });
    for (const opt of options) {
      const value = typeof opt === 'string' ? opt : opt.value;
      const label = typeof opt === 'string' ? opt : opt.label;
      const el = P.el('option', { value: value, text: label });
      if (value === current) el.selected = true;
      box.appendChild(el);
    }
    return {
      el: box,
      get: function () { return box.value; },
      set: function (v) { box.value = v; },
      setOptions: function (list, keep) {
        box.innerHTML = '';
        for (const opt of list) {
          const value = typeof opt === 'string' ? opt : opt.value;
          const label = typeof opt === 'string' ? opt : opt.label;
          box.appendChild(P.el('option', { value: value, text: label }));
        }
        if (keep) box.value = keep;
      }
    };
  }

  /**
   * 数字输入 → ``{el, get(), set(v)}``
   *
   * ## ★ 结构照抄旧界面 ``NumberField``（``gui/widgets.py`` L176+）
   *
   * .. code:: python
   *
   *   self.minus = ToolButton(FluentIcon.REMOVE, self)
   *   self.minus.setFixedSize(30, 30)
   *   self.edit = LineEdit(self)
   *   self.edit.setFixedWidth(76)                            # ← 76px
   *   self.edit.setAlignment(Qt.AlignmentFlag.AlignCenter)   # ← 居中
   *   self.plus = ToolButton(FluentIcon.ADD, self)
   *   self.plus.setFixedSize(30, 30)
   *   layout.setSpacing(6)                                   # ← 间距 6px
   *
   * 即 ``[−] [76px 输入框] [+]`` —— 可以点加减，也可以直接敲。
   *
   * ⚠ 2026-11-02 用户圈「加减号呢」—— 我原来只做了裸输入框。
   *
   * ## ``step`` 默认 1（照抄旧界面 ``step=1.0``）
   *
   * 双爆下限是小数（7.5 / 15.0），但旧界面**就是 1**，
   * 所以照抄（点两下 6.9 → 8.9，想填精确值就直接敲）。
   */
  function numberInput(value, opts) {
    opts = opts || {};
    const step = opts.step != null ? Number(opts.step) : 1;
    //: ★ 2026-11-05 新增两个选项（用户圈图：双爆下限「只能输入数字，
    //: 且暴击只能在 6.3 到 10.5 之间（一位小数）」）。
    //:
    //: ① ``decimals`` —— 保留几位小数（默认 2，**老调用的行为一个像素不变**）。
    //:    之前 ``fmt()`` 硬编码 ``*100/100``，双爆下限要求一位小数做不到。
    //: ② ``numeric`` —— 是否在**输入阶段**就滤掉非法字符。
    //:    以前只靠 ``blur`` 纠错：``type="text"`` 能敲字母，用户敲了 "abc"
    //:    要等失焦才被改成 0，中间那段时间框里就是脏的。
    //:
    //: ⚠ 输入阶段**只滤字符和位数，不夹上下界** —— 中途夹会让打字错乱：
    //:   想填 6.9 的人刚敲 "6" 就被夹成 6.3，后面那个 ".9" 无处可落。
    //:   上下界交给 ``blur``（现有行为）和调用方的 ``validate()``。
    const decimals = opts.decimals != null ? Math.max(0, Number(opts.decimals)) : 2;
    const numeric = opts.numeric === true;
    //: ★★★ 2026-11-03 必须是 ``let``（原来是 ``const``）—— 见下面
    //: ``setRange()`` 的注释：配置页的「有效词条」上下界会跟着核心/可选
    //: 属性**动态变**，而 ``clamp()`` 读的就是这两个变量。
    let min = opts.min != null ? Number(opts.min) : null;
    let max = opts.max != null ? Number(opts.max) : null;

    const wrap = P.el('div', { class: 'numfield' });

    const minus = P.el('button', {
      class: 'numfield-btn',
      type: 'button',
      text: '−',
      title: '减 ' + step,
      onClick: function () { bump(-step); }
    });
    wrap.appendChild(minus);

    const input = P.el('input', {
      class: 'input numfield-edit',
      type: 'text',
      inputmode: 'decimal',
      value: value == null ? '' : String(value),
      placeholder: opts.placeholder || ''
    });
    //: ★ 2026-11-05：建控件时就把上下界写到 DOM 属性上。
    //: 原来只有 ``setRange()`` 会写，构造时传的 ``min``/``max`` 只存在闭包里
    //: —— ``type="text"`` 本来就不认这两个属性、不影响行为，但**探针和
    //: "看一眼属性就知道范围"的场景会读它**（2026-11-05 的探针就因此误判成
    //: 「没限制范围」）。现在两条入口行为一致。
    if (min != null) input.min = String(min);
    if (max != null) input.max = String(max);
    wrap.appendChild(input);

    const plus = P.el('button', {
      class: 'numfield-btn',
      type: 'button',
      text: '＋',
      title: '加 ' + step,
      onClick: function () { bump(step); }
    });
    wrap.appendChild(plus);

    function clamp(n) {
      let out = n;
      if (min != null && out < min) out = min;
      if (max != null && out > max) out = max;
      return out;
    }

    /** 去掉末尾多余的 0（7.00 → 7，6.90 → 6.9）—— 旧界面 ``_fmt_number`` */
    function fmt(n) {
      const num = Number(n);
      if (!isFinite(num)) return '';
      const scale = Math.pow(10, decimals);
      return String(Math.round(num * scale) / scale);
    }

    function current() {
      const n = Number(input.value);
      return isFinite(n) ? n : 0;
    }

    function bump(delta) {
      const next = clamp(current() + delta);
      input.value = fmt(next);
      input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    //: 失焦时把非法内容纠正成合法值（旧界面靠 ``QDoubleValidator`` 拦在输入阶段）
    //:
    //: ★★★ 2026-11-03 加 ``clampOnBlur`` 开关 —— 默认仍然纠错（老行为），
    //: 但配置页的「有效词条」要**看得见自己填的值**：用户圈图那张
    //: （填 3 / 所选属性只有 2 条）要求「应该提示创建失败」，如果这里
    //: 失焦就悄悄夹成 2，用户点「创建」会直接成功，永远看不到提示。
    //: 传 ``clampOnBlur: false`` 时越界值原样留着，由调用方自己校验并报错。
    if (opts.clampOnBlur !== false) {
      input.addEventListener('blur', function () {
        input.value = fmt(clamp(current()));
      });
    }

    //: 输入阶段过滤：只留数字 + 一个小数点 + 最多 ``decimals`` 位小数。
    //: 用 ``input`` 事件而不是 ``keydown`` —— 粘贴、输入法、手机键盘
    //: 都走 ``input``，``keydown`` 只能拦物理按键。
    if (numeric) {
      input.addEventListener('input', function () {
        const raw = input.value;
        let out = '';
        let hasDot = false;
        let decCount = 0;
        for (const ch of raw) {
          if (ch >= '0' && ch <= '9') {
            if (hasDot) {
              if (decCount >= decimals) continue;
              decCount += 1;
            }
            out += ch;
          } else if (ch === '.' && !hasDot && decimals > 0) {
            hasDot = true;
            out += ch;
          }
        }
        if (out !== raw) input.value = out;
      });
    }

    return {
      el: wrap,
      input: input,
      get: function () {
        const n = Number(input.value);
        return isFinite(n) ? n : 0;
      },
      set: function (v) {
        input.value = v == null ? '' : fmt(Number(v));
      },
      /**
       * 换上下界 —— ★★★ 2026-11-03 新增（用户圈图「这里是3，但是所选
       * 属性只有2条，怎么创建，应该提示创建失败」）。
       *
       * ## 为什么需要它（原来的坑）
       *
       * ``min`` / ``max`` 是**建控件时**传进来的常量，``clamp()`` 和
       * ``blur`` 纠错读的都是这两个闭包变量。配置页的 ``syncValidRange()``
       * 只改了 DOM 属性::
       *
       *     input.min = String(low);
       *     input.max = String(high);
       *
       * 但 ``type="text"`` 的 ``min`` / ``max`` **根本不是约束**（那是
       * ``type="number"`` 才认的），``clamp()`` 也读不到。
       * 所以「核心 2 条」时上界早该是 2，输入框却还能停在 3
       * —— 点「创建」后端才按 ``__post_init__`` 静默夹成 2，
       * 用户看到的 3 从头到尾没生效，属于**看不见的偏差**。
       *
       * 现在 ``syncValidRange()`` 调它，闭包里的真上界跟着变。
       */
      setRange: function (lo, hi) {
        min = lo == null ? null : Number(lo);
        max = hi == null ? null : Number(hi);
        if (min != null) input.min = String(min);
        if (max != null) input.max = String(max);
      }
    };
  }

  /** 文本输入 → {el, get(), set(s)} */
  function textInput(value, placeholder) {
    const input = P.el('input', {
      class: 'input',
      type: 'text',
      value: value == null ? '' : String(value),
      placeholder: placeholder || ''
    });
    return {
      el: input,
      get: function () { return input.value; },
      set: function (v) { input.value = v == null ? '' : String(v); }
    };
  }


  // ════════════════════════════════════════════════════════════════════════
  //  ★ 运行追踪：区分「受理了」和「真的跑起来了」
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 创建一个"本轮运行"追踪器。
   *
   * ## 为什么必须是公共组件（2026-11-02，7 个工具里 5 个会用到）
   *
   * 走 ok-ww 的 3 个工具（``echo_change`` / ``auto_combat`` / ``nest_sweep``）
   * 和走异步线程的 2 个（``wuwa_library_update`` / ``gacha``）都有同一个陷阱：
   *
   * .. code:: text
   *
   *   后端返回 {"ok": true}   ← 这只表示"受理了"
   *   但用户以为           ← "开始跑了"
   *
   * 实测（``echo_change``）：``runOkwwTask`` 返回 ``ok:true`` 之后，
   * 状态可能**全程停在 ready 且 runningTask 为空** —— 因为
   * ``input_permission_error()`` 在游戏没开时返回 ``None``（不拦），
   * 引擎起来了但任务跑不动。这个状态和"刚跑完"**完全一样**。
   *
   * 如果面板直接把「runningTask 空」当"结束"，用户会看到一闪而过的
   * 「已完成」—— 而实际一次都没跑。这比显示"失败"糟糕得多。
   *
   * ## 用法
   *
   * .. code:: js
   *
   *   const tracker = Panels.trackRun({
   *     onGiveUp: function () { panel.setState('blocked', '没能真正启动'); }
   *   });
   *
   *   await P.call('runOkwwTask', ...);        // 受理
   *   tracker.accept();                        // 标记"本轮已受理"
   *
   *   // 轮询里：
   *   tracker.observe({running: runningTask === MY_TASK});
   *   if (tracker.isFinished()) { ...done... }
   *   if (tracker.gaveUp())     { ...blocked... }
   *
   * @param {object} [opts]
   * @param {number} [opts.timeoutMs] - 受理后多久没进 running 就放弃（默认 8s）
   * @param {function} [opts.onGiveUp] - 放弃时的回调
   * @param {function} [opts.onFinish] - 判定结束时的回调
   * @returns {object} 追踪器
   */
  function trackRun(opts) {
    opts = opts || {};
    const baseTimeoutMs = Number(opts.timeoutMs) > 0 ? Number(opts.timeoutMs) : 8000;

    const st = {
      /** 本轮是否已受理（点了运行、后端返回 ok） */
      accepted: false,
      /** 本轮是否**真的**看到过 running */
      sawRunning: false,
      /** 受理的时间戳（会被 extend/booting 重置） */
      acceptedAt: 0,
      /** 当前生效的超时（可被 extend 拉长） */
      timeoutMs: baseTimeoutMs,
      /** 已判定结束（防止重复回调） */
      finished: false,
      /** 已判定放弃（防止重复回调） */
      gaveUpFlag: false
    };

    const tracker = {
      /** 标记"本轮已受理"（在 runTask/runOkwwTask 返回 ok 之后调）*/
      accept: function () {
        st.accepted = true;
        st.sawRunning = false;
        st.acceptedAt = Date.now();
        st.timeoutMs = baseTimeoutMs;
        st.finished = false;
        st.gaveUpFlag = false;
      },

      /** 复位（新一次运行开始前调，或运行失败时）*/
      reset: function () {
        st.accepted = false;
        st.sawRunning = false;
        st.acceptedAt = 0;
        st.timeoutMs = baseTimeoutMs;
        st.finished = false;
        st.gaveUpFlag = false;
      },

      /**
       * ★ 延长超时并**重置计时起点**。
       *
       * ## 为什么需要（2026-11-02，lead 指出的真缺陷）
       *
       * 第一版从"受理时刻"硬算 N 秒。但引擎**首次**启动是懒加载，
       * 冷启动可能 10 秒以上 —— 而 ``runOkwwTask`` 明确会返回
       * ``engineState: "booting"`` 表示"别判死，我还在起"。
       *
       * 硬算的结果是：引擎正常启动中，8 秒一到 trackRun 判 ``blocked``，
       * 用户看到「没能真正启动」，1 秒后战斗却真的开始了 —— 自己打自己脸。
       *
       * @param {number} [ms] - 新的超时（不传就沿用当前）
       */
      extendTimeout: function (ms) {
        if (Number(ms) > 0) st.timeoutMs = Number(ms);
        //: 重置起点：从"确认还在启动"这一刻重新计时
        st.acceptedAt = Date.now();
        //: 如果之前已经判过放弃，撤销它（引擎后来确实起来了）
        st.gaveUpFlag = false;
      },

      /**
       * ★ 感知后端上报的引擎状态，自动调整等待策略。
       *
       * @param {string} engineState - 'booting' | 'running' | 'ready' | 'error'
       * @returns {boolean} 是否识别并处理了
       */
      noteEngineState: function (engineState) {
        const value = String(engineState || '');
        if (value === 'booting') {
          //: 引擎还在起 —— 这是**正常**的，给足时间，别判死
          tracker.extendTimeout(Math.max(st.timeoutMs * 2, 20000));
          return true;
        }
        if (value === 'running') {
          st.sawRunning = true;
          st.gaveUpFlag = false;
          return true;
        }
        return false;
      },

      /**
       * 喂一次观测结果。
       *
       * @param {object} obs - {running: boolean, engineState?: string}
       *   ``running`` = 后端此刻是否报告"本任务在跑"
       *   ``engineState`` = 可选，后端上报的引擎状态（有就自动处理）
       */
      observe: function (obs) {
        if (!st.accepted) return;

        //: 有引擎状态就先让它调参（booting 会延长超时）
        if (obs && obs.engineState) {
          tracker.noteEngineState(obs.engineState);
        }

        if (obs && obs.running) {
          st.sawRunning = true;
          st.gaveUpFlag = false;    //: 一旦真跑起来，就不再算"放弃"
          return;
        }

        //: 跑起来过、现在不跑了 → 结束
        if (st.sawRunning) {
          if (!st.finished) {
            st.finished = true;
            if (typeof opts.onFinish === 'function') opts.onFinish();
          }
          return;
        }

        //: 受理了但迟迟没进 running → 放弃
        //
        //: ⚠ 必须用 **st.timeoutMs**（可变），不能用闭包里的
        //: ``timeoutMs`` —— 否则 extendTimeout() 改了 st 却不生效，
        //: 「booting 时延长」等于没做。（这里踩过一次）
        if (Date.now() - st.acceptedAt > st.timeoutMs && !st.gaveUpFlag) {
          st.gaveUpFlag = true;
          if (typeof opts.onGiveUp === 'function') opts.onGiveUp();
        }
      },

      /** 本轮是否真的跑起来过 */
      everRan: function () { return st.sawRunning; },
      /** 是否已判定结束（跑过之后又停了）*/
      isFinished: function () { return st.finished; },
      /** 是否已判定放弃（从来没跑起来）*/
      gaveUp: function () { return st.gaveUpFlag; },
      /** 内部状态（调试/测试用）*/
      state: function () { return Object.assign({}, st); }
    };

    return tracker;
  }

  /**
   * ★ 处理 ``mayNotRun`` —— 后端在启动瞬间就能判断"大概率跑不起来"。
   *
   * ## 为什么需要它（2026-11-02，替代"盲等 8 秒"）
   *
   * 第一版只能靠**猜**：受理后等 8 秒还没看到 running，才判定"没能启动"。
   * 用户白白等 8 秒才知道游戏没开。
   *
   * 现在 ``runOkwwTask`` 起任务后会等 1.2 秒（够引擎 ``booting → ready``），
   * 然后如实回报：
   *
   * .. code:: text
   *
   *   engineStarted: true,  engineState: "running"   → 真的跑起来了
   *   engineStarted: true,  engineState: "ready"     → 引擎起来了但任务没跑（mayNotRun）
   *   engineStarted: false, engineState: "booting"   → 首次启动慢，继续等
   *   engineState: "error"                            → 引擎挂了
   *
   * **``mayNotRun`` 和 ``sawRunning`` 是互补的**：
   * 前者判断"启动瞬间"，后者跟踪"运行过程中"。两个都要留。
   *
   * @param {object} panel - createPanel 的句柄
   * @param {object} data - runOkwwTask 的返回体
   * @returns {string} 'running' | 'booting' | 'stalled' | 'error' | ''
   *   ``stalled`` = 受理了但没跑起来（应立即提示，不用等超时）
   */
  function applyWindow(panel, data) {
    const d = data || {};
    const engineState = String(d.engineState || d.engine_state || '');
    const warning = String(d.warning || '');

    if (d.mayNotRun) {
      //: ★ 立刻提示 —— 不必等 8 秒超时
      if (warning) {
        panel.log('⚠ ' + warning, 'warn');
      }
      panel.notice(
        P.esc(warning) ||
        ('引擎没有进入运行状态。多半是：游戏没开着 / 界面不在正确位置 / ' +
         '不是管理员权限。<br>请逐条检查上面的「运行前提」后重试。'),
        'warn', 'maynotrun'
      );
      panel.setProgress(0, '');
      return engineState === 'error' ? 'error' : 'stalled';
    }

    panel.clearNotice('maynotrun');

    if (engineState === 'running') return 'running';
    if (engineState === 'booting' || d.engineStarted === false) {
      //: 首次启动引擎慢，属于正常 —— 继续轮询
      panel.log('引擎正在启动（首次启动会慢一些）…', 'debug');
      return 'booting';
    }
    if (engineState === 'error') {
      if (warning) panel.notice(P.esc(warning), 'error', 'engine');
      return 'error';
    }
    return '';
  }

  /**
   * ★ 设置「引擎状态行」的文案，空串就整行隐藏（2026-11-03）。
   *
   * ## 为什么要一个 helper
   *
   * 用户圈图要求「说明文字都去掉」。但状态行里混着**两种东西**：
   *
   * ==================  ==========================================
   * 类型                 例子
   * ==================  ==========================================
   * 静态说明（要删）      「引擎：就绪 · 点「启动」开始 4C 刷声骸」
   * 动态反馈（必须留）    「引擎：启动失败 —— …」
   *                      「引擎：被占用（正在跑 xxx）」
   *                      「引擎：正在启动…」（冷启动 ~20 秒）
   * ==================  ==========================================
   *
   * 直接删掉元素会**连失败反馈一起删掉** —— 那就变成静默失败，
   * 正是交接文档里点名批评的头号坑。
   *
   * 所以：**留元素、空文案时隐藏**。
   *
   * ## ⚠ 用 ``.hidden`` 类，不用 ``hidden`` 属性（踩到过）
   *
   * HTML 的 ``hidden`` 属性只是一个 ``display:none`` 的**弱默认值**：
   * 页面里任何一条 ``.some-class { display:flex }`` 都能盖掉它
   * （本项目 ``.cfg-muted`` / ``.cfg-state`` / ``.sw`` 全都是 flex）。
   *
   * 实测：给 ``.cfg-muted`` 元素设 ``el.hidden = true`` 之后它照样显示。
   *
   * 本项目统一用 ``.hidden`` 类 —— ``base.css`` 里是
   * ``display:none !important``，盖不掉。
   *
   * @param {HTMLElement} el - 状态行元素（可能是 null）
   * @param {string} text - 空串 = 隐藏
   */
  function setStateLabel(el, text) {
    if (!el) return;
    const value = String(text == null ? '' : text);
    if (value) {
      el.textContent = value;
      el.classList.remove('hidden');
      el.hidden = false;          //: 双保险（万一有人只看属性）
    } else {
      el.textContent = '';
      el.classList.add('hidden');
      el.hidden = true;
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  导出
  // ════════════════════════════════════════════════════════════════════════

  window.Panels = {
    STATES: STATES,
    stateText: stateText,
    stateTone: stateTone,
    canRun: canRun,
    canStop: canStop,
    create: createPanel,
    handleRunResult: handleRunResult,
    trackRun: trackRun,
    applyWindow: applyWindow,
    field: field,
    select: select,
    numberInput: numberInput,
    textInput: textInput,
    setStateLabel: setStateLabel
  };
})();
