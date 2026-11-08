# 架构设计：muse-auto

## 1. 目标

在 VMOS Edge 云机上，用 Python 驱动 Android 版 **Muse (Meta, `com.facebook.aura`)**，
先完成「扫描 → 连接 → 启动 → 页面识别 → 邮箱注册 → 验证码 → 生日 → 年龄验证 →
邀请码」的最小闭环，并且满足：

- 扫描/连接是一个独立模块；
- 脚本（业务流程）是一个独立模块；
- 脚本内部由可复用组件组成；
- VMOS/邮箱/账本 API 各自独立；
- 任何一层都能单独测试、单独替换；
- 核心不依赖第三方运行时库；XLS 账号保存使用 `xlrd` / `xlwt`。

非目标（MVP 不做）：

- Web 控制台 / 分布式队列；
- 代理/IP 管理、绑卡、支付；
- 全自动 Instagram/Facebook 登录（只等待 OAuth 返回）。

## 2. 分层

```text
┌──────────────────────────────────────────────────────────────┐
│ cli.py                              gui/                     │
│ discover / inspect / run / mail     tkinter 控制台            │
│ ledger / doctor / gui               实例 / 脚本 / 运行 / 检查 │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│ runner/       BatchRunner · FlowContext · ArtifactStore        │
│               实例并发、离线开机、失败聚合、产物目录             │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│ apps/muse/    MuseApp · Pages · Components · Flows            │
│               只认识“页面/控件/业务动作”                        │
└───────────────┬──────────────────────────────┬───────────────┘
                │                              │
┌───────────────▼──────────────┐  ┌────────────▼───────────────┐
│ ui/                          │  │ services/                  │
│ UiTree · Selector · Session  │  │ MailClient · Ledger        │
│ 只认识控件树                  │  │ 与设备无关，可单独跑        │
└───────────────┬──────────────┘  └────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ vmos/         Transport · ContainerApi · DeviceApi · Discovery │
│               只认识 HTTP / VMOS 接口                          │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│ Python 标准库：urllib · xml.etree · json · threading · tkinter │
└──────────────────────────────────────────────────────────────┘
```

**依赖方向只能向下。** 例如：

- `vmos` 不 import `apps.muse`；
- `ui` 不 import `services`；
- `apps.muse` 不拼 URL、不解析 XML、不写 `input tap`；
- `gui` 只调用 `runner` / `services`，不直接碰设备；
- `services` 不 import `vmos`。

## 3. 目录

