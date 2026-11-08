# Muse Auto 使用文档

Muse Auto 是一个运行在 Windows 上的 **VMOS Edge + Muse（Meta AI）自动化工具**。
它通过 VMOS 主机的 HTTP API 控制云手机，完成 Muse 账号注册、换绑邮箱、兑换邀请码、
保存账号表、清理应用数据等步骤，并提供 tkinter 图形界面和 CLI。

当前版本：`0.1.0`  
默认 App：`com.facebook.aura`（Muse）  
默认 VMOS API 端口：`18182`

---

## 1. 运行前需要准备什么

### 1.1 一台 Windows 电脑

- Windows 10 / 11，64 位；
- 能访问 VMOS Edge 主机所在的局域网；
- 便携版 exe **不需要安装 Python**。

### 1.2 VMOS Edge

需要：

1. VMOS Edge 主机在线；
2. 主机 HTTP API 端口 `18182` 可访问；
3. 云手机实例已创建；
4. 实例里已安装 Muse（`com.facebook.aura`）；
5. 注册前实例最好处于运行状态（离线实例可在配置里开启自动开机）。

默认主机写在 `config/settings.json`：

```json
"vmos": {
  "hosts": [],
  "port": 18182,
  "scan": true,
  "use_adb": true
}
```

换主机时改 `hosts`，或者把 `scan` 设为 `true` 让程序自动扫局域网。

### 1.3 注册邮箱（三选一）

#### 方式 A：onlineDispoMail API（默认）

需要：

- API 地址：`https://api.online-disposablemail.com`
- API Key；
- 邮箱余额；
- 服务：`Meta Ai`（`serviceId=302`）；
- 邮箱类型：`26`（`Gmail_1`）。

注意：`25`（Gmail_test）、`1/3/4` 会返回 `41001 Invalid parameter`。

#### 方式 B：自选邮箱 API

文件：项目根目录 `registerEmail.txt.txt`

格式，一行一个：

```text
邮箱----取验证码API
```

例如：

```text
user@example.com----https://your-mail-api.example/read?...
```

每次注册消耗一行。取码 API 需要返回验证码，或返回包含 6 位验证码的正文/HTML/JSON。
如果 API 只返回邮件标题、正文里没有数字码，程序无法提取，会轮询到超时。

#### 方式 C：Outlook 邮箱（Microsoft Graph / OAuth2）

文件：项目根目录 `outlookMail.txt`

格式：

```text
邮箱----密码----client_id----refresh_token
```

例如：

```text
example@outlook.com----your-password----00000000-0000-0000-0000-000000000000----M.C...your-refresh-token...
```

程序使用 refresh_token 调 Microsoft OAuth2 换取 access_token，再读取
`https://graph.microsoft.com/v1.0/me/messages`，从最新邮件标题/正文中提取 6 位验证码。
每次注册消耗一行。

注意：

- refresh_token 是核心授权凭据，**不要外传**；
- 需要该邮箱已授权对应 client_id，并且 refresh_token 未过期；
- 如果 Outlook 收件箱没有 Meta 验证码邮件，程序只能轮询到超时；
- 密码字段当前保留用于资料完整性，Graph 流程实际使用 client_id + refresh_token。

### 1.4 换绑邮箱（步骤2）

需要两个文件：

```text
changeEmailInfo/changeEmail.txt
changeEmailInfo/changeEmailapi.txt
```

- `changeEmail.txt`：替换邮箱池，一行一个邮箱；
- `changeEmailapi.txt`：yich8 取码 API 模板，格式：

```text
http://mail.yich8.com/api/controller.php?imap_key=...&fun=imap_read&imap_ip=127.0.0.1&port=143&delete=0&username=旧邮箱&password=Aa123456
```

程序会自动把 `username` 替换成当前替换邮箱。

### 1.5 邀请码（步骤3）

文件：项目根目录 `inviteCode.txt`

格式，一行一个：

```text
4X2K8I
WUOL2H
XWB1DI
```

每个邀请码默认可用 **30 次**。使用后程序会回写：

```text
4X2K8I---用了1次
4X2K8I---用了2次
```

满 30 次自动换下一行。可用次数和文件路径都可以在 GUI 参数里修改。

