# -*- coding: utf-8 -*-
"""「查询角色练度」工具页 —— 手机号 + 验证码登录，像官方那样展示角色与声骸。

## ★★★ 完整流程（2026-10-03 实测跑通）

    ┌─ ① 手机号 + 短信验证码 → **APP 端登录**（source=android）→ token
    ├─ ② 取游戏角色  /gamer/role/list {gameId:3} → 特征码 + serverId
    ├─ ③ 换「数据令牌」/aki/roleBox/requestToken → accessToken
    └─ ④ 之后所有 /aki/ 请求**只带 b-at 头** → 角色列表 + 声骸详情

## 界面（对齐官方「共鸣者」卡片的展示方式）

    ┌─ ① 登录：特征码 / 手机号 / 验证码（各一行）+ 获取数据
    ├─ ② 账号概览：结晶波片 | 结晶单质 | 活跃度 | 游戏天数 | 联觉等级 | 解锁角色
    ├─ ③ **角色网格**：头像 + 等级 + 共鸣链 + 属性 + 名字（像官方那样）
    │     · 声骸没达标的角色**红框**标出来
    │     · 点角色 → 展开 5 个声骸明细（COST/等级/名/套装/主属性/副词条/有效数）
    └─ ④ 日志（后台写，默认折叠）

## 数据持久化

拉到的数据存 ``data/kuro_练度.json`` —— 重启后**直接显示上次结果**，
不用重新登录/重拉。登录后也会**自动拉一次**。
"""

from __future__ import annotations

import json
import logging
import time

from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    CardWidget,
    ComboBox,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    PushButton,
    ScrollArea,
    StrongBodyLabel,
    SubtitleLabel,
    TitleLabel,
)

from ....core import icon_cache, kuro_account, paths, tool_settings
from ....core import wuwa_guide
from ....core.categories import ToolCategory
from ....core.registry import registry
from ....core.tool_base import BaseTool

logger = logging.getLogger(__name__)

#: 工具 key
TOOL_KEY = "character_build"

#: 设置节名（记特征码 / 手机号）
SETTINGS_KEY = "character_build"

#: 手机号长度（大陆 11 位）
MOBILE_LEN = 11

#: 缓存文件名（用户数据目录）—— 数据持久化，重启直接显示
CACHE_NAME = "kuro_练度.json"

#: 角色格子尺寸（用户参考图：**头像 + 名字**）
#:
#: 用户："一个就展示所有共鸣者，展示不全，可以滑动"
#: → **单独一横行 + 横向滚动**，永远不换行（换行会把详情挤出屏幕）
TILE_SIZE = 72
TILE_W = 96
TILE_H = 132

#: 「达标」筛选下拉的选项
#:
#: 用户 2026-10-05："增加一个分类，等级（未满90级的）"
#: 用户 2026-10-05："40级的应该进**未练**的分类"
#:
#: ⚠ **「未练」= 拿不到声骸数据**（游戏里没装声骸）。
#: 实测 12 个没数据的角色**全是低等级**（Lv1/40/50/70）——
#: "没数据"是"没练"，**不是"达标"**。
FILTER_CHOICES = ("全部", "未达标", "达标", "未练", "未满90级")

#: 满级线（用户要的这个分类就是按它筛）
MAX_LEVEL = 90


def is_below_max_level(role: dict) -> bool:
    """角色是否**没满 90 级**（用户要的筛选分类）。

    ⚠ 缺字段 / 坏值 → **返回 False**（不把它算进"未满级"）。
    我第一版写成 ``int(level or 0) < MAX`` —— ``None``/``{}`` 都会变成 0，
    于是"没数据"被当成"0 级"混进筛选里（测试当场抓出来了）。
    """
    raw = (role or {}).get("level")
    if raw is None or raw == "":
        return False
    try:
        return int(raw) < MAX_LEVEL
    except (TypeError, ValueError):
        return False

#: ★ 不显示的角色 —— **漂泊者（主角）**
#:
#: ## 为什么排除（用户 2026-10-05："把漂泊者除开"）
#:
#: 主角是**必练**的（主线一直带着），不像别的角色那样"要不要练"需要判断；
#: 而且他那套声骸往往是最早配的，拿"达标"去卡他没有意义。
#:
#: ## ⚠ 语义：**彻底不显示**
#:
#: 我问过"要哪种"，用户明确选了「**彻底不显示（从列表里删掉）**」——
#: 所以是**整个从共鸣者列表里过滤掉**：卡片、详情、计数都不算他。
#:
#: （第一版我做成"还在列表里、只是不参与判定"，用户截图回来说
#: "漂泊者还是有" —— 那不是他要的。）
#:
#: ⚠ 按**名字**排除而不是 roleId —— 实测现在只有 1 个漂泊者
#: （``roleId=1310``，导电/迅刀），但主角以后可能出别的属性版本，
#: roleId 会变、名字不会。
EXCLUDED_ROLE_NAMES = frozenset({"漂泊者"})


def is_excluded(role: dict) -> bool:
    """该角色是否**不显示**（见 ``EXCLUDED_ROLE_NAMES``）。"""
    name = str((role or {}).get("roleName") or "").strip()
    return name in EXCLUDED_ROLE_NAMES


def visible_roles(role_list) -> list:
    """过滤掉不显示的角色（漂泊者）。"""
    return [r for r in (role_list or []) if not is_excluded(r)]


def _attr_map(detail: dict) -> dict[str, float]:
    """角色当前属性 → ``{属性名: 数值}``（取 ``roleAttributeList``）。

    ⚠ 官方推荐里的 ``%`` 值和这里的百分比是**同名同单位**，直接比；
    绝对值（生命/攻击）同理。
    """
    out: dict[str, float] = {}
    for item in (detail or {}).get("roleAttributeList") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("attributeName") or "").strip()
        val = wuwa_guide.parse_amount(item.get("attributeValue"))
        if name and val is not None:
            out[name] = val
    return out