```text
muse_auto/
├── cli.py                  # 命令行入口，参数解析 + 命令实现
├── config.py               # JSON 配置、环境变量、校验（dataclass）
├── gui/
│   ├── app.py              # 编排：任务线程、事件队列、脚本分组
│   ├── instances_view.py   # 实例模块：搜索/IP/状态筛选/分配脚本
│   ├── scripts_view.py     # 脚本模块：注册表 + 动态参数表单
│   ├── run_view.py         # 运行模块：并发/轮数/间隔/结果/日志
│   ├── inspect_view.py     # 页面检查
│   ├── widgets.py          # 滚动容器/表单行
│   ├── theme.py            # 颜色/字体
│   ├── logging_bridge.py   # logging → Tk 队列
│   └── __main__.py         # python -m muse_auto.gui
├── scripts/
│   ├── base.py             # ScriptSpec / ScriptField / PreparedScript
│   ├── registry.py         # 脚本注册表
│   └── muse.py             # MuseAI 注册 script / 冒烟 script
├── core/
│   ├── errors.py           # 类型化异常，区分设备/UI/邮箱/页面/停止
│   ├── logging.py          # 控制台 + 单次运行日志；实例前缀
│   ├── retry.py            # 可中断重试
│   └── stop.py             # StopToken：sleep 可被 Ctrl+C 唤醒
├── vmos/
│   ├── models.py           # VmosHost / VmosInstance / 状态归一化
│   ├── transport.py        # 唯一发 HTTP 的地方；超时、重试、代理绕过、二进制
│   ├── container.py        # 主机探测、实例列表、开机
│   ├── device.py           # dump/click/text/key/swipe/screenshot/activity/package
│   ├── discovery.py        # 配置 + adb + /24 扫描 → 实例列表
│   └── adb.py              # 只负责 adb devices 的主机发现
├── ui/
│   ├── node.py             # Rect / UiNode：bounds、center、ancestors
│   ├── parser.py           # XML → UiTree
│   ├── selector.py         # 声明式选择器（text/label/id/class/editable/...）
│   └── session.py          # dump→find→click→wait 的高层操作
├── apps/muse/
│   ├── app.py              # 包名、启动、前台判断、清数据
│   ├── selectors.py        # 所有 Muse 文案/ID 选择器集中在这里
│   ├── pages.py            # 纯函数页面识别（Page enum）
│   ├── components.py       # 权限弹窗/邮箱表单/验证码/生日/年龄门/邀请码
│   ├── account_center.py   # 步骤2：Settings→Meta Account→换邮箱（WebView）
│   ├── invite_center.py    # 步骤3：Settings→Redeem referral code
│   ├── pipeline.py         # 步骤1~6 可组合流程
│   └── flows/
│       ├── base.py         # FlowResult
│       ├── smoke.py        # 启动 + 识别 + 截图/dump
│       └── register.py     # 注册状态机（pipeline 负责步骤2~5）
├── services/
│   ├── mail.py             # OnlineDispoMail 客户端 + 验证码解析
│   ├── registration_mail.py# 自选邮箱 registerEmail.txt.txt（email----API）
│   ├── outlook_mail.py     # Outlook Graph + OAuth2 refresh_token
│   ├── yich8_mail.py       # changeEmail 的 yich8 HTTP 取码
│   ├── email_pool.py       # changeEmail.txt 取一个删一个
│   ├── account_store.py    # muse账号.xls 追加（xlrd/xlwt）
│   ├── ledger.py           # JSONL 账本，追加 + 原子更新 + CSV 导出
│   └── identity.py         # 生日等身份数据
├── runner/
│   ├── context.py          # 组装 device/session/app/components
│   ├── artifacts.py        # 每次运行一个产物目录
│   └── batch.py            # 有界并发、离线开机、结果聚合
└── config/settings.json    # 运行配置（含 API key，已 gitignore）
```

## 4. 为什么这样切

### 4.1 扫描/连接独立（`vmos/`）

`discovery.py` 只做三件事：找候选 IP、验证是不是 VMOS、拉实例列表。
它不知道 Muse，也不知道注册。换 App 不需要改它。

`transport.py` 是唯一打开 socket 的地方，统一处理：

- 绕过系统 HTTP 代理（VMOS 在可信内网）；
- 超时与重试（5xx/连接失败重试，4xx 不重试）；
- `{"code": 200, "data": ...}` 业务信封；
- 二进制响应（截图）。

`device.py` 是唯一知道 Android API 路径的地方，并保留旧镜像的 shell 兜底：
`accessibility/dump` 失败 → `uiautomator dump` + `cat`；`input/click` 失败 → `input tap`。
业务层永远不用拼 shell。

### 4.2 UI 独立（`ui/`）

- `UiTree` 是解析后的控件树，带 `nodes` 扁平列表和 `summary()`；
- `Selector` 是**数据**，不是代码：`Selector(label_contains=("continue",))`；
- `UiSession` 提供意图级方法：`find / wait_for / click / fill / back / screenshot`；
- 选择器可拿一份保存的 dump 做单元测试，不需要设备。

这样解决参考项目「27 处 `ET.fromstring`、98 处 `node_center`」的问题。

### 4.3 App 适配层（`apps/muse/`）

只放 Muse 的事实：

