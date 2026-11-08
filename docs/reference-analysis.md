# 参考项目分析：Threads 傻噶都识得跑 v2.57

> 分析对象：`C:\Users\Administrator\Desktop\threads\Threads傻噶都识得跑_源码_v2.57`
> 目的：提取可复用的设备/自动化经验，同时避免把它的结构问题带进新项目。

## 1. 一句话结论

它把「GUI + 任务编排 + 业务步骤 + UI 自动化 + 设备通信 + 数据持久化」全部塞进了一个
`App(tk.Tk)` 类。能跑，但边界消失，导致改一个页面、换一个 App、抽一个功能都要在
200 KB 的单文件里做手术。

## 2. 量化现状

| 指标 | 数值 |
|---|---:|
| 根目录 Python 文件 | 4 个 |
| `threads_account_manager.py` | 2,897 行 / 184,882 字符 |
| 顶层方法/函数 | 176 个 |
| 最长单行 | 487 字符 |
| 超过 200 字符的行 | 14 行 |
| `except Exception` | 47 处 |
| 硬编码 `self.tap(idx, x, y)` | 18 处 |
| 硬编码 `input swipe ...` | 14 处 |
| `ET.fromstring(...)` 直接解析 XML | 27 处 |
| `self.dump(...)` | 117 处 |
| `self.node_center(...)` | 98 处 |
| `self.find_text_control(...)` | 54 处 |
| `VmosHost(...)` 直接构造 | 6 处 |

这些数字说明的不是「代码长」，而是**同一件事被重复实现了很多遍**：解析 XML、找控件、
算中心点、点击、等待，散落在 176 个方法里。

## 3. 现有结构

```text
threads_account_manager.py   # 2,897 行，App 类：界面/编排/步骤/UI/业务
threads_2fa_manager.py       # 476 行：XLS、邮箱、TOTP、设备工具
vmos_device.py               # 252 行，VMOS HTTP 封装（唯一边界比较清楚的文件）
threads_ck_extractor.py      # CK 提取
vendor/                      # xlrd/xlwt
```

`App` 内部大致分成：

| 区域 | 典型方法 | 问题 |
|---|---|---|
| tkinter 界面 | `_build`、`render_instances`、`render_logs` | 界面状态与任务状态混在 `self` |
| 任务编排 | `instance_worker`、`start_rows`、`run_custom_steps_mode` | 一实例一线程，计划/状态用 `row` dict 隐式传递 |
| 设备访问 | `adb`、`tap`、`dump`、`scale_for` | 设备细节泄漏到业务方法 |
| UI 查找 | `node_center`、`find_text_control`、`find_exact_label` | 每次重新 `ET.fromstring`，选择策略靠包含匹配 |
| 页面判断 | `is_threads_home`、`needs_account_password`、`is_2fa_success` | 页面规则与业务动作混在一起 |
| 业务步骤 | `do_2fa`、`run_instagram_login`、`run_registration_mode` | 直接调用 `self.tap(...)` / `self.dump(...)` |
| 持久化 | `save`、`update_xls` | 和界面线程共享锁 |

## 4. 具体问题（按影响排序）

### 4.1 单体类：没有依赖方向

`App` 同时依赖 tkinter、`vmos_device`、`threads_2fa_manager`、XLS、邮箱、TOTP。
任何一层变化都会传导到整个类。想单独测试「找控件」必须先构造一个 tkinter 窗口。

**后果**：无法单元测试，无法复用，无法替换。

### 4.2 设备层与 UI 层耦合

`App.adb()` 里包含缩放、超时、停止检查、错误翻译；`App.tap()` 里又先尝试 VMOS
`input/click`，失败再走 `adb shell input tap`；`App.dump()` 里还夹带「发生错误/再试一次」
的业务重试。

**后果**：换设备通道（VMOS → 真机/云机）要改业务代码；设备错误无法统一处理。

### 4.3 选择器散落在业务代码里

27 处 `ET.fromstring`、54 处 `find_text_control`、98 处 `node_center`，意味着：
- 没有统一的 `Selector` 抽象；
- 精确/包含/短文本匹配各写一套；
- 控件树解析没有缓存，重复解析；
- 页面规则与点击动作交错，无法单独回归。

### 4.4 隐式状态 `row` dict

每个实例的运行状态放在 `row` 里（`phone`、`number_record`、`email_record`、
`step_states`、`task_steps`……），跨步骤传递，没有类型、没有默认值、没有校验。

**后果**：一个步骤写错 key，另一个步骤静默拿到 `None`；断点恢复很难推理。

### 4.5 页面识别是 ad-hoc 的

- 规则分散在 `流程脚本/*.json`、`POPUP_RULES`、`屏幕字典.json` 三处；
- 大量包含匹配，示例：`code_input` 会命中 `verify_email_code_input`；
- 同一页面可能被多个处理器同时操作（短信流程 vs 邮箱流程）；
- 不认识的页面只截图 + 停止，缺少结构化诊断。