def _meets(have: float, need: float, symbol: str) -> bool:
    """按官方给的比较符判断达标 —— 直接转发到 :mod:`src.core.wuwa_guide`。

    ⚠ 别在这儿再写一份 —— 那张符号表是**从官方 JS 挖出来的**
    （``4`` 是 ``>`` 不是 ``<=``，我第一版猜错过）。
    """
    return wuwa_guide.meets(have, need, symbol)


def _compare_standard(detail: dict, standard) -> list[str]:
    """★★ 拿**角色当前属性**跟**官方推荐**比，返回不达标的项。

    :param standard: :func:`src.core.wuwa_guide.fetch_recommend` 的返回
    :return: 例如 ``["暴击 55% 没到 70%", "暴击伤害 210% 没到 260%"]``

    ⚠ 比较方向看官方给的 ``symbol``（实测都是 ``>=``）——
    不写死"越大越好"，免得以后出个"越低越好"的属性就错了。
    """
    attrs = (standard or {}).get("attrs") or []
    if not attrs:
        return []
    current = _attr_map(detail)
    if not current:
        return []

    bad: list[str] = []
    for a in attrs:
        name = str(a.get("name") or "")
        need = a.get("value")
        have = current.get(name)
        if have is None or need is None:
            continue                           #: 面板里没这个属性 → 不比
        if not _meets(have, need, a.get("symbol") or "≥"):
            unit = a.get("unit") or ""
            bad.append(f"{name} {have:g}{unit} 没到 "
                       f"{a.get('symbol') or '≥'}{need:g}{unit}")
    return bad


def _recommended_set_counts(standard) -> dict[str, int]:
    """从官方标准里取**推荐的套装及件数**。

    ## 原始结构（实测，关键在"同名要去重"）

    ::

        千咲（3+2 混搭）:
            {"echoSet": 3, "texts": [... "命理崩毁之弦"]}
            {"echoSet": 2, "texts": [... "幽夜隐匿之帷"]}

        椿 / 维里奈（5 件套）:
            {"echoSet": 5, "texts": [... "轻云出月"]}
            {"echoSet": 2, "texts": [... "轻云出月"]}     ← ★ **同名！**

    ⚠⚠ 5 件套的角色会**列出两条同名记录**（``5`` 和 ``2``）——
    后一条只是"2 件套效果"的附带说明，**不是"再要 2 件"**。

    我第一版没去重，于是"椿"被算成 `{"轻云出月": 2}` →
    报"现在 ×5，推荐 ×2" —— **29 个角色全被误判**。

    → 正确做法：**同名取最大值**。
    """
    effects = (((standard or {}).get("echo") or {}).get("main") or {}) \
        .get("echoSetEffects") or []
    out: dict[str, int] = {}
    for e in effects:
        if not isinstance(e, dict):
            continue
        name = ""
        #: 优先中文名
        for t in e.get("texts") or []:
            if isinstance(t, dict) and t.get("language") == "zh-Hans" \
                    and t.get("name"):
                name = str(t["name"])
                break
        if not name:                           #: 退回第一个有名字的
            for t in e.get("texts") or []:
                if isinstance(t, dict) and t.get("name"):
                    name = str(t["name"])
                    break
        try:
            count = int(e.get("echoSet") or 0)
        except (TypeError, ValueError):
            count = 0
        if not name or count <= 0:
            continue
        #: ★ 同名取最大值（5 件套会同时给 5 和 2）
        out[name] = max(out.get(name, 0), count)
    return out


def _compare_echo_sets(items, standard) -> list[str]:
    """★★ 跟**官方推荐的套装组合**比（不是"必须统一"）。

    ## 为什么改（用户 2026-10-05 报的）

    千咲属性全绿却进了「未达标」—— 查下来是我那条**自己发明的**
    "套装不统一"规则误判::

        千咲实际:  命理崩毁之弦 ×3 + 幽夜隐匿之帷 ×2   ← 3+2 混搭
        官方推荐:  命理崩毁之弦 ×3 + 幽夜隐匿之帷 ×2   ← **一模一样**

    **3+2 是完全合法的配装**，官方攻略里就是这么推荐的。
    "不统一"根本不是问题 —— **对不上官方组合**才是。

    :return: 对不上时返回一条说明；对得上（或拿不到官方组合）返回 ``[]``
    """
    recommended = _recommended_set_counts(standard)
    if not recommended:
        return []                              #: 官方没给 → 不比，不瞎报

    actual: dict[str, int] = {}
    for x in items or []:
        name = str((x.get("fetterDetail") or {}).get("name") or "").strip()
        if name:
            actual[name] = actual.get(name, 0) + 1

    #: 组合一致 = 每个套装的数量都对得上（**顺序无关**）
    if actual == recommended:
        return []
    got = " + ".join(f"{k}×{v}" for k, v in sorted(actual.items()))
    want = " + ".join(f"{k}×{v}" for k, v in sorted(recommended.items()))
    return [f"套装搭配不符（现在 {got}，推荐 {want}）"]


def cache_file():
    """缓存文件位置（用户数据目录）。"""
    return paths.user_data_dir() / CACHE_NAME


# --------------------------------------------------------------------- 线程

class LoginThread(QThread):
    """后台 APP 端登录 + 换数据令牌 + **自动拉一次数据**。"""

    progress = Signal(str)
    succeeded = Signal(object)                 # Account
    failed = Signal(str)

    def __init__(self, mobile: str, code: str, feature_code: str = "",
                 parent=None):
        super().__init__(parent)
        self._mobile = mobile
        self._code = code
        self._feature = feature_code

    def run(self) -> None:                     # noqa: D102
        try:
            self.progress.emit("正在登录（APP 端）…")
            account = kuro_account.app_login_with_code(self._mobile,
                                                       self._code)
            kuro_account.save_account(account)
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")
            return
        self.succeeded.emit(account)