- `app.py`：包名 `com.facebook.aura`、启动、前台判断；
- `selectors.py`：文案/ID；
- `pages.py`：纯函数页面识别；
- `components.py`：一个控件组的操作；
- `flows/`：业务流程。

换 App 时复制 `apps/muse` 为 `apps/xxx`，`ui`/`vmos`/`runner` 不动。

### 4.4 业务流程组件化

| 层 | 职责 | 例子 |
|---|---|---|
| **Page** | 识别当前页面 | `Page.OTP`、`Page.BIRTHDAY` |
| **Component** | 操作一个控件组 | `EmailForm.enter()`、`OtpForm.submit()` |
| **Flow** | 状态机/步骤编排 | `RegisterFlow` |
| **Runner** | 多实例并发/生命周期 | `BatchRunner` |
| **App adapter** | 包名/入口/版本 | `MuseApp` |

### 4.4.1 脚本注册表（`scripts/`）

实例和脚本是两张独立的表：

- 实例表只知道 `host + db_id + 状态`；
- 脚本表只知道 `id + 名称 + App + 参数字段 + flow factory`；
- `data/gui_state.json` 保存“实例 key → script_id”的绑定。

`ScriptSpec` 示例（MuseAI 注册）：

```python
ScriptSpec(
    id="muse.register",
    name="MuseAI 批量注册",
    app_package="com.facebook.aura",
    fields=(ScriptField("mail_api_key", "API Key", kind="password", group="邮箱 API"), ...),
    defaults=lambda s: {...},
    factory=lambda settings, params, stop: PreparedScript(settings, RegisterFlow(...)),
    billable=True,
)
```

GUI 的「脚本与参数」页直接遍历 `fields` 生成表单；新增脚本不需要改 GUI。

Flow 里没有选择器、没有坐标、没有 XML、没有 URL。它只写：

```python
if match.page is Page.EMAIL:
    components.enter_email(mailbox.email)
elif match.page is Page.OTP:
    components.enter_code(code)
```

### 4.5 服务独立（`services/`）

- `MailClient`：余额、服务列表、买邮箱、轮询验证码；42001 视为「还没到」；
- `CustomMailProvider`：从 `registerEmail.txt.txt` 取 `email----API`，每注册一次消耗一行；
  轮询 API 并解析纯文本/HTML/JSON 中的 6 位码；
- `OutlookMailProvider`：从 `outlookMail.txt` 取
  `email----password----client_id----refresh_token`，用 OAuth2 刷新 access_token，
  再读 Microsoft Graph `/me/messages` 提取验证码；
- `Ledger`：JSONL，买到邮箱立刻落盘，更新用临时文件 + `os.replace`；
- `identity`：生日等纯函数。

它们不 import 设备，可以单独 CLI/测试。

### 4.6 GUI 适配层（`gui/`）

GUI 按业务拆成四个视图，互不复制业务逻辑：

| 视图 | 只负责 |
|---|---|
| `instances_view.py` | 实例扫描、搜索、IP/状态筛选、选择、实例→脚本绑定 |
| `scripts_view.py` | 脚本注册表、当前脚本自己的参数表单、邮箱 API 余额 |
| `run_view.py` | 运行参数（并发/最多/出错停止/自动轮数/每轮等待）、结果表、实时日志 |
| `inspect_view.py` | 页面诊断输出 |

`gui/app.py` 只做编排：后台线程 + 事件队列 + 按实例的脚本分组调用
`ScriptSpec.prepare()` 和 `BatchRunner`。它不拼 URL、不解析 XML、不碰设备。
`python -m muse_auto gui` 与 `python -m muse_auto run ...` 走同一套 Flow。

自动多轮由调用层负责：GUI 的 `_run_worker` / CLI 的 `_cmd_run` 按 `rounds` 循环，
每轮重新调用 `ScriptSpec.prepare()` 和 `BatchRunner.run()`，轮间用 `StopToken.sleep()`
等待 `round_interval` 秒，可被停止按钮打断。默认 `rounds=2`、间隔 `10s`。