### 1.6 账号表

文件：`muse账号.xls`

五列：

```text
账号 | 创建时间 | 账号-api | 邀请码 | 本号邀请码
```

- `账号`：当前账号邮箱；
- `创建时间`：追加时间；
- `账号-api`：`账号----取码API`；
- `邀请码`：本账号使用的邀请码；
- `本号邀请码`：从首页 Invite 弹框读取的本号邀请码。

便携版附带的是只有表头的空表。需要沿用旧数据时，把旧的 `muse账号.xls` 复制到 exe 同级目录即可。

---

## 2. 便携版 exe

目录：

```text
MuseAuto-Portable/
  MuseAuto.exe             # 图形界面，双击运行
  MuseAutoCLI.exe          # 命令行版本
  config/
    settings.json          # 主配置（VMOS、邮箱、运行参数）
  changeEmailInfo/
    changeEmail.txt        # 步骤2 替换邮箱池
    changeEmailapi.txt     # 步骤2 yich8 取码 API
  registerEmail.txt.txt    # 自选注册邮箱池
  outlookMail.txt          # Outlook Graph 邮箱池
  inviteCode.txt           # 邀请码池
  muse账号.xls             # 账号表（空表）
  logs/                    # 运行日志
  artifacts/               # 失败现场、截图、dump
  data/                    # GUI 状态（首次运行创建）
  README.md
  USEDOC.md
```

### 2.1 启动

双击：

```text
MuseAuto.exe
```

不需要 Python。程序会自动读取 exe 同级的 `config/settings.json`。

### 2.2 首次配置

1. 修改 `config/settings.json` 里的 `vmos.hosts`；
2. 打开 GUI「脚本与参数」；
3. 填邮箱 API Key（如果使用 onlineDispoMail）；
4. 检查「注册邮箱来源」「邀请码文件」「每个邀请码可用次数」；
5. 保存参数；
6. 回到「实例」页点「刷新实例」。

### 2.3 CLI

```powershell
.\MuseAutoCLI.exe --help
.\MuseAutoCLI.exe discover
.\MuseAutoCLI.exe run register --instance "实例名" --steps 1,2,3,4,5,6
```

`MuseAutoCLI.exe` 有控制台，适合排错和无人值守。

---

## 3. 目录与文件用途

### 3.1 根目录

| 文件/目录 | 用途 |
|---|---|
| `MuseAuto.exe` | 便携版 GUI |
| `MuseAutoCLI.exe` | 便携版 CLI |
| `config/settings.json` | 主配置：VMOS、App、邮箱、运行参数 |
| `changeEmailInfo/changeEmail.txt` | 步骤2 替换邮箱池 |
| `changeEmailInfo/changeEmailapi.txt` | 步骤2 yich8 取码 API |
| `registerEmail.txt.txt` | 自选注册邮箱池（邮箱----API） |
| `outlookMail.txt` | Outlook Graph 邮箱池（邮箱----密码----client_id----refresh_token） |
| `inviteCode.txt` | 邀请码池与使用次数 |
| `muse账号.xls` | 账号结果表 |
| `data/gui_state.json` | GUI 保存的脚本参数、实例分配（含 API Key，勿外传） |
| `logs/` | 每次运行的日志 |
| `artifacts/` | 失败/成功现场：xml、png、json |
| `README.md` | 项目说明与开发文档 |
| `USEDOC.md` | 本文件 |
| `pyproject.toml` | Python 项目元数据 |
| `requirements.txt` | 运行依赖（xlrd/xlwt） |
| `getEmailInfo.txt` | 邮箱 API 的备注/参考，不参与运行 |
| `muse账号 *.xls` | 用户手工备份，不参与运行 |
| `tests/` | 离线单元测试 |
| `packaging/` | PyInstaller 入口脚本与打包说明 |

### 3.2 `muse_auto/` 代码模块

