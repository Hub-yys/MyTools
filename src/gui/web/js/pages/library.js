/* ══════════════════════════════════════════════════════════════════════════
   pages/library.js —— 资源库（鸣潮图鉴）

   **P2 重写**。P1 版本是明确的占位页（"图鉴数据量大，需要分页 + 虚拟滚动"）。

   ## Qt 版是什么

   ``src/gui/library_interface.py``（444 行）三个区块：

   .. code:: text

     ① 角色       圆形头像 + 名字 +（属性/武器小字）        AVATAR_SIZE=64
     ② 声骸套装   图标 + 名称 + 逐条套装效果 + 收录情况      SET_CARD_WIDTH=640
     ③ 声骸图鉴   图标 + 名字 + 技能说明

   数据**全部读自** ``src/core/data/*.json``（经 ``core.game_data`` 载入）：
   61 个角色 / 37 套套装 / 187 个声骸 / 123 把武器。

   ## 数据量到底多大（这决定要不要虚拟滚动）

   实测：角色 61 + 套装 37 + 声骸 187。**总共不到 300 项**，一次全渲染
   完全没问题（Chromium 渲染 300 个节点是毫秒级）。P1 的注释里
   "上万条"是**错的** —— 那是把抽卡记录（``gacha_history.json`` 977KB）
   和图鉴搞混了。

   所以这里**不分页、不虚拟滚动**，一次渲染 + 前端过滤。真的变成几千条时
   再加虚拟滚动才有意义（那时也是换 ``.map`` 的事，结构不用动）。

   ## 双态

   ``web_bridge.py`` 没有读图鉴的方法，而且 ``assets/game/`` 也没挂到
   ``media_server``（图标的 URL 出不来）。所以：

   * 有 ``getLibraryData()`` + 图标 URL → 完整图鉴（头像/套装图标/声骸图标）
   * 没有 → 明确提示 + 显示「数据规模/来源」自检面板

   接口到位自动升级。图标拿不到时用**首字兜底**（不显示破图）。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  if (!window.App) {
    console.error('[library] app.js 没先加载');
    return;
  }

  if (!window.Pages) {
    console.error('[library] _shared.js 没先加载');
    return;
  }

  const P = window.Pages;
  const App = window.App;

  /** 四个区块 */
  const TABS = [
    { value: 'characters', label: '角色' },
    { value: 'echoSets', label: '声骸套装' },
    { value: 'echoes', label: '声骸图鉴' },
    { value: 'weapons', label: '武器' }
  ];

  const state = {
    available: false,
    assetsAvailable: false,
    tab: 'characters',
    keyword: '',
    data: { characters: [], echoSets: [], echoes: [], weapons: [], meta: {} },
    dom: {}
  };

  P.ready(function () {
    App.registerPage('library', renderLibrary);
  });

  // ════════════════════════════════════════════════════════════════════════
  //  渲染
  // ════════════════════════════════════════════════════════════════════════
  async function renderLibrary(section, app) {
    await load();

    const total = state.data.characters.length +
                  state.data.echoSets.length +
                  state.data.echoes.length;

    const head = P.pageHead({
      title: '资源库',
      subtitle: state.available
        ? '鸣潮图鉴：' + state.data.characters.length + ' 个角色 · ' +
          state.data.echoSets.length + ' 套套装 · ' +
          state.data.echoes.length + ' 个声骸'
        : '鸣潮图鉴：角色 / 声骸套装 / 声骸'
    });
    head.actions.appendChild(P.button('刷新', {
      icon: 'HISTORY',
      size: 'sm',
      onClick: function () { reload(); }
    }));
    section.appendChild(head.head);

    // ── 降级提示 ──
    if (!state.available) {
      section.appendChild(P.notice(
        '<b>图鉴数据接口未接入</b>。数据在 <code>src/core/data/*.json</code>' +
        '（经 <code>core.game_data</code> 载入），图标在 <code>assets/game/</code>。' +
        '需要 Python 侧暴露 <code>getLibraryData()</code>，并把 ' +
        '<code>assets/game/{avatars,echo_sets,echoes,weapons}</code> 挂到 ' +
        '<code>media_server</code> 才能在页面里显示。',
        'warn'
      ));
    } else if (!state.assetsAvailable) {
      //: ★ 后端明确告诉过我们素材可能没有（assets/game 不进仓库）——照实说
      section.appendChild(P.notice(
        '<b>美术素材缺失</b>：<code>assets/game/</code> 下没找到图片，' +
        '所以图标会显示成首字占位。数据本身是完整的。' +
        '跑 <code>tools/fetch_wuwa_assets.py</code> 可以把素材拉下来。',
        'warn'
      ));
    }

    // ── 页签 + 搜索 ──
    const bar = P.el('div', { class: 'result-bar' });
    const segHost = P.el('div');
    segHost.appendChild(P.segmented(
      TABS.map(function (t) {
        const list = state.data[t.value] || [];
        return { value: t.value, label: t.label + '（' + list.length + '）' };
      }),
      state.tab,
      function (value) {
        state.tab = value;
        state.keyword = '';
        if (state.dom.searchInput) state.dom.searchInput.value = '';
        renderBody();
      }
    ));
    bar.appendChild(segHost);

    const search = P.el('div', { class: 'search' });
    const searchIcon = P.el('span', { class: 'nav-icon' });
    const mask = App.icon('DOCUMENT');
    searchIcon.style.maskImage = mask;
    searchIcon.style.webkitMaskImage = mask;
    searchIcon.style.backgroundColor = 'currentColor';
    search.appendChild(searchIcon);
    const input = P.el('input', {
      type: 'search',
      placeholder: '搜索…',
      onInput: function () {
        state.keyword = input.value.trim().toLowerCase();
        renderBody();
      }
    });
    search.appendChild(input);
    bar.appendChild(search);
    section.appendChild(bar);

    // ── 内容区 ──
    const body = P.el('div', { id: 'library-body' });
    section.appendChild(body);

    state.dom.body = body;
    state.dom.searchInput = input;

    if (state.available && total === 0) {
      body.appendChild(P.panel({
        padding: '26px',
        body: P.empty('图鉴是空的',
          '接口返回了但内容是空的 —— 检查 data/ 目录下的游戏数据 JSON。',
          'LIBRARY')
      }));
    } else if (state.available) {
      renderBody();
    } else {
      body.appendChild(buildSelfCheck());
    }
  }

  // ────────────────────────────────────────────────────────────────────────
  //  数据
  // ────────────────────────────────────────────────────────────────────────
  async function load() {
    const result = await P.call('getLibraryData');
    if (!result.ok || !result.data || typeof result.data !== 'object') {
      state.available = false;
      return;
    }

    const data = result.data;
    state.available = true;
    state.assetsAvailable = data.assetsAvailable !== false;

    state.data.characters = Array.isArray(data.characters) ? data.characters : [];
    state.data.echoSets = Array.isArray(data.echoSets) ? data.echoSets : [];
    state.data.weapons = Array.isArray(data.weapons) ? data.weapons : [];
    state.data.meta = data.meta || data.dataMeta || data.counts || {};

    // ── ★ 声骸是「按档位分组」给的（echoesByCost: {"4":[..],"3":[..],"1":[..]}）──
    //
    // 为什么不能直接 Array 化：档位是**有意义的信息**（4C/3C/1C 决定词条池），
    // 合并成一个平表会把 cost 丢掉，界面上就得靠每条的 cost 字段再猜一遍。
    // 这里拍平成列表，但**保留 cost 并在界面上标出来**，并按 4→3→1 排序。
    const echoes = [];
    const byCost = data.echoesByCost || data.echoes || {};
    if (Array.isArray(byCost)) {
      //: 万一后端改成直接给数组
      for (const item of byCost) echoes.push(item);
    } else {
      for (const cost of ['4', '3', '1']) {
        const list = Array.isArray(byCost[cost]) ? byCost[cost] : [];
        for (const item of list) {
          echoes.push(Object.assign({ cost: Number(cost) }, item));
        }
      }
      //: 后端以后加了别的档位也别丢
      for (const key of Object.keys(byCost)) {
        if (['4', '3', '1'].indexOf(key) >= 0) continue;
        const list = Array.isArray(byCost[key]) ? byCost[key] : [];
        for (const item of list) echoes.push(item);
      }
    }
    state.data.echoes = echoes;
  }

  async function reload() {
    await load();
    const section = document.getElementById('page-library');
    if (!section) return;
    //: 整页重渲染（懒渲染标记要清掉）
    section.dataset.rendered = '0';
    section.innerHTML = '';
    await renderLibrary(section, App);
    section.dataset.rendered = '1';
  }

  // ────────────────────────────────────────────────────────────────────────
  //  内容分发
  // ────────────────────────────────────────────────────────────────────────
  function renderBody() {
    const host = state.dom.body;
    if (!host) return;
    P.fill(host, null);

    if (state.tab === 'characters') renderCharacters(host);
    else if (state.tab === 'echoSets') renderEchoSets(host);
    else if (state.tab === 'weapons') renderWeapons(host);
    else renderEchoes(host);
  }

  // ── ① 角色 ──
  function renderCharacters(host) {
    const keyword = state.keyword;
    const rows = state.data.characters.filter(function (c) {
      if (!keyword) return true;
      return (String(c.name) + ' ' + String(c.element) + ' ' + String(c.weapon))
        .toLowerCase().indexOf(keyword) >= 0;
    });

    host.appendChild(resultBar(rows.length, state.data.characters.length));
    if (!rows.length) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty('没有匹配的角色', '换个关键词试试。', 'LIBRARY')
      }));
      return;
    }

    const grid = P.el('div', { class: 'avatar-grid' });
    for (const item of rows) {
      grid.appendChild(avatarTile(item));
    }
    host.appendChild(grid);
  }

  function avatarTile(item) {
    const tile = P.el('div', {
      class: 'avatar-tile',
      title: [item.name, item.element, item.weapon, item.rarity
        ? item.rarity + ' 星' : ''].filter(Boolean).join(' · ')
    });

    const round = P.el('div', {
      class: 'avatar-round',
      dataset: { rarity: String(item.rarity || '') }
    });
    if (linkOf(item)) {
      const img = P.el('img', { src: linkOf(item), alt: '', loading: 'lazy' });
      //: 加载失败 → 首字兜底（图鉴图可能没拉全）
      img.addEventListener('error', function () {
        round.innerHTML = '';
        round.textContent = (item.name || '?').slice(0, 1);
      }, { once: true });
      round.appendChild(img);
    } else {
      round.textContent = (item.name || '?').slice(0, 1);
    }
    tile.appendChild(round);

    tile.appendChild(P.el('div', { class: 'avatar-name', text: item.name || '' }));

    const meta = [item.element, item.weapon].filter(Boolean).join(' · ');
    if (meta) {
      tile.appendChild(P.el('div', { class: 'avatar-meta', text: meta }));
    }
    return tile;
  }

  // ── ② 声骸套装 ──
  function renderEchoSets(host) {
    const keyword = state.keyword;
    const rows = state.data.echoSets.filter(function (s) {
      if (!keyword) return true;
      const effects = Array.isArray(s.effects)
        ? s.effects.map(function (e) { return e.text || ''; }).join(' ')
        : '';
      return (String(s.name) + ' ' + effects).toLowerCase().indexOf(keyword) >= 0;
    });

    host.appendChild(resultBar(rows.length, state.data.echoSets.length));
    if (!rows.length) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty('没有匹配的套装', '换个关键词试试。', 'LIBRARY')
      }));
      return;
    }

    const grid = P.el('div', { class: 'set-grid' });
    for (const item of rows) {
      grid.appendChild(setCard(item));
    }
    host.appendChild(grid);
  }

  function setCard(item) {
    const card = P.el('div', { class: 'card-glass set-card' });

    const iconBox = P.el('div', { class: 'set-icon' });
    if (linkOf(item)) {
      const img = P.el('img', { src: linkOf(item), alt: '', loading: 'lazy' });
      img.addEventListener('error', function () {
        iconBox.innerHTML = '';
        iconBox.textContent = (item.name || '?').slice(0, 1);
      }, { once: true });
      iconBox.appendChild(img);
    } else {
      iconBox.textContent = (item.name || '?').slice(0, 1);
    }
    card.appendChild(iconBox);

    const body = P.el('div', { class: 'set-body' });

    const nameRow = P.el('div', { class: 'set-name-row' }, [
      P.el('div', { class: 'set-name', text: item.name || '' })
    ]);
    if (item.version) {
      nameRow.appendChild(P.el('span', {
        class: 'set-version',
        text: 'v' + item.version
      }));
    }
    body.appendChild(nameRow);

    //: 套装效果逐条（「2件套：攻击力提升10%」）
    const effects = Array.isArray(item.effects) ? item.effects : [];
    if (effects.length) {
      for (const effect of effects) {
        const text = typeof effect === 'string'
          ? effect
          : (effect.pieces ? effect.pieces + '件套：' : '') + (effect.text || '');
        if (!text) continue;
        body.appendChild(P.el('div', { class: 'set-effect', text: text }));
      }
    } else {
      body.appendChild(P.el('div', {
        class: 'set-effect',
        style: 'color:var(--faint)',
        text: '（这套的套装效果还没收录）'
      }));
    }

    //: 收录情况（这套下有几个声骸）
    const echoCount = Number(item.echoCount || (Array.isArray(item.echoes)
      ? item.echoes.length : 0));
    if (echoCount) {
      body.appendChild(P.el('div', {
        class: 'echo-sub',
        style: 'margin-top:6px',
        text: '收录 ' + echoCount + ' 个声骸'
      }));
    }

    card.appendChild(body);
    return card;
  }

  // ── ③ 声骸图鉴 ──
  function renderEchoes(host) {
    const keyword = state.keyword;
    const rows = state.data.echoes.filter(function (e) {
      if (!keyword) return true;
      //: ★ 必须把 stats（主词条）也纳入搜索。
      //: 只搜 name/skill 的话，用户搜「暴击」几乎什么都搜不到 ——
      //: 「暴击」是**主词条**（stats），不是技能说明里的词。实测只命中 1 条，
      //: 而用户想找的显然是「能出暴击词条的声骸」。
      const haystack = [
        e.name,
        e.cost,
        e.cost ? e.cost + 'C' : '',
        e.skill,
        Array.isArray(e.stats) ? e.stats.join(' ') : ''
      ].join(' ').toLowerCase();
      return haystack.indexOf(keyword) >= 0;
    });

    host.appendChild(resultBar(rows.length, state.data.echoes.length));
    if (!rows.length) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty('没有匹配的声骸', '换个关键词试试。', 'LIBRARY')
      }));
      return;
    }

    const grid = P.el('div', { class: 'echo-grid' });
    for (const item of rows) {
      grid.appendChild(echoRow(item));
    }
    host.appendChild(grid);
  }

  function echoRow(item) {
    const row = P.el('div', {
      class: 'card echo-row',
      title: item.skill || item.name || ''
    });

    const iconBox = P.el('div', { class: 'echo-icon' });
    if (linkOf(item)) {
      const img = P.el('img', { src: linkOf(item), alt: '', loading: 'lazy' });
      img.addEventListener('error', function () {
        iconBox.innerHTML = '';
        iconBox.textContent = (item.name || '?').slice(0, 1);
      }, { once: true });
      iconBox.appendChild(img);
    } else {
      iconBox.textContent = (item.name || '?').slice(0, 1);
    }
    row.appendChild(iconBox);

    const body = P.el('div', { class: 'echo-body' }, [
      P.el('div', { class: 'echo-name', text: item.name || '' })
    ]);

    const sub = [];
    if (item.cost) sub.push(item.cost + 'C');
    if (item.cooldown) sub.push('CD ' + item.cooldown);
    if (item.setName) sub.push(item.setName);
    if (sub.length) {
      body.appendChild(P.el('div', { class: 'echo-sub', text: sub.join(' · ') }));
    }

    //: 主词条（这就是"搜索为什么命中"的答案，也是强化筛选用到的字段）
    const stats = Array.isArray(item.stats) ? item.stats : [];
    if (stats.length) {
      body.appendChild(P.el('div', {
        class: 'echo-sub',
        style: 'white-space:normal',
        title: '主词条：' + stats.join('、'),
        text: '词条 ' + (stats.length > 3
          ? stats.slice(0, 3).join('、') + ' 等 ' + stats.length + ' 种'
          : stats.join('、'))
      }));
    }

    row.appendChild(body);
    return row;
  }

  // ── ④ 武器 ──
  function renderWeapons(host) {
    const keyword = state.keyword;
    const rows = state.data.weapons.filter(function (w) {
      if (!keyword) return true;
      return (String(w.name) + ' ' + String(w.type) + ' ' + String(w.rarity))
        .toLowerCase().indexOf(keyword) >= 0;
    });

    host.appendChild(resultBar(rows.length, state.data.weapons.length));
    if (!rows.length) {
      host.appendChild(P.panel({
        padding: '26px',
        body: P.empty('没有匹配的武器', '换个关键词试试。', 'LIBRARY')
      }));
      return;
    }

    const grid = P.el('div', { class: 'echo-grid' });
    for (const item of rows) {
      grid.appendChild(weaponRow(item));
    }
    host.appendChild(grid);
  }

  function weaponRow(item) {
    const row = P.el('div', {
      class: 'card echo-row',
      title: [item.name, item.type, item.rarity ? item.rarity + ' 星' : '']
        .filter(Boolean).join(' · ')
    });

    const iconBox = P.el('div', { class: 'echo-icon' });
    if (linkOf(item)) {
      const img = P.el('img', { src: linkOf(item), alt: '', loading: 'lazy' });
      img.addEventListener('error', function () {
        iconBox.innerHTML = '';
        iconBox.textContent = (item.name || '?').slice(0, 1);
      }, { once: true });
      iconBox.appendChild(img);
    } else {
      iconBox.textContent = (item.name || '?').slice(0, 1);
    }
    row.appendChild(iconBox);

    const body = P.el('div', { class: 'echo-body' }, [
      P.el('div', { class: 'echo-name', text: item.name || '' })
    ]);
    const sub = [];
    if (item.type) sub.push(item.type);
    if (item.rarity) sub.push(item.rarity + ' 星');
    if (sub.length) {
      body.appendChild(P.el('div', { class: 'echo-sub', text: sub.join(' · ') }));
    }
    row.appendChild(body);
    return row;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  小工具
  // ────────────────────────────────────────────────────────────────────────

  /**
   * 取图标 URL。
   *
   * 后端可能给 ``iconUrl``（完整 HTTP URL），也可能只给 ``icon``
   * （``avatars/绯雪.png`` 这种相对路径）。后者需要 media_server 挂载
   * ``/game/`` 才能加载 —— 没挂就是加载失败 → 首字兜底。
   */
  function linkOf(item) {
    return item.iconUrl || item.avatarUrl || item.url || '';
  }

  function resultBar(count, total) {
    const bar = P.el('div', { class: 'result-bar' });
    bar.appendChild(P.el('div', {
      class: 'result-count',
      text: count === total
        ? '共 ' + total + ' 项'
        : '匹配 ' + count + ' / ' + total + ' 项'
    }));
    return bar;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  自检面板（降级时显示 —— 至少让人知道数据在哪、有多少）
  // ────────────────────────────────────────────────────────────────────────
  function buildSelfCheck() {
    const rows = [
      ['角色', 'core.game_data.CHARACTERS', 'assets/game/avatars/'],
      ['声骸套装', 'core.game_data.ECHO_SETS', 'assets/game/echo_sets/'],
      ['声骸', 'core.game_data.ECHOES_BY_COST', 'assets/game/echoes/'],
      ['武器', 'core.game_data.WEAPONS', 'assets/game/weapons/']
    ];

    const grid = P.el('div', { class: 'detail-grid' });
    for (const [label, source, icons] of rows) {
      grid.appendChild(P.el('div', { class: 'detail-key', text: label }));
      grid.appendChild(P.el('div', {
        class: 'detail-val',
        text: source + '  ·  图标 ' + icons
      }));
    }

    return P.panel({
      title: '图鉴数据源',
      subtitle: '数据是现成的，缺的只是「页面拿到它」的那条通道',
      body: [
        grid,
        P.el('div', {
          class: 'detail-val',
          style: 'margin-top:14px;font-size:11.5px;color:var(--dim);line-height:1.7',
          text: '数据文件：src/core/data/*.json（wuwa_characters / wuwa_echo_sets / '
              + 'wuwa_echo_skills），由 core.game_data 在导入时载入内存。'
              + '接口就绪后，这里会变成可搜索的角色网格、套装卡、声骸图鉴三块。'
        })
      ]
    });
  }
})();