### 4.7 步骤 1~6：可组合流程

`MusePipelineFlow` 只按编号顺序跑选中的步骤：

```text
1 RegisterFlow（注册到 HOME）
2 AccountCenter + Yich8MailClient（换邮箱）
3 InviteCenter（Settings→Redeem referral code）
4 InviteCenter.read_own_code()（首页 Invite 弹框）
5 MuseAccountStore（muse账号.xls: 账号 / 创建时间 / 账号-api / 邀请码 / 本号邀请码）
6 MuseApp.clear_data()（pm clear，清 cache+storage）
```

默认 `1→2→3→4→5`。步骤3从 `inviteCode.txt` 取未满 30 次的码并回写
`code---用了N次`；用满自动换下一行。步骤2和步骤3失败时会 force-stop/重启 Muse，
最多重试 3 次；步骤2会先检查邮箱是否已生效，步骤3重试时检测到“已兑换”按成功处理。
步骤5单独执行时会读取当前绑定邮箱；步骤2单独执行要求实例在首页；步骤4要求首页并读取本号邀请码；步骤6可以单独执行。
CLI 用 `--steps 1,2,3,4,5,6` / `--flow-name`，GUI 用 1~6 勾选框。

## 5. 一次注册的调用链

```text
cli run register
  └─ discover_instances()                 # 配置 + adb + /24
      └─ BatchRunner.run(instances, task)
          ├─ 实例离线？ start_offline ? ContainerApi.start : skip
          ├─ build_context()
          │   ├─ DeviceApi(instance)
          │   ├─ UiSession(device)
          │   ├─ MuseApp(device)
          │   └─ MuseComponents(session, app)
          └─ RegisterFlow.run(ctx)
              ├─ app.installed() / app.launch()
              ├─ 等一个已知页面（不买邮箱）
              ├─ mail.buy_mailbox()       # 第一个付费动作
              ├─ ledger.upsert(...)
              └─ 状态机循环
                  ├─ Page.PERMISSION → dismiss_permission()  # 精确匹配 ALLOW，避免点到 DON'T ALLOW
                  ├─ Page.WELCOME    → advance_welcome()
                  ├─ Page.EMAIL      → enter_email()  → ledger=email_submitted
                  ├─ Page.OTP        → wait_for_code() → enter_code() → ledger=otp_verified
                  ├─ Page.BIRTHDAY   → enter_birthday()
                  ├─ Page.AGE_GATE   → skip_age_gate()（等待 IG/FB OAuth 返回）
                  ├─ Page.HOME       → 步骤2 EmailPool.take → AccountCenter.change_email
                  │                    → Yich8MailClient.wait_for_code
                  │                    → 步骤3 InviteCenter.redeem(inviteCode.txt)
                  │                    → 步骤4 InviteCenter.read_own_code()
                  │                    → 步骤5 MuseAccountStore.append → muse账号.xls
                  │                    → 步骤6 pm clear
                  └─ Page.UNKNOWN    → 保存 dump+截图 → UnknownPage
```

关键点：**先启动/识别，再买邮箱**。如果实例已经登录，直接
`already_signed_in`，不消耗余额。

## 6. 页面识别

`pages.py` 是纯函数，输入 `UiTree` + 前台包名，输出 `PageMatch(page, reason, edit_count)`。
规则按「最具体 → 最宽泛」排序：

```text
PERMISSION → SYSTEM_SHEET → ERROR → OTP → ONBOARDING → BIRTHDAY → AGE_GATE
          → EMAIL → INVITE → SETTINGS → HOME → WELCOME
```

为什么 OTP 在 EMAIL 前面：验证码页同时含 `email` 和 `code`，先匹配 OTP 才不会误判。
为什么 AGE_GATE 在 EMAIL 前面：年龄页可能也带 `email` 字样。
真机还会弹出 Google credential manager（`SYSTEM_SHEET`）和网络错误页（`ERROR`），
两者都要在业务动作之前处理。

