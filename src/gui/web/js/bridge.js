/* ══════════════════════════════════════════════════════════════════════════
   bridge.js —— QWebChannel 封装

   ## 为什么需要这一层

   QWebChannel 生成的 JS 代理有几个坑，直接用很难受：

   1. **所有方法都是回调式**：``bridge.getTools(function(json){...})``
      —— 在 async 函数里没法 ``await``，嵌套三层就是回调金字塔。
   2. **返回值是 JSON 字符串**（见 ``src/core/web_bridge.py`` 的说明），
      每个调用点都要手动 ``JSON.parse`` + try/catch。
   3. **Python 推送事件**走的是 ``bridge.event.connect(fn)``，
      和「方法调用」混在一起，得自己分发。

   这一层把它们包成 Promise + 事件总线，页面代码就能写成：

   .. code:: js

     const tools = await Bridge.call('getTools');
     Bridge.on('logLine', ({text}) => appendLog(text));

   ## 加载时序

   ``qwebchannel.js`` 由 Qt 注入，它需要 ``qt.webChannelTransport``
   才能建立通道 —— 而 transport 是 Qt 在页面加载完成后才注入的。
   所以：**不能**在脚本顶层直接 ``new QWebChannel``，必须等
   ``window.onload``（或轮询探测 transport）。

   这里用「onload + 轮询兜底」：onload 时试一次，失败就每 50ms 再试，
   直到通道建立或超时（8 秒）。超时后 ``Bridge.ready`` 会 reject，
   页面显示错误提示而不是白屏。
   ══════════════════════════════════════════════════════════════════════════ */