| 目录/文件 | 用途 |
|---|---|
| `__main__.py` | `python -m muse_auto` 入口 |
| `cli.py` | 所有 CLI 命令：discover/inspect/run/change-email/mail/ledger/doctor/gui |
| `config.py` | JSON 配置加载、校验、环境变量覆盖、项目根目录解析 |
| `vmos/` | VMOS 主机/实例/设备 API |
| `vmos/discovery.py` | 主机发现、局域网扫描、实例列表 |
| `vmos/container.py` | 主机探测、实例开关机 |
| `vmos/device.py` | dump/点击/输入/滑动/截图/Activity/包信息 |
| `vmos/transport.py` | 唯一 HTTP 客户端，超时/重试/二进制 |
| `vmos/models.py` | `VmosHost` / `VmosInstance` |
| `vmos/adb.py` | 从 `adb devices` 取主机 |
| `ui/` | 控件树层，不认识 Muse 业务 |
| `ui/parser.py` | XML → UiTree |
| `ui/selector.py` | 声明式选择器 |
| `ui/session.py` | dump/find/click/fill/wait 高层封装 |
| `ui/node.py` | 控件节点、坐标、祖先 |
| `apps/muse/` | Muse App 适配层 |
| `apps/muse/app.py` | 包名、启动、前台、清数据 |
| `apps/muse/pages.py` | 页面识别（EMAIL/OTP/BIRTHDAY/ONBOARDING/HOME…） |
| `apps/muse/selectors.py` | Muse 文案/ID 选择器 |
| `apps/muse/components.py` | 权限、邮箱、验证码、生日、年龄门、欢迎页 |
| `apps/muse/account_center.py` | 步骤2 Meta Account 换邮箱 |
| `apps/muse/invite_center.py` | 步骤3 Redeem referral code |
| `apps/muse/pipeline.py` | 步骤1~6 编排、重试、重启 App |
| `apps/muse/flows/register.py` | 注册状态机 |
| `apps/muse/flows/smoke.py` | 冒烟检查 |
| `scripts/` | 脚本注册表与参数定义 |
| `scripts/registry.py` | 内置脚本列表 |
| `scripts/muse.py` | Muse 注册脚本的字段、默认值、工厂 |
| `scripts/base.py` | `ScriptSpec` / `ScriptField` / `PreparedScript` |
| `services/` | 与设备无关的外部服务 |
| `services/mail.py` | onlineDispoMail 客户端 |
| `services/registration_mail.py` | 自选注册邮箱 email----API 客户端 |
| `services/yich8_mail.py` | 步骤2 yich8 取码 API |
| `services/email_pool.py` | 步骤2 替换邮箱池 |
| `services/invite_pool.py` | 邀请码池与次数回写 |
| `services/account_store.py` | `muse账号.xls` 读写 |
| `services/ledger.py` | JSONL 账本 |
| `services/gui_store.py` | GUI 状态持久化 |
| `services/identity.py` | 生日等身份数据 |
| `runner/` | 任务执行层 |
| `runner/context.py` | 为每个实例组装 device/session/app/components |
| `runner/batch.py` | 有界并发、单实例任务、结果 |
| `runner/artifacts.py` | 每次运行的产物目录 |
| `gui/` | tkinter 界面 |
| `gui/app.py` | 主窗口、事件队列、运行编排、多轮 |
| `gui/instances_view.py` | 实例列表、搜索、IP/状态筛选、脚本分配 |
| `gui/scripts_view.py` | 脚本列表、参数表单、邮箱余额 |
| `gui/run_view.py` | 并发/轮数/间隔、结果表、日志 |
| `gui/inspect_view.py` | 页面检查 |
| `gui/theme.py` / `widgets.py` | 主题、控件 |
| `core/` | 错误、日志、重试、停止令牌 |

---

## 4. GUI 使用

### 实例

- 刷新实例；
- 搜索实例名/db_id；
- 按 IP、状态筛选；
- 选择实例；
- 分配脚本（当前默认 MuseAI 批量注册）；
- 双击实例做页面检查。

### 脚本与参数

- 左侧选择脚本；
- 右侧填写参数；
- 「注册邮箱来源」默认 `onlineDispoMail`，也可以选「自选邮箱API」或「Outlook邮箱」；
- 「随机名字」组有 First names / Last names 两个输入框；点「随机生成 20 个 First/Last name」会各生成 20 个，姓名页出现时随机取一个。
- 邀请码文件、每个邀请码可用次数；
- 执行步骤 1~6；
- 流程名称；
- 查余额、保存、恢复默认、分配到选中实例。