### 4.6 异常与重试不可观测

47 处 `except Exception`，其中不少是 `pass` 或只打一行日志。失败后很难知道：
- 是网络、设备、页面、还是业务规则？
- 重试了几次？为什么重试？
- 当前页面到底是什么？

### 4.7 UI 与任务线程强绑定

`self.after(0, ...)` 从工作线程更新 tkinter；停止/暂停用 `threading.Event` 穿过
`pause`、`tap`、`dump`、`wait` 各处。业务逻辑无法脱离 GUI 运行。

### 4.8 硬编码坐标与 540×960 设计稿

18 处硬编码点击、14 处硬编码滑动，依赖 `scale_for()` 把 540×960 映射到实际分辨率。
换分辨率/换机型/换语言就会漂移。

## 5. 值得保留的经验

这些是参考项目真正的价值，新框架应保留：

1. **主机发现三来源**：配置 + `adb devices` + 本机私网 /24 扫描。
2. **端口/指纹**：18182，`/v1/net_info` + `/container_api/v1/list_names`。
3. **agent 主通道 + shell 兜底**：控件树/点击/输入优先走 `android_api`，失败再走
   `uiautomator dump` / `input tap`。
4. **dump → find → click → 再 dump** 的闭环。
5. **实例间并行、实例内串行**。
6. **停止/暂停可中断**，等待要能被 stop 事件打断。
7. **失败现场**：截图 + 控件树 + 页面摘要。
8. **成本控制**：先检查再执行付费动作（新项目把它前移到「先启动 App，再买邮箱」）。

## 6. 根因

不是「文件太大」，而是**没有定义依赖方向和模块边界**：

```text
业务步骤 ──直接调用──> tkinter / XLS / 邮箱 / ET / 坐标 / HTTP
```

所有东西都可以直接调用所有东西，所以只能不断往同一个类里加方法。

## 7. 目标结构（新项目采用）

```text
CLI / Runner
   │
   ▼
apps/muse     页面、组件、业务流程（只认识 Page/Component）
   │
   ▼
ui            Selector / UiTree / UiSession（只认识控件）
   │
   ▼
vmos          DeviceApi / ContainerApi / Discovery（只认识 HTTP）
   │
   ▼
stdlib        urllib / xml.etree / json

services      mail / ledger（与设备无关，可单独测试）
```

依赖只能向下，不能反向：

- `vmos` 不知道 Muse；
- `ui` 不知道注册流程；
- `apps/muse` 不拼 URL、不解析 XML、不写 `input tap`；
- `services` 不依赖设备。

## 8. 旧 → 新映射

| 旧实现 | 新模块 |
|---|---|
| `vmos_device.py` | `vmos/models.py`、`vmos/transport.py`、`vmos/container.py`、`vmos/device.py`、`vmos/discovery.py` |
| `App.adb/tap/dump/scale_for` | `vmos/device.py`（通道 + 兜底/缩放） |
| `App.node_center/find_text_control/find_exact_label` | `ui/node.py`、`ui/parser.py`、`ui/selector.py` |
| `App.dump` 的错误重试 | `ui/session.py` + `core/retry.py` |
| `App.launch/restart_threads` | `apps/muse/app.py` |
| `run_registration_mode` 等 | `apps/muse/flows/register.py` |
| 页面 is_xxx / 弹窗规则 | `apps/muse/pages.py` + `apps/muse/components.py` |
| `threads_2fa_manager` 邮箱部分 | `services/mail.py` |
| XLS 保存 | `services/ledger.py`（JSONL + CSV 导出） |
| tkinter 主界面 | `cli.py`（MVP）；以后可加 GUI 适配层，不碰核心 |
| `程序配置.json` | `config/settings.json` + 环境变量覆盖 |

## 9. 迁移策略（如果以后要搬旧功能）

不要一次性重写 2,897 行。按风险从低到高：

1. **纯函数先搬**：验证码解析、TOTP、文本匹配、XLS 读写 → 加测试。
2. **设备层搬**：把 `vmos_device.py` 放进 `vmos/`，补上超时/错误类型。
3. **UI 层搬**：把 `node_center/find_text_control` 改成 `Selector` + `UiSession`。
4. **页面规则搬**：每个 `is_xxx` 变成 `Page` 规则 + fixture dump。
5. **业务流程搬**：每个 `run_xxx_mode` 变成 Flow，按步骤组合组件。
6. **最后才做 GUI**：GUI 只调用 Runner/Flow，不直接碰设备。

## 10. 结论

参考项目的价值在「真实踩坑经验」，不在代码组织。新项目保留它的设备发现、
agent 兜底、dump-find-click 闭环和失败现场，但把所有横切关注点拆成独立模块，
让「扫描连接」「脚本」「组件」「API」「业务」可以分别替换、分别测试。
