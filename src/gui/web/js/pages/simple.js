/* ══════════════════════════════════════════════════════════════════════════
   pages/simple.js —— 「检查更新」/「消息通知」两个简单占位页

   这两个页面在 Qt 版里有实现，但都比较重（更新走网络 + 下载安装包；
   通知要读写本地库），P1 不搬，只留占位。

   ## 为什么单独一个文件

   ``library.js`` 里的 ``__stubPage`` 是给「资源库」那种大页面用的；
   这两页内容更少，也没「待迁移能力」清单，单独写更清爽。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  if (!window.App) {
    console.error('[simple] app.js 没先加载');
    return;
  }

  // ────────────────────────────────────────────────────────────────────────
  //  检查更新
  // ────────────────────────────────────────────────────────────────────────
  window.App.registerPage('update', function (section, app) {
    const head = document.createElement('div');
    head.className = 'page-head';
    head.innerHTML =
      '<div class="page-head-text">' +
      '  <div class="page-title">检查更新</div>' +
      '  <div class="page-subtitle">当前版本 v' +
      escapeHtml(app.info.version) + '</div>' +
      '</div>';
    section.appendChild(head);

    const card = document.createElement('div');
    card.className = 'card-glass';
    card.style.padding = '26px';
    card.innerHTML =
      '<div class="empty" style="padding:26px 16px">' +
      '  <div class="empty-title">更新检查</div>' +
      '  <div class="empty-hint">' +
      '    Python 侧的更新逻辑在 <span class="selectable" ' +
      '    style="font-family:monospace">src/core/updater.py</span>，' +
      '    已经能用了。页面这侧等 P2 接一个 ' +
      '    <span class="selectable" style="font-family:monospace">checkUpdate()</span> ' +
      '    / <span class="selectable" style="font-family:monospace">downloadUpdate()</span>。' +
      '  </div>' +
      '  <div class="empty-hint" style="margin-top:10px">' +
      '    启动时静默检查更新（<span class="selectable" ' +
      '    style="font-family:monospace">_maybe_auto_check_update</span>）在 Qt 版里' +
      '    会往侧栏写黄字 —— Web 版会改成往 "检查更新" 导航项上挂 ' +
      '    <span class="selectable" style="font-family:monospace">.nav-badge</span>。' +
      '  </div>' +
      '</div>';
    section.appendChild(card);
  });

  // ────────────────────────────────────────────────────────────────────────
  //  消息通知
  // ────────────────────────────────────────────────────────────────────────
  window.App.registerPage('notice', function (section) {
    //: ★★★ 2026-11-03 用户圈图：
    //:   「工具不自动展开，而且这个箭头图标不是向右而是向下吧，
    //:     这里会变成可清空的列表」
    //:
    //: 圈的是**说明文字那一整段**（"通知的存储与清理在
    //: src/core/notifications.py（Qt 版 notify_page.py）。P2 接
    //: getNotices() 之后这里会变成可清空的列表。"）——
    //: 那是给开发者看的实现说明，不该出现在界面上。
    //:
    //: 副标题「最近 10 条通知，每天自动清理」**保留** ——
    //: 那是用户可见的功能描述（告诉他这里会有多少条、怎么清理）。
    const head = document.createElement('div');
    head.className = 'page-head';
    head.innerHTML =
      '<div class="page-head-text">' +
      '  <div class="page-title">消息通知</div>' +
      '  <div class="page-subtitle">最近 10 条通知，每天自动清理</div>' +
      '</div>';
    section.appendChild(head);

    const card = document.createElement('div');
    card.className = 'card-glass';
    card.style.padding = '26px';
    card.innerHTML =
      '<div class="empty" style="padding:26px 16px">' +
      '  <div class="empty-title">还没有通知</div>' +
      '</div>';
    section.appendChild(card);
  });

  function escapeHtml(text) {
    return String(text == null ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }
})();