识别失败不猜坐标：保存 `fail.xml` / `fail.png` / `fail.json`，抛 `UnknownPage`。
这是刻意的——**未知页面必须变成可诊断事件**，而不是随机点击。

## 7. 失败、重试、停止

| 异常 | 来源 | 处理 |
|---|---|---|
| `VmosConnectionError` | 主机/实例不可达 | 重试 2 次；仍失败则实例失败 |
| `VmosApiError` | 业务 code 非 200 | 4xx 不重试；5xx 重试 |
| `DeviceError` | Android 命令失败 | 上报 Flow；可重试的由 Session 重试 |
| `NodeNotFound` | 选择器找不到 | 组件抛 `FlowError`，Flow 保存现场 |
| `UnknownPage` | 页面不认识 | 保存 dump/截图，标记失败 |
| `MailError` | 邮箱 API/超时 | 标记失败；账本保留已买邮箱 |
| `Stopped` | Ctrl+C/停止 | 立即展开，账本标记 stopped |

`StopToken` 贯穿所有等待：`sleep()` 被 stop 唤醒，不会卡 180 秒。

`UiSession.dump()` 用 `retry_call` 重试 3 次；`DeviceApi` 内部对旧镜像自动兜底。

## 8. 产物与账本

每次实例运行一个目录：

```text
artifacts/20261104-193000_PH19L-003/
├── smoke.xml / smoke.png / smoke_meta.json
├── fail.xml / fail.png / fail.json        # 失败现场
├── success.xml / success.png              # 成功现场
└── result.json                            # email/order/status
```

账本 `data/accounts.jsonl`：

```json
{"email":"...","order_id":"...","status":"registered","instance":"PH19L-003",
 "host":"192.168.1.18","db_id":"EDGE...","invite_redeemed":false,...}
```

状态机：`mailbox_bought → email_submitted → otp_verified → registered → invite_redeemed`
失败：`failed` / `manual_required`。

`ledger --csv out.csv` 可导出 Excel 友好的 CSV。

## 9. 邮箱与成本

- 服务商：`https://api.online-disposablemail.com`；
- 通过 `/api/services` 按名称找 `Meta Ai`（serviceId 302）；
- 买邮箱：`GET /api/mailbox?apiKey=...&serviceId=302&emailTypeId=26`；
  实测 `emailTypeId=1/3/4` 对 Meta Ai 返回 41001，`26`（Gmail_1）可用；
- 取码：`GET /api/latest/code?orderId=...`，42001 = 等待中；
- 验证码从 `data.code` 或 HTML 正文提取（6–8 位，支持 `123 456` 分隔）。

余额在 `doctor` / `run` 前打印。MVP 默认并发 2，避免一次买太多。

## 10. 配置

`config/settings.json`，启动时校验未知字段（拼错会直接报错）。
敏感项可被环境变量覆盖：

| 环境变量 | 覆盖 |
|---|---|
| `MUSE_MAIL_API_KEY` | `mail.api_key` |
| `MUSE_VMOS_HOSTS` | `vmos.hosts`（逗号分隔） |
| `MUSE_INVITE_POOL` | `run.invite_pool_path` |
| `MUSE_LOG_LEVEL` | `logging.level` |

## 11. 扩展指南

### 加一个页面

1. `pages.py` 加 `Page.XXX` 和识别文案；
2. `selectors.py` 加选择器；
3. `components.py` 加一个组件方法；
4. `flows/register.py` 加一个 `elif match.page is Page.XXX`；
5. 用 `inspect --tree` 的真实 dump 写一个 fixture + 单元测试。

### 加一个 App

复制 `apps/muse` → `apps/otherapp`，改 `app.py`/`selectors.py`/`pages.py`，
新增对应 Flow；`vmos`/`ui`/`runner` 不改。