class FetchThread(QThread):
    """后台拉账号数据（基础 + 角色列表 + 声骸）。

    ## ★ 为什么要"边拉边存"（2026-10-03 实测教训）

    43 个角色 = **43 次网络请求**，实测要**十几到几十秒**。
    用户日志停在 `正在拉声骸详情（43 个角色）…` 之后就没下文 ——
    因为**没跑完就被关掉了**，`succeeded` 从没发出 → **缓存从没写**
    → 下次打开还是"没数据"。

    所以现在：
      * 每拉完**一个**角色就 ``progress.emit``（界面能看到进度在动）
      * 声骸详情是**逐步累积**的，中途被打断也**已经存了一部分**
      * ``partial`` 信号：拉到一半也能先把已有数据交给界面
    """

    progress = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str)
    #: ★ 阶段性成果（拉到一半也先给界面用）
    partial = Signal(object)

    def __init__(self, account, feature_code: str = "", parent=None):
        super().__init__(parent)
        self._account = account
        self._feature_code = (feature_code or "").strip()
        self._stop = False

    def stop(self) -> None:
        """请求中止（界面关掉时调）—— 循环会尽快退出并保存已拉到的。"""
        self._stop = True

    def run(self) -> None:                     # noqa: D102
        try:
            acc = self._account
            roles = acc.roles or []

            # ★★ 特征码：用户填了就以它为准（留空 = 用绑定的那个）
            role = None
            want = self._feature_code
            if want:
                role = next((r for r in roles
                             if str(r.get("roleId") or "").strip() == want),
                            None)
                if role is None:
                    role = kuro_account.resolve_role(acc.token, want)
                if role is None:
                    self.failed.emit(
                        f"查不到特征码 {want} 对应的角色。\n"
                        f"当前账号绑定的角色："
                        f"{[r.get('roleName') for r in roles] or '（无）'}")
                    return
            elif roles:
                role = next((r for r in roles
                             if str(r.get("gameId")) == "3"), roles[0])
            if role is None:
                self.failed.emit("没拿到任何游戏角色 —— 请先登录")
                return

            role_id = str(role.get("roleId"))
            server_id = str(role.get("serverId"))
            self.progress.emit(f"目标角色：{role.get('roleName') or role_id}"
                               f"（特征码 {role_id}）")

            self.progress.emit("正在换数据令牌…")
            data_token, _req = kuro_account.request_data_token(
                acc.token, role_id, server_id)
            acc.data_token = data_token
            acc.user_id = str(role.get("userId") or "")

            self.progress.emit("正在拉账号数据…")
            base = kuro_account.fetch_base_data(data_token, role_id,
                                                server_id)
            self.progress.emit("正在拉角色列表…")
            rd = kuro_account.fetch_role_data(data_token, role_id, server_id)
            role_list = (rd or {}).get("roleList") or []

            total = len(role_list)
            self.progress.emit(f"正在拉声骸详情（{total} 个角色）…")
            details: dict = {}
            for i, r in enumerate(role_list, 1):
                if self._stop:
                    self.progress.emit(f"已中止（拉到 {i - 1}/{total}）")
                    break
                cid = r.get("roleId")
                try:
                    details[str(cid)] = kuro_account.fetch_role_detail(
                        data_token, role_id, server_id, cid)
                except Exception:              # noqa: BLE001 - 单个失败不中断
                    continue
                # ★ 每拉几个就报一次进度 + 交给界面（中途关掉也不白拉）
                if i % 5 == 0 or i == total:
                    self.progress.emit(f"  声骸进度 {i}/{total}")
                    payload = self._payload(role, base, role_list, details)
                    save_cache(payload)
                    self.partial.emit(payload)

            payload = self._payload(role, base, role_list, details)
            save_cache(payload)
            acc.roles = roles
            try:
                kuro_account.save_account(acc)
            except Exception:                  # noqa: BLE001
                pass

            # ★★ 拉**官方推荐属性**（达标标准）—— 用户 2026-10-05 给的来源
            #
            # 攻略站是公开接口，不需要令牌；每个角色两次请求
            # （先列表拿 strategy_id，再详情拿 roleAttribute）。
            # ⚠ 查不到不该让整体失败（官方可能还没出新角色的攻略）。
            try:
                self.progress.emit(f"正在拉官方推荐标准（{total} 个角色）…")
                standards: dict = {}
                for i, r in enumerate(role_list, 1):
                    if self._stop:
                        break
                    cid = r.get("roleId")
                    try:
                        got = wuwa_guide.fetch_recommend(cid)
                    except Exception:          # noqa: BLE001
                        continue
                    if got.get("attrs"):
                        standards[str(cid)] = got
                    if i % 10 == 0 or i == total:
                        self.progress.emit(f"  推荐标准 {i}/{total}")
                        payload = self._payload(role, base, role_list,
                                                details, standards)
                        save_cache(payload)
                        self.partial.emit(payload)
                payload = self._payload(role, base, role_list, details,
                                        standards)
                save_cache(payload)
                self.progress.emit(
                    f"  推荐标准：{len(standards)}/{total} 个角色拿到")
            except Exception as exc:           # noqa: BLE001
                self.progress.emit(f"  推荐标准跳过：{exc}")

            # ★ 顺手把详情要用的图标下下来（**在后台线程里**，不卡界面）
            try:
                urls: list[str] = []
                for d in details.values():
                    urls.extend(icon_cache.collect_urls(d))
                for r in role_list:
                    if r.get("roleIconUrl"):
                        urls.append(r["roleIconUrl"])
                if urls:
                    self.progress.emit(f"正在缓存图标（{len(urls)} 个）…")
                    ok, bad = icon_cache.ensure_many(
                        urls, log=lambda m: self.progress.emit(m))
                    self.progress.emit(f"  图标缓存完成（{ok} 成功）")
            except Exception as exc:           # noqa: BLE001 - 少图不该失败
                self.progress.emit(f"  图标缓存跳过：{exc}")

            self.succeeded.emit(payload)
        except kuro_account.RoleNotFound as exc:
            self.failed.emit(str(exc))
        except Exception as exc:               # noqa: BLE001
            self.failed.emit(f"{type(exc).__name__}: {exc}")

    @staticmethod
    def _payload(role, base, role_list, details, standards=None) -> dict:
        return {
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "role": role, "base": base,
            "roleList": role_list, "details": details,
            #: ★ 官方推荐属性（每个角色的达标线）—— 见 ``wuwa_guide``
            "standards": standards or {},
        }