### 运行

- 并发；
- 最多实例（0=全部）；
- 出错停止；
- 自动轮数（默认 2）；
- 每轮等待秒数（默认 10）；
- 开始/停止；
- 结果表带「轮」列；
- 实时日志。

---

## 5. 步骤说明

| 步骤 | 内容 |
|---|---|
| 1 | 注册账号：买邮箱/取自选邮箱 → 邮箱页 → OTP → 生日 → 年龄验证 → 欢迎页 → 首页 |
| 2 | 换绑定邮箱：Settings → Meta Account → Add email → yich8 取码 → 保存新邮箱 |
| 3 | 兑换邀请码：Settings → 滑到底 → Redeem referral code → 输入 `inviteCode.txt` 的码 |
| 4 | 获取本号邀请码：首页右上角 Invite → Invite friends 弹框 → 读取本号邀请码 |
| 5 | 保存 `muse账号.xls`：账号、创建时间、账号-api、邀请码、本号邀请码 |
| 6 | 清除 Muse 缓存/存储（`pm clear`） |

默认 `1→2→3→4→5→6`。

步骤2/3失败会 **force-stop + 重开 Muse + 回首页**，最多尝试 3 次：

- 步骤2重试前会读当前绑定邮箱，已生效则直接完成；
- 步骤3复用同一个邀请码，重试时检测到已兑换按成功处理；
- 3 次都失败才回滚邮箱/邀请码次数。

---

## 6. 配置文件说明

`config/settings.json` 主要节点：

```json
{
  "vmos": {
    "hosts": [],
    "port": 18182,
    "scan": true,
    "use_adb": true,
    "start_offline": false
  },
  "app": {
    "package": "com.facebook.aura",
    "clear_data_before_register": false
  },
  "mail": {
    "base_url": "https://api.online-disposablemail.com",
    "api_key": "...",
    "service": "Meta Ai",
    "email_type_id": 26
  },
  "run": {
    "mail_source": "onlineDispoMail",
    "register_email_path": "registerEmail.txt.txt",
    "outlook_mail_path": "outlookMail.txt",
    "invite_pool_path": "inviteCode.txt",
    "invite_uses_per_code": 30,
    "email_pool_path": "changeEmailInfo/changeEmail.txt",
    "email_api_path": "changeEmailInfo/changeEmailapi.txt",
    "account_xls_path": "muse账号.xls",
    "birthday": "1992-06-15",
    "first_names": "",
    "last_names": "",
    "steps": "1,2,3,4,5,6",
    "rounds": 2,
    "round_interval": 10.0
  }
}
```

环境变量覆盖：

```powershell
$env:MUSE_MAIL_API_KEY="..."
$env:MUSE_VMOS_HOSTS="192.168.1.104"
$env:MUSE_INVITE_POOL="inviteCode.txt"
$env:MUSE_INVITE_USES="30"
```

---

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| GUI 刷新 0 个实例 | 检查 `vmos.hosts`；VPN/虚拟网卡可能抢默认路由，建议显式配置主机 |
| 实例未运行 | 配置 `vmos.start_offline=true`，或手动开机 |
| 未安装 `com.facebook.aura` | 先在实例安装 Muse |
| 邮箱 41001 | `Meta Ai` 必须 `emailTypeId=26` |
| 验证码一直不到 | 检查邮箱 API；自选邮箱 API 是否返回正文/6 位码；Outlook 是否有 Meta 邮件 |
| Outlook OAuth2 失败 | 检查 client_id/refresh_token 是否有效；token 可能已过期 |
| Outlook 收件箱没有新邮件 | 确认邮箱地址正确、垃圾邮件箱/其他文件夹，Meta 可能未投递 |
| 生日页出现 First/Last name 输入框 | 自动从随机名字池取 First/Last name，填写生日后点 Confirm 继续 |
| 年龄验证页一直不跳转 | 自动 `pm clear` 清除 Muse 缓存/存储，下一轮重新注册 |
| 邀请码已成功但日志报输入失败/重复填写 | 邀请码输入不再回读校验；检测 Success 或错误文案，成功一次即结束 |
| 步骤2 等待 `account settings` 超时 / 点不到邮箱 | 新版 Meta Account 页改为等待 `Login and security`/`Default contact info`；WebView 按钮左点无效时自动中间重点 |
| 本号邀请码读不到 / 全字母码 | 支持无数字邀请码和带空格拆分；步骤4最多重试 3 次 |
| 首页右上角只有礼物图标 | 自动识别 Invite/gift/reward 文本或无描述的最右侧图标按钮 |
| 邀请码已满 30 次仍被调用 | 失败不再回滚已占用次数，满 30 自动换下一码 |
| 注册后系统权限弹框 | 当前轮最多尝试 3 次点击 ALLOW |
| 年龄验证后出现 A few things to know | 已识别为 ONBOARDING，会自动点 Get started |
| 步骤2/3失败 | 会自动重启 Muse 重试 3 次；看日志和 artifacts |
| XLS 被 WPS/Excel 占用 | 写备用快照 + pending 日志；关闭表格后 `MuseAutoCLI.exe ledger --xls-merge` |
| 邀请码用完 | 补 `inviteCode.txt` 或增大每个码次数 |
| 启动时提示配置错误 | 确认 `config/settings.json` 与 exe 同级 |