### 加一个脚本

在 `scripts/` 新增模块，定义 `ScriptSpec`：

```python
MY_SCRIPT = ScriptSpec(
    id="myapp.login",
    name="MyApp 登录",
    app_package="com.example.myapp",
    fields=(ScriptField("account", "账号", required=True),),
    defaults=lambda s: {"account": ""},
    factory=build_myapp_flow,
)
```

再把它加入 `scripts/registry.py` 的 `_SCRIPTS`。GUI 会自动出现在脚本列表，
参数表单会根据 `fields` 自动生成；实例页可以给实例分配该脚本。


### 加一个设备通道

在 `vmos/` 加新模块，保持 `DeviceApi` 的公开方法（dump/click/text/...）不变；
`ui` 和 `apps` 不用改。

### 加一个邮箱服务商

在 `services/` 加新客户端，暴露 `buy_mailbox()` / `wait_for_code()`；
`RegisterFlow` 只依赖这两个方法。

## 12. 已知限制（MVP）

1. **已真机跑通主链路**（`US13X-010`，2026-11-04，120 秒，`registered`）；
2. **生日滚轮已实现**：三个 `SeekBar`（Month/Day/Year），每次 100px 拖动一格，
   用 `Birthday, June 15, 1992` 按钮文案做闭环校验；
3. **OTP 是自动提交**：6 位输完 App 自己提交，不能再点 Confirm/按 BACK；
4. **账号选择**：邮箱已关联 Meta 账号时会出现
   `Choose an account to continue`，流程固定选 `Create new account`；
5. **邀请码已真机跑通**：Settings → 滑到底 → Redeem referral code → 输入
   `NW81BJ` → `Congratulations`；入口不是首页 Invite 按钮；
6. **年龄验证/绑卡未触发**：本次新账号流程未出现 `Confirm your age`；
   `skip_age_gate` 只负责点 Instagram/Facebook 链接并等 OAuth；
7. **邮箱类型**：`email_type_id=26`（Gmail_1）实测可买；1/3/4 对 Meta Ai 返回
   41001；
8. **网络是硬前提**：Muse 注册必须能访问 Meta HTTPS；测试中曾出现
   `No connection`，后来恢复。批量前先 `doctor` 检查 HTTPS 出口；
9. **无 Web UI / 无代理管理 / 无绑卡**：tkinter 控制台已有，Web/代理/绑卡是后续模块；
10. **并发默认 2**：VMOS 主机和邮箱余额都有限，先小批量验证。

## 13. 测试

```bash
python -m unittest discover -s tests -v
```

覆盖：

- XML 解析、bounds/center、选择器、可点击祖先；
- 5 个页面的识别与优先级；
- 验证码提取、服务解析、pending 处理；
- 账本追加/更新/导出；
- 配置校验/环境变量；
- 用 FakeDevice + FakeMail 跑完整注册状态机（不连设备、不花钱）。

## 14. 与参考项目的关键差异

| 维度 | 参考项目 | muse-auto |
|---|---|---|
| 入口 | tkinter `App` | CLI 子命令 |
| 设备访问 | `App.adb/tap/dump` 混在业务 | `vmos` 独立层 |
| UI 查找 | 27 处 `ET.fromstring` | `UiTree` + `Selector` |
| 页面规则 | `is_xxx` 混在 App | `pages.py` 纯函数 |
| 流程 | 线性 op + if/else | 状态机 + 组件 |
| 状态 | `row` dict | `AccountRecord` / `FlowContext` |
| 异常 | 47 处宽泛捕获 | 类型化异常 + 现场 |
| 配置 | 分散 JSON | 单文件 + 校验 + env |
| 测试 | 无 | 89 个离线测试 |
| 依赖 | xlrd/xlwt/... | 核心标准库；XLS 用 xlrd/xlwt |