# --------------------------------------------------------------------- 缓存

def save_cache(payload: dict) -> None:
    """把拉到的数据落盘（重启后直接显示，不用重拉）。"""
    try:
        path = cache_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
    except Exception as exc:                   # noqa: BLE001
        logger.warning("练度缓存写不进去：%s", exc)


def load_cache() -> dict:
    """读上次拉的数据；没有 / 坏了都返回空 dict。"""
    try:
        path = cache_file()
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:                          # noqa: BLE001
        return {}


def clear_cache() -> None:
    try:
        cache_file().unlink()
    except Exception:                          # noqa: BLE001
        pass


# --------------------------------------------------------------------- 控件
#
# 角色格子 / 详情视图在 detail_view.py 里（那边是图文并茂的官方布局）。

from .detail_view import CharacterTile, EchoDetailView  # noqa: E402


# --------------------------------------------------------------------- 面板

class CharacterBuildPanel(ScrollArea):
    """登录 + 概览 + 角色网格 + 明细 + 日志（折叠）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("CharacterBuildPanel")
        self._account = kuro_account.load_account()
        self._thread: QThread | None = None
        self._login_thread: QThread | None = None   # ★ 单独持有，别被覆盖
        self._data: dict = load_cache()        # ★ 直接显示上次结果
        self._cards: list = []
        self._selected: str = ""               # 当前选中的角色 id
        self._auto_fetched = False
        self._build()
        self._render(self._data)               # 有缓存就先显示
        # ★ 已登录但**没有缓存**（比如上次没拉完）→ 自动拉一次
        #   （用户："我上次已经登陆，为什么不显示数据"）
        QTimer.singleShot(300, self._maybe_auto_fetch)

    def _maybe_auto_fetch(self) -> None:
        """已登录 + 没数据 → 自动拉一次（不用用户再点）。"""
        if self._auto_fetched or self._data.get("roleList"):
            return
        if not self._account.logged_in:
            return
        self._auto_fetched = True
        self._say("检测到已登录但本地没有数据 —— 自动拉取一次…")
        self._on_fetch()

    # ------------------------------------------------------------- 构建
    def _build(self) -> None:
        view = QWidget(self)
        self.setWidget(view)
        self.setWidgetResizable(True)
        root = QVBoxLayout(view)
        root.setContentsMargins(24, 20, 24, 24)
        root.setSpacing(12)

        root.addWidget(TitleLabel("查询角色练度", view))
        root.addWidget(BodyLabel(
            "登录库街区后拉取你账号里的角色与声骸数据，"
            "用来比对哪些角色的声骸属性需要重刷。", view))

        root.addWidget(self._build_login_card(view))
        root.addWidget(self._build_overview_card(view))
        root.addWidget(self._build_roles_card(view))
        root.addWidget(self._build_detail_card(view))
        root.addWidget(self._build_log_card(view))
        root.addStretch(1)
        self._refresh_login_state()

    def _build_login_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(10)
        head.addWidget(SubtitleLabel("① 登录库街区", card))
        self._login_status = CaptionLabel("未登录", card)
        head.addWidget(self._login_status)
        head.addStretch(1)
        self._logout_button = PushButton("退出登录", card)
        self._logout_button.clicked.connect(self._on_logout)
        head.addWidget(self._logout_button)
        box.addLayout(head)

        def field(label: str, placeholder: str, width: int, maxlen: int = 0):
            row = QHBoxLayout()
            row.setSpacing(8)
            tag = CaptionLabel(label, card)
            tag.setFixedWidth(48)
            row.addWidget(tag)
            edit = QLineEdit(card)
            edit.setPlaceholderText(placeholder)
            edit.setFixedWidth(width)
            if maxlen:
                edit.setMaxLength(maxlen)
            row.addWidget(edit)
            row.addStretch(1)
            box.addLayout(row)
            return edit

        # ⚠ 特征码**保留输入框**（用户 2026-10-03 要求）：
        #   留空 = 登录后自动用「绑定的游戏角色」；填了 = 就查那个号。
        #   （我先删掉它是错的 —— 用户明确说"特征码呢"）
        self._feature_edit = field("特征码", "留空 = 自动用绑定账号",
                                   200)
        self._mobile_edit = field("手机号", "手机号", 200, MOBILE_LEN)
        self._code_edit = field("验证码", "短信验证码", 200, 8)
        # ★ 三个输入框都**记住上次的值**（用户要求：登录一次后默认保存）
        self._restore_inputs()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self._login_button = PushButton("登录", card)
        self._login_button.clicked.connect(self._on_login)
        btn_row.addWidget(self._login_button)
        # ⚠ 「获取数据」按钮已去掉（用户要求）：登录后**自动拉**，
        #   之后想重拉点「刷新数据」。
        self._refresh_button = PushButton("刷新数据", card)
        self._refresh_button.clicked.connect(self._on_fetch)
        btn_row.addWidget(self._refresh_button)
        btn_row.addStretch(1)
        box.addLayout(btn_row)

        box.addWidget(CaptionLabel(
            "验证码在任意官方入口获取（库街区 App / 网页登录框）—— 两边通用。"
            "　**登录后会自动拉取数据**；之后想重拉点「刷新数据」。", card))
        return card

    def _build_overview_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)
        box.addWidget(SubtitleLabel("② 账号概览", card))
        self._summary = StrongBodyLabel("尚未拉取数据", card)
        self._summary.setWordWrap(True)
        box.addWidget(self._summary)
        return card

    def _build_roles_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)

        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(SubtitleLabel("③ 共鸣者", card))
        self._roles_hint = CaptionLabel("", card)
        head.addWidget(self._roles_hint)
        head.addStretch(1)

        # ★ 搜索框（用户："加个下拉列表搜索"）
        self._search_edit = LineEdit(card)
        self._search_edit.setPlaceholderText("搜索角色名 / 属性 / 武器")
        self._search_edit.setFixedWidth(200)
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(
            lambda _t: self._render(self._data))
        head.addWidget(self._search_edit)

        # ★ 达标筛选下拉（用户："达标/未达标"）
        self._filter_box = ComboBox(card)
        self._filter_box.addItems(list(FILTER_CHOICES))
        self._filter_box.setFixedWidth(120)
        self._filter_box.currentTextChanged.connect(
            lambda _t: self._render(self._data))
        head.addWidget(self._filter_box)
        box.addLayout(head)

        # ★★ 共鸣者列表：**单独一横行，放不下就横向滚动**
        #:
        #: 用户："一个就展示所有共鸣者，展示不全，可以滑动"
        #:
        #: ⚠ 之前用 QGridLayout 换行 → 43 个角色铺了 6 行，
        #: 把下面的详情区挤到屏幕外。现在改成
        #: ``QScrollArea(横向) + QHBoxLayout`` —— **永远只占一行**。
        self._roles_scroll = QScrollArea(card)
        self._roles_scroll.setWidgetResizable(True)
        self._roles_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._roles_scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._roles_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        #: ★ 只让它高一行（不然 ScrollArea 会想撑满）
        self._roles_scroll.setFixedHeight(TILE_H + 22)

        self._roles_host = QWidget()
        self._roles_row = QHBoxLayout(self._roles_host)
        self._roles_row.setContentsMargins(0, 0, 0, 0)
        self._roles_row.setSpacing(6)
        self._roles_row.addStretch(1)
        self._roles_scroll.setWidget(self._roles_host)
        box.addWidget(self._roles_scroll)
        return card

    def _build_detail_card(self, parent) -> CardWidget:
        """④ 共鸣者详情 —— **图文并茂**（按用户给的官方参考图）。"""
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(8)
        box.addWidget(SubtitleLabel("④ 共鸣者详情", card))

        self._detail = EchoDetailView(card)
        #: ★ 给足高度 —— 官方那个详情页很长（属性/武器/声骸/技能/共鸣链），
        #: 太矮的话用户得在小框里滚，很难看。
        self._detail.setMinimumHeight(720)
        box.addWidget(self._detail)
        return card

    def _build_log_card(self, parent) -> CardWidget:
        card = CardWidget(parent)
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)

        head = QHBoxLayout()
        head.addWidget(SubtitleLabel("日志", card))
        head.addStretch(1)
        self._log_toggle = PushButton("展开", card)
        self._log_toggle.setCheckable(True)
        self._log_toggle.clicked.connect(self._toggle_log)
        head.addWidget(self._log_toggle)
        box.addLayout(head)

        self._log = QTextEdit(card)
        self._log.setReadOnly(True)
        self._log.setMinimumHeight(120)
        self._log.setVisible(False)            # ★ 默认折叠
        box.addWidget(self._log)
        return card

    def _toggle_log(self) -> None:
        show = self._log_toggle.isChecked()
        self._log.setVisible(show)
        self._log_toggle.setText("收起" if show else "展开")

    # ----------------------------------------------------- 输入框记忆
    def _remember_inputs(self) -> None:
        """记住输入的**特征码 + 手机号**（用户要求：登录一次后默认保存）。

        ⚠ **不存验证码** —— 那个是一次性的，留着没用还占地方。
        """
        try:
            tool_settings.save(SETTINGS_KEY, {
                "feature_code": self._feature_edit.text().strip(),
                "mobile": self._mobile_edit.text().strip(),
            })
        except Exception as exc:               # noqa: BLE001
            logger.debug("记住输入失败：%s", exc)

    def _restore_inputs(self) -> None:
        """回填上次输入的特征码 / 手机号。

        ⚠ 手机号**只存后 4 位**（``mobile_tail``）—— 出于隐私从不存全号，
        所以这里**拼不出来**，只在"用户真的存过全号"时才回填。
        界面上用 ``_login_status`` 显示「已登录（****7393）」。
        """
        try:
            saved = tool_settings.load(SETTINGS_KEY) or {}
        except Exception:                      # noqa: BLE001
            return
        feature = str(saved.get("feature_code") or "").strip()
        mobile = str(saved.get("mobile") or "").strip()
        #: 没存过就用**账号里绑定的**特征码
        if not feature and self._account.roles:
            rid = str(self._account.roles[0].get("roleId") or "").strip()
            # ⚠ 只认**像特征码**的值（纯数字、够长）。
            #   防的是"测试脚本写进令牌文件的假 roleId" ——
            #   2026-10-03 我那个 `_repro_stuck.py` 把 roles 写成
            #   `[{'roleId': '1'}]`，界面就回填了一个 `1`，
            #   用户问"填个1是啥意思"。
            if rid.isdigit() and len(rid) >= 6:
                feature = rid
        if feature:
            self._feature_edit.setText(feature)
        if mobile and len(mobile) == MOBILE_LEN:
            self._mobile_edit.setText(mobile)

    # ------------------------------------------------------------- 小工具
    def _say(self, message: str) -> None:
        self._log.append(message)
        logger.info("查询角色练度：%s", message)

    def _toast(self, message: str, ok: bool = True) -> None:
        maker = InfoBar.success if ok else InfoBar.error
        maker(title="查询角色练度", content=message,
              orient=Qt.Horizontal, isClosable=True,
              position=InfoBarPosition.TOP, duration=5000, parent=self)

    def _refresh_login_state(self) -> None:
        if self._account.logged_in:
            tail = self._account.mobile_tail
            self._login_status.setText(
                f"已登录（手机号 ****{tail}）" if tail else "已登录")
            # ★ 已登录时把手机号提示写在 placeholder 里 ——
            #   我们**只存后 4 位**（隐私），拼不出全号，所以框里是空的。
            #   但用户看到空框会以为坏了，这里说清楚"不用再填"。
            if not self._mobile_edit.text().strip():
                self._mobile_edit.setPlaceholderText(
                    f"已登录 ****{tail}，换号才要填" if tail
                    else "已登录，换号才要填")
        else:
            self._login_status.setText("未登录")
            self._mobile_edit.setPlaceholderText("手机号")
        self._refresh_button.setEnabled(self._account.logged_in)

    def _busy(self, busy: bool) -> None:
        for b in (self._login_button, self._refresh_button):
            b.setEnabled(not busy)
        if not busy:
            self._refresh_login_state()

    # ------------------------------------------------------------- 登录
    def _on_login(self) -> None:
        mobile = self._mobile_edit.text().strip()
        code = self._code_edit.text().strip()
        if len(mobile) != MOBILE_LEN or not mobile.isdigit():
            self._toast(f"手机号要填 {MOBILE_LEN} 位数字", ok=False)
            return
        if not code:
            self._toast("请填短信验证码", ok=False)
            return
        self._busy(True)
        self._say("正在登录（APP 端）…")
        thread = LoginThread(mobile, code, "", self)
        thread.progress.connect(self._say)
        thread.succeeded.connect(self._on_logged_in)
        thread.failed.connect(self._on_failed)
        # ★ 用**单独的引用** —— 之前赋给 self._thread 后，
        #   _on_logged_in → _on_fetch 会把它覆盖掉（登录线程还在跑），
        #   日志里就出现了两条"正在登录"（重复触发）。
        self._login_thread = thread
        thread.start()

    def _on_logged_in(self, account) -> None:
        self._account = account
        try:
            kuro_account.save_account(account)  # ★ 先落盘（下次打开就是已登录）
        except Exception:                      # noqa: BLE001
            pass
        # ★ 记住输入的手机号 + 特征码
        self._remember_inputs()
        names = [str(r.get("roleName") or r.get("roleId"))
                 for r in (account.roles or [])]
        self._say(f"✓ 登录成功。绑定的游戏角色：{names or '（没拿到）'}")
        self._toast("登录成功")
        # ★ 登录后**自动拉一次**（用户要求：不用再点「获取数据」）
        self._busy(False)
        self._on_fetch()

    # ------------------------------------------------------------- 数据
    def _on_fetch(self) -> None:
        if not self._account.logged_in:
            self._toast("请先登录", ok=False)
            return
        feature = self._feature_edit.text().strip()
        self._busy(True)
        self._say("开始拉取数据…" + (f"（特征码 {feature}）" if feature else ""))
        thread = FetchThread(self._account, feature, self)
        thread.progress.connect(self._say)
        thread.succeeded.connect(self._on_fetched)
        thread.failed.connect(self._on_failed)
        # ★ 拉到一半也先画出来 —— 43 次请求要几十秒，
        #   不能等全拉完才有画面（用户会以为卡死了）
        thread.partial.connect(self._on_fetched)
        self._thread = thread
        thread.start()

    def _on_fetched(self, data) -> None:
        """收到数据（可能是**阶段性的**，也可能是最终结果）。

        ⚠ ``partial`` 和 ``succeeded`` 都连到这里 —— 阶段性的不能
        ``self._busy(False)``（那会让用户在还在拉的时候点按钮）。
        靠线程的 ``isRunning()`` 判断是不是最终结果。
        """
        self._data = data or {}
        self._render(self._data)

        thread = self._thread
        running = bool(thread is not None and thread.isRunning())
        if running:
            return                              # 还在拉，别解锁按钮
        self._busy(False)
        self._toast("数据拉取完成")

    # ------------------------------------------------------------- 渲染
    def _render(self, data: dict) -> None:
        """把数据画成界面（像官方那样）。

        ⚠ 这个函数会被调两次（外层一次，``_show_detail`` 刷新高亮再一次）——
        **但不会无限递归**：第一次进来就把 ``_selected`` 设上了，
        第二次那个"默认选中"分支就不再成立（实测 2 次就停）。

        我一度加过 ``_rendering`` 锁，后来实测发现**根本不会递归**，
        锁是多余的 → 删掉（少一个状态少一个坑）。
        """
        base = (data or {}).get("base") or {}
        role_list = (data or {}).get("roleList") or []
        details = (data or {}).get("details") or {}
        #: ★ 官方推荐标准（每个角色的达标线）—— 见 :mod:`src.core.wuwa_guide`
        standards = (data or {}).get("standards") or {}

        # ★ 漂泊者（主角）**彻底不显示** —— 详情也一起滤掉，
        #   否则"待优化数"还会把他算进去（见 EXCLUDED_ROLE_NAMES）。
        kept = {str(r.get("roleId")) for r in visible_roles(role_list)}
        details = {k: v for k, v in details.items() if str(k) in kept}

        self._summary.setText(self._format_base(base) if base
                              else "尚未拉取数据")

        # ── 清掉旧卡片
        for card in self._cards:
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()

        if not role_list:
            self._roles_hint.setText("（还没数据 —— 登录后会自动拉取）")
            return

        # ★ 漂泊者（主角）**彻底不显示**（用户："把漂泊者除开"，
        #   并明确选了"从列表里删掉"）—— 卡片 / 计数 / 筛选都不算他。
        role_list = visible_roles(role_list)

        # ── 判定哪些角色"声骸未达标"
        flagged = {cid: self._echo_issues(details.get(cid),
                                          standards.get(cid))
                   for cid in details}

        # ── 筛选条件（下拉 + 搜索）
        choice = self._filter_box.currentText() or "全部"
        keyword = (self._search_edit.text() or "").strip().lower()

        shown = 0
        # ★★ 排序：**按最新获得倒序**（用户："角色按最新获得顺序倒序排序"）
        #
        # 接口**没有"获得时间"字段**，但 ``roleData.roleList`` 返回的
        # **原始顺序就是游戏里的顺序**（不是按 roleId 数值排的 ——
        # 实测 1402,1202,1103,1602… 后两位并不递增）。
        # 所以**反转原始列表**就是"最新获得在前"。
        #
        # ⚠ 别再按 level / roleName 排 —— 那会把游戏顺序打乱。
        ordered = list(reversed(role_list))
        for role in ordered:
            cid = str(role.get("roleId"))
            issues = flagged.get(cid)
            has_data = cid in details

            # ★★★ 筛选（**三态**：没数据 / 未达标 / 达标）
            #
            # ⚠⚠ 用户 2026-10-05 发现：「丽贝卡 Lv.40」出现在**「达标」**里。
            #
            # 根因：``flagged`` 只遍历 ``details``，**没声骸数据的角色
            # 根本不在字典里** → ``issues`` 是 ``None`` → 判 False →
            # 两个分支都跳过 → 落进"达标"。
            #
            # 而"没数据"其实是**没练**（游戏里没装声骸）——
            # 实测 12 个没数据的角色**全是低等级**（Lv1/40/50/70）。
            # **"没数据" ≠ "达标"** —— 这是两个完全不同的状态。
            if choice == "未达标":
                #: ⚠ ``flagged`` 只含**有数据**的角色，"没数据"天然不在这
                #: —— 这个 ``has_data`` 是**防御性**的（以后改了
                #: ``flagged`` 的构造方式也不会漏）。
                if not has_data or not issues:
                    continue
            elif choice == "达标":
                #: ★★★ **只有"有数据且没问题"才算达标**
                #:
                #: ⚠⚠ 这里漏掉 ``has_data`` 就是用户报的那个 bug：
                #: "没数据"的 ``issues`` 是 ``None``（假），会被当成达标。
                if not has_data or issues:
                    continue
            elif choice == "未练":
                #: 没声骸数据 = 没练（用户："40级的应该进未练的分类"）
                if has_data:
                    continue
            # ★ 等级筛选（用户："增加一个分类，等级（未满90级的）"）
            if choice == "未满90级" and not is_below_max_level(role):
                continue
            # ★ 搜索（名字 / 属性 / 武器）
            if keyword:
                hay = " ".join(str(role.get(k) or "") for k in
                               ("roleName", "attributeName",
                                "weaponTypeName", "acronym")).lower()
                if keyword not in hay:
                    continue
            tile = CharacterTile(role, flagged=bool(issues),
                                 selected=(cid == self._selected),
                                 size=TILE_SIZE, parent=self._roles_host)
            tile.setFixedSize(QSize(TILE_W, TILE_H))
            tile.clicked.connect(self._show_detail)
            #: ★ 插到末尾那个 stretch 之前（否则会被推到最右）
            self._roles_row.insertWidget(self._roles_row.count() - 1, tile)
            self._cards.append(tile)
            shown += 1

        bad_n = sum(1 for v in flagged.values() if v)
        total = len(role_list)
        extra = ""
        if choice != "全部" or keyword:
            extra = f"　（筛出 {shown} 个）"
        self._roles_hint.setText(
            f"共 {total} 个　声骸待优化 {bad_n} 个{extra}")

        self._say(f"✓ 角色 {total} 个，拿到声骸详情的 {len(details)} 个，"
                  f"其中 {bad_n} 个需要优化")

        # ★★ 没选角色时 → **默认显示排在第一位的那个**（用户要求）
        #
        # ⚠ ``_show_detail`` 结尾会再调一次 ``_render``（刷新选中高亮），
        # 但**不会无限递归** —— 那时 ``_selected`` 已经有值，
        # 这个分支不再成立（实测 2 次就停）。
        if not self._selected and self._cards:
            self._show_detail(self._cards[0]._cid)

    @staticmethod
    def _echo_issues(detail, standard=None) -> list[str]:
        """★ 判断一个角色的声骸有没有问题（返回问题列表）。

        ## 判定分两类（用户 2026-10-05 给了官方标准后重写）

        **① 官方推荐属性（★★ 主要判据）**

        用户给了官方攻略站，那里每个角色都有「属性推荐」::

            白芷      共鸣效率 ≥260.0% / 治疗效果加成 ≥40.0% / 生命 ≥24000
            今汐      暴击 ≥70.0% / 暴击伤害 ≥275.0% / 共鸣技能伤害加成 ≥20.0%

        ``standard`` 就是那份标准（见 :mod:`src.core.wuwa_guide`）。
        拿**角色当前属性**（``roleAttributeList``）跟它比，不达标就报出来。

        **② 结构性问题（客观事实，和标准无关）**

        ====================  ============================================
        规则                  说明
        ====================  ============================================
        **等级没满**           有声骸 ``level < 25``
        **套装不统一**         5 个声骸的套装名不止一种
        **COST 配比不对**      不是 4-3-3-1-1
        ====================  ============================================

        ⚠ 原来那条"有效词条 < 10"**删掉了** —— 那个 10 是我瞎定的，
        现在改用官方推荐属性（有依据）。
        """
        issues: list[str] = []
        detail = detail or {}
        ph = detail.get("phantomData") or {}
        items = ph.get("equipPhantomList") or []
        if not items:
            return ["没拿到声骸数据"]

        # ① ★★ 官方推荐属性
        issues.extend(_compare_standard(detail, standard))

        # ② 等级
        not_max = [x for x in items if (x.get("level") or 0) < 25]
        if not_max:
            issues.append(f"{len(not_max)} 个声骸没满级")

        # ③ ★★ 套装 —— 跟**官方推荐**比，不是"必须统一"
        #
        # ⚠⚠ 我原来写的是"套装不统一（N 种）就算问题" —— **那是错的**。
        #
        # 用户 2026-10-05（截图圈出千咲：属性全绿却进了「未达标」）：
        # "达标的怎么进了未达标的？"
        #
        # 查下来千咲是 **3+2 混搭**（3 件命理崩毁之弦 + 2 件幽夜隐匿之帷）——
        # 而**官方推荐的正是这个组合**（``standard.echo.main.echoSetEffects``
        # 里写着 ``echoSet=3`` 和 ``echoSet=2``）。
        #
        # **3+2 是完全合法的配装**，"不统一"根本不是问题。
        # 现在改成：**跟官方的套装组合比**，对不上才报。
        issues.extend(_compare_echo_sets(items, standard))

        # ④ COST 配比（期望 4-3-3-1-1 = 12）
        costs = sorted((x.get("cost") or 0 for x in items), reverse=True)
        if costs != [4, 3, 3, 1, 1]:
            issues.append("COST 配比 " + "-".join(str(c) for c in costs))

        return issues

    def _show_detail(self, char_id: str) -> None:
        """点角色格子 → 展示完整详情（**图文并茂**，官方那个布局）。

        ⚠ 画法全在 :class:`~.detail_view.EchoDetailView` 里 ——
        这里只管"选谁 + 传数据"。之前是在这里拼一大段文字，
        用户要的是官方那种**带图**的排版。
        """
        self._selected = str(char_id)
        detail = (self._data.get("details") or {}).get(str(char_id))
        standard = (self._data.get("standards") or {}).get(str(char_id))
        if not detail:
            self._detail.show_detail(
                {}, ["这个角色还没拿到声骸数据（可能没开放展示）"])
        else:
            self._detail.show_detail(
                detail, self._echo_issues(detail, standard), standard)
        # ★ 重画网格 → 选中的格子高亮
        self._render(self._data)

    @staticmethod
    def _substat_hits(items) -> tuple[int, int]:
        """推荐辅音词条命中数（官方那个黄色数字）。

        库街区用 ``valid`` 标"是不是推荐词条" —— 直接数它。
        """
        hit = total = 0
        for item in items:
            for s in (item.get("subProps") or []):
                total += 1
                if s.get("valid"):
                    hit += 1
        return hit, total

    def _role_hits(self, char_id: str) -> tuple[int, int]:
        """某个角色的「有效词条 / 总词条」—— 画在卡片上。"""
        detail = (self._data.get("details") or {}).get(str(char_id)) or {}
        items = ((detail.get("phantomData") or {})
                 .get("equipPhantomList") or [])
        return self._substat_hits(items)

    @staticmethod
    def _format_base(base: dict) -> str:
        """账号概览一行（字段名来自实测）。"""
        if not base:
            return "尚未拉取数据"
        parts = [
            f"结晶波片 {base.get('energy', '?')}/{base.get('maxEnergy', '?')}",
            f"结晶单质 {base.get('storeEnergy', '?')}"
            f"/{base.get('storeEnergyLimit', '?')}",
            f"活跃度 {base.get('liveness', '?')}"
            f"/{base.get('livenessMaxCount', '?')}",
            f"游戏天数 {base.get('activeDays', '?')}",
            f"联觉等级 {base.get('level', '?')}",
            f"解锁角色 {base.get('roleNum', '?')}",
        ]
        stamp = base.get("__at")
        return "　|　".join(parts) + (f"　　拉取于 {stamp}" if stamp else "")

    # ------------------------------------------------------------- 收尾
    def _on_logout(self) -> None:
        kuro_account.clear_account()
        clear_cache()
        self._account = kuro_account.Account()
        self._data = {}
        self._render({})
        self._detail.setPlainText("")
        self._detail_title.setText("④ 声骸明细")
        self._refresh_login_state()
        self._say("已退出登录（令牌 + 缓存都已删除）")
        self._toast("已退出登录")

    def _on_failed(self, message: str) -> None:
        self._busy(False)
        self._say(f"✗ 失败：{message}")
        self._toast(message, ok=False)


# --------------------------------------------------------------------- 工具

@registry.register(
    category=ToolCategory.GAME,
    name="查询角色练度",
    description="登录库街区，拉取账号里的角色与声骸数据，比对哪些声骸需要重刷",
    icon_name="CERTIFICATE",
    coming_soon=False,
)
class CharacterBuildTool(BaseTool):
    """查询角色练度。"""

    key = TOOL_KEY
    #: ★ 自带图标 —— 和另外 5 个工具**同一套风格**
    #: （深色圆角底 + 金色边框 + 发光紫线条；512x512。
    #:  用户 2026-10-04："这个图标不能设计跟前面的风格一样吗"）
    #: 用 ``tools/make_character_build_icon.py`` 生成。
    icon_path = str(paths.resource_dir("assets", "icons",
                                       "character_build.png"))
    coming_soon = False
    supports_task_run = False

    def create_widget(self, parent=None):
        return CharacterBuildPanel(parent)