---

## 8. 安全提醒

- `config/settings.json`、`data/gui_state.json` 内含邮箱 API Key，**不要外传**；
- `muse账号.xls` 含真实账号，**不要公开**；
- `logs/`、`artifacts/` 可能含邮箱、验证码、截图；
- 便携版默认带上当前 `config/settings.json`，分享给他人前把 Key 清空；
- 本工具仅用于自己的账号/设备，遵守目标平台条款。

---

## 9. 从源码构建 exe

### 9.1 安装依赖

```powershell
python -m pip install -r requirements.txt pyinstaller
```

### 9.2 构建 GUI

```powershell
python -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name MuseAuto --paths . `
  --collect-submodules muse_auto `
  --collect-all xlrd --collect-all xlwt `
  packaging/gui_entry.py
```

### 9.3 构建 CLI

```powershell
python -m PyInstaller --noconfirm --clean --onefile --console `
  --name MuseAutoCLI --paths . `
  --collect-submodules muse_auto `
  --collect-all xlrd --collect-all xlwt `
  packaging/cli_entry.py
```

### 9.4 组装干净便携目录

不要手工复制开发目录里的邮箱池、XLS、日志，直接运行：

```powershell
python packaging/build_portable.py
```

脚本会生成 `dist/MuseAuto-Portable/`，并**新建空模板**：

```text
MuseAuto.exe
MuseAutoCLI.exe
config/settings.json          # API Key 为空，hosts 为空
outlookMail.txt               # 只有注释，没有真实邮箱
changeEmailInfo/changeEmail.txt
changeEmailInfo/changeEmailapi.txt
registerEmail.txt.txt
inviteCode.txt
muse账号.xls                  # 只有 5 列表头
README.md
USEDOC.md
logs/ artifacts/ data/        # 空目录
```

脚本明确不会复制：

```text
outlookMail.txt
changeEmailInfo/
registerEmail.txt.txt
inviteCode.txt
muse账号.xls
logs/
artifacts/
data/
```

打包后把需要使用的邮箱/邀请码/API Key 填进新包，不要从开发目录覆盖。

### 9.5 离线运行要求

PyInstaller 已把 Python、tkinter、xlrd、xlwt 打进 exe；目标机器不需要 Python。
前提是 Windows 10/11 64 位，且能访问 VMOS 主机和邮箱 API。

---

## 10. 快速检查清单

- [ ] VMOS Edge 主机在线，`18182` 可访问
- [ ] 实例已安装 Muse
- [ ] `config/settings.json` 的 `vmos.hosts` 正确
- [ ] 注册邮箱来源可用（onlineDispoMail 余额/Key，或自选邮箱文件）
- [ ] `changeEmailInfo/changeEmail.txt` 有替换邮箱
- [ ] `changeEmailInfo/changeEmailapi.txt` 可访问
- [ ] `inviteCode.txt` 有未用满的邀请码
- [ ] `muse账号.xls` 没被 WPS/Excel 占用
- [ ] 要保留登录态就不要勾步骤6
