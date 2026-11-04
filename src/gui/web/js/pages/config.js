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

  /** 分类定义（value 和 Python 侧的 config_kind 对应）
   *
   * ★★★ 2026-11-03 用户圈图：「干掉角色战斗配置」
   *
   * 去掉了一整条 tab（``{value:'battle_profile', label:'战斗配置'}``）。
   *
   * ## 为什么可以直接去掉
   *
   * * 用户的战斗配置数量是 **0**（列表标题写着「0 条角色战斗配置」）
   * * 「角色战斗配置」的**编辑表单本来就没做**（点新增选它会提示
   *   「下一轮做」，见 ``TYPE_BATTLE_PROFILE`` 那个分支）
   *
   * 也就是说这条 tab **永远是空的、也建不了新条目** —— 留着只占地方。
   *
   * ⚠ **只删 tab，不删底层数据读取**：如果哪天用户从旧界面建了战斗配置，
   *   它仍会出现在「全部」里（``state.items`` 不按 tab 过滤时照常显示）。
   *   真要恢复这条 tab，把这一行加回来即可。
   */
  const KINDS = [
    { value: 'all', label: '全部', kind: '' },
    { value: 'loadout', label: '角色声骸筛选', kind: 'loadout' },
    { value: 'echo_profile', label: '角色声骸强化', kind: 'echo_profile' }
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

  /**
   * 角色搜索的**全量候选池**。
   *
   * ★★★ 2026-11-03 用户圈图（圈住整个候选面板）：
   *   「这个是角色搜索，**包含游戏目前所有的角色**」
   *
   * 之前候选是从 ``state.items`` 抽的 —— 只有**已经配置过**的角色
   * （本机 8 个），用户自然觉得「怎么才这么几个」。
   *
   * 现在改成先拉 ``getCharacterOptions('')``：后端读
   * :mod:`src.core.game_data` 的 ``CHARACTERS``（本机 61 个，已按实装
   * 版本倒序 —— 用户 2026-10-24 要求过「新角色降序」），**不要自己
   * 重排**。和旧界面（main 分支 ``echo_profile_ui.py``）用的是同一个
   * 清单：``set_choices([(c.name, ...) for c in self._characters])``。
   *
   * ``characters === null`` 表示还没拉到 / 拉失败 —— 这时候选退化成
   * 「只有已配置的角色」（老行为），页面照常能用。
   */
  const SEARCH_STATE = {
    /** ``null`` = 未加载；``[]`` = 拉失败 */
    characters: null,
    /** 正在拉（防重复请求）*/
    loading: false
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
    // ★★★ 2026-11-03 用户圈图：
    //    「新增按钮移到配置旁边」
    //    「刷新 → 干掉」
    //
    // ## 改了什么
    //
    // * **新增**：原来在 ``.page-head-actions``（``margin-left:auto`` 推到
    //   页面最右边）。用户要它**紧挨着「配置」标题**。
    // * **刷新**：删掉。它本来就不是旧界面的东西（P4 自己加的），
    //   而且用户手动改了数据后想刷新，切走再切回来（``reload()``）
    //   效果一样 —— 没有它也丢不了功能。
    //
    // ## 怎么实现「贴着标题」
    //
    // ``pageHead()`` 把 ``actions`` 放在右侧（``margin-left:auto``）。
    // 想贴标题只能**不用 actions**，自己往 ``page-head-text`` 里塞。
    // 这里直接手工拼一个页头。
    const head = P.el('div', { class: 'page-head' });
    const headText = P.el('div', { class: 'page-head-text' });
    //: 标题 + 新增按钮**同一行**（按钮垂直居中于标题）
    const titleRow = P.el('div', { class: 'page-title-row' });
    titleRow.appendChild(P.el('div', { class: 'page-title', text: '配置' }));
    const addBtn = P.button('新增', {
      kind: 'primary',
      size: 'sm',
      //: ★ 2026-11-03 用户圈图：「这个新增放的也太紧凑了吧」
      //: 原来是 ``margin-left:10px`` —— 24px 的大标题旁边贴一个 27px 的
      //: 小按钮，只有 10px 缝，看着像标题的一部分。
      //: 现在改由 ``.page-title-row`` 的 ``gap`` 统一给 14px，
      //: 按钮自己不再带 margin。
      onClick: function () { openConfigTypeDialog(app); }
    });
    addBtn.dataset.action = 'add-config';
    titleRow.appendChild(addBtn);
    headText.appendChild(titleRow);
    head.appendChild(headText);
    section.appendChild(head);

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
    //  角色搜索 —— ★★★ 2026-11-03 **改成「下拉列表 + 输入匹配」**
    //
    //  用户（第三次提这件事）：
    //    「这个搜索这么难做？首先这是一个下拉列表，选择角色，
    //      然后他还可以输入，根据输入直接匹配到角色」
    //    「然后所有的角色搜索都按照这样做」
    //
    //  ## 之前是什么
    //
    //  一个纯 ``<input type=search>``：只能打字，**没有候选可点**，
    //  也不能"选择角色"。用户得凭记忆把名字打对。
    //
    //  ## 现在（和配置页弹框里的 ``characterPicker`` 同一套交互）
    //
    //  * 点输入框 → 展开**候选列表**（带头像 + 名字 + 类型）
    //  * 打字 → 实时过滤（名字 / 拼音 / 类型都算）
    //  * 点候选 → 直接过滤到那个角色（``state.keyword = 名字``）
    //  * ``×`` 清除
    //
    //  ## 候选从哪来
    //
    //  ``state.items`` 里已经有全部配置，每条带 ``name``（角色名）、
    //  ``avatarUrl``、``kindLabel``。直接取，不用再打接口。
    //
    //  ⚠ 候选要去重（同一个角色可能同时有「声骸强化」和「声骸筛选」两条）。
    // ══════════════════════════════════════════════════════════════════════
    const searchRow = P.el('div', { class: 'config-search-row' });
    const search = P.el('div', {
      class: 'search config-search config-char-search',
      style: 'width:280px;flex:0 0 280px'
    });
    //: ★★★ 2026-11-03 用户圈图：「这个是什么？干掉」
    //:
    //: 左侧那个**深色小方块**是 ``App.icon('DOCUMENT')`` 的 mask
    //: （一个「文档」图标）—— 在 32px 高的搜索框里只有 14px，
    //: 糊成一坨灰块，既不像放大镜也不说明任何事。
    //:
    //: 用户要的是「下拉列表」：**左边不要图标**，右边要一个能点的
    //: **下拉箭头**（「这个下拉列表的下拉按钮呢」）。
    //: 图标整个删掉，箭头在下面 ``caretBtn`` 那里补。

    const searchInput = P.el('input', {
      type: 'search',
      placeholder: '搜索角色名（支持拼音，如 feixue / fx）',
      autocomplete: 'off'
    });
    search.appendChild(searchInput);

    //: 候选面板
    const searchPanel = P.el('div', { class: 'config-search-panel' });
    searchPanel.hidden = true;
    searchPanel.classList.add('hidden');
    search.appendChild(searchPanel);

    /**
     * 拉**全量角色**候选池（``getCharacterOptions('')``）—— 只拉一次。
     *
     * ★ 用户 2026-11-03：「这个是角色搜索，包含游戏目前所有的角色」
     *
     * 旧界面（main 分支 ``echo_profile_ui.py``）就是这么做的：
     * ``set_choices([(c.name, ...) for c in self._characters])``，
     * ``self._characters = list(game_data.CHARACTERS)``。
     *
     * ⚠ **不要传 kind**：传了后端会按「已被占用的角色」筛掉一部分，
     *   而搜索框是要能搜到**所有角色**的（哪怕已经配过）。
     *   ``taken`` 标记在这里不用 —— 已配置 / 未配置只影响候选行的
     *   淡化（``is-plain``），不再是文字标签。
     */
    async function loadSearchCharacters() {
      if (SEARCH_STATE.loading) return;
      if (SEARCH_STATE.characters && SEARCH_STATE.characters.length) return;
      SEARCH_STATE.loading = true;
      try {
        const result = await P.call('getCharacterOptions', '');
        const data = (result.ok && result.data) || {};
        const items = Array.isArray(data.items) ? data.items : [];
        if (data.ok === false || !items.length) {
          //: 接口不可用 → 退化成「只列已配置的角色」，页面照常能用
          SEARCH_STATE.characters = [];
        } else {
          SEARCH_STATE.characters = items.map(function (item) {
            return {
              name: String(item.name || ''),
              avatarUrl: String(item.avatarUrl || ''),
              pinyin: Array.isArray(item.pinyin) ? item.pinyin : []
            };
          }).filter(function (item) { return item.name; });
        }
      } catch (err) {
        SEARCH_STATE.characters = [];
      } finally {
        SEARCH_STATE.loading = false;
        //: 面板正开着就按新池重画一次
        if (!searchPanel.hidden) renderSearchPanel();
      }
    }

    /**
     * 候选池：**全部角色**（后端 ``game_data.CHARACTERS``，61 个）。
     *
     * ★★★ 2026-11-03 用户圈图：「这个搜索应该是下拉列表搜索，
     * **可根据名称或拼音模糊匹配角色**」
     *
     * ## 第一版补了什么
     *
     * 上一版只把 ``{name, avatarUrl, kindLabel}`` 塞进候选 —— 于是
     * ``renderSearchPanel`` 里只有一句 ``x.name.indexOf(kw)``，
     * **打 ``fx`` / ``feixue`` 一个候选都出不来**（用户抱怨的就是这个）。
     * 后端 ``getConfigList`` 每条本来都带 ``pinyin: [全拼, 首字母]``
     * （``text_match.pinyin_keys`` 算的），``normalizeConfigs`` 也原样
     * 保留了 —— 只是这里没接着往下传。现在带上。
     *
     * ## ★★★ 第二次圈图：「`这个是角色搜索，包含游戏目前所有的角色`」
     *
     * 候选池**不再**只从 ``state.items`` 抽（那样只有已配置的 8 个），
     * 主池改成 ``SEARCH_STATE.characters``（后端 ``getCharacterOptions('')``
     * 给的**全部 61 个角色**，含头像 / 拼音）。再拿 ``state.items``
     * 按名字建索引，只为了标出**哪些是已配置的**（渲染时淡化，
     * 文字标签已按用户「干掉」的要求去掉）。
     *
     * 拉不到全量候选时（``characters === null`` 或空）自动退回老行为：
     * 只列已配置的角色 —— 页面不能因为一个接口没通就空着。
     */
    function searchPool() {
      //: 名字 → {avatar, pinyin}（已配置的角色才有）
      const byName = {};
      for (const it of (state.items || [])) {
        const nm = String(it.name || '').trim();
        if (!nm) continue;
        if (!byName[nm]) {
          byName[nm] = {
            avatar: String(it.avatar || it.avatarUrl || ''),
            pinyin: Array.isArray(it.pinyin) ? it.pinyin : []
          };
        }
      }

      const out = [];
      const seen = {};
      const all = Array.isArray(SEARCH_STATE.characters) ? SEARCH_STATE.characters : null;

      if (all && all.length) {
        //: ① 全量角色池（后端已按实装版本倒序，**不要重排**）
        for (const ch of all) {
          const nm = String(ch.name || '').trim();
          if (!nm || seen[nm]) continue;
          seen[nm] = true;
          const conf = byName[nm];
          out.push({
            name: nm,
            avatarUrl: String(ch.avatarUrl || (conf && conf.avatar) || ''),
            configured: !!conf,
            //: ★ 拼音索引 ``[全拼, 首字母]`` —— 全量池和后端保证一致
            pinyin: Array.isArray(ch.pinyin) && ch.pinyin.length
              ? ch.pinyin
              : ((conf && conf.pinyin) || [])
          });
        }
        //: ② 有配置但不在 CHARACTERS 里的名字（数据比角色库新时会发生）——
        //:    不能默默吞掉，补在最后
        for (const nm of Object.keys(byName)) {
          if (seen[nm]) continue;
          seen[nm] = true;
          const conf = byName[nm];
          out.push({
            name: nm,
            avatarUrl: conf.avatar || '',
            configured: true,
            pinyin: conf.pinyin
          });
        }
        return out;
      }

      //: ③ 降级：接口没通 → 只列已配置的角色（老行为）
      for (const nm of Object.keys(byName)) {
        const conf = byName[nm];
        out.push({
          name: nm,
          avatarUrl: conf.avatar || '',
          configured: true,
          pinyin: conf.pinyin
        });
      }
      return out;
    }

    /**
     * 候选命中判定 —— **和全项目同一套规则**（``core/text_match.matches_keyword``）：
     *
     * 1. 空关键词 → 全命中
     * 2. 角色名**子串**（打中文直接命中）
     * 3. **纯字母** additionally 走拼音（全拼 ``feixue`` 或首字母 ``fx``）
     *
     * ⚠ 2026-11-03 用户圈图（两处）：候选行右侧那串
     * 「角色声骸强化 / 角色声骸筛选」标签要「干掉」，紧接着又说
     * 「我都选心了怎么还出现这些不相关的」——
     * **看得见什么，就只能按什么筛**。所以匹配维度只剩
     * 角色名 + 拼音，类型名 / 元素 / 武器一律不再参与
     * （旧界面 ``config_interface._matches_search`` 也是只比名字）。
     *
     * @param {object} opt - ``searchPool()`` 里的一项
     * @param {string} kw - 已 ``trim().toLowerCase()`` 的关键词
     * @returns {boolean}
     */
    function matchOption(opt, kw) {
      if (!kw) return true;
      if (opt.name.toLowerCase().indexOf(kw) >= 0) return true;
      //: 只有**纯字母**才试拼音 —— 打中文时子串已经够，硬算白费
      if (!/^[a-z]+$/.test(kw)) return false;
      const keys = opt.pinyin || [];
      const full = String(keys[0] || '').toLowerCase();
      const initial = String(keys[1] || '').toLowerCase();
      return (!!full && full.indexOf(kw) >= 0) ||
             (!!initial && initial.indexOf(kw) >= 0);
    }

    /** 渲染候选（按当前输入过滤）*/
    function renderSearchPanel() {
      P.fill(searchPanel, null);
      const kw = String(searchInput.value || '').trim().toLowerCase();
      //: 排序：**名字前缀**命中的排前面（打 ``fx`` → 绯雪 排在非雪前），
      //: 其次是**已配置**的（同一批候选里，配过的更容易被找）
      const pool = searchPool();
      const list = pool.filter(function (x) {
        return matchOption(x, kw);
      }).sort(function (a, b) {
        const ap = (kw && a.name.toLowerCase().indexOf(kw) === 0) ? 0 : 1;
        const bp = (kw && b.name.toLowerCase().indexOf(kw) === 0) ? 0 : 1;
        if (ap !== bp) return ap - bp;
        return (b.configured ? 1 : 0) - (a.configured ? 1 : 0);
      //: ★ 全量角色 61 个都画出来（面板自带滚动）——
      //:   只画前 30 个会让用户以为「角色不全」
      }).slice(0, 120);

      //: ★★★ 2026-11-03 用户圈图：「这个是角色搜索，包含游戏目前所有的角色」
      //:
      //: 面板只有 340px 高、一次看得到十来个 —— 光把 61 个塞进去，
      //: 用户还是会怀疑「剩下的呢」。所以顶部钉一行字，直接说清楚
      //: **候选池有多大、当前筛出几个**。
      if (pool.length) {
        const total = pool.length;
        const configured = pool.filter(function (x) { return x.configured; }).length;
        let hint = '全部 ' + total + ' 个角色';
        if (configured) hint += '（已配置 ' + configured + '）';
        if (kw) hint += ' · 匹配 ' + list.length + ' 个';
        searchPanel.appendChild(P.el('div', {
          class: 'config-search-hint',
          text: hint
        }));
      }

      if (!list.length) {
        searchPanel.appendChild(P.el('div', {
          class: 'config-search-empty',
          text: kw ? '没有匹配的角色' : '还没有角色数据'
        }));
        return;
      }
      for (const item of list) {
        const row = P.el('div', {
          class: 'config-search-opt' + (item.configured ? '' : ' is-plain')
        });
        //: 头像
        const face = P.el('span', { class: 'config-search-face' });
        if (item.avatarUrl) {
          const img = P.el('img', {
            src: item.avatarUrl, alt: '', loading: 'lazy'
          });
          img.addEventListener('error', function () {
            P.fill(face, null);
            face.textContent = item.name.slice(0, 1);
          }, { once: true });
          face.appendChild(img);
        } else {
          face.textContent = item.name.slice(0, 1);
        }
        row.appendChild(face);
        row.appendChild(P.el('span', {
          class: 'config-search-name', text: item.name
        }));
        //: ★★★ 2026-11-03 用户圈图：「干掉」
        //:
        //: 原来每行右边还有一枚类型标签（「角色声骸强化 / 角色声骸筛选」）——
        //: 用户圈掉它，一是列宽被它吃掉、名字反而挤，二是**看见标签
        //: 就会以为可以按它搜**（结果打了个「心」冒出一堆不相关的）。
        //: 现在候选行只有「头像 + 角色名」，干净的纯角色列表。
        //:
        //: 已配置 / 未配置的区别用行的整体透明度暗示（``is-plain``），
        //: 不再挂文字。
        //: ⚠ 用 mousedown —— click 会先触发 blur 把面板收掉
        row.addEventListener('mousedown', function (ev) {
          ev.preventDefault();
          searchInput.value = item.name;
          state.keyword = item.name;
          clearBtn.style.display = '';
          closeSearchPanel();
          renderRows();
        });
        searchPanel.appendChild(row);
      }
    }

    function openSearchPanel() {
      renderSearchPanel();
      searchPanel.hidden = false;
      searchPanel.classList.remove('hidden');
      //: 箭头跟着翻（``.search.is-open .search-caret`` 的旋转）
      search.classList.add('is-open');
    }
    function closeSearchPanel() {
      searchPanel.hidden = true;
      searchPanel.classList.add('hidden');
      search.classList.remove('is-open');
    }

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
        closeSearchPanel();
        renderRows();
        searchInput.focus();
      }
    });
    clearBtn.style.display = 'none';
    search.appendChild(clearBtn);

    /**
     * 右侧**下拉箭头**。
     *
     * ★★★ 2026-11-03 用户圈图：「这个下拉列表的下拉按钮呢」
     *
     * 之前只有「点输入框展开」这一条路 —— 用户看不出这是个下拉，
     * 也不知道可以点。补一个 ``▾``：点它 = 展开/收起候选面板，
     * 面板开着时箭头**翻转**（靠 ``.search.is-open`` 的 CSS 旋转）。
     *
     * ⚠ 用 ``mousedown`` 而不是 ``click`` —— 和候选行同理：
     *   ``click`` 会先让输入框 ``blur``（120ms 后关面板），
     *   顺序上抢不过，点了会「开了又关」。
     */
    const caretBtn = P.el('button', {
      class: 'search-caret',
      type: 'button',
      title: '展开/收起候选角色',
      //: ★ 2026-11-03 用户圈图：「这个下拉箭头也太小了吧」——
      //: 除了 CSS 放大（24×24 / 15px），字形也换成更实的 ``▼``
      //: （``▾`` 是小三角，同字号下视觉上只有一半大）
      text: '▼',
      onMousedown: function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (searchPanel.hidden) {
          searchInput.focus();
          openSearchPanel();
        } else {
          closeSearchPanel();
        }
      }
    });
    search.appendChild(caretBtn);

    searchInput.addEventListener('input', function () {
      clearBtn.style.display = searchInput.value ? '' : 'none';
      state.keyword = searchInput.value.trim();
      renderRows();
      //: 打字时面板要跟着过滤；没开就打开
      if (searchPanel.hidden) openSearchPanel(); else renderSearchPanel();
    });
    //: 点输入框就展开候选（用户要的是"下拉列表"）
    searchInput.addEventListener('mousedown', function () {
      if (searchPanel.hidden) openSearchPanel();
    });
    searchInput.addEventListener('focus', function () {
      if (searchPanel.hidden) openSearchPanel();
    });
    searchInput.addEventListener('blur', function () {
      //: 延迟收，否则 mousedown 选不中
      setTimeout(closeSearchPanel, 120);
    });
    searchInput.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') { closeSearchPanel(); searchInput.blur(); }
      if (ev.key === 'Enter') {
        const first = searchPanel.querySelector('.config-search-opt');
        if (first) {
          ev.preventDefault();
          first.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        }
      }
    });

    searchRow.appendChild(search);
    section.appendChild(searchRow);

    //: ★ 全量角色候选池（61 个）—— 异步拉，拉回来之前先用已配置的角色顶着
    void loadSearchCharacters();

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
  //  只读（「查看」）
  // ══════════════════════════════════════════════════════════════════════

  /**
   * 把已经建好的弹框整体锁成只读。
   *
   * ## 用户要求（2026-11-04）
   *
   * 「查看和编辑应该是一样的页面，只是查看不能改东西」——
   * 所以直接用编辑那套表单，不另拼一个。
   *
   * ## 为什么要在**建完之后**统一扫一遍
   *
   * 表单里有好几处回调会**重新点亮**控件（这些都在各自的同步函数里，
   * 改起来很容易漏一个）：
   *
   * * ``buildCostSection`` 的 ``syncPick()``：``scb.disabled = !cb.checked``
   * * ``buildDialogSettingsEditor`` 的 ``syncCore()``：核心满 5 条置灰
   * * ``buildDialogSettingsEditor`` 的 ``syncOptional()``：被核心占用置灰
   * * 双爆开关回调：``critField.input.disabled = !on``
   *
   * 那些函数里已经加了 ``if (readOnly) return``，这里再兜一层
   * ——「所有能点的都不给点」是最后一道保险。
   *
   * ## 例外（必须放行）
   *
   * * ``.coll-toggle`` —— 折叠卡展开按钮。禁了就没法看「核心属性」
   *   那些收起来的区块，等于查看不了。
   * * ``.dlg-close`` / ``.dlg-foot .btn`` —— 关闭按钮，得能退出。
   *
   * @param {HTMLElement} box ``openDialog`` 返回的 ``el``
   */
  function lockDialogReadOnly(box) {
    if (!box) return;
    const items = box.querySelectorAll('input, select, textarea, button');
    for (const node of items) {
      if (node.classList.contains('coll-toggle')) continue;
      if (node.classList.contains('dlg-close')) continue;
      if (node.closest && node.closest('.dlg-foot')) continue;
      node.disabled = true;
    }
    //: 鼠标手型也去掉 —— 看起来能点、点不动最难受
    const toggles = box.querySelectorAll('.coll-toggle');
    for (const t of toggles) t.disabled = false;
    box.classList.add('dlg-readonly');
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
    //:
    //: ★ 2026-11-03 用户：「这个下拉箭头也太小了吧」「所有设计角色搜索的，
    //:   都按照这个做」—— 搜索框那边已经换成 24×24 / 15px 的 ``▼``，
    //:   弹框这个 ``▾``（字号 11、22×22）比它小一半，对齐过来。
    const arrow = P.el('button', {
      class: 'char-arrow', type: 'button', text: '▼', title: '展开候选',
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
        //: ★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
        //:
        //: 原来这里是
        //: ``matchesKeyword({name, summary: item.element, pinyin})`` ——
        //: 把**元素**塞进 ``summary`` 当匹配依据。于是打「冷凝」能把所有
        //: 冷凝角色筛出来，但候选行上并没有"冷凝"两个字，用户根本看不出
        //: 为什么命中（配置页同一个毛病，已经被圈图「干掉」过一次）。
        //: 现在只传名字 + 拼音，和配置页 ``matchOption()`` 完全一致。
        return matchesKeyword(
          { name: item.name, pinyin: item.pinyin },
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
        //: ★★★ 2026-11-03 用户圈图：「这里名字左边加上那个角色头像」
        //:
        //: 原来每项只有纯名字（``text: item.name``）—— 用户要在
        //: 几十个角色里找人对号，没有头像很难认。
        //:
        //: 现在每项 = [头像][名字][元素]。
        //: 头像来源和 ``updateAvatar`` 完全一致（``item.iconUrl`` 优先，
        //: 挂了退回首字色块），所以列表里看到的和右边大图一致。
        const opt = P.el('div', {
          class: 'char-option' + (idx === activeIndex ? ' is-active' : ''),
          dataset: { name: item.name },
          onMousedown: function (ev) {
            //: ⚠ 用 mousedown 而不是 click —— blur 会先触发、把菜单收掉
            ev.preventDefault();
            choose(item.name);
          }
        });

        //: 头像
        const face = P.el('span', { class: 'char-option-face' });
        //: ★★★ 2026-11-03 修：字段名是 ``avatarUrl``
        //:
        //: 我第一版写成 ``item.iconUrl || item.avatar`` —— **两个都不存在**，
        //: 所以永远走「没有头像」分支，用户看到的还是首字色块
        //: （圈图：「图片呢」）。
        //:
        //: 后端 ``getCharacterOptions`` 给的字段是::
        //:
        //:     {name, avatarUrl, avatarHue, initial, taken, element, ...}
        //:
        //: 其中 ``avatarUrl`` **只在文件真在时才有值**（``_safe_icon_url``
        //: 会先 ``path.exists``），空串就该走首字兜底 —— 所以判断
        //: ``if (avatarUrl)`` 就够了，不用再试别的字段名。
        const iconUrl = String(item.avatarUrl || '');
        if (iconUrl) {
          const img = P.el('img', { src: iconUrl, alt: '', loading: 'lazy' });
          img.addEventListener('error', function () {
            //: 图挂了 → 退回首字色块（和右侧大图同一套兜底）
            P.fill(face, null);
            face.classList.add('is-initial');
            const initial = item.initial;
            face.textContent = String(
              (initial && initial.initial) || item.name.slice(0, 1));
            if (initial && initial.color) {
              face.style.backgroundColor = String(initial.color);
            }
          }, { once: true });
          face.appendChild(img);
        } else {
          face.classList.add('is-initial');
          const initial = item.initial;
          face.textContent = String(
            (initial && initial.initial) || item.name.slice(0, 1));
          if (initial && initial.color) {
            face.style.backgroundColor = String(initial.color);
          }
        }
        opt.appendChild(face);
        opt.appendChild(P.el('span', {
          class: 'char-option-name', text: item.name
        }));
        //: ★ 2026-11-03 用户：「所有设计角色搜索的，都按照这个做」
        //:
        //: 这里原来还挂一截 ``.char-option-meta``（元素，如「冷凝」）——
        //: 配置页候选行的类型标签已经被用户要求「干掉」了，理由一样：
        //: 候选行上多出来的那截字，用户会以为**能按它筛**，一旦按元素
        //: 命中又看不出理由。统一成「头像 + 名字」。
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
      //: ★★★ 2026-11-03 用户：「加个角色头像，**选择角色的时候自动匹配**到头像」
      //:
      //: ## 之前的缺口
      //:
      //: 这里原来只做**精确匹配** ``x.name === name``。用户：
      //:   * 从下拉里点选 → 名字完全一致 → 头像正常 ✅
      //:   * **手打**「莉莉」但还没从下拉里点 → 也是一致，正常 ✅
      //:   * 手打到一半（「莉」）→ 匹配不到 → 头像退化成首字色块
      //:     ← 用户看到的就是"头像没跟上"
      //:
      //: ## 现在
      //:
      //: 三级匹配：精确 → 前缀 → 包含。手打到一半也能立刻看到对应的头像。
      const pool = DIALOG_STATE.charOptions || [];
      const byName = function (n) {
        return pool.find(function (x) { return x.name === n; });
      };
      const item = byName(name)
        || pool.find(function (x) {
          return x.name && x.name.indexOf(name) === 0;
        })
        || pool.find(function (x) {
          return x.name && x.name.indexOf(name) >= 0;
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
  //  而那一份我在 ④ 已经按旧界面复刻完了 —— **可以直接复用**。
  //
  //  「角色声骸筛选」（LoadoutDialog 631 行：套装 + 4C/3C/1C 逐档挑选）
  //  是独立一大块，下一轮做。
  // ════════════════════════════════════════════════════════════════════════

  //: ★★★ 2026-11-03 用户：「角色战斗配置不是让你删掉吗，**新增里也要删除**」
  //:
  //: 去掉 ``'角色战斗配置'``。它本来也建不了（编辑表单没做，
  //: 选了只会提示「下一轮做」），留着只是让用户白点一次。
  //:
  //: ⚠ ``TYPE_BATTLE_PROFILE`` 常量**保留** —— 它还被
  //:   ``openEditDialog`` 用来识别"这条是战斗配置"从而给提示
  //:   （万一用户从旧界面建过，列表里还能看到、点编辑会说清楚）。
  const CONFIG_TYPES = ['角色声骸筛选', '角色声骸强化'];
  const TYPE_LOADOUT = '角色声骸筛选';
  const TYPE_ECHO_PROFILE = '角色声骸强化';
  const TYPE_BATTLE_PROFILE = '角色战斗配置';

  // ══════════════════════════════════════════════════════════════════════
  //  第一步：配置类型选择（``ConfigTypeDialog`` L80-108）
  // ══════════════════════════════════════════════════════════════════════

  function openConfigTypeDialog(app) {
    const body = P.el('div', { class: 'dlg-form' });

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
  //: ★★★ 2026-11-03 用户圈图：「默认是勾上已锁定」
  //:
  //: 原来默认是「未标记」。用户的场景是**要刷的声骸先锁上**再筛，
  //: 所以新建配置时默认「已锁定」更贴合实际用法。
  //:
  //: ⚠ 这个常量有 **4 处**在用（新建默认 / 回填兜底 / 保存 / 读取），
  //:   改一处就全改 —— 这正是把它抽成常量而不是到处硬编码的价值。
  const DEFAULT_STATUS = '已锁定';
  //: 旧界面 ``game_data.COST_SECTIONS``
  const COST_SECTIONS = [[4, '4C'], [3, '3C'], [1, '1C']];

  /**
   * 打开「角色声骸筛选」对话框。
   *
   * @param {object} app
   * @param {object|null} existing - 编辑时传原配置（含 character / echoSet / picks…）
   */
  async function openLoadoutDialog(app, existing, opts) {
    const creating = !existing;
    opts = opts || {};
    //: 只读（「查看」）—— 同一个表单，只是不能改
    const readOnly = !!opts.readOnly;
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

    //: ★ 2026-11-03 和「新增配置」弹框保持一致：角色行（含右侧头像）
    //: 套玻璃卡底，并删掉「N 个角色已有配置，不在候选里」那行说明
    //: —— 用户圈图原话「这里也是一个卡片」「删掉」。理由见
    //: ``openEchoProfileDialog`` 里同名注释（两处是分开实现的）。
    const charCard = P.el('div', { class: 'dlg-card-row card-glass' });
    charCard.appendChild(charRow);
    body.appendChild(charCard);

    // ── 声骸套装（37 套，**带图标**）──
    //
    //: ★★★ 2026-11-03 用户圈图：「图标呢」
    //:
    //: 原来用 ``Panels.select()``（原生 ``<select>``）—— 而
    //: ``<option>`` **只能放纯文本，放不进 ``<img>``**，
    //: 所以后端早就给了 ``iconUrl``（``assets/game/echo_sets/``
    //: 下 37 个 png 都在）却也显示不出来。
    //:
    //: 现在换成 ``buildIconPicker()``：按钮 + 自定义弹层，
    //: 每一项都是「图标 + 套装名」，选中后 trigger 里也带图标。
    const sets = await loadEchoSetList();
    const setRow = P.el('div', { class: 'dlg-row' });
    setRow.appendChild(requiredLabel('声骸套装'));
    const setPicker = buildIconPicker(
      sets.map(function (s) {
        return { name: s.name, iconUrl: s.iconUrl };
      }),
      existing && existing.echoSet ? existing.echoSet : SET_PLACEHOLDER,
      {
        placeholder: SET_PLACEHOLDER,
        //: ★★★ 2026-11-03 **换套装要立刻重建声骸区**
        //:
        //: 踩到过：从原生 ``<select>`` 换成自定义 picker 后，
        //: 原来挂在 ``select.change`` 上的监听没了 ——
        //: 选完套装，下面 4C/3C/1C 区**一直停在「请先在上方选择声骸套装」**，
        //: 用户会以为套装没选上（实测截图确认）。
        //:
        //: 所以 picker 必须显式回调这里。``rebuildEchoArea`` 会重新
        //: 拉 ``getEchoSetDetail`` 并重画。
        onChange: function () {
          rebuildEchoArea(null);
        }
      }
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
          //: 只读（「查看」）时属性框一律置灰 —— 别让下面那句
          //: ``!cb.checked`` 把已勾选的那些又点亮
          scb.disabled = readOnly ? true : !cb.checked;
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
          //: 只读时不要动 —— 否则一次 change 就把「查看」点亮成可编辑
          if (readOnly) return;
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
    const dlg = openDialog({
      title: creating ? '新增配置'
        : (readOnly ? '查看配置' : '修改配置'),
      width: LOADOUT_DIALOG_WIDTH,
      body: body,
      actions: readOnly
        ? [{ label: '关闭', kind: 'primary', name: 'close-detail',
             onClick: closeDialog }]
        : [
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
    if (readOnly) lockDialogReadOnly(dlg.el);
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

  /**
   * ★★★ 2026-11-03 带图标的**自定义下拉**（替换原生 ``<select>``）。
   *
   * ## 为什么不能用 ``<select>``
   *
   * 用户圈图：「图标呢」—— 声骸套装下拉里每套都该有图标，
   * 但原生 ``<option>`` **只能放纯文本**，放不进 ``<img>``。
   *
   * 后端 ``getLibraryData`` 早就给了 ``iconUrl``（
   * ``assets/game/echo_sets/<套装名>.png``，37 个文件都在），
   * 只是 ``<select>`` 渲染不出来。
   *
   * ## 实现
   *
   * 一个按钮 + 一个绝对定位的弹层（``.picker-panel``）：
   *
   * .. code:: text
   *
   *     [🖼 轻云出月            ▼]     ← .picker-trigger
   *      ┌────────────────────┐
   *      │ 🖼 轻云出月         │       ← .picker-option（带图标）
   *      │ 🖼 命理崩毁之弦     │
   *      └────────────────────┘
   *
   * ## 交互
   *
   * * 点 trigger → 开/关
   * * 点选项 → 选中 + 关闭
   * * 点外部 / Esc → 关闭
   * * 选中项在 trigger 里**也显示图标**
   *
   * @param {Array<{name:string, iconUrl:string}>} items
   * @param {string} current - 当前值
   * @param {object} [opts] - ``{placeholder, onChange}``
   * @returns {{el, get, set, setOptions}}
   */
  function buildIconPicker(items, current, opts) {
    opts = opts || {};
    const placeholder = opts.placeholder || '';
    let value = current || placeholder;
    let options = (items || []).slice();

    const root = P.el('div', { class: 'picker' });
    const trigger = P.el('button', {
      class: 'picker-trigger', type: 'button'
    });
    const triggerIcon = P.el('span', { class: 'picker-trigger-icon' });
    const triggerText = P.el('span', { class: 'picker-trigger-text' });
    const triggerArrow = P.el('span', {
      class: 'picker-trigger-arrow', text: '▼'
    });
    trigger.appendChild(triggerIcon);
    trigger.appendChild(triggerText);
    trigger.appendChild(triggerArrow);
    root.appendChild(trigger);

    const panel = P.el('div', { class: 'picker-panel' });
    panel.hidden = true;
    panel.classList.add('hidden');
    root.appendChild(panel);

    /** 造一个「图标 + 文字」片段 */
    function makeFace(name, iconUrl) {
      const frag = [];
      const icon = P.el('span', { class: 'picker-opt-icon' });
      if (iconUrl) {
        const img = P.el('img', { src: iconUrl, alt: '', loading: 'lazy' });
        img.addEventListener('error', function () {
          //: 图标挂了就藏起来（不留破图），文字照常显示
          icon.style.display = 'none';
        }, { once: true });
        icon.appendChild(img);
      } else {
        icon.style.display = 'none';
      }
      frag.push(icon);
      frag.push(P.el('span', { class: 'picker-opt-text', text: name }));
      return frag;
    }

    function findItem(name) {
      for (const it of options) {
        if (String(it.name) === String(name)) return it;
      }
      return null;
    }

    function syncTrigger() {
      P.fill(triggerIcon, null);
      P.fill(triggerText, null);
      const hit = findItem(value);
      const label = value || placeholder || '请选择';
      const isPlaceholder = !hit && (!value || value === placeholder);
      if (hit && hit.iconUrl) {
        const img = P.el('img', { src: hit.iconUrl, alt: '' });
        img.addEventListener('error', function () {
          triggerIcon.style.display = 'none';
        }, { once: true });
        triggerIcon.appendChild(img);
        triggerIcon.style.display = '';
      } else {
        triggerIcon.style.display = 'none';
      }
      triggerText.textContent = label;
      trigger.classList.toggle('is-placeholder', isPlaceholder);
    }

    function renderPanel() {
      P.fill(panel, null);
      //: 占位项（「请选择」）排在第一个，和旧界面一致
      const list = [];
      if (placeholder) list.push({ name: placeholder, iconUrl: '' });
      for (const it of options) list.push(it);
      for (const it of list) {
        const row = P.el('div', {
          class: 'picker-option'
            + (String(it.name) === String(value) ? ' is-current' : '')
        }, makeFace(String(it.name), it.iconUrl));
        row.addEventListener('click', function (ev) {
          ev.stopPropagation();
          setValue(String(it.name));
          close();
          if (typeof opts.onChange === 'function') opts.onChange(value);
        });
        panel.appendChild(row);
      }
    }

    function open() {
      renderPanel();
      panel.hidden = false;
      panel.classList.remove('hidden');
      root.classList.add('is-open');
    }
    function close() {
      panel.hidden = true;
      panel.classList.add('hidden');
      root.classList.remove('is-open');
    }
    function toggle() {
      if (panel.hidden) open(); else close();
    }

    function setValue(v) {
      value = v == null ? '' : String(v);
      syncTrigger();
    }

    trigger.addEventListener('click', function (ev) {
      ev.stopPropagation();
      toggle();
    });
    //: 点外部关闭
    document.addEventListener('click', function () { close(); });
    //: Esc 关闭
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape') close();
    });

    syncTrigger();

    const api = {
      el: root,
      panelEl: panel,
      triggerEl: trigger,
      get: function () { return value; },
      set: setValue,
      setOptions: function (list, keep) {
        options = (list || []).slice();
        if (keep != null) setValue(keep);
        else syncTrigger();
        if (!panel.hidden) renderPanel();
      },
      open: open,
      close: close
    };
    return api;
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
  async function openEchoProfileDialog(app, existing, opts) {
    const creating = !existing;
    opts = opts || {};
    //: 只读（「查看」）—— 同一个表单，只是不能改
    //
    //: 用户 2026-11-04：「查看和编辑应该是一样的页面，只是查看不能改东西」。
    const readOnly = !!opts.readOnly;
    const title = creating ? '新增配置'
      : (readOnly ? '查看配置' : '编辑配置');

    const body = P.el('div', { class: 'dlg-form' });

    //: ★★★ 2026-11-03 用户圈图：「干掉」——删掉弹框顶部那段说明：
    //:
    //:   「设置区 = **「声骸自动强化」工具页那一份**；
    //:     **新增时的默认 = 它每次打开显示的那套（出厂默认）**。
    //:     改这里**不会**动到工具页，反之亦然（两者互不影响）。」
    //:
    //: 这是**实现说明**（讲代码怎么复用组件的），不是给用户看的。
    //: 而且里面还有 ``**`` 这种 markdown 星号——旧界面 Qt 不渲染
    //: markdown，所以原样显示成星号，看着更乱。
    //:
    //: ⚠ 旧界面确实有这一段（``L178-186`` 逐字照抄），但用户现在
    //:   明确要求去掉，以最新要求为准。

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

    // ══════════════════════════════════════════════════════════════════════
    //  ★★★ 2026-11-03 用户圈图（两处，同一行）：
    //    ① 圈住右边的圆形头像 →「这里也是一个卡片」
    //    ② 圈住下面那行小字 →「删掉」
    // ══════════════════════════════════════════════════════════════════════
    //
    //  ① 头像为什么看着"掉在外面"：``.char-picker`` 是裸的 inline-flex，
    //     它右边的 ``.char-avatar`` 直接贴在弹框背景上。而这张弹框里
    //     别的行（双爆下限 / 满值锁定 / 有效词条）**都有玻璃卡底**
    //     —— 于是头像和角色下拉像"少了一张卡"。
    //     现在把整行套进 ``.dlg-card-row card-glass``，和那几张卡同一套配方。
    //
    //  ② 删掉的是这行：
    //
    ///        「（3 个角色已经有配置了，不在候选里 —— 一个角色只能有一条）」
    //
    //     —— 旧界面 ``echo_profile_ui.py`` 的 ``_taken`` 提示。
    //     用户从 2026-11-02 起反复要求「说明文字全删」，这行到现在还留着；
    //     而且它说的信息（已占用的角色不在候选里）**打开下拉就看得见**
    //     （候选里本来就没有它们），再写一行纯属噪声。
    const nameCard = P.el('div', { class: 'dlg-card-row card-glass' });
    nameCard.appendChild(nameRow);
    body.appendChild(nameCard);

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

    // ── 设置区：复用工具页那套卡（旧界面 ``EchoSettingsEditor``，少两张）──
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
    const editor = buildDialogSettingsEditor(settings, readOnly);
    settingsArea.appendChild(editor.el);
    body.appendChild(settingsArea);

    // ── 底部按钮（旧界面 L274-275：创建时「创建」、编辑时「保存」）──
    const dlg = openDialog({
      title: title,
      width: 720,
      body: body,
      actions: readOnly
        ? [{ label: '关闭', kind: 'primary', name: 'close-detail',
             onClick: closeDialog }]
        : [
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
              //: ★★★ 2026-11-03 用户圈图：「这里是3，但是所选属性只有2条，
              //: 怎么创建，应该提示创建失败」—— 设置项自己也要能拦。
              //: 理由见 ``buildDialogSettingsEditor`` 里 ``validate()`` 的注释。
              const badSettings = editor.validate();
              if (badSettings) {
                showDialogError(errorEl, badSettings);
                //: 把出事的那一行滚到视野里（弹框比 900px 高的屏幕还长）
                const validCard = settingsArea.querySelector('.enh-valid-hint');
                if (validCard && validCard.scrollIntoView) {
                  validCard.scrollIntoView({ block: 'center' });
                }
                return;
              }
              hideDialogError(errorEl);
              await submitEchoProfile(name, editor.read(), existing, app);
            }
          }
        ]
    });
    if (readOnly) lockDialogReadOnly(dlg.el);
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
  //  对话框里的设置编辑器 —— 复用 ④ 那套卡，但**用局部状态**
  // ══════════════════════════════════════════════════════════════════════

  /**
   * 建一套独立的设置控件（不碰工具页的 DOM / ENHANCE_STATE）。
   *
   * 结构照抄旧界面 ``EchoSettingsEditor`` L79-84，但**少两张卡**：
   *   ① 核心属性（CollapsibleCard）  ② 双爆下限（玻璃卡）
   *   ③ 满值锁定（CardWidget）       ④ 可选属性（CollapsibleCard）
   *   ⑤ 有效词条（玻璃卡）
   *
   * ★ 2026-11-04 删掉旧界面的「自动停止」卡 —— 用户点名：新增配置的
   *   弹框里**不要**【自动停止】和【指定强化】。两者都还在工具页
   *   （``tool-panels.js`` 的 ``buildEnhanceAutostopCard`` /
   *   ``buildEnhanceDesignatedCard``），那是它们该待的地方；
   *   弹框里再放一份就是同一个开关两个入口。
   *
   * @param {object|null} saved - 已有的设置（编辑模式）
   * @returns {{el: Element, read: Function}}
   */
  function buildDialogSettingsEditor(saved, readOnly) {
    //: 只读（「查看」）—— 建完由 ``lockDialogReadOnly`` 统一禁用，
    //: 这里只在几个「会重新点亮控件」的同步函数里兜底
    const ro = !!readOnly;
    const root = P.el('div', { class: 'enh-editor' });
    const local = {
      coreBoxes: {},
      optionalBoxes: {},
      critField: null,
      critDmgField: null,
      critSwitch: null,
      maxrollSwitch: null,
      validStepper: null,
      //: ★ 2026-11-03 当前「有效词条」的合法范围 / 属性条数
      //: （``syncValidRange()`` 每次重算后写进来，``validate()`` 读它）
      validRange: null,
      coreSummary: null
    };
    const s = saved || {};

    // ── ① 核心属性（CollapsibleCard，默认收起）──
    //
    //: ★★★ 2026-11-03 用户圈图：「说明干掉」
    //:
    //: 删掉的是一整段（约 4 行）灰色说明：
    //:
    //:   「必须有，缺任意一条就弃置。暴击、暴击伤害强制勾选且不可取消 ——
    //:     上限 5 条里它们已占 2 条，自选最多还能勾 3 条（勾满后其余
    //:     自选框会置灰；已勾的随时可取消）。
    //:     出厂默认只有暴击、暴击伤害两条；每次进入本页都是这套默认值，
    //:     这里的勾选不会跨次保留（摘要若标「非默认」说明本次改过，
    //:     点标题栏的「恢复默认」可立刻还原）。」
    //:
    //: 用户从 2026-11-02 起反复要求「说明文字全删」，工具页那 7 个
    //: 早就删了，**配置页的对话框一直漏着** —— 这次一并清掉。
    //:
    //: ⚠ 摘要行（``summary``）**保留** —— 那不是说明，是**当前勾选
    //:   状态的回显**（「已勾选 2 / 5 条：暴击、暴击伤害」），
    //:   用户需要看得见自己勾了什么。
    const coreColl = TP.collapsibleCard('核心属性', {
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
      cb.disabled = forced || ro;
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
      const custom = checked - 2;                    //: 暴击 + 爆伤 强制占 2
      const limit = TP.ENHANCE_MAX_CORE - 2;
      for (const stat of TP.ENHANCE_ALL_STATS) {
        const cb = local.coreBoxes[stat];
        if (!cb) continue;
        if (stat === TP.ENHANCE_CRIT || stat === TP.ENHANCE_CRIT_DMG) continue;
        //: ★★★ 2026-11-03 用户圈图：
        //:   「这里属性是互斥的，上面先选了，下面就不能选，
        //:     下面先选了，上面就不能选」
        //:
        //: 可选属性里已经勾了同名项 → 这边**勾不动**（灰掉）。
        //: 上限控制（勾满 5 条）和互斥是两件独立的事，取或。
        const optBox = local.optionalBoxes[stat];
        const takenByOptional = !!(optBox && optBox.checked);
        cb.disabled = ro
          ? true
          : (takenByOptional || ((custom >= limit) && !cb.checked));
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

    // ── ② 双爆下限（★ 2026-11-03 补玻璃卡底）──
    //
    //: 用户圈图：「这里的卡片呢，还有3个启用/未启用按钮没对齐」
    //:
    //: ## 两个问题
    //:
    //: ① **没有卡片底** —— 这一行夹在「核心属性」卡片和「满值锁定」卡片
    //:    之间，是条裸行，看起来像"少了一张卡"。工具页那边上一轮已经
    //:    补了 ``.enh-crit-card``，**配置页这边漏了**（两处是分开实现的）。
    //:
    //: ② **三个开关没对齐** —— 这行的开关靠 ``flex:1 1 auto`` 推到了
    //:    最右，而下面「满值锁定」卡的开关也在最右（当时还有「自动停止」
    //:    卡，2026-11-04 已按要求删掉），但**卡片的左右内边距不同**
    //:    （裸行 vs ``card-glass`` 的 padding），
    //:    于是几者的 x 坐标差几个像素，看着就是没对齐。
    //:
    //: ## 修法
    //:
    //: 套上 ``.enh-crit-card``（和工具页同一个类，同样的 padding / 圆角），
    //: 开关改用 ``margin-left: auto``（CSS 里 ``.enh-crit-row > label.sw``
    //: 已经写好）—— 三行的右边界就都由同一套 padding 决定，自然对齐。
    const critCard = P.el('div', { class: 'enh-crit-card card-glass' });
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
    //: ⚠ 这里原来有个 ``flex:1 1 auto`` 的占位 div —— 去掉它，
    //: 改由 CSS ``.enh-crit-row > label.sw { margin-left: auto }``
    //: 把开关推到右边（和工具页保持一致）
    const critOn = s.enable_crit_check !== false;
    const critSw = P.toggle('启用', critOn, function (on) {
      //: 只读时不要跟着开关改 —— 查看态下这两个输入框要一直是灰的
      if (ro) return;
      local.critField.input.disabled = !on;
      local.critDmgField.input.disabled = !on;
    }, { onText: '启用', offText: '不启用' });
    critRow.appendChild(critSw);
    local.critSwitch = critSw.querySelector('input[type="checkbox"]');
    local.critField.input.disabled = ro ? true : !critOn;
    local.critDmgField.input.disabled = ro ? true : !critOn;
    critCard.appendChild(critRow);
    root.appendChild(critCard);

    // ── ③ 满值锁定（CardWidget + 开关 AlignTop）──
    //
    //: ★ 2026-11-03 用户圈图「说明干掉」——删掉了这段：
    //:
    //:   「出现满值词条（暴击 10.5 / 爆伤 21）时：不看别的条件，
    //:     一律强化到满级并上锁，不弃置。判定排在双爆下限与有效词条
    //:     之前 —— 出了满值就保住。」
    //:
    //: ⚠ ``.enh-switch-left`` 容器**保留** —— 没有它开关会被
    //:   ``.enh-switch-row`` 的 ``align-items: flex-start`` 顶到最左，
    //:   和「双爆下限」那行的开关错位（那才是用户说的"没对齐"）。
    const maxCard = P.el('div', { class: 'enh-switch-card card-glass' });
    const maxRow = P.el('div', { class: 'enh-switch-row' });
    const maxLeft = P.el('div', { class: 'enh-switch-left' });
    maxLeft.appendChild(P.el('div', {
      class: 'enh-switch-title',
      text: '满' + TP.ENHANCE_CRIT + ' / 满爆伤 自动锁定'
    }));
    maxRow.appendChild(maxLeft);
    const maxSw = P.toggle('启用', s.enable_max_roll_lock !== false, function () {},
      { onText: '启用', offText: '不启用' });
    maxSw.classList.add('enh-switch-top');
    local.maxrollSwitch = maxSw.querySelector('input[type="checkbox"]');
    maxRow.appendChild(maxSw);
    maxCard.appendChild(maxRow);
    root.appendChild(maxCard);

    // ── ⑤ 可选属性（CollapsibleCard）──
    //
    //: ★ 2026-11-03 用户圈图「说明干掉」——删掉 ``hint: '核心属性之外，
    //: 这些出现了也算有效词条。'``。
    //:
    //: 这是配置页对话框里**最后一条**说明文字（核心属性 / 满值锁定那两条
    //: 前面已删）。删完这一条，三个可折叠卡的 hint 全部为空 ——
    //: 和工具页那边保持一致。
    const optColl = TP.collapsibleCard('可选属性', {
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
      //: ★★★ 2026-11-03 用户圈图：「这里属性是互斥的，上面先选了，
      //: 下面就不能选，下面先选了，上面就不能选」。
      //:
      //: ## 规则
      //:
      //: 暴击 / 暴击伤害 只在核心属性里出现（可选网格本来就跳过它们）；
      //: 其余 11 项**同一时间只能待在一侧** —— 核心勾了，可选这一项就
      //: 灰掉；可选勾了，核心那一项就灰掉（在 ``syncCore()`` 里）。
      //:
      //: ## 为什么要在这里兜一次 ``opt.checked = false``
      //:
      //: 后端 ``EchoSettings.from_dict`` **不过滤交集**（
      //: ``settings.py:148-162`` 只做去重保序），所以磁盘上可能存着
      //: 「核心有攻击百分比、可选也有攻击百分比」的老数据。打开弹框时
      //: 以**核心属性**为准把可选那侧摘掉 —— 核心是主要求（用户先勾的
      //: 那一侧），可选是补充项。
      for (const stat of TP.ENHANCE_ALL_STATS) {
        if (stat === TP.ENHANCE_CRIT || stat === TP.ENHANCE_CRIT_DMG) continue;
        const opt = local.optionalBoxes[stat];
        if (!opt) continue;
        const core = local.coreBoxes[stat];
        const takenByCore = !!(core && core.checked);
        //: 只读时**不要**摘掉冲突项 —— 那是「修正数据」，查看态
        //: 不该改动正在看的东西（显示就得是磁盘上那份）
        if (takenByCore && opt.checked && !ro) opt.checked = false;
        opt.disabled = ro ? true : takenByCore;
      }
      const picked = TP.ENHANCE_ALL_STATS.filter(function (x) {
        const cb = local.optionalBoxes[x];
        return cb && cb.checked;
      });
      optColl.setSummary(picked.length
        ? '已选 ' + picked.length + ' 条：' + picked.join('、')
        : '未选');
    }
    syncOptional();
    //: ★ 2026-11-03 互斥联动：可选网格建好后**再算一次核心** ——
    //: 磁盘上若存着「可选也有攻击百分比」的老数据，``syncOptional()``
    //: 会先按「核心优先」把它从可选里摘掉；反过来若只剩可选那一侧
    //: 有它，这里要把核心对应的勾选框灰掉。
    syncCore();

    // ── ⑥ 有效词条 ──
    //
    //: ★★★ 2026-11-03 用户圈图：
    //:   「我给了三核心词条，2 条有效词条，但是有效词条至少数量设置为 3，
    //:     应该提示至少为 4」
    //:
    //: ## 规则（后端 ``valid_count_range``）
    //:
    //: .. code:: text
    //:
    //:     下界 = 核心属性条数     ← 「核心几条，有效词条最低就几条」
    //:     上界 = 核心 ∪ 可选 总条数
    //:
    //: ## 之前错在哪
    //:
    //: 这里写死 ``{min: 2, max: 5}`` —— **没跟核心属性联动**。
    //: 勾了 3 个核心，有效词条还能选 3（甚至 2），界面完全不拦，
    //: 等点保存/运行才被模型按 clamp 处理，用户根本不知道。
    //:
    //: ## 现在
    //:
    //: ``syncValidRange()`` 在**每次核心/可选属性变化时**重算范围：
    //:   * 加减框的 min/max 跟着变
    //:   * 当前值低于下界 → **当场**把值抬到下界，并在下面显示
    //:     「至少 N 条（核心属性 M 条）」的提示
    //:
    //: 用户要的"应该提示至少为 4"就是这个提示。
    const validCard = P.el('div', { class: 'enh-crit-card card-glass' });
    const validRow = P.el('div', { class: 'enh-crit-row' });
    validRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '有效词条' }));
    validRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '至少' }));
    local.validStepper = Panels.numberInput(
      s.min_valid_count != null ? s.min_valid_count : TP.ENHANCE_DEFAULT_VALID,
      //: ★★★ 2026-11-03 用户圈图：「这里是3，但是所选属性只有2条，怎么创建，
      //: 应该提示创建失败」。
      //:
      //: ``clampOnBlur: false`` —— 越界值**不许静默纠正**。
      //: 原因：这里（配置弹框）和工具页不一样，它是**一次性提交表单**，
      //: 用户填完点「创建」。如果我们失焦就把 3 夹成 2，用户永远不会
      //: 知道自己填的数没生效（后端 ``__post_init__`` 也是静默夹的）。
      //: 保留原值 → 点创建时 ``validate()`` 报错 → 用户看得见、改得动。
      { min: 2, max: 5, clampOnBlur: false });
    local.validStepper.el.classList.add('cfg-number');
    local.validStepper.input.classList.add('cfg-number-input');
    //: ★ 2026-11-03 专属类 —— ``cfg-number-input`` 三个控件共用
    //: （暴击下限 / 爆伤下限 / 有效词条），测试脚本和调试时
    //: ``.cfg-number-input`` 抓到的可能是 7.5 那个。这里单独标一个。
    local.validStepper.input.classList.add('enh-valid-number');
    validRow.appendChild(local.validStepper.el);
    validRow.appendChild(P.el('span', { class: 'enh-inline-label', text: '条' }));
    //: 提示位（值不足时显示「至少 N 条（核心属性 M 条）」）
    local.validHint = P.el('span', {
      class: 'enh-inline-label enh-valid-hint'
    });
    validRow.appendChild(local.validHint);
    validCard.appendChild(validRow);
    root.appendChild(validCard);

    /**
     * 按当前核心/可选属性条数重算「有效词条数」范围并纠正当前值。
     *
     * ⚠ 算法必须和后端 ``settings.valid_count_range`` **完全一致** ——
     * 两边算不一样就是新的 bug。所以这里照抄它的三行：
     *   ``total = len(core | optional)`` / ``low = max(2, len(core))`` /
     *   ``high = max(low, min(5, total))``
     */
    function syncValidRange() {
      const coreN = Object.keys(local.coreBoxes).filter(function (k) {
        return local.coreBoxes[k] && local.coreBoxes[k].checked;
      }).length;
      const optN = Object.keys(local.optionalBoxes).filter(function (k) {
        return local.optionalBoxes[k] && local.optionalBoxes[k].checked;
      }).length;
      const MINV = 2;
      const MAXV = 5;
      const total = coreN + optN;
      const low = Math.max(MINV, coreN);
      const high = Math.max(low, Math.min(MAXV, total));
      local.validRange = { low: low, high: high, total: total, coreN: coreN, optN: optN };

      const input = local.validStepper.input;
      if (input) {
        input.min = String(low);
        input.max = String(high);
        //: ★★★ 2026-11-03 关键一步：把边界**真正**交给加减框
        //:
        //: 上面两行只改 DOM 属性 —— 而 ``type="text"`` 的 ``min``/``max``
        //: 不构成约束，``Panels.numberInput`` 的 ``clamp()`` 读的是建控件
        //: 时传进去的闭包常量（``{min: 2, max: 5}``）。
        //: 于是「核心 2 条」时上界本应是 2，输入框却还能被 ＋ 到 3 ——
        //: 用户圈图那张截图（值 3、提示「核心属性 2 条」）就是这么来的。
        //:
        //: 现在 ``setRange()`` 把闭包里的 min/max 一起换掉，
        //: ＋/− 和失焦纠错都会按新边界夹住。
        if (typeof local.validStepper.setRange === 'function') {
          local.validStepper.setRange(low, high);
        }
        //: 当前值越界就抬到合法范围内（用户圈图要的就是这个自动纠正）
        const cur = parseInt(String(local.validStepper.get()), 10);
        if (!isFinite(cur) || cur < low) {
          local.validStepper.set(low);
        } else if (cur > high) {
          local.validStepper.set(high);
        }
      }
      if (local.validHint) {
        //: ★★★ 2026-11-03 用户圈图：「这里是3，但是所选属性只有2条，
        //: 怎么创建，应该提示创建失败」。
        //:
        //: 提示分两种：
        //:   ① 常态 —— 说明下界怎么来的（核心几条，不能少于几条）
        //:   ② 核心 ∪ 可选**凑不够 2 条**（``total < MINV``）——
        //:      这时候连下界都凑不出来，是**配置本身不成立**，
        //:      要说清楚"创建会被拒绝"，而不是继续显示一句温柔的灰字。
        if (total < MINV) {
          local.validHint.textContent = '（至少勾 ' + MINV +
            ' 条属性才凑得出来，现在只有 ' + total + ' 条 —— 创建会被拒绝）';
          local.validHint.classList.add('is-invalid');
        } else {
          local.validHint.textContent = coreN
            ? '（核心属性 ' + coreN + ' 条，不能少于 ' + low + '）'
            : '';
          local.validHint.classList.remove('is-invalid');
        }
      }
    }

    //: ★★★ 2026-11-03 让「有效词条」范围**跟着核心/可选属性联动**
    //:
    //: ## ⚠ 我第一版写错了，这里记下来别再犯
    //:
    //: 写成了::
    //:
    //:     const _syncCore0 = syncCore;
    //:     syncCore = function () { _syncCore0(); syncValidRange(); };   // ❌ 无效
    //:
    //: ``syncCore`` 是 **function 声明**（hoisted 的绑定），在它被调用时
    //: 解析的是外层作用域那个函数 —— 给同名变量**重新赋值不会**穿到
    //: 已有的调用点（那些 checkbox 的 ``change`` 监听早就在闭包里
    //: 绑到了原函数）。
    //:
    //: 实测症状：勾了 3 个核心，hint 还写着「核心属性 2 条，不能少于 2」。
    //:
    //: ## 现在
    //:
    //: 直接给 checkbox **补一个独立的 change 监听** —— 不改任何已有函数，
    //: 也不依赖声明顺序。这是最稳的做法。
    for (const stat of Object.keys(local.coreBoxes)) {
      const cb = local.coreBoxes[stat];
      if (cb) cb.addEventListener('change', syncValidRange);
    }
    for (const stat of Object.keys(local.optionalBoxes)) {
      const cb = local.optionalBoxes[stat];
      if (cb) cb.addEventListener('change', syncValidRange);
    }
    //: ★★★ 2026-11-03 互斥联动（用户：「上面先选了，下面就不能选，
    //: 下面先选了，上面就不能选」）。
    //:
    //: ⚠ 这里**同样不能**靠"包装 syncCore / syncOptional"来加联动 ——
    //: 见上面 2902 行那条教训：两个函数都是 function 声明，早就有
    //: checkbox 把**原函数**绑进了 change 监听，给变量重新赋值不会
    //: 穿过去。所以一律**补独立监听**，每个分组各挂对方那半边的同步函数。
    for (const stat of Object.keys(local.coreBoxes)) {
      const cb = local.coreBoxes[stat];
      //: 核心动了 → 可选那侧的同名项要跟着灰掉/放开
      if (cb) cb.addEventListener('change', syncOptional);
    }
    for (const stat of Object.keys(local.optionalBoxes)) {
      const cb = local.optionalBoxes[stat];
      //: 可选动了 → 核心那侧的「已勾满」置灰规则要重算，互斥要重判
      if (cb) cb.addEventListener('change', syncCore);
    }
    //: 初次进来也算一次
    syncValidRange();

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
        //: ★ 2026-11-04 弹框里已删「自动停止」卡（用户要求），但**字段还要
        //: 传** —— 后端 ``EchoSettings.from_dict`` 读它，缺了会落到默认值
        //: True。这里**原样保留磁盘上的值**（``s.enable_auto_stop``）：
        //: 老配置里若存着 False，编辑别的东西时不该被悄悄改成 True；
        //: 新建时 ``s`` 是空对象，自然取默认 True。
        //: 想改这个开关请去工具页 —— 那里的开关仍然生效，且「一改就存」。
        enable_auto_stop: s.enable_auto_stop !== false,
        min_valid_count: local.validStepper.get()
      };
    }

    /**
     * 保存前校验「有效词条」这一项 —— ★★★ 2026-11-03 用户圈图：
     *   **「这里是3，但是所选属性只有2条，怎么创建，应该提示创建失败」**
     *
     * ## 用户为什么不接受静默处理
     *
     * 后端 ``EchoSettings.__post_init__`` 会把越界的 ``min_valid_count``
     * 悄悄夹进 ``[low, high]`` —— 配置确实存下来了，但**用户填的 3 没生效**。
     * 界面上还显示着 3，下一次打开又变成 2，用户会以为是丢数据。
     * 所以要**在点「创建」时当场说清楚**，而不是让它悄悄过去。
     *
     * ## 什么时候算不成立
     *
     * 能凑出来的有效词条**最多**只有 ``total = 核心 ∪ 可选`` 条
     * （声骸 5 个孔位里每种词条只出现一次，见 ``settings.py`` 的注释）。
     * ``total < 2`` 时连下界都凑不出来 → 这个配置根本跑不出结果。
     *
     * ⚠ 只在 ``total < 2`` 时拒绝 —— 值只是「偏高」的情况
     *   （``high < cur``）``syncValidRange()`` 已经当场夹回去了，
     *   用户看得见输入框变成几，不需要再弹一次错误。
     *
     * @returns {string} 空串 = 通过；否则是要显示给用户的错误文案
     */
    function validate() {
      const range = local.validRange;
      if (!range) return '';
      const MINV = 2;
      //: ① 连下界都凑不出来 —— 这个配置根本跑不出结果
      if (range.total < MINV) {
        return '有效词条至少 ' + MINV + ' 条，但「核心属性 + 可选属性」只选了 ' +
          range.total + ' 条 —— 凑不出这么多有效词条，无法创建。请至少再勾选 ' +
          (MINV - range.total) + ' 条属性。';
      }
      //: ② 输入框里还留着越界值（用户直接打字、且没触发失焦纠错）
      const cur = parseInt(String(local.validStepper.get()), 10);
      if (isFinite(cur) && (cur < range.low || cur > range.high)) {
        //: 上下界相等时别说「2 ~ 2 条」（那是机器话）
        const span = range.low === range.high
          ? '只有 ' + range.low + ' 条'
          : range.low + ' ~ ' + range.high + ' 条';
        return '「有效词条」填的是 ' + cur + ' 条，但所选属性' + span +
          '（核心 ' + range.coreN + ' 条 + 可选 ' + range.optN +
          ' 条）—— 无法创建。';
      }
      return '';
    }

    return { el: root, read: read, validate: validate };
  }

  // ══════════════════════════════════════════════════════════════════════
  //  保存
  // ══════════════════════════════════════════════════════════════════════

  async function submitEchoProfile(name, settings, existing, app) {
    // ══════════════════════════════════════════════════════════════════════
    //  ★★★ 2026-11-03 修「保存必报 data 必须是对象」（用户圈图）
    //
    //  ## 症状
    //
    //  点「创建」必然红字报错：**「data 必须是对象」** ——
    //  配置根本存不进去。
    //
    //  ## 根因
    //
    //  后端 ``setConfig`` 要求的协议是::
    //
    //      {"kind": "echo_profile", "id"?: "...", "data": { 真正的配置体 }}
    //
    //  而这里发的是::
    //
    //      {"kind": "echo_profile", "name": "...", "settings": {...}}
    //      └─ 没有 data ───────────────────────────────────┘
    //
    //  → 后端 ``body = data.get("data")`` 拿到 ``None`` →
    //    ``not isinstance(None, dict)`` → 报 "data 必须是对象"。
    //
    //  ## 为什么之前没被发现
    //
    //  旁边的 ``submitLoadout`` **是对的**（``{kind, data: _loadoutWire(data)}``）
    //  —— 两个函数一个抄一个，抄漏了一层。而「角色声骸强化」的保存
    //  大概从没被真正点通过（用户之前都是 0 条战斗配置/在建声骸筛选）。
    //
    //  ## 现在
    //
    //  按协议包一层 ``data``。**注意是扁平的** —— 后端
    //  ``_save_echo_profile`` 直接 ``EchoProfile.from_dict(body)``，
    //  而 ``from_dict`` 读的是 ``data["name"]`` / ``data["settings"]``
    //  （都是**顶层**字段，不是嵌套）::
    //
    //      {"kind": "echo_profile",
    //       "id"?: "...",
    //       "data": {"name": "景燃", "settings": {...}}}
    //                 └─ 这两个必须在 data 的**顶层** ─┘
    //
    //  ⚠ 我第一版写成了 ``data: {name, settings: {...}}`` 里再嵌
    //    ``name`` —— 那就成了 ``data.name.name``，后端读不到。
    //    对照 ``EchoProfile.from_dict`` 的字段列表就是这个形状。
    const payload = {
      kind: 'echo_profile',
      data: {
        name: name,
        settings: settings
      }
    };
    if (existing && existing.id) {
      payload.id = existing.id;
      //: 修改时后端也需要 id 在 body 里（``target_id = data.id or body.id``）
      payload.data.id = existing.id;
    }

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
    //: ★★★ 2026-11-03 用户圈图：
    //:   「新增角色声骸筛选，怎么没有这条配置？」
    //:
    //: ## 症状
    //:
    //: 在「角色声骸强化」tab 下点「新增」并建了一条**声骸筛选**配置，
    //: 弹框关了、列表刷新了 —— 但**当前 tab 还是「角色声骸强化」**，
    //: 而新条目属于「角色声骸筛选」→ 看不见，用户以为没创建成功。
    //:
    //: ## 修法
    //:
    //: 建完自动切到**新条目所属的那个 tab**（``KINDS`` 里按 kind 找）。
    //: 这正是 ``KINDS`` 要带 ``kind`` 字段的用处。
    const kindOfNew = String(payload.kind || '');
    const targetTab = KINDS.find(function (k) {
      return k.kind && k.kind === kindOfNew;
    });
    if (targetTab && state.kind !== targetTab.value) {
      state.kind = targetTab.value;
      renderRows();
      //: 顺带给个确认 —— 用户刚建完，需要知道"东西在哪"
      toast('<b>已创建</b>「' + P.esc(String(payload.name || '')) +
        '」，已切到「' + P.esc(targetTab.label) + '」分类', 'ok');
    }
    void app;
  }

  /** 打开「编辑」—— 现在两种类型都能用了（P7）*/
  async function openEditDialog(item, app, opts) {
    if (!item) return;
    opts = opts || {};
    if (item.kind === 'echo_profile') {
      await openEchoProfileDialog(app, item, opts);
      return;
    }
    if (item.kind === 'loadout') {
      await openLoadoutDialog(app, item, opts);
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

    //: ② 中文子串 —— **只比角色名**
    //:
    //: ★★★ 2026-11-03 用户圈图：「我都选心了怎么还出现这些不相关的」
    //:
    //: 原来这里还比 ``summary``（那一长串「核心：暴击、暴击伤害…」），
    //: 于是打一个「心」→ ``indexOf`` 命中所有摘要里的「**核心**」→
    //: 赞妮 / 卡提希娅 … 全被筛出来。摘要里的字和用户要找的角色毫无
    //: 关系，属于**看不见理由的匹配**。
    //:
    //: 旧界面 ``config_interface._matches_search(name)`` 本来也**只比名字**，
    //: 这里对齐。
    const name = String(item.name || '');
    if (name.indexOf(kw) >= 0) return true;

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

    //: 分组（★ 顺序照抄旧界面：强化 → 筛选）
    //:
    //: ⚠ 2026-11-03：``battle_profile``（角色战斗配置）已被用户要求删掉
    //: （页签和「新增」里都删了），这里**必须同步删** —— 否则「全部」
    //: 页签下还会冒出一个「角色战斗配置」分组标题，用户会以为没删干净。
    //: 真恢复时，把这一行加回来即可（``state.items`` 仍会读这类数据）。
    const groups = [
      { kind: 'echo_profile', title: '角色声骸强化' },
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
    //: ★★★ 2026-11-03 **这才是真正渲染页签的那份表**
    //:
    //: ⚠ 踩过一次：文件里有两份「分类表」——
    //:   ``KINDS``（第 84 行附近，给别处用）
    //:   ``TABS``（这里，**页签真正读的是这份**）
    //: 我上一轮只改了 ``KINDS``，页签纹丝不动，用户又圈了一次：
    //:   「角色战斗配置不是让你删掉吗，新增里也要删除」
    //:
    //: 现在两边都去掉 ``battle_profile``。
    const TABS = [
      { value: 'all', label: '全部', kind: '' },
      { value: 'echo_profile', label: '角色声骸强化', kind: 'echo_profile' },
      { value: 'loadout', label: '角色声骸筛选', kind: 'loadout' }
    ];
    const counts = {
      all: state.items.length,
      echo_profile: 0,
      loadout: 0
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
      //: ⚠ 2026-11-03：**去掉「角色战斗配置」那一项**。
      //:
      //: 用户已经把这条类型从页签和「新增」里删掉了，但说明行还在统计
      //: 它 —— 界面上写着「共 15 条角色声骸强化配置 · 0 条角色战斗
      //: 配置 · 8 条角色声骸筛选配置」，用户圈图问「战斗配置不是删了吗」。
      //: 三种数的**顺序也照旧界面**：强化 → 筛选。
      el.textContent = '共 ' + [
        typeCount(countOf('echo_profile'), '角色声骸强化'),
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

    //: ② 查看 —— 和「编辑」同一个表单，只是全部只读
    //
    //: 用户 2026-11-04：「查看和编辑应该是一样的页面，只是查看不能改东西」。
    //: 以前另拼了一套键值网格（``showDetail``），跟编辑表单长得完全不一样，
    //: 用户看一眼再点编辑会以为换了个东西。
    actions.appendChild(P.button('查看', {
      size: 'sm',
      title: '查看这条配置（只读）',
      onClick: function () { openEditDialog(item, null, { readOnly: true }); }
    }));

    //: ③ 删除
    //: ★ 2026-11-03 用户圈图：「删除时，要弹出一个提示确认是否删除」
    //: 之前是点两次（按钮就地变「确认删除？」），现在改成弹对话框确认，
    //: 见 ``confirmDeleteConfig``。
    const delBtn = P.button('删除', {
      size: 'sm',
      title: '删除这条配置',
      onClick: function () { confirmDeleteConfig(item); }
    });
    delBtn.dataset.action = 'delete';
    actions.appendChild(delBtn);
    row.appendChild(actions);

    return row;
  }


  // ────────────────────────────────────────────────────────────────────────
  //  删除（真接口，2026-11-02 接；确认方式 2026-11-03 改弹框）
  // ────────────────────────────────────────────────────────────────────────
  /**
   * 点「删除」→ **弹框确认**（用户 2026-11-03 圈图要求）。
   *
   * ## 为什么不再用「点两次」
   *
   * 之前：第一次点，按钮就地变成「确认删除？」，3 秒内再点才真删。
   * 用户反馈「删除时，要弹出一个提示确认是否删除」—— 就地变字不够
   * 醒目（眼睛还在列表上，容易漏看），而且按钮宽度一变整行会抖。
   *
   * 现在复用项目里已有的 ``openDialog``（``新增配置`` / ``编辑`` 用的
   * 同一套），正文写清**删的是哪个角色、哪一类配置、不可撤销**，
   * 底部「取消」+ 红色「删除」。
   *
   * ## 为什么不用 window.confirm()
   *
   * QtWebEngine 里 ``window.confirm`` 需要宿主程序实现
   * ``QWebEnginePage.javaScriptConfirm``，没实现时**默认返回 false**
   * —— 点了确认也删不掉，而且看起来像"点了没反应"。
   *
   * @param {object} item - ``state.items`` 里的一项
   */
  function confirmDeleteConfig(item) {
    const body = P.el('div', { class: 'dlg-form' });

    //: 要删的是谁 —— 头像 + 名字 + 类型，别让用户删错角色
    const target = P.el('div', { class: 'del-target' });
    const face = P.el('span', { class: 'del-target-face' });
    const avatarUrl = String(item.avatar || '');
    if (avatarUrl) {
      const img = P.el('img', { src: avatarUrl, alt: '' });
      img.addEventListener('error', function () {
        P.fill(face, null);
        face.textContent = String(item.name || '?').slice(0, 1);
      }, { once: true });
      face.appendChild(img);
    } else {
      face.textContent = String(item.name || '?').slice(0, 1);
    }
    target.appendChild(face);

    const meta = P.el('div', { class: 'del-target-meta' });
    meta.appendChild(P.el('div', {
      class: 'del-target-name', text: String(item.name || '(未命名)')
    }));
    meta.appendChild(P.el('div', {
      class: 'del-target-kind',
      text: String(item.kindLabel || item.kind || '')
    }));
    target.appendChild(meta);
    body.appendChild(target);

    body.appendChild(P.el('div', {
      class: 'dlg-hint',
      text: '删除后不可恢复 —— 这条配置会从数据文件里移除，没有回收站。'
    }));

    openDialog({
      title: '删除配置',
      width: 420,
      body: body,
      actions: [
        { label: '取消', name: 'cancel', onClick: function () { closeDialog(); } },
        {
          label: '删除',
          kind: 'danger',
          name: 'confirm-delete',
          onClick: async function () {
            const btn = document.querySelector(
              '.dlg-foot [data-action="confirm-delete"]');
            if (btn) {
              btn.disabled = true;
              btn.textContent = '删除中…';
            }
            const ok = await deleteConfig(item);
            if (ok) {
              closeDialog();
            } else if (btn) {
              //: 失败 → 留在弹框里，让用户看到错误提示再决定
              btn.disabled = false;
              btn.textContent = '删除';
            }
          }
        }
      ]
    });
  }

  /**
   * 真删一条配置（确认之后才走到这里）。
   *
   * @param {object} item - ``state.items`` 里的一项
   * @returns {Promise<boolean>} 成功 ``true``
   */
  async function deleteConfig(item) {
    const result = await P.callMulti('deleteConfig', [item.kind, item.id]);

    if (!result.ok) {
      //: 桥接层调用失败（方法不存在 / 通道断了 / 缺多参能力）
      showError('删除失败：' + (result.missing
        ? '桥接暂时不支持带两个参数的调用（需要 bridge.js 的 callWith）。' +
          '请在 Qt 版配置页删除。'
        : String(result.error && result.error.message || result.error)));
      return false;
    }

    const data = result.data || {};
    if (!data.ok) {
      //: 后端 message 是给用户看的，直接用
      showError('删除失败：' + (data.message || data.reason || '未知原因'));
      return false;
    }

    // ── 成功：从本地状态移除并重渲染 ──
    state.items = state.items.filter(function (it) {
      return !(it.kind === item.kind && it.id === item.id);
    });
    //: 「查看」弹框如果正看着这条，一起关掉（2026-11-04 起查看也是弹框）
    if (DIALOG_STATE.root && DIALOG_STATE.root.dataset.configId === item.id) {
      closeDialog();
    }
    renderRows();
    showOk('已删除「' + (item.name || item.id) + '」');
    return true;
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
