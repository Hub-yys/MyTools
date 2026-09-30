# 第三方代码与素材来源声明（NOTICES）

本项目的「4C 自动战斗」工具内置了下列第三方代码与素材，随包分发。各自的许可与
来源如下；分发 MyTools 时**必须**连同本目录一起分发。

## 1. ok-ww（vendored 源码与素材）

- 来源：<https://github.com/ok-oldking/ok-wuthering-waves>（master 分支）
- 引入方式：`vendor/okww/` —— `okww/`（原 `src/`，包名由 src 改为 okww，导入路径相应
  改写，逻辑未动）、`config.py`、`assets/`（模板图 / YOLO 声骸模型）、`i18n/`
- 许可：**GNU Affero General Public License v3.0**（全文见
  `ok-ww-LICENSE-AGPL-3.0.txt`）

  **AGPL-3.0 的分发义务**：只要把含 ok-ww 衍生代码的 MyTools 安装包交给第三方
  （哪怕免费送人），就必须按 AGPL-3.0 提供对应源码。最简单的合规做法：
  **每次发安装包时，把整个 MyTools 源码目录（或对应 commit 的 zip）一起发过去**，
  并保留本目录的许可文本。

## 2. ok-script（PyPI 依赖，非 vendored）

- 来源：<https://pypi.org/project/ok-script/>（版本 2.0.7b1，ok-ww 指定版本）
- 许可：Apache-2.0 + Commons Clause 附加条款（全文见
  `ok-script-LICENSE-Apache2-CommonsClause.txt`）。该许可**明确允许**作为更大
  应用的一部分分发、允许闭源使用，仅禁止"出售 ok-script 本身"。

## 3. 其他 Python 依赖

其余依赖（PySide6 / qfluentwidgets / onnxocr-ppocrv5 / opencv / numpy 等）的许可
见各自 PyPI 页面或 wheel 内的 LICENSE 文件；PyInstaller 打包时已把可收集到的
许可文本一并放入 `_internal/*.dist-info/licenses/`。
## 4. 使用风险提示（来自 ok-ww 原文的忠告）

ok-ww 与本工具均为 UI 自动化程序，不读写游戏内存；但**自动化操作是否违反游戏
服务条款由厂商政策决定**，使用导致的账号风险请自行评估。

## 5. 「唤取记录分析」工具的联网行为（与其它工具不同）

**这是本项目唯一一个会联网读取账号数据的工具**，特此声明：

- **它做什么**：把你粘贴的「唤取记录」链接里的玩家参数
  （`playerId` / `recordId` / `cardPoolId` 等）**发送给库洛官方接口**
  `gmserver-api.aki-game2.com/gacha/record/query`，取回你自己账号的抽卡记录做统计。
- **它不做什么**：不读游戏内存、不读存档、不模拟任何游戏操作、
  不修改任何游戏数据、不需要管理员权限。**只读**。
- **数据去向**：请求只发往**库洛官方域名**，本工具没有自己的服务器，
  **不收集、不上传、不分享**你的任何数据；拉取结果只在你本机内存/界面里。
- **前提**：需要联网；且必须先在游戏里**打开「唤取记录」页面**，
  否则接口会以记录过期拒绝（这是库洛侧的机制）。

> 该接口为库洛官方前端使用的接口，**非公开文档化的开放 API**，
> 可能随版本更新而变化或失效。变更导致的不可用属正常情况。
> 使用本工具即表示你知晓并自行承担由此产生的风险。