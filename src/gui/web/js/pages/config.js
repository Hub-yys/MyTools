/* ══════════════════════════════════════════════════════════════════════════
   pages/config.js —— 配置页（配置列表）

   **P2 重写**。P1 版本只有皮肤色板 + 玻璃参数说明，没有任何配置项。

   ## ⚠ 先说清楚：Qt 版的「配置页」不是「设置页」

   任务书里写的是「游戏路径、各种开关、表单提交」，但源码
   ``src/gui/config_interface.py``（677 行）实际是**配置列表页**：

   .. code:: text

     配置页 —— 一条一条列出已保存的配置
               每条：查看 / 修改 / 删除
               左上角：新增（先选类型）

   两类配置（用户 2026-09-26 要求，**一个角色一条**）：

   ===================================  ================================  ==============
   类型                                  数据源                             角色
   ===================================  ================================  ==============
   角色声骸筛选（loadout）                ``core.loadout.LoadoutStore``     ``loadouts.json``
   角色声骸强化（echo_profile）           ``core.echo_profile.EchoProfileStore`` ``echo_profiles.json``
   ===================================  ================================  ==============

   所以这个页面照源码做**配置列表**，不是设置表单。
   真正的应用设置（壁纸/玻璃/皮肤）在「主题皮肤」页，不在这儿。

   ## 三类配置？源码里还有 BattleProfileStore

   ``config_interface`` 引入了 ``BattleProfileStore`` 和 ``KIND_BATTLE_PROFILE``，
   但页面主体是 loadout + echo_profile。这里也按两类做，第三类等接口
   明确给出来再加（接口返回什么就显示什么，见 :func:`normalizeConfigs`）。

   ## 双态

   ``web_bridge.py`` 目前没有读配置的方法。所以：

   * 有 ``getConfigList()`` → 渲染真实配置（头像 / 摘要 / 查看·修改·删除）
   * 没有 → 明确提示 + 保留「玻璃配方自检」面板（它不依赖后端，
     而且真的能证明桥接和 CSS 变量是通的）

   接口一到位自动升级，页面不用改。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  if (!window.App) {
    console.error('[config] app.js 没先加载');
    return;
  }

  if (!window.Pages) {
    console.error('[config] _shared.js 没先加载');
    return;
  }

  const P = window.Pages;

  //: ★ ``tool-panels.js`` 导出的卡片构件（``cfgCard`` / ``collapsibleCard``
  //: 和声骸强化的常量）。
  //:
  //: ## 为什么需要它
  //:
  //: 「新增/编辑」弹框的设置区 = **「声骸自动强化」工具页那一份**
  //: （旧界面 ``EchoProfileDialog`` 直接用 ``EchoSettingsEditor``）。
  //: 而那些构件定义在 ``tool-panels.js`` 的 IIFE 里 —— 两个文件是
  //: **独立作用域**，不导出就调不到。
  //:
  //: ⚠ 2026-11-02 踩过：调不到时报 ``collapsibleCard is not defined``，
  //: 而且因为弹框是 **async** 打开的，这个异常**不进 ``window.onerror``**
  //: —— 表现只是「点了「下一步」什么都没发生」，极难查。
  //: 现在由 ``showDialogFailure()`` 把异常显示出来。
  const TP = window.ToolPanels || {};

  if (!TP.collapsibleCard) {
    console.error('[config] tool-panels.js 没先加载（缺 ToolPanels 导出）');
  }
  const App = window.App;

  /** 分类定义（value 和 Python 侧的 config_kind 对应）*/
  const KINDS = [
    { value: 'all', label: '全部', kind: '' },
    { value: 'loadout', label: '角色声骸筛选', kind: 'loadout' },
    { value: 'echo_profile', label: '角色声骸强化', kind: 'echo_profile' },
    { value: 'battle_profile', label: '战斗配置', kind: 'battle_profile' }
  ];

  const state = {
    /** 全部配置（归一化后）*/
    items: [],
    /** 当前分类 */
    kind: 'all',
    /** 是否拿到了真实数据 */
    available: false,
    /** 搜索关键词 */
    keyword: '',
    dom: {}
  };

  P.ready(function () {
    App.registerPage('config', renderConfig);
  });

  // ════════════════════════════════════════════════════════════════════════
  //  渲染
  // ════════════════════════════════════════════════════════════════════════
  async function renderConfig(section, app) {
    // ══════════════════════════════════════════════════════════════════════
    //  ★ P5 重写：**照抄旧界面** ``config_interface.py`` L218-255
    //
    //  旧界面从上到下的顺序：
    //
    //  .. code:: python
    //
    //    header = QHBoxLayout()
    //    header.addWidget(TitleLabel("配置", ...))        # 标题
    //    add_button = PrimaryPushButton(FluentIcon.ADD, "新增")
    //    header.addWidget(add_button)                    # ★ 「+ 新增」在标题**右边**
    //    header.addStretch(1)
    //
    //    self.search_edit = SearchLineEdit(...)           # 搜索框（280）
    //    self.subtitle = CaptionLabel("")                 # ★ 计数说明行
    //    self.list_host = QWidget(...)                    # 列表（按类型分组）
    //
    //  P4 我做成了「页签切换 + 右上角搜索」，和旧界面不一样。
    // ══════════════════════════════════════════════════════════════════════
    const head = P.pageHead({ title: '配置' });

    //: ★ 「+ 新增」按钮在标题右边（旧界面 L225-227）
    const addBtn = P.button('新增', {
      kind: 'primary',
      size: 'sm',
      onClick: function () { openConfigTypeDialog(app); }
    });
    addBtn.dataset.action = 'add-config';
    head.actions.appendChild(addBtn);

    //: 刷新按钮（旧界面没有，但 P4 加的它不占主要位置，保留在新增右边）
    head.actions.appendChild(P.button('刷新', {
      icon: 'HISTORY',
      size: 'sm',
      onClick: function () { reload(); }
    }));
    section.appendChild(head.head);

    //: 数据加载（双态）
    await load();

    // ── 提示条（仅在降级时） ──
    const noticeHost = P.el('div');
    section.appendChild(noticeHost);
    if (!state.available) {
      noticeHost.appendChild(P.notice(
        '<b>配置数据接口未接入</b>。配置存在 <code>data/loadouts.json</code> 与 ' +
        '<code>data/echo_profiles.json</code>，由 <code>core.loadout.LoadoutStore</code> / ' +
        '<code>core.echo_profile.EchoProfileStore</code> 管理。' +
        '需要 Python 侧暴露 <code>getConfigList()</code> 才能在页面里显示。',
        'warn'
      ));
    }

    // ══════════════════════════════════════════════════════════════════════
    //  搜索框 —— 照抄旧界面 L231-245
    //
    //  .. code:: python
    //
    //    # ---- 搜索框（用户 2026-09-30："加上搜索，和前面下拉列表搜索一样的"）----
    //    self.search_edit = SearchLineEdit(self.view)
    //    self.search_edit.setPlaceholderText("搜索角色名（支持拼音，如 feixue / fx）")
    //    self.search_edit.setClearButtonEnabled(True)
    //    self.search_edit.setFixedWidth(280)
    //
    //  三个要点：
    //   ① **位置在列表上方**、左对齐 —— 不是右上角
    //   ② 宽度**固定 280px**
    //   ③ placeholder **逐字照抄**（含拼音示例）
    // ══════════════════════════════════════════════════════════════════════
    const searchRow = P.el('div', { class: 'config-search-row' });
    const search = P.el('div', {
      class: 'search config-search',
      style: 'width:280px;flex:0 0 280px'
    });
    const searchIcon = P.el('span', { class: 'nav-icon' });
    const searchMask = App.icon('DOCUMENT');
    searchIcon.style.maskImage = searchMask;
    searchIcon.style.webkitMaskImage = searchMask;
    searchIcon.style.backgroundColor = 'currentColor';
    search.appendChild(searchIcon);

    const searchInput = P.el('input', {
      type: 'search',
      placeholder: '搜索角色名（支持拼音，如 feixue / fx）',
      onInput: function () {
        state.keyword = searchInput.value.trim();
        renderRows();
      }
    });
    search.appendChild(searchInput);

    //: 旧界面 ``setClearButtonEnabled(True)``
    const clearBtn = P.el('button', {
      class: 'search-clear',
      type: 'button',
      title: '清除',
      text: '×',
      onClick: function (ev) {
        ev.stopPropagation();
        searchInput.value = '';
        state.keyword = '';
        clearBtn.style.display = 'none';
        renderRows();
        searchInput.focus();
      }
    });
    clearBtn.style.display = 'none';
    search.appendChild(clearBtn);

    searchInput.addEventListener('input', function () {
      clearBtn.style.display = searchInput.value ? '' : 'none';
    });

    searchRow.appendChild(search);
    section.appendChild(searchRow);

    // ══════════════════════════════════════════════════════════════════════
    //  ★ 计数说明行（旧界面 L247-249 + ``_subtitle_text`` L347-362）
    //
    //  .. code:: python
    //
    //    if not keyword:
    //        return "共 " + " · ".join((
    //            _type_count(len(all_profiles), TYPE_ECHO_PROFILE),   # 角色声骸强化
    //            _type_count(len(all_battles), TYPE_BATTLE_PROFILE),  # 角色战斗配置
    //            _type_count(len(all_loadouts), TYPE_LOADOUT),        # 角色声骸筛选
    //        ))
    //    return f"搜索「{keyword}」：命中 {hit} / 共 {total} 条"
    //
    //  ⚠ 搜索时**必须带上总数** —— 否则用户看到"共 1 条"会以为配置被删了。
    // ══════════════════════════════════════════════════════════════════════
    const subtitle = P.el('div', { class: 'config-subtitle', id: 'config-subtitle' });
    section.appendChild(subtitle);

    // ── 列表（**按类型分组**，不是页签）──
    const listHost = P.el('div', { id: 'config-list' });
    section.appendChild(listHost);

    state.dom.listHost = listHost;
    state.dom.searchInput = searchInput;
    state.dom.noticeHost = noticeHost;
    state.dom.subtitle = subtitle;

    renderRows();
  }

  // ════════════════════════════════════════════════════════════════════════
  //  配置对话框（新增 / 编辑）
  //
  //  ## 旧界面的两步流程
  //
  //  ``config_interface.open_add_dialog`` → ``ConfigTypeDialog``（先选类型）
  //  → 对应编辑对话框：
  //
  //    角色声骸筛选  → ``loadout_dialog.LoadoutDialog``（631 行）
  //    角色声骸强化  → ``echo_profile_ui.EchoProfileDialog``（412 行）
  //    角色战斗配置  → ``battle_profile_dialog``
  //
  //  ## ★ 核心控件是 ``FilterComboBox``（``pickers.py`` L149）
  //
  //  旧界面文档写的行为，逐条照抄：
  //
  //  .. code:: text
  //
  //    - **点输入框本身就展开**（不用非得去够右边那个小箭头）
  //    - 菜单开着的时候**输入即过滤**，候选列表就地变
  //    - 匹配不到 → 没有候选
  //
  //  过滤规则和配置页搜索框**完全一样**（中文子串 + 拼音全拼/首字母），
  //  复用 ``matchesKeyword()``。
  //
  //  ## ⚠ 一个角色只能有一条配置（用户 2026-09-26 要求）
  //
  //  ``loadout_dialog.py`` L133-137：
  //
  //  .. code:: python
  //
  //    taken_chars = **已经被别的配置占用**的角色名（修改模式下不含自己）
  //    界面拿它把已占用的角色从下拉里剔掉，并在 validate 里再校一次
  //
  //  **为什么候选里剔掉还不够**：这个下拉是**可输入**的，
  //  用户能直接打字输入一个不在候选里的名字 → 所以保存时还要再校一次。
  // ════════════════════════════════════════════════════════════════════════

  //: loadout 对话框的缓存（套装列表 / 单套明细）
  const LOADOUT_STATE = {
    sets: null,
    detailCache: null
  };

  const DIALOG_STATE = {
    root: null,
    onClose: null,
    escHandler: null,
    charOptions: null,
    //: 按 ``kind|excludeId`` 缓存（同样的参数只拉一次）
    charOptionsCache: null,
    charOptionsFailed: false,
    taken: null,
    current: null,
    picker: null
  };

  // ══════════════════════════════════════════════════════════════════════
  //  通用 modal 骨架
  // ══════════════════════════════════════════════════════════════════════

  /**
   * 打开一个模态对话框。
   *
   * @param {object} opts
   *   - title   {string}  标题
   *   - body    {Element} 内容
   *   - actions {Array<{label, kind, onClick, disabled}>} 底部按钮
   *   - width   {number}  宽度（默认 520）
   *   - onClose {Function}
   * @returns {{close: Function, el: Element}}
   */
  function openDialog(opts) {
    opts = opts || {};
    closeDialog();

    const overlay = P.el('div', { class: 'dlg-overlay' });
    const box = P.el('div', {
      class: 'dlg-box',
      style: 'width:' + (opts.width || 520) + 'px'
    });

    //: 标题行：标题 + 右上角关闭
    const head = P.el('div', { class: 'dlg-head' });
    head.appendChild(P.el('div', { class: 'dlg-title', text: opts.title || '' }));
    head.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    const closeBtn = P.el('button', {
      class: 'dlg-close', type: 'button', text: '×', title: '关闭',
      onClick: function () { closeDialog(); }
    });
    head.appendChild(closeBtn);
    box.appendChild(head);

    //: 内容
    const body = P.el('div', { class: 'dlg-body' });
    if (opts.body) body.appendChild(opts.body);
    box.appendChild(body);

    //: 底部按钮
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
    //: Esc 关闭
    DIALOG_STATE.escHandler = function (ev) {
      if (ev.key === 'Escape') closeDialog();
    };
    document.addEventListener('keydown', DIALOG_STATE.escHandler);

    document.body.appendChild(overlay);
    DIALOG_STATE.root = overlay;
    DIALOG_STATE.onClose = opts.onClose || null;
    return { close: closeDialog, el: box, body: body };
  }

  function closeDialog() {
    if (DIALOG_STATE.escHandler) {
      document.removeEventListener('keydown', DIALOG_STATE.escHandler);
      DIALOG_STATE.escHandler = null;
    }
    if (DIALOG_STATE.root && DIALOG_STATE.root.parentNode) {
      DIALOG_STATE.root.parentNode.removeChild(DIALOG_STATE.root);
    }
    DIALOG_STATE.root = null;
    const cb = DIALOG_STATE.onClose;
    DIALOG_STATE.onClose = null;
    if (typeof cb === 'function') cb();
  }

  // ══════════════════════════════════════════════════════════════════════
  //  角色候选（旧界面 ``CHARACTERS``，61 个）
  // ══════════════════════════════════════════════════════════════════════

  /**
   * 拉候选列表（``getCharacterOptions()``）。
   *
   * ## 参数格式（web-shell-dev 2026-11-02）
   *
   * ``Bridge.call`` 只能传**一个字符串**，所以 kind 和 excludeId 拼在一起：
   *
   * .. code:: javascript
   *
   *   getCharacterOptions('loadout')                  // 新增
   *   getCharacterOptions('loadout|' + editingId)     // 修改（排除自己）
   *
   * ## ★ ``kind`` 决定 taken 从哪类配置算
   *
   * ``loadout``      → ``LoadoutStore.character``
   * ``echo_profile`` → ``EchoProfileStore.name``
   * ``""``           → 两类并集
   *
   * **两类配置各自独立** —— 一个角色可以同时有「声骸筛选」和「强化配置」
   * 各一条（用户 2026-09-26："两类配置是无关的"）。
   *
   * 所以弹框里**必须按 kind 传**，否则会把另一类占用的角色也误剔掉。
   *
   * ## ★ 修改模式要传 ``excludeId``
   *
   * 编辑时如果不排除自己，自己的角色会被判成「已占用」→ 用户改不了。
   *
   * @param {string} kind - ``loadout`` / ``echo_profile``
   * @param {string} [excludeId] - 编辑时这条配置的 id（echo_profile 传名字）
   * @returns {Promise<Array>}
   */
  async function loadCharacterOptions(kind, excludeId) {
    const key = String(kind || '') +
      (excludeId ? '|' + String(excludeId) : '');
    //: 同样的 kind|id 只拉一次
    DIALOG_STATE.charOptionsCache = DIALOG_STATE.charOptionsCache || {};
    if (DIALOG_STATE.charOptionsCache[key]) {
      DIALOG_STATE.charOptions = DIALOG_STATE.charOptionsCache[key];
      return DIALOG_STATE.charOptions;
    }

    const result = await P.call('getCharacterOptions', key);
    if (!result.ok) {
      DIALOG_STATE.charOptionsFailed = true;
      DIALOG_STATE.charOptions = [];
      return [];
    }
    const data = result.data || {};
    if (data.ok === false) {
      DIALOG_STATE.charOptionsFailed = true;
      DIALOG_STATE.charOptions = [];
      return [];
    }
    const items = Array.isArray(data.items) ? data.items : [];
    DIALOG_STATE.charOptions = items.map(function (item) {
      return {
        name: String(item.name || ''),
        avatarUrl: item.avatarUrl || '',
        element: item.element || '',
        rarity: item.rarity,
        weapon: item.weapon || '',
        pinyin: Array.isArray(item.pinyin) ? item.pinyin : null,
        initial: item.initial || null,
        avatarHue: item.avatarHue,
        //: ★ 后端已经算好「被占用」（按 kind）
        taken: !!item.taken
      };
    }).filter(function (item) { return item.name; });
    DIALOG_STATE.charOptionsCache[key] = DIALOG_STATE.charOptions;
    return DIALOG_STATE.charOptions;
  }

  /**
   * 已经被别的配置占用的角色名（旧界面 ``_taken_chars``）。
   *
   * .. code:: python
   *
   *   taken = {x.character for x in store.all()}       # 声骸筛选
   *   taken |= {x.name for x in profiles.all()}        # 声骸强化
   *
   * ⚠ **修改模式下要排除自己**（否则自己占着自己，下拉里反而没有自己）。
   */
  function takenCharacters(kind, selfId) {
    const taken = new Set();
    for (const item of state.items) {
      if (!item || !item.name) continue;
      //: 编辑自己时不算"被占用"
      if (selfId && String(item.id) === String(selfId)) continue;
      //: 旧界面里两类配置共用「角色唯一」这条规则
      taken.add(String(item.name));
    }
    void kind;
    return taken;
  }

  // ══════════════════════════════════════════════════════════════════════
  //  角色下拉（``FilterComboBox`` 的 HTML 版）
  // ══════════════════════════════════════════════════════════════════════

  /**
   * 建一个「可输入、边打字边过滤」的角色下拉。
   *
   * ## 行为（照抄 ``FilterComboBox`` 的文档）
   *
   * 1. **点输入框本身就展开**（不用去够右边箭头）
   * 2. 菜单开着时**输入即过滤**
   * 3. 匹配不到 → 显示「没有匹配的角色」
   * 4. 选中后**头像联动**
   *
   * @param {object} opts - {value, excluded, onChange}
   * @returns {{el, input, get, set, avatarEl, refresh}}
   */
  function characterPicker(opts) {
    opts = opts || {};
    let excluded = opts.excluded instanceof Set ? opts.excluded : new Set();
    let currentValue = String(opts.value || '');
    let open = false;
    let activeIndex = -1;

    const wrap = P.el('div', { class: 'char-picker' });
    const row = P.el('div', { class: 'char-picker-row' });

    const input = P.el('input', {
      class: 'input char-input',
      type: 'text',
      placeholder: '点击展开，可输入过滤（支持拼音）',
      autocomplete: 'off'
    });
    input.value = currentValue;
    row.appendChild(input);

    //: 右侧小箭头（点它也能展开 —— 旧界面那个 ComboBox 的样子）
    const arrow = P.el('button', {
      class: 'char-arrow', type: 'button', text: '▾', title: '展开候选',
      onClick: function (ev) {
        ev.stopPropagation();
        input.focus();
        setOpen(!open);
      }
    });
    row.appendChild(arrow);
    wrap.appendChild(row);

    //: 候选列表
    const menu = P.el('div', { class: 'char-menu' });
    menu.hidden = true;
    wrap.appendChild(menu);

    //: 头像（跟着选中角色联动）
    const avatarEl = P.el('div', { class: 'char-avatar' });
    wrap.appendChild(avatarEl);

    function options() {
      const all = DIALOG_STATE.charOptions || [];
      return all.filter(function (item) {
        return !excluded.has(item.name);
      });
    }

    function filtered() {
      const keyword = (input.value || '').trim();
      const pool = options();
      if (!keyword) return pool;
      return pool.filter(function (item) {
        //: 复用配置页搜索同一套规则（中文子串 + 拼音）
        return matchesKeyword(
          { name: item.name, summary: item.element, pinyin: item.pinyin },
          keyword
        );
      });
    }

    function renderMenu() {
      P.fill(menu, null);
      const pool = options();
      const list = filtered();

      if (!pool.length) {
        menu.appendChild(P.el('div', {
          class: 'char-menu-empty',
          text: DIALOG_STATE.charOptionsFailed
            ? '角色候选接口未就绪 —— 请直接输入角色名'
            : '没有可选角色（都已有配置了）'
        }));
        return;
      }
      if (!list.length) {
        menu.appendChild(P.el('div', {
          class: 'char-menu-empty',
          text: '没有匹配的角色'
        }));
        return;
      }
      //: 最多画 60 个（61 个角色不超过这个数）
      list.slice(0, 60).forEach(function (item, idx) {
        const opt = P.el('div', {
          class: 'char-option' + (idx === activeIndex ? ' is-active' : ''),
          text: item.name,
          dataset: { name: item.name },
          onMousedown: function (ev) {
            //: ⚠ 用 mousedown 而不是 click —— blur 会先触发、把菜单收掉
            ev.preventDefault();
            choose(item.name);
          }
        });
        if (item.element) {
          opt.appendChild(P.el('span', {
            class: 'char-option-meta', text: String(item.element)
          }));
        }
        menu.appendChild(opt);
      });
    }

    function setOpen(next) {
      open = !!next;
      menu.hidden = !open;
      wrap.classList.toggle('is-open', open);
      if (open) {
        activeIndex = -1;
        renderMenu();
      }
    }

    function choose(name) {
      currentValue = String(name);
      input.value = currentValue;
      setOpen(false);
      updateAvatar();
      if (typeof opts.onChange === 'function') opts.onChange(currentValue);
    }

    function updateAvatar() {
      P.fill(avatarEl, null);
      const name = currentValue;
      if (!name) {
        avatarEl.textContent = '?';
        avatarEl.classList.add('is-empty');
        return;
      }
      avatarEl.classList.remove('is-empty');
      const item = (DIALOG_STATE.charOptions || []).find(function (x) {
        return x.name === name;
      });

      function useInitial() {
        P.fill(avatarEl, null);
        const initial = item && item.initial;
        avatarEl.textContent = String(
          (initial && initial.initial) || name.slice(0, 1));
        const hue = Number(item && item.avatarHue);
        if (isFinite(hue)) {
          avatarEl.style.backgroundColor = 'hsl(' + hue + ', 42%, 30%)';
          avatarEl.style.color = 'rgba(255,255,255,0.92)';
        }
      }

      if (item && item.avatarUrl) {
        const img = P.el('img', { src: item.avatarUrl, alt: '', loading: 'lazy' });
        img.addEventListener('error', useInitial, { once: true });
        avatarEl.appendChild(img);
      } else {
        useInitial();
      }
    }

    // ── 事件 ──
    //: ★ **点输入框就展开**（旧界面 FilterComboBox 的第一条行为）
    input.addEventListener('mousedown', function () {
      if (!open) setOpen(true);
    });
    input.addEventListener('input', function () {
      currentValue = input.value;
      if (!open) setOpen(true);
      else renderMenu();
      updateAvatar();
      if (typeof opts.onChange === 'function') opts.onChange(currentValue);
    });
    input.addEventListener('blur', function () {
      //: 延迟收，否则 mousedown 选不中
      setTimeout(function () { setOpen(false); }, 120);
    });
    //: 键盘上下 / 回车
    input.addEventListener('keydown', function (ev) {
      const list = filtered();
      if (ev.key === 'ArrowDown') {
        ev.preventDefault();
        if (!open) { setOpen(true); return; }
        activeIndex = Math.min(activeIndex + 1, Math.min(list.length, 60) - 1);
        renderMenu();
      } else if (ev.key === 'ArrowUp') {
        ev.preventDefault();
        activeIndex = Math.max(activeIndex - 1, 0);
        renderMenu();
      } else if (ev.key === 'Enter') {
        if (open && activeIndex >= 0 && list[activeIndex]) {
          ev.preventDefault();
          choose(list[activeIndex].name);
        }
      } else if (ev.key === 'Escape') {
        setOpen(false);
      }
    });

    updateAvatar();

    return {
      el: wrap,
      input: input,
      avatarEl: avatarEl,
      get: function () { return String(currentValue || '').trim(); },
      set: function (name) { choose(String(name || '')); },
      setExcluded: function (set) {
        excluded = set instanceof Set ? set : new Set();
        refresh();
      },
      refresh: function () {
        updateAvatar();
        if (open) renderMenu();
      }
    };
  }

  // ════════════════════════════════════════════════════════════════════════
  //  「新增 / 编辑」对话框（P7）
  //
  //  旧界面是**两步**（``config_interface.open_add_dialog``）：
  //
  //  .. code:: text
  //
  //    点「+ 新增」
  //      ↓
  //    ConfigTypeDialog（``echo_profile_ui.py`` L80-108）—— 先选类型
  //      ↓
  //    EchoProfileDialog / LoadoutDialog / BattleProfileDialog —— 编辑表单
  //
  //  ## 本轮只做「角色声骸强化」（EchoProfile）
  //
  //  理由：它的设置区 = **「声骸自动强化」工具页那一份**（``EchoSettingsEditor``），
  //  而那一份我在 ④ 已经按旧界面复刻完了（6 张卡）—— **可以直接复用**。
  //
  //  「角色声骸筛选」（LoadoutDialog 631 行：套装 + 4C/3C/1C 逐档挑选）
  //  是独立一大块，下一轮做。
  // ════════════════════════════════════════════════════════════════════════

  //: 旧界面 ``config_names.CONFIG_TYPES``（下拉里的三个选项）
  const CONFIG_TYPES = ['角色声骸筛选', '角色声骸强化', '角色战斗配置'];
  const TYPE_LOADOUT = '角色声骸筛选';
  const TYPE_ECHO_PROFILE = '角色声骸强化';
  const TYPE_BATTLE_PROFILE = '角色战斗配置';

  // ══════════════════════════════════════════════════════════════════════
  //  第一步：配置类型选择（``ConfigTypeDialog`` L80-108）
  // ══════════════════════════════════════════════════════════════════════

  function openConfigTypeDialog(app) {
    const body = P.el('div', { class: 'dlg-form' });

    //: 说明（旧界面 L89-95，**逐字照抄**）
    //: 说明（旧界面 L89-95，**逐字照抄**）
    body.appendChild(P.el('div', {
      class: 'dlg-hint',
      text: '「' + TYPE_LOADOUT + '」= 角色 + 声骸套装 + 各档声骸；\n' +
        '「' + TYPE_ECHO_PROFILE + '」= 一套强化判定条件' +
        '（核心属性 / 双爆下限 / 有效词条数…）；\n' +
        '「' + TYPE_BATTLE_PROFILE + '」= 一个角色的技能快捷键 / 链路 / 战斗脚本。\n' +
        '三者互不影响：后两类只是存着，不改变各自工具自己的设置。'
    }));

    //: 类型下拉（旧界面 L100-102 ``ComboBox`` + ``CONFIG_TYPES``）
    const row = P.el('div', { class: 'dlg-row' });
    const picker = Panels.select(
      CONFIG_TYPES.map(function (t) { return { value: t, label: t }; }),
      TYPE_ECHO_PROFILE        //: 默认选「角色声骸强化」——本轮唯一可建的类型
    );
    picker.el.classList.add('dlg-select');
    row.appendChild(picker.el);
    body.appendChild(row);

    // ══════════════════════════════════════════════════════════════════════
    //  ★ 弹框内的提示位（不支持的类型的说明放这里）
    //
    //  ⚠⚠ 2026-11-02 修的一个静默失败：原来点「下一步」先 ``closeDialog()``，
    //  再把提示挂到 ``state.dom.noticeHost``（配置页顶部）。结果：
    //    · 弹框关了，页面没变化
    //    · 提示在**页面顶部**，用户刚点完「下一步」眼睛还在弹框位置 —— 根本没看见
    //    · 更糟的是 ``noticeHost`` 在页面重新渲染后会失效，
    //      ``if (!host) return`` 直接吞掉 → **什么都不显示**
    //
    //  **正确做法：不支持的路径不关弹框，就在框里说清楚。**
    //  （支持的路径才关 —— 因为要换成下一步的表单）
    // ══════════════════════════════════════════════════════════════════════
    const inlineNote = P.el('div', { class: 'dlg-error', id: 'dlg-type-note' });
    inlineNote.hidden = true;
    body.appendChild(inlineNote);

    openDialog({
      title: '新增配置',
      width: 460,
      body: body,
      actions: [
        { label: '取消', name: 'cancel', onClick: closeDialog },
        {
          label: '下一步',
          kind: 'primary',
          name: 'next',
          onClick: function () {
            const chosen = picker.get();

            if (chosen === TYPE_ECHO_PROFILE) {
              //: 支持的路径：关掉选类型框，开编辑表单
              closeDialog();
              //: ⚠ ``openEchoProfileDialog`` 是 async —— 抛异常会变成
              //: **未处理的 Promise rejection**，``window.onerror`` 抓不到，
              //: 表现就是「点了「下一步」什么都没发生」。所以必须自己兜住。
              openEchoProfileDialog(app, null).catch(function (err) {
                //: ★ 双通道：toast（用户可见）+ console.error（排查用）
                //: 2026-11-02 教训：只有 toast 时，若 toast 自身出问题就全哑了
                console.error('[config] openEchoProfileDialog failed:', err);
                showDialogFailure('打开表单失败', err);
              });
              return;
            }

            if (chosen === TYPE_LOADOUT) {
              closeDialog();
              openLoadoutDialog(app, null).catch(function (err) {
                showDialogFailure('打开表单失败', err);
              });
              return;
            }

            // ── 不支持的类型：**留在弹框里**说明原因 ──
            inlineNote.textContent = typeUnavailableMessage(chosen);
            inlineNote.hidden = false;
          }
        }
      ]
    });
  }

  /**
   * ★ 通用 toast —— **失败提示的兜底通道**。
   *
   * ## 为什么需要它（2026-11-02 踩到的静默失败）
   *
   * 原来所有提示都挂到 ``state.dom.noticeHost``（配置页顶部的一个容器），
   * 然后：
   *
   * .. code:: javascript
   *
   *   const host = state.dom.noticeHost;
   *   if (!host) return;        //: ★ 静默吞掉 —— 用户什么都没看到
   *
   * 而 ``noticeHost`` 在**页面重新渲染后就会失效**（旧 DOM 被替换掉了），
   * 所以「点了没反应」的真正原因就是这个 ``return``。
   *
   * ## 兜底顺序
   *
   * 1. ``state.dom.noticeHost``（在的话，效果最好 —— 页面内联）
   * 2. **``document.body``**（永远在，挂成固定定位的浮层）
   *
   * **绝不允许静默返回。**
   *
   * @param {string} html - 提示内容（会原样插入，调用方自己 ``P.esc``）
   * @param {string} [level] - ``warn`` / ``error`` / ``ok``
   * @param {number} [timeoutMs] - 自动消失时间（0 = 不消失）
   */
  function toast(html, level, timeoutMs) {
    const tag = 'toast-' + Date.now();
    let node = null;
    let floating = false;

    const host = state.dom && state.dom.noticeHost;
    if (host && host.isConnected) {
      node = P.notice(html, level || 'warn', tag);
      host.appendChild(node);
    } else {
      //: ★ 兜底：挂到 body，固定定位在右上角
      floating = true;
      node = P.el('div', {
        class: 'toast-float notice notice-' + (level || 'warn'),
        html: html
      });
      document.body.appendChild(node);
    }

    const ttl = timeoutMs == null ? 9000 : timeoutMs;
    if (ttl > 0) {
      setTimeout(function () {
        if (node && node.parentNode) node.parentNode.removeChild(node);
      }, ttl);
    }
    void floating;
    return node;
  }

  /** 还没做的两类 —— 说明文字（旧界面哪块没做、去旧界面怎么建）*/
  function typeUnavailableMessage(typeName) {
    if (typeName === TYPE_LOADOUT) {
      return '「' + TYPE_LOADOUT + '」的编辑表单下一轮做：' +
        '它要选声骸套装 + 4C/3C/1C 各档声骸' +
        '（旧界面 loadout_dialog.py 631 行），独立一大块。\n' +
        '现在要建这一类，请用旧界面：MYTOOLS_WEB_SHELL=0 python main.py';
    }
    if (typeName === TYPE_BATTLE_PROFILE) {
      return '「' + TYPE_BATTLE_PROFILE + '」的编辑表单下一轮做：' +
        '它要配技能快捷键 / 链路 / 战斗脚本。\n' +
        '现在要建这一类，请用旧界面：MYTOOLS_WEB_SHELL=0 python main.py';
    }
    return '「' + typeName + '」的表单还没做。';
  }

  // ══════════════════════════════════════════════════════════════════════
  //  第二步（另一种）：角色声骸筛选（``loadout_dialog.LoadoutDialog``）
  //
  //  ## 旧界面的结构（``loadout_dialog.py`` L141-166）
  //
  //  .. code:: python
  //
  //    self.widget.setFixedWidth(DIALOG_WIDTH)          # 880
  //    self.viewLayout.addWidget(TitleLabel("修改配置" / "新增配置"))
  //    self.viewLayout.addWidget(self._build_character_row())   # 角色 + 头像
  //    self.viewLayout.addWidget(self._build_echo_set_row())    # 声骸套装
  //    self.viewLayout.addWidget(self._build_filter_rows())     # 状态 + 品质
  //    self.viewLayout.addWidget(self._build_echo_area())       # 4C/3C/1C
  //
  //  ## ★ 必填规则（``core/loadout.py`` L177-210，**照抄**）
  //
  //  .. code:: python
  //
  //    """* 角色必填；
  //       * 声骸套装必填（声骸是挂在套装下的，没套装就无从谈起）。
  //       各档（1C / 3C / 4C）**一个都不选也是合法的** —— 用户可能只想先建一条
  //       "先筛选、后补声骸"的配置，或者这次只想限制其中一档。
  //       以前这里会报「4C 声骸为必填项」，正是截图里那条拦人的提示。
  //
  //       ⚠ 保留的检查：**已经选了**的声骸必须带上属性 —— 半截数据
  //       （选了声骸没选属性）会让筛选步骤生成不出来，属于真错误。"""
  //
  //  ⚠ **各档可以一个都不选** —— 这条最容易做错，别把必填加回去。
  //
  //  ## ★★ 写入侧的字段名是**下划线**，读出来是**驼峰**
  //
  //  2026-11-02 实测（读一条 → 原样写回 → 对比）：
  //
  //  .. code:: text
  //
  //    getConfigList().loadouts[]  →  echoSet     （驼峰）
  //    setConfig 的 data           →  echo_set    （下划线，Loadout.from_dict 认这个）
  //
  //  写错的话 ``setConfig`` 会返回 **``ok:true`` + warnings「请先选择声骸套装」**，
  //  然后 ``echoSet`` 被**静默清空** —— 数据丢失，而且前端还当成功。
  //
  //  所以 :func:`submitLoadout` 里显式做映射，见 ``_loadoutWire()``。
  // ══════════════════════════════════════════════════════════════════════

  //: 旧界面 ``loadout_dialog.py`` L74-75
  const LOADOUT_DIALOG_WIDTH = 880;
  const LOADOUT_ECHO_AREA_HEIGHT = 380;
  //: 套装下拉里那一项占位（选中它 = 还没选套装），L72
  const SET_PLACEHOLDER = '请选择';

  //: 旧界面 ``core/loadout.py`` 的常量
  const QUALITY_CHOICES = ['二星', '三星', '四星', '五星'];
  const DEFAULT_QUALITIES = ['五星'];
  const STATUS_CHOICES = ['已弃置', '已锁定', '未标记'];
  const DEFAULT_STATUS = '未标记';
  //: 旧界面 ``game_data.COST_SECTIONS``
  const COST_SECTIONS = [[4, '4C'], [3, '3C'], [1, '1C']];

  /**
   * 打开「角色声骸筛选」对话框。
   *
   * @param {object} app
   * @param {object|null} existing - 编辑时传原配置（含 character / echoSet / picks…）
   */
  async function openLoadoutDialog(app, existing) {
    const creating = !existing;
    const body = P.el('div', { class: 'dlg-form dlg-form-wide' });

    // ── 角色（候选：按 kind 传，编辑时排除自己）──
    await loadCharacterOptions('loadout', existing ? existing.id : '');
    const taken = new Set(
      (DIALOG_STATE.charOptions || [])
        .filter(function (x) { return x.taken; })
        .map(function (x) { return x.name; })
    );

    const charRow = P.el('div', { class: 'dlg-row' });
    charRow.appendChild(requiredLabel('角色'));
    const charPicker = characterPicker({
      value: existing ? existing.character : '',
      excluded: taken
    });
    charRow.appendChild(charPicker.el);
    charRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    body.appendChild(charRow);

    if (taken.size) {
      body.appendChild(P.el('div', {
        class: 'dlg-note',
        text: taken.size + ' 个角色已有配置，不在候选里（一个角色只能有一条）'
      }));
    }

    // ── 声骸套装（37 套，带图标 + 版本）──
    const sets = await loadEchoSetList();
    const setRow = P.el('div', { class: 'dlg-row' });
    setRow.appendChild(requiredLabel('声骸套装'));
    const setPicker = Panels.select(
      [SET_PLACEHOLDER].concat(sets.map(function (s) { return s.name; }))
        .map(function (n) { return { value: n, label: n }; }),
      existing && existing.echoSet ? existing.echoSet : SET_PLACEHOLDER
    );
    setPicker.el.classList.add('dlg-select', 'dlg-set-select');
    setRow.appendChild(setPicker.el);
    setRow.appendChild(P.el('span', {
      class: 'dlg-note',
      text: '共 ' + sets.length + ' 套'
    }));
    setRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    body.appendChild(setRow);

    // ── 状态（单选）+ 品质（多选）──
    //: 旧界面 ``_build_filter_rows`` L274-332
    const statusRow = P.el('div', { class: 'dlg-row' });
    statusRow.appendChild(plainLabel('状态'));
    const statusBoxes = {};
    for (const name of STATUS_CHOICES) {
      const lbl = P.el('label', { class: 'dlg-radio' });
      const radio = P.el('input', { type: 'radio', name: 'loadout-status' });
      radio.value = name;
      lbl.appendChild(radio);
      lbl.appendChild(P.el('span', { text: name }));
      statusRow.appendChild(lbl);
      statusBoxes[name] = radio;
    }
    statusRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    body.appendChild(statusRow);

    const qualityRow = P.el('div', { class: 'dlg-row' });
    qualityRow.appendChild(plainLabel('品质'));
    const qualityBoxes = {};
    for (const name of QUALITY_CHOICES) {
      const lbl = P.el('label', { class: 'dlg-check' });
      const cb = P.el('input', { type: 'checkbox' });
      lbl.appendChild(cb);
      lbl.appendChild(P.el('span', { text: name }));
      qualityRow.appendChild(lbl);
      qualityBoxes[name] = cb;
    }
    qualityRow.appendChild(P.el('span', {
      class: 'dlg-note', text: '默认只勾' + DEFAULT_QUALITIES[0]
    }));
    qualityRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    body.appendChild(qualityRow);

    // ── 声骸区（4C/3C/1C 逐档多选）──
    const echoHost = P.el('div', { class: 'echo-area' });
    body.appendChild(echoHost);

    // ── 错误提示位 ──
    const errorEl = P.el('div', { class: 'dlg-error' });
    errorEl.hidden = true;
    body.appendChild(errorEl);

    // ══════════════════════════════════════════════════════════════════
    //  声骸区的状态（等 ``getEchoSetDetail`` 接口）
    // ══════════════════════════════════════════════════════════════════
    const echoState = {
      setName: '',
      picks: {},          //: {4: [{echo, stats}], 3: [...], 1: [...]}
      detail: null,       //: 当前套装明细（接口到位后才有）
      available: false
    };

    /** 换套装 → 重建声骸区 */
    async function rebuildEchoArea(keepPicks) {
      const chosen = setPicker.get();
      P.fill(echoHost, null);
      echoState.setName = chosen === SET_PLACEHOLDER ? '' : chosen;
      echoState.picks = keepPicks && keepPicks === echoState.picks
        ? echoState.picks : {};

      if (!echoState.setName) {
        echoHost.appendChild(P.el('div', {
          class: 'echo-hint', text: '请先在上方选择声骸套装'
        }));
        return;
      }

      echoState.detail = await loadEchoSetDetail(echoState.setName);
      if (!echoState.detail) {
        //: ★ 接口没就绪 —— **如实告知**，不假装能选
        echoHost.appendChild(P.el('div', {
          class: 'echo-hint echo-hint-warn',
          text: '声骸明细接口（getEchoSetDetail）还没就绪 —— ' +
            '现在只能填角色 / 声骸套装 / 状态 / 品质，4C/3C/1C 选不了。\n' +
            '要填完整的声骸请用旧界面：MYTOOLS_WEB_SHELL=0 python main.py'
        }));
        echoState.available = false;
        return;
      }
      echoState.available = true;

      //: 1 件套只有 4C —— 别的档位不是"缺数据"，是本来就不存在（旧界面 L425-427）
      if (echoState.detail.isSinglePiece) {
        echoHost.appendChild(P.el('div', {
          class: 'echo-hint',
          text: '这套是 1 件套 —— 装一个声骸就生效，所以只有 4C，不需要 3C/1C。'
        }));
      }

      // ══════════════════════════════════════════════════════════════════
      //  ★ 摆哪几档：用 ``availableCosts``，**不是** ``requiredCosts``
      //
      //  web-shell-dev 2026-11-02 指出：有 2 套 ``isConfigurable: false``
      //  （茜染怀想之花 / 镜影流电之瞬）——
      //  ``requiredCosts=[4,3,1]`` 但 ``availableCosts=[4,3]``，**缺 1C 数据**。
      //
      //  **照 requiredCosts 摆空框会让用户卡在"必须选但没得选"。**
      // ══════════════════════════════════════════════════════════════════
      const required = Array.isArray(echoState.detail.requiredCosts)
        ? echoState.detail.requiredCosts : [4, 3, 1];
      const available = Array.isArray(echoState.detail.availableCosts)
        ? echoState.detail.availableCosts : required;
      const showCosts = echoState.detail.isConfigurable === false
        ? available : required;

      //: 数据不全时说清缺了哪一档
      if (echoState.detail.isConfigurable === false) {
        const missing = COST_SECTIONS.filter(function (pair) {
          return required.indexOf(pair[0]) >= 0 &&
            available.indexOf(pair[0]) < 0;
        }).map(function (pair) { return pair[1]; });
        if (missing.length) {
          echoHost.appendChild(P.el('div', {
            class: 'echo-hint echo-hint-warn',
            text: '「' + echoState.setName + '」的 ' + missing.join('、') +
              ' 档声骸明细还没收录 —— 只能先填已有的档。\n' +
              '要补数据：tools/refresh_wuwa_data.py --echoes'
          }));
        }
      }

      for (const pair of COST_SECTIONS) {
        const cost = pair[0];
        const label = pair[1];
        if (showCosts.indexOf(cost) < 0) continue;
        echoHost.appendChild(buildCostSection(cost, label,
          (echoState.detail.byCost || {})[String(cost)] || [],
          echoState.picks[String(cost)] || []));
      }
    }

    /** 一档（4C / 3C / 1C）—— 旧界面 ``CostSection`` L78-127 */
    function buildCostSection(cost, label, echoes, savedPicks) {
      const wrap = P.el('div', { class: 'echo-section' });
      wrap.appendChild(P.el('div', {
        class: 'echo-section-title',
        text: label + '（可多选）'
      }));

      if (!echoes.length) {
        //: 旧界面 L95-106 的原话
        wrap.appendChild(P.el('div', {
          class: 'echo-hint',
          text: '这套的 ' + label + ' 声骸明细还没收录，这一档暂时选不了 —— ' +
            '换一套，或跑 tools/refresh_wuwa_data.py --echoes 刷一下'
        }));
        return wrap;
      }

      const savedByName = {};
      for (const p of savedPicks) savedByName[p.echo] = p;

      for (const echo of echoes) {
        const saved = savedByName[echo.name];
        const row = P.el('div', {
          class: 'echo-row' + (saved ? ' is-selected' : '')
        });

        //: 勾选框（选中 = 这一条要刷）
        const checkLbl = P.el('label', { class: 'echo-check' });
        const cb = P.el('input', { type: 'checkbox' });
        cb.checked = !!saved;
        checkLbl.appendChild(cb);
        row.appendChild(checkLbl);

        //: 图标
        const icon = P.el('div', { class: 'echo-icon' });
        if (echo.iconUrl) {
          const img = P.el('img', { src: echo.iconUrl, alt: '', loading: 'lazy' });
          img.addEventListener('error', function () {
            P.fill(icon, null);
            icon.textContent = String(echo.name || '?').slice(0, 1);
          }, { once: true });
          icon.appendChild(img);
        } else {
          icon.textContent = String(echo.name || '?').slice(0, 1);
        }
        row.appendChild(icon);

        //: 名字
        row.appendChild(P.el('div', {
          class: 'echo-name', text: String(echo.name || '')
        }));

        //: ★ 主属性**多选**（2026-09-22 起的规则：一条声骸可以要多个主属性）
        const statsBox = P.el('div', { class: 'echo-stats' });
        const statBoxes = {};
        const stats = Array.isArray(echo.stats) ? echo.stats : [];
        for (const stat of stats) {
          const lbl = P.el('label', { class: 'echo-stat' });
          const scb = P.el('input', { type: 'checkbox' });
          const picked = saved && Array.isArray(saved.stats)
            ? saved.stats.indexOf(stat) >= 0 : false;
          scb.checked = picked;
          scb.disabled = !cb.checked;
          lbl.appendChild(scb);
          lbl.appendChild(P.el('span', { text: stat }));
          statsBox.appendChild(lbl);
          statBoxes[stat] = scb;
        }
        row.appendChild(statsBox);

        /** 把这一行的勾选状态写回 ``echoState.picks`` */
        function syncPick() {
          const key = String(cost);
          const list = (echoState.picks[key] || []).filter(function (p) {
            return p.echo !== echo.name;
          });
          if (cb.checked) {
            const chosen = stats.filter(function (s) {
              return statBoxes[s].checked;
            });
            list.push({ echo: echo.name, stats: chosen });
          }
          echoState.picks[key] = list;
          row.classList.toggle('is-selected', cb.checked);
          //: 取消勾选时属性框置灰（旧界面也是这样）
          for (const s of stats) statBoxes[s].disabled = !cb.checked;
        }

        cb.addEventListener('change', syncPick);
        for (const s of stats) {
          statBoxes[s].addEventListener('change', syncPick);
        }

        wrap.appendChild(row);
      }
      return wrap;
    }

    //: 换套装时重建（旧界面 L403-431 ``_rebuild_sections``）
    setPicker.el.addEventListener('change', function () {
      rebuildEchoArea(null);
    });

    // ── 回填（编辑模式）──
    if (existing) {
      //: 状态
      const st = STATUS_CHOICES.indexOf(existing.status) >= 0
        ? existing.status : DEFAULT_STATUS;
      if (statusBoxes[st]) statusBoxes[st].checked = true;
      //: 品质
      const qs = Array.isArray(existing.qualities) ? existing.qualities
        : DEFAULT_QUALITIES;
      for (const name of QUALITY_CHOICES) {
        if (qualityBoxes[name]) qualityBoxes[name].checked = qs.indexOf(name) >= 0;
      }
      //: 声骸（先塞进 picks，重建时用）
      const rawPicks = existing.picks || {};
      echoState.picks = {};
      for (const pair of COST_SECTIONS) {
        const key = String(pair[0]);
        if (Array.isArray(rawPicks[key])) {
          echoState.picks[key] = rawPicks[key].map(function (p) {
            return {
              echo: String(p.echo || ''),
              stats: Array.isArray(p.stats) ? p.stats.slice() : []
            };
          });
        }
      }
      const savedPicks = echoState.picks;
      await rebuildEchoArea(savedPicks);
      echoState.picks = savedPicks;
    } else {
      //: 新增：默认只勾五星 + 未标记
      if (statusBoxes[DEFAULT_STATUS]) statusBoxes[DEFAULT_STATUS].checked = true;
      for (const name of DEFAULT_QUALITIES) {
        if (qualityBoxes[name]) qualityBoxes[name].checked = true;
      }
      await rebuildEchoArea(null);
    }

    // ── 打开对话框 ──
    openDialog({
      title: creating ? '新增配置' : '修改配置',
      width: LOADOUT_DIALOG_WIDTH,
      body: body,
      actions: [
        { label: '取消', name: 'cancel', onClick: closeDialog },
        {
          label: '保存',
          kind: 'primary',
          name: 'save',
          onClick: async function () {
            const character = charPicker.get();
            const echoSet = setPicker.get() === SET_PLACEHOLDER
              ? '' : setPicker.get();
            let status = DEFAULT_STATUS;
            for (const name of STATUS_CHOICES) {
              if (statusBoxes[name] && statusBoxes[name].checked) status = name;
            }
            const qualities = QUALITY_CHOICES.filter(function (name) {
              return qualityBoxes[name] && qualityBoxes[name].checked;
            });

            // ══════════════════════════════════════════════════════════
            //  校验 —— **照抄 ``Loadout.validate()`` 的三条**
            //
            //  ⚠ **各档可以一个都不选**（用户 2026-09-28 明确要求）。
            //    别把「4C 声骸为必填项」加回来 —— 那是用户被困扰过的提示。
            // ══════════════════════════════════════════════════════════
            const errors = [];
            if (!character) {
              errors.push('角色为必填项');
            } else {
              //: 角色必须在表里、且没被占用（后端也会再校一次）
              const err = validateLoadoutCharacter(character, taken, existing);
              if (err) errors.push(err);
            }
            if (!echoSet) {
              errors.push('请先选择声骸套装');
            } else if (!sets.some(function (s) { return s.name === echoSet; })) {
              errors.push('声骸套装「' + echoSet + '」不在数据集里');
            } else {
              //: ★ 只校验**选了的**声骸有没有带属性（半截数据是真错误）
              for (const pair of COST_SECTIONS) {
                const key = String(pair[0]);
                const list = echoState.picks[key] || [];
                const missing = list.filter(function (p) {
                  return !Array.isArray(p.stats) || !p.stats.length;
                }).map(function (p) { return p.echo; });
                if (missing.length) {
                  errors.push(pair[1] + ' 声骸「' + missing.join('、') +
                    '」还没选属性');
                }
              }
            }

            if (errors.length) {
              showDialogError(errorEl, errors.join('；'));
              return;
            }
            hideDialogError(errorEl);

            await submitLoadout({
              character: character,
              echoSet: echoSet,
              status: status,
              qualities: qualities,
              picks: echoState.picks
            }, existing, app);
          }
        }
      ]
    });
    void app;
  }

  /** 必填标签（文字 + 红星）—— 旧界面 ``_required_label`` L169-185 */
  function requiredLabel(text) {
    const holder = P.el('span', { class: 'dlg-label dlg-label-required' });
    holder.appendChild(P.el('span', { text: text }));
    holder.appendChild(P.el('span', { class: 'dlg-star', text: '*' }));
    return holder;
  }

  function plainLabel(text) {
    return P.el('span', { class: 'dlg-label', text: text });
  }

  /** 角色校验（旧界面 ``character_choice_error`` 的前端版）*/
  function validateLoadoutCharacter(name, taken, existing) {
    const text = String(name || '').trim();
    if (!text) return '';
    const all = DIALOG_STATE.charOptions || [];
    if (all.length && !all.some(function (x) { return x.name === text; })) {
      return '「' + text + '」不是一个角色 —— 请从列表里选一个';
    }
    const isSelf = existing && String(existing.character) === text;
    if (!isSelf && taken && taken.has(text)) {
      return '「' + text + '」已经有一条配置了 —— 一个角色只能有一条';
    }
    return '';
  }

  /** 套装列表（``getLibraryData().echoSets``，37 套，已够用）*/
  async function loadEchoSetList() {
    if (LOADOUT_STATE.sets) return LOADOUT_STATE.sets;
    const result = await P.call('getLibraryData');
    if (!result.ok || !result.data) {
      LOADOUT_STATE.sets = [];
      return [];
    }
    const sets = Array.isArray(result.data.echoSets) ? result.data.echoSets : [];
    LOADOUT_STATE.sets = sets.map(function (s) {
      return { name: String(s.name || ''), iconUrl: s.iconUrl || '' };
    }).filter(function (s) { return s.name; });
    return LOADOUT_STATE.sets;
  }

  /**
   * 单套的声骸明细（``getEchoSetDetail``）—— **接口还没就绪**。
   *
   * 返回 ``null`` 时调用方要**如实提示**，不能假装能选。
   *
   * 期望结构（已报给 lead / web-shell-dev）：
   *
   * .. code:: jsonc
   *
   *   {"ok": true,
   *    "name": "茜染怀想之花",
   *    "isSinglePiece": false,
   *    "requiredCosts": [4, 3, 1],
   *    "byCost": {
   *      "4": [{"name":"千傀重楼","cost":4,"iconUrl":"…",
   *             "stats":["暴击","暴击伤害","治疗加成",…],
   *             "skill":"…","cooldown":"20s"}],
   *      "3": [...],
   *      "1": [...]
   *    }}
   */
  /**
   * 套装列表（``getEchoSetList()``）—— 打开对话框时调一次（约 5 KB）。
   *
   * 返回的每项：
   *
   * .. code:: jsonc
   *
   *   {"name":"茜染怀想之花", "isSinglePiece":false,
   *    "requiredCosts":[4,3,1], "availableCosts":[4,3],
   *    "isConfigurable":false, "iconUrl":"…", "version":"3.7"}
   *
   * ## ⚠ ``isConfigurable: false`` 的套（2 个：茜染怀想之花 / 镜影流电之瞬）
   *
   * ``requiredCosts=[4,3,1]`` 但 ``availableCosts=[4,3]`` —— **缺 1C 数据**。
   *
   * **别照 ``requiredCosts`` 摆空框**，用户会卡在"必须选但没得选"。
   * 要摆 ``availableCosts`` 并提示缺了哪一档。
   */
  async function loadEchoSetList() {
    if (LOADOUT_STATE.sets) return LOADOUT_STATE.sets;
    const result = await P.call('getEchoSetList');
    if (!result.ok) {
      LOADOUT_STATE.sets = [];
      return [];
    }
    const data = result.data || {};
    //: ⚠ Slot 不存在时返回 ``{ok:true, data:{}}``（不是失败），见 $5 静默失败
    if (data.ok === false || !Array.isArray(data.sets)) {
      LOADOUT_STATE.sets = [];
      return [];
    }
    LOADOUT_STATE.sets = data.sets.map(function (s) {
      return {
        name: String(s.name || ''),
        iconUrl: s.iconUrl || '',
        version: s.version || '',
        isSinglePiece: !!s.isSinglePiece,
        isConfigurable: s.isConfigurable !== false,
        requiredCosts: Array.isArray(s.requiredCosts) ? s.requiredCosts : [4, 3, 1],
        availableCosts: Array.isArray(s.availableCosts) ? s.availableCosts : null
      };
    }).filter(function (s) { return s.name; });
    return LOADOUT_STATE.sets;
  }

  /**
   * 单套的声骸明细（``getEchoSetDetail(name)``）—— 切套装时才调（约 2.2 KB/套）。
   *
   * 返回 ``data.set``：
   *
   * .. code:: jsonc
   *
   *   {"name":"茜染怀想之花", "isSinglePiece":false,
   *    "requiredCosts":[4,3,1], "availableCosts":[4,3], "isConfigurable":false,
   *    "effects": [[2,"治疗效果提升10%。"], [5,"…"]],
   *    "byCost": {
   *      "4": [{"name":"千傀重楼","cost":4,"iconUrl":"…",
   *             "stats":["暴击","暴击伤害","治疗加成","攻击百分比",…],
   *             "skill":"…","cooldown":"20s"}],
   *      "3": [...],
   *      "1": []                     ← 空数组（这套没有 1C）
   *    }}
   *
   * ⚠ ``byCost`` 的 key 是**字符串** ``"4"/"3"/"1"``（JSON 对象只能字符串 key）。
   * ⚠ ``stats`` 是**这个声骸**的可选主属性，不是全部属性池 ——
   *   千傀重楼 6 个、解形煞 10 个，**别用同一个池子校验**。
   *
   * @returns {object|null} ``data.set``；接口不可用/找不到 → ``null``
   */
  async function loadEchoSetDetail(setName) {
    LOADOUT_STATE.detailCache = LOADOUT_STATE.detailCache || {};
    if (LOADOUT_STATE.detailCache[setName]) {
      return LOADOUT_STATE.detailCache[setName];
    }
    const result = await P.call('getEchoSetDetail', String(setName));
    if (!result.ok) return null;
    const data = result.data || {};
    //: 找不到套装时后端给 ``{ok:false, reason:"not_found", available:[...]}``
    if (data.ok === false) return null;

    //: ⚠ **必须有这个检查**：Slot 不存在时 ``P.call`` 返回 ``{ok:true, data:{}}``
    //: （空对象，不是失败）。只判 ``data.ok !== false`` 会把它当成功，
    //: 然后渲染出「明细还没收录」，把用户引向"去刷数据"的错误方向。
    const detail = data.set;
    if (!detail || !detail.byCost || typeof detail.byCost !== 'object') {
      return null;
    }

    LOADOUT_STATE.detailCache[setName] = detail;
    return detail;
  }

  /**
   * 提交一条 loadout。
   *
   * ## 字段名：**直接用驼峰**（``echoSet``）
   *
   * 2026-11-02 的历史：
   *
   * * 当时 ``getConfigList`` 输出驼峰 ``echoSet``，而 ``Loadout.from_dict``
   *   只认下划线 ``echo_set`` → 原样写回会**静默清空套装**，
   *   而且返回 ``{"ok": true, "warnings": ["请先选择声骸套装"]}``。
   * * web-shell-dev 已在**桥接层**修好（``_normalize_loadout_payload``
   *   做驼峰→下划线别名映射），并保持 ``core`` 干净。
   *
   * 所以现在**前端不需要做任何字段名转换** —— 原样传驼峰即可。
   *
   * ⚠ 如果哪天又要在前端做映射，**先确认桥接层没做过**（会互相覆盖）。
   */
  function _loadoutWire(data) {
    return {
      character: String(data.character || ''),
      echoSet: String(data.echoSet || ''),
      status: String(data.status || DEFAULT_STATUS),
      qualities: Array.isArray(data.qualities) ? data.qualities.slice() : [],
      picks: data.picks || {}
    };
  }

  async function submitLoadout(data, existing, app) {
    const payload = { kind: 'loadout', data: _loadoutWire(data) };
    if (existing && existing.id) payload.id = existing.id;

    const result = await P.call('setConfig', JSON.stringify(payload));
    const current = DIALOG_STATE.current;
    const errEl = current ? current.body.querySelector('.dlg-error') : null;

    if (!result.ok) {
      if (errEl) showDialogError(errEl, '保存失败：接口 setConfig() 未就绪。');
      return;
    }
    const res = result.data || {};

    //: ★ 后端可能返回 ok:true + warnings —— **必须让用户看见**，否则就是静默数据丢失
    const warnings = Array.isArray(res.warnings) ? res.warnings : [];
    if (res.ok === false) {
      const reason = String(res.reason || '');
      const message = (reason === 'bad_character' || reason === 'bad_echo_set')
        ? String(res.message || '保存被拒绝')
        : (Array.isArray(res.errors)
            ? res.errors.join('；')
            : String(res.message || res.reason || '保存被拒绝'));
      if (errEl) showDialogError(errEl, message);

      //: ★ 高亮出问题的那一栏（旧界面也会把焦点挪过去）
      //:   ``bad_character`` → 角色下拉
      //:   ``bad_echo_set``  → 套装下拉
      if (reason === 'bad_character' || reason === 'bad_echo_set') {
        const sel = reason === 'bad_character'
          ? '.char-input' : '.dlg-set-select';
        const target = current ? current.body.querySelector(sel) : null;
        if (target) {
          target.classList.add('is-invalid');
          if (typeof target.focus === 'function') target.focus();
          setTimeout(function () { target.classList.remove('is-invalid'); }, 2200);
        }
      }
      return;
    }
    if (warnings.length) {
      if (errEl) {
        showDialogError(errEl, '保存了，但有问题：' + warnings.join('；'));
      }
      return;
    }

    closeDialog();
    await reload();
    void app;
  }

  // ══════════════════════════════════════════════════════════════════════
  //  第二步：角色声骸强化（``EchoProfileDialog`` L111-280）
  // ══════════════════════════════════════════════════════════════════════

  /**
   * @param {object} app
   * @param {object|null} existing - 编辑时传原配置（含 name / settings）
   */
  async function openEchoProfileDialog(app, existing) {
    const creating = !existing;
    const title = creating ? '新增配置' : '编辑配置';

    const body = P.el('div', { class: 'dlg-form' });

    //: hint（旧界面 L178-186，**逐字照抄**）
    body.appendChild(P.el('div', {
      class: 'dlg-hint',
      text: '设置区 = **「声骸自动强化」工具页那一份**；' +
        '**新增时的默认 = 它每次打开显示的那套（出厂默认）**。\n' +
        '改这里**不会**动到工具页，反之亦然（两者互不影响）。'
    }));

    // ── 角色行（旧界面 L188-211）──
    //: 先拉候选（按 kind + 排除自己）；接口没就绪时降级成手动输入
    //: ⚠ ``echo_profile`` 的主键**就是角色名**（没有独立 id），
    //:   所以 excludeId 传名字。
    await loadCharacterOptions('echo_profile', existing ? existing.name : '');

    //: ★ 后端已经按 kind 标好 ``taken``，直接用（不再本地重算）
    const taken = new Set(
      (DIALOG_STATE.charOptions || [])
        .filter(function (x) { return x.taken; })
        .map(function (x) { return x.name; })
    );
    DIALOG_STATE.taken = taken;

    const nameRow = P.el('div', { class: 'dlg-row' });
    nameRow.appendChild(P.el('span', {
      class: 'dlg-label', text: '角色'
    }));
    //: 必填星号（旧界面 label 是"角色"，星号在 hint 里体现）
    nameRow.appendChild(P.el('span', {
      class: 'dlg-required', text: '*'
    }));

    const picker = characterPicker({
      value: existing ? existing.name : '',
      excluded: taken,
      onChange: function () { /* 头像内部自己联动 */ }
    });
    nameRow.appendChild(picker.el);
    nameRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    body.appendChild(nameRow);

    //: 已占用说明（旧界面 L213-219）
    if (taken.size) {
      body.appendChild(P.el('div', {
        class: 'dlg-note',
        text: '（' + taken.size + ' 个角色已经有配置了，不在候选里 —— ' +
          '一个角色只能有一条）'
      }));
    }

    //: 老数据里可能存着不是角色的名字（旧界面 L221-230）
    if (existing && (DIALOG_STATE.charOptions || []).length) {
      const known = (DIALOG_STATE.charOptions || []).some(function (x) {
        return x.name === existing.name;
      });
      if (!known) {
        body.appendChild(P.el('div', {
          class: 'dlg-note dlg-note-warn',
          text: '这条配置的名字「' + existing.name + '」不是已知角色' +
            '（可能是改名前的数据）—— 请重新选一个角色再保存。'
        }));
      }
    }

    //: 错误提示位（旧界面 L261 ``errorLabel``）
    const errorEl = P.el('div', { class: 'dlg-error' });
    errorEl.hidden = true;
    body.appendChild(errorEl);

    // ── 设置区：**复用 ④ 那 6 张卡**（旧界面 ``EchoSettingsEditor``）──
    //
    //: 旧界面 L242：``self.viewLayout.addWidget(area)`` —— area 就是
    //: ``EchoSettingsEditor``。这正是「设置区和工具页那一份完全一样」的实现方式。
    //
    //: ⚠ 这里必须**新建一套控件**（不能复用工具页的 DOM —— 那会把工具页的
    //:   控件搬走）。所以把 ④ 的构建函数再调一次，产生独立的控件树。
    //
    //: ⚠ 但 ``ENHANCE_STATE`` 是全局单例，会互相覆盖。所以这里用一个
    //:   **局部状态**，构建完立刻把值取出来，不依赖 ENHANCE_STATE。
    const settingsArea = P.el('div', { class: 'dlg-settings' });
    const settings = existing && existing.settings ? existing.settings : null;
    const editor = buildDialogSettingsEditor(settings);
    settingsArea.appendChild(editor.el);
    body.appendChild(settingsArea);

    // ── 底部按钮（旧界面 L274-275：创建时「创建」、编辑时「保存」）──
    const dlg = openDialog({
      title: title,
      width: 720,
      body: body,
      actions: [
        { label: '取消', name: 'cancel', onClick: closeDialog },
        {
          label: creating ? '创建' : '保存',
          kind: 'primary',
          name: 'submit',
          onClick: async function () {
            const name = picker.get();
            const error = validateProfileName(name, taken, existing);
            if (error) {
              showDialogError(errorEl, error);
              return;
            }
            hideDialogError(errorEl);
            await submitEchoProfile(name, editor.read(), existing, app);
          }
        }
      ]
    });
    DIALOG_STATE.current = dlg;
    void app;
  }

  function showDialogError(el, message) {
    if (!el) return;
    el.textContent = String(message);
    el.hidden = false;
  }

  /**
   * 对话框流程抛异常时**如实报出来**。
   *
   * ⚠ async 函数里的异常不会进 ``window.onerror``（变成未处理的
   * Promise rejection），页面看起来只是"点了没反应"。
   * 这个函数把它变成用户能看见的错误 —— 至少能截图给我定位。
   */
  function showDialogFailure(what, err) {
    const detail = err && (err.message || err.stack)
      ? String(err.message || err.stack)
      : String(err || '未知错误');
    //: ★ 走 ``toast()`` 的兜底通道 —— 原来这里是
    //: ``const host = ...noticeHost; if (host) {...}``，
    //: host 失效就**什么都不显示**。对话框流程出错本来就已经"没反应"了，
    //: 再把错误吞掉 = 完全没法排查。
    toast(
      '<b>' + P.esc(what) + '</b>：' + P.esc(detail.slice(0, 300)) +
      '<br>请把这条发给开发者（或按 F12 看控制台）。',
      'error', 0
    );
  }

  function hideDialogError(el) {
    if (!el) return;
    el.textContent = '';
    el.hidden = true;
  }

  /**
   * 校验角色名 —— **旧界面 ``validate`` 的第二道防线**。
   *
   * .. code:: python
   *
   *   # loadout_dialog.py L133-137 / echo_profile_ui.py L285-295
   *   why = validate_profile_name(name, self._taken, MAX_NAME_LENGTH)
   *
   * 三种错误（顺序和旧界面一致）：
   *   ① 空 → 「请先选一个角色」
   *   ② 不在角色表里 → 「「X」不是已知角色」
   *   ③ 已被占用 → 「「X」已经有配置了（一个角色只能有一条）」
   *
   * ⚠ **为什么候选里剔掉还不够**：这个下拉是**可输入**的，
   *   用户能直接打字输入一个不在候选里的名字 → 必须在这里再校一次。
   */
  function validateProfileName(name, taken, existing) {
    const text = String(name || '').trim();
    if (!text) return '请先选一个角色。';
    const all = DIALOG_STATE.charOptions || [];
    if (all.length) {
      const known = all.some(function (x) { return x.name === text; });
      if (!known) {
        return '「' + text + '」不是已知角色 —— 请从候选里选一个。';
      }
    }
    //: 编辑自己时不算"被占用"
    const isSelf = existing && String(existing.name) === text;
    if (!isSelf && taken && taken.has(text)) {
      return '「' + text + '」已经有配置了（一个角色只能有一条）。';
    }
    if (text.length > 24) {
      return '名字太长了（最多 24 个字）。';
    }
    return '';
  }

  // ══════════════════════════════════════════════════════════════════════
  //  对话框里的设置编辑器 —— 复用 ④ 的 6 张卡，但**用局部状态**
  // ══════════════════════════════════════════════════════════════════════

  /**
   * 建一套独立的设置控件（不碰工具页的 DOM / ENHANCE_STATE）。
   *
   * 结构照抄旧界面 ``EchoSettingsEditor`` L79-84 的 6 张卡：
   *   ① 核心属性（CollapsibleCard）  ② 双爆下限（裸行）
   *   ③ 满值锁定（CardWidget）       ④ 自动停止（CardWidget）
   *   ⑤ 可选属性（CollapsibleCard）  ⑥ 有效词条（裸行）
   *
   * @param {object|null} saved - 已有的设置（编辑模式）
   * @returns {{el: Element, read: Function}}
   */
  function buildDialogSettingsEditor(saved) {
    const root = P.el('div', { class: 'enh-editor' });
    const local = {
      coreBoxes: {},
      optionalBoxes: {},
      critField: null,
      critDmgField: null,
      critSwitch: null,
      maxrollSwitch: null,
      autostopSwitch: null,
      validStepper: null,
      coreSummary: null
    };
    const s = saved || {};

    // ── ① 核心属性（CollapsibleCard，默认收起）──
    const coreColl = TP.collapsibleCard('核心属性', {
      hint: '必须有，缺任意一条就弃置。' + TP.ENHANCE_CRIT + '、' + TP.ENHANCE_CRIT_DMG +
        '强制勾选且不可取消 —— 上限 ' + TP.ENHANCE_MAX_CORE + ' 条里它们已占 2 条，' +
        '自选最多还能勾 ' + (TP.ENHANCE_MAX_CORE - 2) + ' 条' +
        '（勾满后其余自选框会置灰；已勾的随时可取消）。\n' +
        '出厂默认只有暴击、暴击伤害两条；**每次进入本页都是这套默认值**，' +
        '这里的勾选不会跨次保留（摘要若标「非默认」说明本次改过，' +
        '点标题栏的「恢复默认」可立刻还原）。',
      summary: '',
      expanded: false
    });
    local.coreSummary = coreColl;
    const coreGrid = P.el('div', { class: 'enh-core-grid' });
    const coreSaved = Array.isArray(s.core_stats) ? s.core_stats : null;
    for (const stat of TP.ENHANCE_ALL_STATS) {
      const forced = stat === TP.ENHANCE_CRIT || stat === TP.ENHANCE_CRIT_DMG;
      const lbl = P.el('label', { class: 'enh-check' });
      const cb = P.el('input', { type: 'checkbox' });
      //: 有保存值用它，没有就出厂默认（只有暴击/爆伤）
      cb.checked = forced || (coreSaved ? coreSaved.indexOf(stat) >= 0 : false);
      cb.disabled = forced;
      if (forced) cb.title = '必须保留，不可取消';
      cb.addEventListener('change', syncCore);
      lbl.appendChild(cb);
      lbl.appendChild(P.el('span', { text: stat }));
      if (forced) lbl.classList.add('is-forced');
      coreGrid.appendChild(lbl);
      local.coreBoxes[stat] = cb;
    }
    coreColl.contentEl.appendChild(coreGrid);
    root.appendChild(coreColl.card);

    function syncCore() {
      let checked = 0;
      for (const stat of TP.ENHANCE_ALL_STATS) {
        const cb = local.coreBoxes[stat];
        if (cb && cb.checked) checked += 1;
      }
      const custom = checked - 2;
      const limit = TP.ENHANCE_MAX_CORE - 2;
      for (const stat of TP.ENHANCE_ALL_STATS) {
        const cb = local.coreBoxes[stat];
        if (!cb) continue;
        if (stat === TP.ENHANCE_CRIT || stat === TP.ENHANCE_CRIT_DMG) continue;
        cb.disabled = (custom >= limit) && !cb.checked;
      }
      const names = TP.ENHANCE_ALL_STATS.filter(function (x) {
        const cb = local.coreBoxes[x];
        return cb && cb.checked;
      });
      local.coreSummary.setSummary(
        '已勾选 ' + checked + ' / ' + TP.ENHANCE_MAX_CORE + ' 条：' +
        (names.join('、') || '（无）'));
    }
    syncCore();

    // ── ② 双爆下限（裸行，旧界面 ``_build_crit_card``）──
    const critRow = P.el('div', { class: 'enh-crit-row' });
    critRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '暴击不低于' }));
    local.critField = Panels.numberInput(
      s.crit_min != null ? s.crit_min : TP.ENHANCE_DEFAULT_CRIT_MIN,
      { min: 0, max: 100 });
    local.critField.el.classList.add('cfg-number');
    local.critField.input.classList.add('cfg-number-input');
    critRow.appendChild(local.critField.el);
    critRow.appendChild(P.el('span', { style: 'width:22px;flex:0 0 auto' }));
    critRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '爆伤不低于' }));
    local.critDmgField = Panels.numberInput(
      s.crit_dmg_min != null ? s.crit_dmg_min : TP.ENHANCE_DEFAULT_CRIT_DMG_MIN,
      { min: 0, max: 300 });
    local.critDmgField.el.classList.add('cfg-number');
    local.critDmgField.input.classList.add('cfg-number-input');
    critRow.appendChild(local.critDmgField.el);
    critRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    const critOn = s.enable_crit_check !== false;
    const critSw = P.toggle('启用', critOn, function (on) {
      local.critField.input.disabled = !on;
      local.critDmgField.input.disabled = !on;
    }, { onText: '启用', offText: '不启用' });
    critRow.appendChild(critSw);
    local.critSwitch = critSw.querySelector('input[type="checkbox"]');
    local.critField.input.disabled = !critOn;
    local.critDmgField.input.disabled = !critOn;
    root.appendChild(critRow);

    // ── ③ 满值锁定（CardWidget + 开关 AlignTop）──
    const maxCard = P.el('div', { class: 'enh-switch-card card-glass' });
    const maxRow = P.el('div', { class: 'enh-switch-row' });
    const maxLeft = P.el('div', { class: 'enh-switch-left' });
    maxLeft.appendChild(P.el('div', {
      class: 'enh-switch-title',
      text: '满' + TP.ENHANCE_CRIT + ' / 满爆伤 自动锁定'
    }));
    maxLeft.appendChild(P.el('div', {
      class: 'enh-switch-hint',
      text: '出现满值词条（暴击 10.5 / 爆伤 21）时：不看别的条件，' +
        '一律强化到满级并上锁，不弃置。判定排在双爆下限与有效词条之前 —— ' +
        '出了满值就保住。'
    }));
    maxRow.appendChild(maxLeft);
    const maxSw = P.toggle('启用', s.enable_max_roll_lock !== false, function () {},
      { onText: '启用', offText: '不启用' });
    maxSw.classList.add('enh-switch-top');
    local.maxrollSwitch = maxSw.querySelector('input[type="checkbox"]');
    maxRow.appendChild(maxSw);
    maxCard.appendChild(maxRow);
    root.appendChild(maxCard);

    // ── ④ 自动停止（P8：用户要求简写 + 删说明，见 tool-panels.js 的注释）──
    const stopCard = P.el('div', { class: 'enh-switch-card card-glass' });
    const stopRow = P.el('div', { class: 'enh-switch-row' });
    const stopLeft = P.el('div', { class: 'enh-switch-left' });
    stopLeft.appendChild(P.el('div', {
      class: 'enh-switch-title',
      text: '自动停止'
    }));
    stopRow.appendChild(stopLeft);
    const stopSw = P.toggle('启用', s.enable_auto_stop !== false, function () {},
      { onText: '启用', offText: '不启用' });
    stopSw.classList.add('enh-switch-top');
    local.autostopSwitch = stopSw.querySelector('input[type="checkbox"]');
    stopRow.appendChild(stopSw);
    stopCard.appendChild(stopRow);
    root.appendChild(stopCard);

    // ── ⑤ 可选属性（CollapsibleCard）──
    const optColl = TP.collapsibleCard('可选属性', {
      hint: '核心属性之外，这些出现了也算有效词条。',
      summary: '',
      expanded: false
    });
    const optGrid = P.el('div', { class: 'enh-core-grid' });
    const optSaved = Array.isArray(s.optional_stats) ? s.optional_stats : [];
    for (const stat of TP.ENHANCE_ALL_STATS) {
      if (stat === TP.ENHANCE_CRIT || stat === TP.ENHANCE_CRIT_DMG) continue;
      const lbl = P.el('label', { class: 'enh-check' });
      const cb = P.el('input', { type: 'checkbox' });
      cb.checked = optSaved.indexOf(stat) >= 0;
      cb.addEventListener('change', syncOptional);
      lbl.appendChild(cb);
      lbl.appendChild(P.el('span', { text: stat }));
      optGrid.appendChild(lbl);
      local.optionalBoxes[stat] = cb;
    }
    optColl.contentEl.appendChild(optGrid);
    root.appendChild(optColl.card);

    function syncOptional() {
      const picked = TP.ENHANCE_ALL_STATS.filter(function (x) {
        const cb = local.optionalBoxes[x];
        return cb && cb.checked;
      });
      optColl.setSummary(picked.length
        ? '已选 ' + picked.length + ' 条：' + picked.join('、')
        : '未选');
    }
    syncOptional();

    // ── ⑥ 有效词条（裸行）──
    const validRow = P.el('div', { class: 'enh-crit-row' });
    validRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '有效词条' }));
    validRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '至少' }));
    local.validStepper = Panels.numberInput(
      s.min_valid_count != null ? s.min_valid_count : TP.ENHANCE_DEFAULT_VALID,
      { min: 2, max: 5 });
    local.validStepper.el.classList.add('cfg-number');
    local.validStepper.input.classList.add('cfg-number-input');
    validRow.appendChild(local.validStepper.el);
    validRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '条' }));
    validRow.appendChild(P.el('div', { style: 'flex:1 1 auto' }));
    root.appendChild(validRow);

    // ── 读值（和工具页 ``getToolSettings`` 的字段名一致）──
    function read() {
      const core = TP.ENHANCE_ALL_STATS.filter(function (x) {
        const cb = local.coreBoxes[x];
        return cb && cb.checked;
      });
      const optional = TP.ENHANCE_ALL_STATS.filter(function (x) {
        const cb = local.optionalBoxes[x];
        return cb && cb.checked;
      });
      return {
        core_stats: core,
        optional_stats: optional,
        crit_min: local.critField.get(),
        crit_dmg_min: local.critDmgField.get(),
        enable_crit_check: local.critSwitch ? local.critSwitch.checked : true,
        enable_max_roll_lock: local.maxrollSwitch
          ? local.maxrollSwitch.checked : true,
        enable_auto_stop: local.autostopSwitch
          ? local.autostopSwitch.checked : true,
        min_valid_count: local.validStepper.get()
      };
    }

    return { el: root, read: read };
  }

  // ══════════════════════════════════════════════════════════════════════
  //  保存
  // ══════════════════════════════════════════════════════════════════════

  async function submitEchoProfile(name, settings, existing, app) {
    const payload = {
      kind: 'echo_profile',
      name: name,
      settings: settings
    };
    if (existing && existing.id) payload.id = existing.id;

    const result = await P.call('setConfig', JSON.stringify(payload));
    const current = DIALOG_STATE.current;
    const errEl = current ? current.body.querySelector('.dlg-error') : null;

    if (!result.ok) {
      //: 不静默失败（P5 的教训）
      if (errEl) {
        showDialogError(errEl, '保存失败：接口 setConfig() 未就绪。');
      }
      return;
    }
    const data = result.data || {};

    // ══════════════════════════════════════════════════════════════════
    //  ★ 后端**也会拦**角色问题（第二道防线，用旧界面同一个函数
    //  ``game_data.character_choice_error``）。
    //
    //  ``reason == "bad_character"`` 时后端给的 ``message`` 就是旧界面原话：
    //    「「卡提希娅」已经有一条配置了 —— 一个角色只能有一条」
    //    「「绯雪声骸强化配置」不是一个角色 —— 请从列表里选一个」
    //    「请先选一个角色」
    //
    //  **直接弹给用户看**，不要自己再编一套文案。
    // ══════════════════════════════════════════════════════════════════
    if (data.ok === false) {
      const isBadChar = String(data.reason || '') === 'bad_character';
      const message = isBadChar
        ? String(data.message || '角色不可用')
        : (Array.isArray(data.errors)
            ? data.errors.join('；')
            : String(data.message || data.reason || '保存被拒绝'));
      if (errEl) {
        showDialogError(errEl, message);
        //: 高亮角色下拉（旧界面也会把焦点挪过去）
        const input = current ? current.body.querySelector('.char-input') : null;
        if (input) {
          input.classList.add('is-invalid');
          input.focus();
          setTimeout(function () {
            input.classList.remove('is-invalid');
          }, 2200);
        }
      }
      return;
    }

    closeDialog();
    await reload();
    void app;
  }

  /** 打开「编辑」—— 现在两种类型都能用了（P7）*/
  async function openEditDialog(item, app) {
    if (!item) return;
    if (item.kind === 'echo_profile') {
      await openEchoProfileDialog(app, item);
      return;
    }
    if (item.kind === 'loadout') {
      await openLoadoutDialog(app, item);
      return;
    }
    //: 角色战斗配置还没做
    toast(
      '<b>「' + P.esc(item.kindLabel || item.kind) + '」的编辑表单还没做</b>。' +
      '要改这一类，请用旧界面：<code>MYTOOLS_WEB_SHELL=0 python main.py</code>',
      'warn'
    );
  }


  // ────────────────────────────────────────────────────────────────────────
  //  搜索匹配（★ 规则照抄旧界面 ``src/gui/pickers.py`` 的 matches_keyword）
  // ────────────────────────────────────────────────────────────────────────

  /**
   * 这条配置是否命中关键词。
   *
   * ## 旧界面的规则（``pickers.py`` L64-93，逐条照抄）
   *
   * .. code:: python
   *
   *   keyword = keyword.strip()
   *   if not keyword: return True                # 空 = 全命中
   *   if keyword in text: return True            # ① 中文子串
   *   if not (keyword.isascii() and keyword.isalpha()):
   *       return False                           # 非纯字母 → 不试拼音
   *   lowered = keyword.lower()
   *   full, initial = keys                       # ("feixue", "fx")
   *   return lowered in full or lowered in initial   # ② 纯字母走拼音
   *
   * ## ⚠ 拼音数据必须由**后端**给
   *
   * 拼音要靠 ``pypinyin`` 算，JS 侧算不出来（除非内置一张全汉字音表 —— 不可能）。
   * 所以 ``getConfigList()`` 的每条里应该带 ``pinyin: ["feixue", "fx"]``。
   *
   * **后端没给时降级为只做中文子串匹配** —— 功能少一点，但不会骗用户
   * （搜索框 placeholder 里的「支持拼音」会由 :func:`searchSupportsPinyin`
   * 决定要不要显示「支持拼音」那半句）。
   *
   * @param {object} item - 归一化后的配置条目（含 name / summary / pinyin）
   * @param {string} keyword - 原始输入（内部会 strip）
   * @returns {boolean}
   */
  function matchesKeyword(item, keyword) {
    const kw = String(keyword == null ? '' : keyword).trim();
    //: ① 空关键词 = 全命中（含纯空白 —— 旧界面特意兜了这点）
    if (!kw) return true;

    //: ② 中文子串（先查角色名，再查摘要 —— 摘要里可能含套装名）
    const name = String(item.name || '');
    const summary = String(item.summary || '');
    if (name.indexOf(kw) >= 0 || summary.indexOf(kw) >= 0) return true;

    //: ③ 只有**纯字母**才试拼音（打中文时子串已经够，硬算只会白费）
    if (!/^[A-Za-z]+$/.test(kw)) return false;

    const keys = item.pinyin;
    if (!Array.isArray(keys) || keys.length < 2) return false;
    const lowered = kw.toLowerCase();
    const full = String(keys[0] || '').toLowerCase();
    const initial = String(keys[1] || '').toLowerCase();
    if (!full && !initial) return false;   //: 后端没算出拼音（如 pypinyin 没装）
    return full.indexOf(lowered) >= 0 || initial.indexOf(lowered) >= 0;
  }

  /** 后端有没有给拼音数据（决定 placeholder 里要不要写「支持拼音」）*/
  function searchSupportsPinyin() {
    return state.items.some(function (it) {
      return Array.isArray(it.pinyin) && it.pinyin.length >= 2 &&
        (it.pinyin[0] || it.pinyin[1]);
    });
  }

  // ────────────────────────────────────────────────────────────────────────
  //  数据
  // ────────────────────────────────────────────────────────────────────────
  async function load() {
    const result = await P.call('getConfigList');

    if (!result.ok) {
      state.available = false;
      state.items = [];
      return;
    }

    state.available = true;
    state.items = normalizeConfigs(result.data);
  }

  /**
   * 把接口返回归一化成统一条目。
   *
   * ## 实际返回（``web_bridge.getConfigList``）
   *
   * .. code:: json
   *
   *   {
   *     "loadouts": [{id, character, avatar, avatarUrl, echoSet, status,
   *                   qualities, updatedAt, picks: {"4":[...]}, errors}],
   *     "echoProfiles": [{id, name, created, updated_at, settings}]
   *   }
   *
   * 两组字段**完全不同**，所以摘要要各自拼：
   *
   * * loadout → 套装 + 三档声骸（对应 Qt 版 ``Loadout.summary()``）
   * * echoProfile → 核心属性 / 双爆 / 有效词条（对应 ``EchoProfile.describe()``）
   *
   * 之所以在页面里拼而不让后端给 ``summary``：后端已经把这些字段都给了，
   * 再拼一遍是重复劳动；而且页面能按屏幕宽度决定摘要多长。
   */
  function normalizeConfigs(data) {
    const out = [];
    if (!data || typeof data !== 'object') return out;

    // ── 声骸筛选配置（loadout）──
    for (const item of (Array.isArray(data.loadouts) ? data.loadouts : [])) {
      out.push({
        id: item.id || item.character || '',
        kind: 'loadout',
        kindLabel: kindLabelOf('loadout'),
        name: item.character || '(未命名)',
        avatar: item.avatarUrl || '',
        summary: summariseLoadout(item),
        updatedAt: item.updatedAt || '',
        errors: Array.isArray(item.errors) ? item.errors : [],
        //: ★ 拼音索引（后端 ``text_match.pinyin_keys`` 算的 [全拼, 首字母]）。
        //: 没有就留 undefined —— 搜索会降级成只做中文子串。
        pinyin: Array.isArray(item.pinyin) ? item.pinyin : undefined,
        //: ★ 首字兜底：完整对象（含 color/textColor，和旧界面逐位一致）
        initialRaw: (item.initial && typeof item.initial === 'object')
          ? item.initial : null,
        //: 只要色相（后端 ``crc32(name) % 360``，和旧界面一致）
        avatarHue: Number.isFinite(item.avatarHue) ? item.avatarHue : undefined,
        raw: item
      });
    }

    // ── 声骸强化配置（echoProfile）──
    for (const item of (Array.isArray(data.echoProfiles) ? data.echoProfiles : [])) {
      out.push({
        id: item.id || item.name || '',
        kind: 'echo_profile',
        kindLabel: kindLabelOf('echo_profile'),
        name: item.name || '(未命名)',
        avatar: item.avatarUrl || '',
        summary: summariseProfile(item),
        updatedAt: item.updatedAt || item.updated_at || item.created || '',
        errors: [],
        pinyin: Array.isArray(item.pinyin) ? item.pinyin : undefined,
        initialRaw: (item.initial && typeof item.initial === 'object')
          ? item.initial : null,
        avatarHue: Number.isFinite(item.avatarHue) ? item.avatarHue : undefined,
        raw: item
      });
    }

    // ── 其它形状（扁平数组 / 别的键）也尽量吃 ──
    if (!out.length && Array.isArray(data)) {
      for (const item of data) {
        if (!item || typeof item !== 'object') continue;
        const kind = item.kind || item.config_kind || '';
        out.push({
          id: item.id || item.key || item.name || '',
          kind: kind,
          kindLabel: kindLabelOf(kind),
          name: item.character || item.name || item.title || '(未命名)',
          avatar: item.avatarUrl || item.avatar || '',
          summary: item.summary || item.describe || '',
          updatedAt: item.updatedAt || item.updated_at || '',
          errors: Array.isArray(item.errors) ? item.errors : [],
          raw: item
        });
      }
    }

    //: 最近改的排最前（对齐 EchoProfileStore.all 的排序意图）
    out.sort(function (a, b) {
      return String(b.updatedAt || '').localeCompare(String(a.updatedAt || ''));
    });
    return out;
  }

  /** 对应 Qt 版 ``Loadout.summary()``：套装 · 4C x · 3C x · 1C x */
  function summariseLoadout(item) {
    const parts = [item.echoSet || '未选套装'];

    //: picks 的键是 "4" / "3" / "1"（字符串），固定按 4→3→1 显示
    const picks = item.picks || {};
    for (const cost of ['4', '3', '1']) {
      const list = Array.isArray(picks[cost]) ? picks[cost] : [];
      const text = list.length
        ? list.map(function (p) {
            const name = p.echo || '';
            const stats = Array.isArray(p.stats) && p.stats.length
              ? '（' + p.stats.join('、') + '）' : '';
            return name + stats;
          }).join('、')
        : '未选';
      parts.push(cost + 'C ' + text);
    }

    //: 状态 / 品质（筛选条件）
    const tags = [];
    if (item.status) tags.push(item.status);
    if (Array.isArray(item.qualities) && item.qualities.length) {
      tags.push(item.qualities.join('/'));
    }
    const head = parts.join(' · ');
    return tags.length ? head + '  [' + tags.join(' · ') + ']' : head;
  }

  /** 对应 Qt 版 ``EchoProfile.describe()`` */
  function summariseProfile(item) {
    const s = item.settings || {};
    const parts = [];

    const core = Array.isArray(s.core_stats) ? s.core_stats : [];
    parts.push('核心：' + (core.length ? core.join('、') : '（未设）'));

    const crit = s.crit_min != null ? s.crit_min : 7.5;
    const critDmg = s.crit_dmg_min != null ? s.crit_dmg_min : 15.0;
    parts.push('双爆 ≥' + crit + '/' + critDmg);

    if (s.min_valid_count != null) {
      parts.push('有效词条 ≥' + s.min_valid_count);
    }
    if (s.enable_max_roll_lock) parts.push('满值保护开');

    const optional = Array.isArray(s.optional_stats) ? s.optional_stats : [];
    if (optional.length) parts.push('可选：' + optional.join('、'));

    return parts.join(' · ');
  }

  function kindLabelOf(kind) {
    const hit = KINDS.find(function (k) { return k.kind === kind; });
    if (hit && hit.value !== 'all') return hit.label;
    return kind || '配置';
  }

  function countByKind() {
    const counts = { all: state.items.length };
    for (const kind of KINDS) {
      if (kind.value === 'all') continue;
      counts[kind.kind] = state.items.filter(function (it) {
        return it.kind === kind.kind;
      }).length;
    }
    return counts;
  }
  void countByKind;

  // ────────────────────────────────────────────────────────────────────────
  //  列表渲染
  // ────────────────────────────────────────────────────────────────────────
  /**
   * 渲染列表 —— **照抄旧界面** ``config_interface.reload()`` L287-345。
   *
   * ## 旧界面的结构：按**类型分组**（不是页签切换）
   *
   * .. code:: python
   *
   *   # ---- 角色声骸强化（判定条件，和强化工具自己的设置互不影响）----
   *   if profiles:
   *       self.list_layout.addWidget(self._section(TYPE_ECHO_PROFILE))
   *       for profile in profiles: ... EchoProfileRow ...
   *
   *   # ---- 角色战斗配置（★ 2026-09-30 新增）----
   *   if battles:
   *       self.list_layout.addWidget(self._section(TYPE_BATTLE_PROFILE))
   *       for battle in battles: ... BattleProfileRow ...
   *
   *   # ---- 角色声骸筛选配置 ----
   *   if loadouts:
   *       self.list_layout.addWidget(self._section(TYPE_LOADOUT))
   *       for loadout in loadouts: ... LoadoutRow ...
   *
   * ⚠ **顺序是「声骸强化 → 战斗配置 → 声骸筛选」**，不是按数量或字母。
   * P4 我做成了页签（全部/筛选/强化/战斗），和旧界面对不上。
   *
   * ## 空组不画标题
   *
   * 旧界面每个 `if xxx:` 才画 `_section(...)` —— 0 条的类型**整个跳过**，
   * 不显示空分组标题。
   */
  function renderRows() {
    const host = state.dom.listHost;
    if (!host) return;
    P.fill(host, null);

    if (!state.available) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty(
          '配置列表待接入',
          '接口就绪后，这里会列出全部配置：左边头像 + 名字 + 类型，' +
          '中间摘要，右边 编辑 / 查看 / 删除。',
          'SETTING'
        )
      }));
      return;
    }

    const keyword = state.keyword;

    //: 过滤（规则照抄 ``pickers.matches_keyword``）
    const hit = state.items.filter(function (it) {
      return matchesKeyword(it, keyword);
    });

    //: 分组（★ 顺序照抄旧界面：强化 → 战斗 → 筛选）
    const groups = [
      { kind: 'echo_profile', title: '角色声骸强化' },
      { kind: 'battle_profile', title: '角色战斗配置' },
      { kind: 'loadout', title: '角色声骸筛选' }
    ];

    // ── 计数说明行（旧界面 ``_subtitle_text``）──
    updateSubtitle(hit, keyword);

    // ══════════════════════════════════════════════════════════════════════
    //  ★ 类型页签（P8，用户 2026-11-02：「这里改成声骸筛选和切换」）
    //
    //  用户第 6 张截图圈的是**资源库页的页签**，写「像这样」——
    //  .. code:: text
    //
    //    [角色(61)] [声骸套装(37)] [声骸图鉴(187)] [武器(123)]
    //
    //  所以配置页照这个样式做：
    //
    //  .. code:: text
    //
    //    [全部(13)] [角色声骸强化(5)] [角色声骸筛选(8)] [角色战斗配置(0)]
    //
    //  ## 选 A：「全部」页签**保留分组标题**
    //
    //  lead 定的：
    //    * 「全部」页签下 13 条混在一起，不分组很难扫（旧界面就是分组的）
    //    * 其他页签只有一类，分组标题是冗余的
    //
    //  ⚠ 页签上的数字是**全量**（不受搜索影响）—— 搜索时数字不变，
    //    这样用户能看到"总共就这么多"。
    // ══════════════════════════════════════════════════════════════════════
    const TABS = [
      { value: 'all', label: '全部', kind: '' },
      { value: 'echo_profile', label: '角色声骸强化', kind: 'echo_profile' },
      { value: 'loadout', label: '角色声骸筛选', kind: 'loadout' },
      { value: 'battle_profile', label: '角色战斗配置', kind: 'battle_profile' }
    ];
    const counts = {
      all: state.items.length,
      echo_profile: 0,
      loadout: 0,
      battle_profile: 0
    };
    for (const it of state.items) {
      if (counts[it.kind] != null) counts[it.kind] += 1;
    }
    const tabBar = P.el('div', { class: 'segmented config-tabs' });
    for (const tab of TABS) {
      const isActive = tab.value === state.kind;
      tabBar.appendChild(P.el('button', {
        class: 'seg' + (isActive ? ' is-active' : ''),
        type: 'button',
        text: tab.label + '(' + (counts[tab.value] || 0) + ')',
        dataset: { value: tab.value },
        onClick: function () {
          if (state.kind === tab.value) return;
          state.kind = tab.value;
          renderRows();
        }
      }));
    }
    host.appendChild(tabBar);

    //: ★ 当前页签筛出的行（``all`` = 不筛）
    const shown = state.kind === 'all'
      ? hit
      : hit.filter(function (it) { return it.kind === state.kind; });

    if (!shown.length) {
      //: 旧界面 ``_empty_hint`` L364-376
      const text = keyword
        ? '没有匹配「' + keyword + '」的配置。换个词试试（支持拼音）。'
        : (state.kind === 'all'
            ? '还没有配置，点上面的「新增」建一条。'
            : '这一类还没有配置，点上面的「新增」建一条。');
      host.appendChild(P.el('div', {
        class: 'config-empty-hint',
        text: text
      }));
      return;
    }

    //: ★ 「全部」页签按类型分组；其他页签平铺（分组标题是冗余的）
    if (state.kind === 'all') {
      for (const group of groups) {
        const rows = shown.filter(function (it) { return it.kind === group.kind; });
        //: 空组**不画标题**（旧界面每个 if 才 section）
        if (!rows.length) continue;

        host.appendChild(P.el('div', {
          class: 'config-section',
          text: group.title
        }));

        const list = P.el('div', { class: 'list' });
        for (const row of rows) {
          list.appendChild(buildRow(row));
        }
        host.appendChild(list);
      }

      //: 未知类型（后端以后加了新 kind）—— 也要显示，不能默默吞掉
      const known = {};
      for (const g of groups) known[g.kind] = true;
      const others = shown.filter(function (it) { return !known[it.kind]; });
      if (others.length) {
        host.appendChild(P.el('div', {
          class: 'config-section',
          text: '其它配置'
        }));
        const list = P.el('div', { class: 'list' });
        for (const row of others) list.appendChild(buildRow(row));
        host.appendChild(list);
      }
      return;
    }

    //: 单类页签 —— 平铺
    const list = P.el('div', { class: 'list' });
    for (const row of shown) list.appendChild(buildRow(row));
    host.appendChild(list);
  }

  /**
   * 计数说明行 —— 照抄旧界面 ``_subtitle_text`` L347-362。
   *
   * .. code:: python
   *
   *   if not keyword:
   *       return "共 " + " · ".join((
   *           _type_count(len(all_profiles), TYPE_ECHO_PROFILE),
   *           _type_count(len(all_battles), TYPE_BATTLE_PROFILE),
   *           _type_count(len(all_loadouts), TYPE_LOADOUT),
   *       ))
   *   hit = len(profiles) + len(loadouts) + len(battles)
   *   total = len(all_profiles) + len(all_loadouts) + len(all_battles)
   *   return f"搜索「{keyword}」：命中 {hit} / 共 {total} 条"
   *
   * ⚠ 搜索时**必须带上总数** —— 否则用户看到「共 1 条」会以为配置被删了。
   */
  function updateSubtitle(hit, keyword) {
    const el = state.dom.subtitle;
    if (!el) return;

    function countOf(kind) {
      return state.items.filter(function (it) { return it.kind === kind; }).length;
    }
    //: ``_type_count(count, type_name)`` → "N 条<类型名>配置"
    function typeCount(n, name) {
      const suffix = name.endsWith('配置') ? '' : '配置';
      return n + ' 条' + name + suffix;
    }

    if (!keyword) {
      el.textContent = '共 ' + [
        typeCount(countOf('echo_profile'), '角色声骸强化'),
        typeCount(countOf('battle_profile'), '角色战斗配置'),
        typeCount(countOf('loadout'), '角色声骸筛选')
      ].join(' · ');
    } else {
      el.textContent = '搜索「' + keyword + '」：命中 ' + hit.length +
        ' / 共 ' + state.items.length + ' 条';
    }
  }

  /**
   * 画角色头像（★ 照抄旧界面 ``pickers.avatar_icon`` 的两级兜底）。
   *
   * ## 旧界面的行为（``src/gui/pickers.py`` L113）
   *
   * .. code:: python
   *
   *   def avatar_icon(relative, name=""):
   *       """角色头像：**文件不在就用名字首字现画一个**
   *          （用户 2026-09-28："如果角色头像没拿到，先用第一个字填充"）。"""
   *       icon = load_icon(relative)
   *       if not icon.isNull():
   *           return icon
   *       return _initial_icon(name)      # 圆底 + 首字，色相 = crc32(name) % 360
   *
   * 所以是**两级**：
   *   ① ``assets/game/avatars/<角色名>.png`` 存在 → 用图
   *   ② 不存在 → 画「散列色相圆底 + 白色首字」，
   *      而且**同名角色两次渲染颜色一致**（crc32 保证确定性）
   *
   * ## 后端给的字段（``getConfigList`` 的两组都有）
   *
   * .. code:: jsonc
   *
   *   "avatarUrl": "http://…/game/avatars/%E7%BB%AF%E9%9B%AA.png",  // 空 = 文件不在
   *   "avatarHue": 63,
   *   "initial": {"name":"绯雪","initial":"绯","hue":63,
   *               "color":"#C4C881","textColor":"rgba(255,255,255,0.96)"}
   *
   * ⚠ ``avatarUrl`` **只在文件真在时才有值**（web-shell-dev 特意改了这点，
   * 否则页面会拿到 404 的 URL，``<img>`` 加载失败后什么都不显示 = 灰圈）。
   * 所以这里的规则可以很干脆：**有 URL 就用图，没有就画首字**。
   *
   * @param {object} item - 归一化后的配置条目
   * @returns {HTMLElement}
   */
  function buildAvatar(item) {
    const avatar = P.el('div', { class: 'config-avatar' });

    // ── ① 有真实头像 → 用图 ──
    if (item.avatar) {
      const img = P.el('img', { src: item.avatar, alt: '' });
      img.addEventListener('error', function () {
        //: 图加载失败（文件被删 / 服务没起）→ **退回首字**，不留灰圈
        P.fill(avatar, null);
        applyInitial(avatar, item);
      }, { once: true });
      avatar.appendChild(img);
      return avatar;
    }

    // ── ② 没头像 → 画「圆底 + 首字」──
    applyInitial(avatar, item);
    return avatar;
  }

  /** 把「圆底 + 首字」铺到一个容器上（备用也是兜底）*/
  function applyInitial(host, item) {
    const ini = item.initialRaw || null;

    //: 后端给了完整的 initial 对象 → 直接用它的颜色（和旧界面逐位一致）
    if (ini && ini.initial) {
      host.textContent = String(ini.initial);
      host.style.backgroundColor = String(ini.color || 'transparent');
      host.style.color = String(ini.textColor || 'rgba(255,255,255,0.96)');
      host.classList.add('has-initial-color');
      return;
    }

    //: 只给了 hue → 自己算 HSL（后端 ``_hsv_to_hex`` 是 HSV，这里用同 hue 的 HSL，
    //: 视觉接近；真正精确的走上面那条分支）
    const name = String(item.name || '');
    host.textContent = name ? name.slice(0, 1) : '?';
    if (Number.isFinite(item.avatarHue)) {
      host.style.backgroundColor = 'hsl(' + item.avatarHue + ' 55% 45%)';
    } else {
      host.style.backgroundColor = 'rgba(255,255,255,0.10)';
    }
    host.style.color = 'rgba(255,255,255,0.96)';
    host.classList.add('has-initial-color');
  }

  function buildRow(item) {
    const row = P.el('div', {
      class: 'card config-row',
      dataset: { configId: item.id, kind: item.kind }
    });

    // ── 身份列：**头像在上、名字在下**（竖排）──
    //
    //: ★ 照抄旧界面 ``LoadoutRow._build_identity()`` /
    //: ``EchoProfileRow``：左列是 ``QVBoxLayout``，头像 48x48 居中，
    //: 名字在**下面**（QSS 里名字带类型后缀，如「绯雪-声骸强化」）。
    //: 左列宽度 ``ROW_LEFT_WIDTH = 160``（旧界面 L41，因为名字最长 154px）。
    const identity = P.el('div', { class: 'config-identity' });
    identity.appendChild(buildAvatar(item));
    identity.appendChild(P.el('div', {
      class: 'config-name',
      text: item.name || '(未命名)'
    }));
    //: 类型后缀（旧界面 ``config_display_name``：名字 + "-" + 类型）
    identity.appendChild(P.el('div', {
      class: 'config-kind',
      text: item.kindLabel
    }));
    row.appendChild(identity);

    // ── 摘要 ──
    const summary = P.el('div', { class: 'config-summary' });
    if (item.summary) {
      summary.textContent = item.summary;
      //: 摘要被 CSS 截到 3 行 —— 全文放 hover 提示和「查看」里，别丢信息
      summary.title = item.summary;
    } else {
      summary.textContent = '（没有摘要）';
      summary.style.color = 'var(--faint)';
    }
    row.appendChild(summary);

    // ── 操作 ──
    //
    //: ★ 按钮顺序**照抄旧界面**：``编辑 / 查看 / 删除``
    //:
    //: 三个 Row 类的信号连接顺序（config_interface.py L317-320 / 327-331）：
    //:   ``row.editRequested`` → ``row.viewRequested`` → ``row.deleteRequested``
    //: 而 ``EchoProfileRow`` / ``LoadoutRow`` 的构造函数里就是按这个顺序
    //: 加按钮的（``for text, signal in (("编辑", edit), ("查看", view), ("删除", delete))``）。
    const actions = P.el('div', { class: 'config-actions' });

    //: ① 编辑（旧界面在第一个）—— P7 起真的能编辑了
    actions.appendChild(P.button('编辑', {
      size: 'sm',
      title: '编辑这条配置',
      onClick: function () { openEditDialog(item, null); }
    }));

    //: ② 查看
    actions.appendChild(P.button('查看', {
      size: 'sm',
      onClick: function () { showDetail(item); }
    }));

    //: ③ 删除
    const delBtn = P.button('删除', {
      size: 'sm',
      title: '删除这条配置（需要点两次确认）',
      onClick: function () { deleteConfig(item, row); }
    });
    delBtn.dataset.action = 'delete';
    actions.appendChild(delBtn);
    row.appendChild(actions);

    return row;
  }

  /**
   * 「查看」→ 详情面板。
   *
   * 只读展示原始字段，不做编辑 —— 编辑要等 ``setConfig()`` 接口。
   */
  function showDetail(item) {
    const existing = document.getElementById('config-detail-host');
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

    const host = P.el('div', { id: 'config-detail-host' });
    const body = P.el('div');

    //: 摘要区
    if (item.summary) {
      body.appendChild(P.el('div', { class: 'detail-section' }, [
        P.el('div', { class: 'detail-title', text: '摘要' }),
        P.el('div', { class: 'detail-val', text: item.summary })
      ]));
    }

    //: 原始字段（只挑有值的，跳过嵌套太深的）
    const raw = item.raw || {};
    const grid = P.el('div', { class: 'detail-grid' });
    let rows = 0;
    for (const [key, value] of Object.entries(raw)) {
      if (value == null || value === '' || key === 'summary') continue;
      if (typeof value === 'object' && !Array.isArray(value)) {
        //: picks 这类嵌套 dict —— 逐档展开
        for (const [subKey, subValue] of Object.entries(value)) {
          const text = Array.isArray(subValue)
            ? subValue.map(function (x) {
                return typeof x === 'object'
                  ? (x.echo || '') + (Array.isArray(x.stats) && x.stats.length
                    ? '（' + x.stats.join('、') + '）' : '')
                  : String(x);
              }).join('、')
            : String(subValue);
          if (!text) continue;
          grid.appendChild(P.el('div', { class: 'detail-key', text: subKey + 'C' }));
          grid.appendChild(P.el('div', { class: 'detail-val', text: text }));
          rows += 1;
        }
        continue;
      }
      const text = Array.isArray(value) ? value.join('、') : String(value);
      grid.appendChild(P.el('div', { class: 'detail-key', text: key }));
      grid.appendChild(P.el('div', { class: 'detail-val', text: text }));
      rows += 1;
    }

    if (rows) {
      body.appendChild(P.el('div', { class: 'detail-section' }, [
        P.el('div', { class: 'detail-title', text: '字段' }),
        grid
      ]));
    } else {
      body.appendChild(P.el('div', {
        class: 'detail-val',
        text: '这条配置没有更多可展开的字段。'
      }));
    }

    host.appendChild(P.panel({
      title: item.name || '(未命名)',
      subtitle: item.kindLabel + (item.updatedAt
        ? ' · 更新于 ' + P.timeAgo(item.updatedAt) : ''),
      padding: '18px 20px',
      actions: [
        P.button('关闭', {
          size: 'sm',
          onClick: function () {
            if (host.parentNode) host.parentNode.removeChild(host);
          }
        })
      ],
      body: body
    }));

    //: 插在列表后面
    const listHost = state.dom.listHost;
    if (listHost && listHost.parentNode) {
      listHost.parentNode.insertBefore(host, listHost.nextSibling);
    }
  }

  // ────────────────────────────────────────────────────────────────────────
  //  删除（真接口，2026-11-02 接）
  // ────────────────────────────────────────────────────────────────────────
  /**
   * 删除一条配置。
   *
   * ## 为什么要二次确认
   *
   * 这是**不可撤销的破坏性操作**，而且没有回收站 ——
   * 一次误点就少一条用户辛苦配的声骸方案。
   * Qt 版用的是 ``MessageBox``，这里用等价的「点两次」：第一次把按钮
   * 变成「确认删除？」，3 秒内再点才真的删。
   *
   * ## 为什么不用 window.confirm()
   *
   * QtWebEngine 里 ``window.confirm`` 需要宿主程序实现
   * ``QWebEnginePage.javaScriptConfirm``，没实现时**默认返回 false**
   * —— 点了确认也删不掉，而且看起来像"点了没反应"。
   */
  async function deleteConfig(item, row) {
    const btn = row.querySelector('[data-action="delete"]');
    if (!btn) return;

    // ── 第一次点：进入确认态 ──
    if (btn.dataset.confirming !== '1') {
      btn.dataset.confirming = '1';
      btn.textContent = '确认删除？';
      btn.classList.add('is-confirming');
      if (btn._confirmTimer) clearTimeout(btn._confirmTimer);
      //: 3 秒内没再点 → 退回原状（防误触后按钮一直停在确认态）
      btn._confirmTimer = setTimeout(function () {
        btn.dataset.confirming = '';
        btn.textContent = '删除';
        btn.classList.remove('is-confirming');
      }, 3000);
      return;
    }

    // ── 第二次点：真删 ──
    if (btn._confirmTimer) clearTimeout(btn._confirmTimer);
    btn.dataset.confirming = '';
    btn.textContent = '删除中…';
    btn.disabled = true;

    const result = await P.callMulti('deleteConfig', [item.kind, item.id]);

    if (!result.ok) {
      //: 桥接层调用失败（方法不存在 / 通道断了 / 缺多参能力）
      btn.textContent = '删除';
      btn.disabled = false;
      showError('删除失败：' + (result.missing
        ? '桥接暂时不支持带两个参数的调用（需要 bridge.js 的 callWith）。' +
          '请在 Qt 版配置页删除。'
        : String(result.error && result.error.message || result.error)));
      return;
    }

    const data = result.data || {};
    if (!data.ok) {
      btn.textContent = '删除';
      btn.disabled = false;
      //: 后端 message 是给用户看的，直接用
      showError('删除失败：' + (data.message || data.reason || '未知原因'));
      return;
    }

    // ── 成功：从本地状态移除并重渲染 ──
    state.items = state.items.filter(function (it) {
      return !(it.kind === item.kind && it.id === item.id);
    });
    //: 详情面板如果开着这条，一起关掉
    const detail = document.getElementById('config-detail-host');
    if (detail && detail.dataset.configId === item.id) detail.remove();
    renderRows();
    showOk('已删除「' + (item.name || item.id) + '」');
  }

  //: ★ 这两个原来都是 ``const host = ...noticeHost; if (!host) return;`` ——
  //: 容器失效时**静默吞掉**错误/成功提示。现在统一走 ``toast()``
  //: （有 ``document.body`` 兜底，永远能显示）。
  function showError(text) {
    toast(P.esc(String(text)), 'error');
  }

  function showOk(text) {
    toast(P.esc(String(text)), 'ok', 2500);
  }

})();
