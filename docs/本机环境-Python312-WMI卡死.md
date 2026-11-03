# ★ 本机环境问题：Python 3.12 的 WMI 查询会永久卡死

> 2026-10-13 查明。**这是环境问题，不是代码问题**。
> 记在这里是因为它让整个项目"看起来跑不起来"，很难查。

---

## 症状

PyCharm（以及命令行）**跑不起来项目** —— 像是卡死，没有报错。

---

## 根因：Python 3.12 换了 `platform` 的实现

Python 3.12 给 `platform` 新增了 C 扩展 **`_wmi`**，
用 `_wmi.exec_query("SELECT ... FROM Win32_OperatingSystem")`
**直接查 WMI**。而 3.11 走的是旧的 `win32_ver()`，**不碰 WMI**。

本机 WMI 查询**永久卡住**（`Get-CimInstance` 25 秒以上无响应）。

实测对比：

| Python | `platform.release()` |
|---|---|
| `D:\Python 3.11.4\python.exe` | **0.02 秒** ✅ |
| `.venv` 的 `cpython-3.12.14`（uv 装的） | **卡死 >25 秒** ❌ |

卡死的调用栈（`faulthandler` 抓的）：

```
platform.py:1006 release()
platform.py:922  uname()
platform.py:450  win32_ver()
platform.py:388  _win32_ver()
platform.py:327  _wmi_query()      ← 卡在这里，永不返回
```

### 为什么表现成"PyCharm 跑不起来"

```
qfluentwidgets → darkdetect → platform.win32_ver() → WMI  ← 卡死
```

而**每个工具页都 import qfluentwidgets** → 项目看起来完全起不来。

---

## 修法（已实施）

在 **venv 的 site-packages 里放 `sitecustomize.py`**，
把 `_wmi` 挡掉 → 3.12 的 platform 退回 `raise OSError("not supported")`
分支 → 不再发 WMI 查询。

Python 启动时由标准库 `site` 自动导入 `sitecustomize`，
所以**PyCharm 不用改任何 Run Configuration**。

文件位置：`.venv/Lib/site-packages/sitecustomize.py`

### 效果

```
修前：platform.release()  卡死 >25 秒
修后：platform.release() = 11   0.04s
      QApplication OK          0.14s
      工具 8 个                 总 0.66s   ★ 全部正常
```

之后 `platform.release()` 返回 `'11'`（无 WMI 时的兜底值）。
⚠ **对本项目零影响** —— 代码里不用 Windows 版本号做任何判断。

---

## ⚠ 这是 workaround，不是修好了

它**只解决本机**。真正的选择有三个：

| 方案 | 说明 |
|---|---|
| **修 WMI** | 管理员运行 `winmgmt /verifyrepository`；不行就重启 Winmgmt 服务、或重启机器 |
| **换 Python 3.11** | 3.11 不走 WMI 路径，天然没这问题。重建 venv 即可 |
| **保留这个 stub** | 最省事，但要记住它在那儿（换机器/修好 WMI 后它是多余的） |

### 怎么判断 WMI 好没好

```powershell
# 这条如果不返回（>10 秒），说明 WMI 还卡着
Get-CimInstance Win32_OperatingSystem | Select-Object Caption
```

或者直接测 Python：

```powershell
.venv\Scripts\python.exe -c "import platform; print(platform.release())"
# 秒回 = 好了（不管返回 10 还是 11）
# 卡住 = 还没好
```

## WMI 修好后怎么清理

删掉 `.venv/Lib/site-packages/sitecustomize.py` 即可。

> ⚠ 这个文件在 **venv 里**，不在仓库里 —— 所以不占 git，
> 也不会跟着代码传到别的机器（这正是我们想要的：
> 它是**本机环境**的事，不是产品的事）。

---

## 顺带：这台机器上"跑测试"也要注意

`sitecustomize.py` 放在 venv 里之后，**测试也能正常跑了**：

```
nest_sweep 单测     67 个全过（0.04 秒）
```

修之前这些会**卡到超时**（因为 import Qt 就卡在 WMI）。