(function () {
  'use strict';

  /** 通道建立的超时（毫秒）*/
  const TIMEOUT_MS = 8000;
  /** 轮询间隔（毫秒）*/
  const POLL_MS = 50;

  /** Python 侧 bridge 对象（通道建立后才有）*/
  let _bridge = null;
  /** 事件订阅表：{eventName: Set<fn>} */
  const _handlers = new Map();
  /** 通配订阅（收所有事件）*/
  const _anyHandlers = new Set();
  /** ready 的 resolve/reject */
  let _resolveReady = null;
  let _rejectReady = null;
  /** 是否已连上 */
  let _connected = false;

  /** 通道建立完成的 Promise —— 所有 call() 都等它 */
  const readyPromise = new Promise((resolve, reject) => {
    _resolveReady = resolve;
    _rejectReady = reject;
  });

  // ════════════════════════════════════════════════════════════════════════
  //  内部：分发一个事件
  // ════════════════════════════════════════════════════════════════════════
  function dispatch(name, data) {
    // 1) 按名字订阅的
    const set = _handlers.get(name);
    if (set) {
      for (const fn of Array.from(set)) {
        try {
          fn(data, name);
        } catch (err) {
          console.error('[bridge] 事件处理出错:', name, err);
        }
      }
    }
    // 2) 通配订阅的
    for (const fn of Array.from(_anyHandlers)) {
      try {
        fn(name, data);
      } catch (err) {
        console.error('[bridge] 通配处理器出错:', name, err);
      }
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  内部：拿到一个 Python 方法的 Promise 版本
  // ════════════════════════════════════════════════════════════════════════

  /**
   * 组装回调：把 Python 返回的 JSON 字符串解析成 JS 对象。
   *
   * @param {string} method - 方法名（只用来打日志）
   * @param {function} resolve
   */
  function makeCallback(method, resolve) {
    return function (raw) {
      // Python 侧统一返回 JSON 字符串；空值当作 null
      if (raw === undefined || raw === null || raw === '') {
        resolve(null);
        return;
      }
      if (typeof raw !== 'string') {
        // 万一哪天 Python 改成直接返回对象，也别炸
        resolve(raw);
        return;
      }
      try {
        resolve(JSON.parse(raw));
      } catch (err) {
        console.warn('[bridge] 返回的不是 JSON:', method, raw);
        resolve(raw);
      }
    };
  }

  /**
   * ★ 内部核心：调用 Python 方法，**按实参个数**精确匹配 Slot 签名。
   *
   * ## ⚠⚠ 为什么必须按个数传（2026-11-02 踩到的真 bug）
   *
   * ``QWebChannel`` 是按 **JS 实参个数**去 Python 侧找签名匹配的 Slot。
   * 少传/多传一个都不会报错 —— 只会静默失败：
   *
   * .. code:: text
   *
   *     No candidates found for "deleteConfig" with 1 arguments
   *
   * 而 ``deleteConfig`` 是 ``@Slot(str, str, result=str)`` ——
   * 第一版 ``Bridge.call('deleteConfig', kind)`` 只传 1 个参数，
   * 于是**永远调不通，而且没有任何异常**（page-converter 报的）。
   *
   * 所以这条路径改成：``args`` 数组原样展开 + 末尾追加回调。
   * 调用方对每个方法传**正好**那么多参数。
   *
   * @param {string} method
   * @param {Array} args - 位置参数（不含回调）
   * @returns {Promise<*>}
   */
  function callRaw(method, args) {
    return new Promise((resolve, reject) => {
      if (!_bridge) {
        reject(new Error('bridge 未连接'));
        return;
      }
      const fn = _bridge[method];
      if (typeof fn !== 'function') {
        reject(new Error('bridge 上没有方法: ' + method));
        return;
      }
      try {
        const cb = makeCallback(method, resolve);
        //: ★ 展开参数 + 末尾追加回调 —— 个数必须和 @Slot 声明一致
        fn.apply(_bridge, (args || []).concat([cb]));
      } catch (err) {
        reject(err);
      }
    });
  }

  // ════════════════════════════════════════════════════════════════════════
  //  内部：连接
  // ════════════════════════════════════════════════════════════════════════
  function connect() {
    if (_connected) return;
    if (typeof QWebChannel === 'undefined') {
      return;   // qwebchannel.js 还没解析完
    }
    if (typeof qt === 'undefined' || !qt.webChannelTransport) {
      return;   // Qt 还没注入 transport
    }

    try {
      new QWebChannel(qt.webChannelTransport, function (channel) {
        _bridge = channel.objects.bridge;
        if (!_bridge) {
          _rejectReady(new Error('通道里没有 bridge 对象'));
          return;
        }
        _connected = true;

        // Python 侧的 event Signal(String) → 这里解析后分发
        _bridge.event.connect(function (raw) {
          let payload;
          try {
            payload = JSON.parse(raw);
          } catch (err) {
            console.warn('[bridge] 事件不是 JSON:', raw);
            return;
          }
          if (!payload || typeof payload !== 'object') return;
          dispatch(payload.name, payload.data || {});
        });

        // 每个专用 Signal 也接一下 —— 方便直接绑 .taskStarted 之类
        // （主要是调试时用，页面代码推荐走 event / on）
        _resolveReady(Bridge);
      });
    } catch (err) {
      _rejectReady(err);
    }
  }

  // ════════════════════════════════════════════════════════════════════════
  //  对外 API
  // ════════════════════════════════════════════════════════════════════════
  const Bridge = {

    /** 通道建立完成（Promise）*/
    get ready() {
      return readyPromise;
    },

    /** 通道是否已连上 */
    get connected() {
      return _connected;
    },

    /**
     * 调用 Python 侧**只收 0 或 1 个参数**的 bridge 方法。
     *
     * @param {string} method - 方法名（camelCase，和 web_bridge.py 一致）
     * @param {*} [arg] - 单个参数
     * @returns {Promise<*>} 解析后的 JS 对象
     *
     * @example
     *   await Bridge.call('getTools');
     *   await Bridge.call('runTask', 'echo_enhance');
     */
    call(method, arg) {
      return readyPromise.then(function () {
        return callRaw(method, arg === undefined ? [] : [arg]);
      });
    },

    /**
     * ★ 调用**多参数**的 Python bridge 方法。
     *
     * ## 什么时候必须用它
     *
     * ``QWebChannel`` 按 **JS 实参个数**精确匹配 Slot 签名，
     * 个数不对就静默失败（只在控制台留一句
     * ``No candidates found for "xxx" with N arguments``）。
     *
     * 所以凡是 ``@Slot`` 声明了 2 个以上参数的（比如
     * ``deleteConfig(kind, id)`` = ``@Slot(str, str, result=str)``），
     * **必须**用这个，参数个数要和 Python 声明**完全一致**。
     *
     * @param {string} method
     * @param {Array} args - 位置参数数组（不含回调，会自动追加）
     * @returns {Promise<*>}
     *
     * @example
     *   await Bridge.callWith('deleteConfig', ['loadout', 'abc123']);
     */
    callWith(method, args) {
      return readyPromise.then(function () {
        return callRaw(method, Array.isArray(args) ? args : [args]);
      });
    },

    /**
     * 订阅一个事件。
     *
     * @param {string} name - 事件名（logLine / progress / taskStarted / ...）
     * @param {function} fn - (data, name) => void
     * @returns {function} 退订函数
     */
    on(name, fn) {
      if (typeof fn !== 'function') return function () {};
      let set = _handlers.get(name);
      if (!set) {
        set = new Set();
        _handlers.set(name, set);
      }
      set.add(fn);
      return function off() {
        set.delete(fn);
        if (set.size === 0) _handlers.delete(name);
      };
    },

    /**
     * 订阅**所有**事件（DSH 风格的总线）。
     *
     * @param {function} fn - (name, data) => void
     * @returns {function} 退订函数
     */
    subscribe(fn) {
      if (typeof fn !== 'function') return function () {};
      _anyHandlers.add(fn);
      return function off() {
        _anyHandlers.delete(fn);
      };
    },

    /** 手工触发一个本地事件（页面内部通讯用，Python 侧收不到）*/
    emit(name, data) {
      dispatch(name, data || {});
    }
  };

  // ════════════════════════════════════════════════════════════════════════
  //  启动：onload 后试连，失败就轮询
  // ════════════════════════════════════════════════════════════════════════
  function boot() {
    const started = Date.now();

    function tick() {
      connect();
      if (_connected) return;

      if (Date.now() - started > TIMEOUT_MS) {
        const msg = typeof QWebChannel === 'undefined'
          ? 'qwebchannel.js 没有加载（qrc 资源不可用？）'
          : 'Qt 没有注入 webChannelTransport（QWebChannel 没注册？）';
        console.error('[bridge] 连接超时：' + msg);
        _rejectReady(new Error(msg));
        return;
      }
      setTimeout(tick, POLL_MS);
    }

    tick();
  }

  if (document.readyState === 'complete') {
    boot();
  } else {
    window.addEventListener('load', boot, { once: true });
  }

  //: 挂到全局（app.js / pages/*.js 直接用）
  window.Bridge = Bridge;

  //: ready 失败时别让控制台报 unhandled rejection
  readyPromise.catch(function (err) {
    console.error('[bridge] 通道建立失败:', err && err.message);
  });
})();
