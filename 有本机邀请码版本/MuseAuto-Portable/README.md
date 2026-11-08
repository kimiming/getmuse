# muse-auto

VMOS Edge 云机 + **Muse (Meta)** Android App 的模块化 Python 自动化框架。
当前目标：**扫描/连接云机 → 启动 Muse → 注册 → 验证码 → 生日 → 首页 →
更换绑定邮箱 → 写入 muse账号.xls**。

- 核心纯标准库；只有 XLS 步骤用 `xlrd` / `xlwt`；
- 设备层、UI 层、App 适配层、业务流程、邮箱/账本全部拆开；
- 每个实例独立上下文，有界并发；
- 失败保存 dump + 截图 + 页面摘要，不猜坐标；
- 提供 **tkinter 操作界面**（实例 / 脚本与参数 / 运行 / 页面检查），也保留 CLI。

> **状态（2026-11-04）**：注册主链路已在 `US13X-010` 真机跑通；
> 步骤2/3 已在 `US测试AI` 真机跑通（换绑 3 个邮箱并写入 `muse账号.xls`）。
> `serviceId=302`（Meta Ai），`emailTypeId=26`（Gmail_1）。

## 1. 快速开始

要求：Windows 10/11，Python 3.10+（已用 3.15 验证），与 VMOS 主机同一私网。
XLS 步骤需要：

```powershell
python -m pip install xlrd xlwt
```

### 1.1 图形界面（推荐日常使用）

```powershell
cd C:\Users\Administrator\Desktop\museAI
python -m muse_auto gui
```

![Muse Auto GUI](docs/gui.png)

界面按模块拆成 4 个 Tab：

| 模块 | 功能 |
|---|---|
| **实例** | 实例名/状态/db_id/IP/ADB/脚本列；搜索、按 IP 筛选、按状态筛选；全选运行中/当前筛选；分配脚本；双击页面检查 |
| **脚本与参数** | 左侧脚本注册表（MuseAI 批量注册 / 冒烟检查）；右侧当前脚本自己的参数：邮箱 API 地址/Key/service/emailTypeId、邀请码文件/每个码可用次数、生日、随机 First/Last name（一键生成各 20 个）、年龄验证、清空数据、执行步骤 1~6、流程名称、换绑邮箱池/取码 API/账号 XLS；查余额、保存、恢复默认、分配到选中实例 |
| **运行** | 运行参数（并发、最多实例、出错停止、自动轮数、每轮等待秒数）+ 开始/停止 + 任务结果 + 实时日志；默认 2 轮、每轮结束等 10 秒 |
| **页面检查** | 前台 Activity、屏幕、安装状态、页面识别、控件树摘要、截图/artifacts 路径 |
| **说明** | 模块说明、当前配置、推荐流程 |

![脚本与参数](docs/gui-scripts.png)

关键点：

- 实例只负责“是哪台机器、跑哪个脚本”，不保存业务参数；
- 脚本参数跟着脚本走，当前是 `muse_auto/scripts/` 里的 `ScriptSpec`；
- 运行参数（并发/最多/出错停止）只在「运行」页；
- 每个实例的脚本选择会保存到 `data/gui_state.json`；换 App 脚本不影响实例表。

新增一个 App 脚本（不改 GUI）：

1. 新建 `apps/<app>/`（复用 `ui`/`vmos`）；
2. 在 `scripts/<app>.py` 定义 `ScriptSpec`（参数 `fields`、默认值、`factory`）；
3. 加入 `scripts/registry.py` 的 `_SCRIPTS`。

GUI 会自动出现该脚本，并根据 `fields` 生成参数表单；实例表可以分配它。

启动后会自动扫描一次实例；也可以关掉自动扫描：

```powershell
python -m muse_auto gui --no-auto-discover
```

### 1.2 命令行

```powershell
# 1) 自检：配置、邮箱余额、主机、App
python -m muse_auto doctor

# 2) 只发现，不操作
python -m muse_auto discover --running

# 3) 看某个实例的真实页面/控件树/截图（第一次必做）
python -m muse_auto inspect --instance PH19L-003 --tree

# 4) 启动 + 识别，不开邮箱、不点业务
python -m muse_auto run smoke --instance PH19L-003

# 5) 注册计划（不买邮箱、不点 App）
python -m muse_auto run register --instance PH19L-003 --limit 1 --dry-run

# 6) 真跑一个（会买 1 个邮箱，消耗余额）
python -m muse_auto run register --instance PH19L-003 --limit 1

# 7) 批量（先小批量）
python -m muse_auto run register --all-running --limit 3 --concurrency 2 `
  --invite-code YOUR_CODE
```

> `--limit` 默认 1，`0` 表示不限制。批量前先用 1 个实例跑通。

## 2. 配置

`config/settings.json`（已从 `getEmailInfo.txt` 填入 API key；该文件在 `.gitignore` 中）：

```json
{
  "vmos": {
    "hosts": [],
    "scan": true,
    "use_adb": true,
    "start_offline": false,
    "start_timeout": 90
  },
  "app": {
    "package": "com.facebook.aura",
    "launch_wait": 8,
    "action_delay": 0.6,
    "clear_data_before_register": false
  },
  "mail": {
    "base_url": "https://api.online-disposablemail.com",
    "api_key": "d7a55f...",
    "service": "Meta Ai",
    "email_type_id": 26,
    "poll_timeout": 180
  },
  "run": {
    "concurrency": 2,
    "mail_source": "onlineDispoMail",
    "register_email_path": "registerEmail.txt.txt",
    "outlook_mail_path": "outlookMail.txt",
    "invite_pool_path": "inviteCode.txt",
    "invite_uses_per_code": 30,
    "age_gate": "instagram",
    "birthday": "1992-06-15",
    "change_email": true,
    "email_pool_path": "changeEmailInfo/changeEmail.txt",
    "email_api_path": "changeEmailInfo/changeEmailapi.txt",
    "account_xls_path": "muse账号.xls",
    "steps": "1,2,3,4,5,6",
    "flow_name": "默认全流程",
    "rounds": 2,
    "round_interval": 10.0
  }
}
```

敏感项可用环境变量覆盖：

```powershell
$env:MUSE_MAIL_API_KEY="..."
$env:MUSE_VMOS_HOSTS="192.168.1.18,192.168.1.73"
$env:MUSE_INVITE_POOL="inviteCode.txt"
```

## 3. 命令

| 命令 | 作用 |
|---|---|
| `gui` | 打开 tkinter 操作界面（推荐） |
| `discover` | 配置 + `adb devices` + 本机 /24 扫描，列出主机/实例 |
| `inspect` | 指定实例：前台 Activity、分辨率、安装状态、页面识别、控件树、截图 |
| `run smoke` | 启动 App，抓页面并保存 `smoke.xml/png/meta.json` |
| `run register` | 批量注册/自定义步骤（`--steps`、`--flow-name`、`--rounds`、`--interval`） |
| `change-email` | 对已注册实例单独执行步骤2/3：换邮箱 + 写 XLS |
| `mail balance` | 邮箱余额 |
| `mail services --filter meta` | 服务列表/ID |
| `ledger` | 账本统计；`--csv out.csv` 导出 |
| `doctor` | 全量自检 |

通用参数：

- `--host 192.168.1.18`：追加主机（可重复）；
- `--no-scan` / `--no-adb`：关闭扫描 / 关闭 adb；
- `--config other.json`：换配置；
- `--log-level DEBUG`：调试日志。

## 4. 第一次跑：先校准选择器

Muse 的 UI 文案会随版本/语言变化。MVP 的选择器按 Meta 常见英文流程写，
**必须**先用真实 dump 校准：

```powershell
python -m muse_auto inspect --instance PH19L-003 --tree --launch
```

输出示例：

```text
实例：PH19L-003 [EDGE...] 192.168.1.18
前台：com.facebook.aura/com.facebook.aura.MainActivity
屏幕：1080x2400
App ：com.facebook.aura installed=True version=14.0.0.4.149
页面：welcome（welcome copy）
控件：57 个
摘要：Muse / Your personal AI agent / Get started / Continue with email ...
产物：...\artifacts\20261104-193000_inspect_PH19L-003
```

`ui.xml` 里每个 `<node>` 的 `text` / `content-desc` / `resource-id` 就是选择器来源：

| 想找的控件 | 用哪个 |
|---|---|
| 文案是 "Continue" | `Selector(text="Continue")` |
| 文案包含 "continue" | `Selector(label_contains=("continue",))` |
| 输入框 | `Selector(editable=True)` |
| 某个 ID 包含 email | `Selector(resource_id_contains=("email",))` |
| 可点击按钮 | 文案选择器 + 点击时自动向上找可点击祖先 |

改选择器只需要改 `muse_auto/apps/muse/selectors.py`，不要改 Flow。

## 5. 页面与流程

`apps/muse/pages.py` 的识别顺序：

```text
PERMISSION → SYSTEM_SHEET → ERROR → OTP → ONBOARDING → BIRTHDAY → AGE_GATE
          → EMAIL → INVITE → SETTINGS → HOME → WELCOME
```

`RegisterFlow` 的状态机：

```text
launch
  → 关闭 Google 账号弹层 / 权限弹窗
  → 等待已知页面（此时不买邮箱）
  → 买邮箱 / 落账本
  → WELCOME: 点 Continue with email
  → EMAIL:   填邮箱 + Continue
  → OTP:     轮询邮箱 → 6 位自动提交
  → BIRTHDAY:三滚轮拨到生日 + Confirm
  → AGE_GATE:点 Instagram/Facebook 链接，等 OAuth 返回
  → HOME:    步骤1 完成
  → UNKNOWN: 保存现场 → 失败
```

### 步骤 1~6 与自定义流程

`MusePipelineFlow` 把业务拆成 6 个可组合步骤：

| 编号 | 步骤 | 说明 |
|---|---|---|
| 1 | 注册账号 | 买邮箱 → 注册 → 到首页；会消耗邮箱余额 |
| 2 | 更换绑定邮箱 | 从 `changeEmail.txt` 取一个 → Meta Account 换绑 → yich8 取码 |
| 3 | 兑换邀请码 | 从 `inviteCode.txt` 取未满 30 次的码 → Settings → Redeem referral code |
| 4 | 获取本号邀请码 | 首页右上角 `Invite` → Invite friends 弹框 → 读取本号邀请码 |
| 5 | 保存 muse账号.xls | 保存账号/API/本次邀请码/本号邀请码 |
| 6 | 清除 Muse 缓存/存储 | `pm clear com.facebook.aura`，同时清 cache + storage |

默认流程：`1 → 2 → 3 → 4 → 5 → 6`。

邀请码在 `inviteCode.txt` 里，一行一个；每个码默认用 30 次，用一次回写
`4X2K8I---用了1次`，满 30 次自动换下一行。可用次数和文件路径都在「脚本与参数」里修改。

可以只执行其中一个，也可以任意组合：

```powershell
# 只清缓存/存储（不注册，步骤6）
python -m muse_auto run register --instance "US测试AI" --steps 6

# 对已登录实例：换邮箱 + 兑换邀请码 + 本号邀请码 + 保存
python -m muse_auto run register --instance "US测试AI" --steps 2,3,4,5

# 注册 + 换邮箱 + 邀请码 + 本号邀请码 + 保存，不清理
python -m muse_auto run register --instance "US测试AI" --steps 1,2,3,4,5

# 自定义流程名称
python -m muse_auto run register --instance "US测试AI" `
  --steps 1,2,3,4,5 --flow-name "注册后换邮箱并邀请"

# 自动多轮：默认 2 轮、每轮间隔 10 秒
python -m muse_auto run register --instance "US测试AI" --rounds 3 --interval 30
```

GUI「运行」页也可以直接改**自动轮数**和**每轮等待(秒)**，默认 `2` 轮、`10` 秒。
每轮结束后等待，再对同一批实例重新执行整条流程；任务结果表会带“轮”列。

依赖关系：

- 步骤3单独执行时要求实例在首页；从 `inviteCode.txt` 取码，全部用满会报错；
- 步骤4单独执行时要求实例在首页，会点右上角 `Invite` 读取本号邀请码；
- 步骤5单独执行时，如果不知道当前邮箱，会进入 Meta Account 读取当前绑定邮箱，再写 XLS；
- 步骤2单独执行时，实例必须已经在 Muse 首页；
- 步骤6可以单独执行；
- 步骤按编号顺序执行，不会按输入顺序倒序。

GUI 的「脚本与参数」页有 1~6 的步骤勾选框和「流程名称」输入框，选好后保存即可。

### 步骤 2 / 3 / 4 / 5：换邮箱、邀请码、本号邀请码、保存账号

步骤2、步骤3都支持**最多 3 次重试**：

```text
失败 → force-stop Muse → 重新启动 → 回首页 → 再执行整步
```

- 步骤2重试前会读取当前绑定邮箱，如果上一次其实已经换成功，直接算完成；
- 步骤3复用同一个邀请码；如果重试时页面显示“已兑换”，按成功处理，不再多占次数；
- 3 次都失败才恢复邮箱池/邀请码次数，并把任务标为失败。

注册进入首页后，如果步骤包含 2/3 会自动执行：

```text
左上角抽屉 → Settings（左下角）→ 滑到底部
→ Meta Account → 当前邮箱 → Default contact info
→ 当前邮箱 → Contact points → Add or edit contact info
→ Add new contact info → Add email → 输入替换邮箱 → Next
→ 从 changeEmailInfo/changeEmailapi.txt 的 yich8 API 取码
→ 输入 confirmation code → Next → Email added
→ 把新邮箱 + 当前时间追加到 muse账号.xls
```

步骤3（兑换邀请码）：

```text
首页左上角抽屉 → Settings（左下角）→ 滑到底部
→ Redeem referral code → 等待页面
→ 输入邀请码（从 inviteCode.txt 取）→ 点底部 Redeem
→ Congratulations / redemption successful
```

相关文件：

| 文件 | 作用 |
|---|---|
| `changeEmailInfo/changeEmail.txt` | 替换邮箱池，一行一个；`EmailPool.take()` 取第一个并写回剩余 |
| `changeEmailInfo/changeEmailapi.txt` | yich8 取码 API 模板，`username` 自动替换 |
| `inviteCode.txt` | 邀请码池；一行一个，使用后回写 `---用了N次`，满 30 次换下一行 |
| `muse账号.xls` | 五列：`账号`、`创建时间`、`账号-api`、`邀请码`、`本号邀请码` |

`账号-api` 示例：

```text
9285xw33pk5@yich8.com----http://mail.yich8.com/api/controller.php?imap_key=imap_hehe6688hdhd985&fun=imap_read&imap_ip=127.0.0.1&port=143&delete=0&username=9285xw33pk5@yich8.com&password=Aa123456
```

旧的两列/三列 XLS 会自动补 `账号-api` 和 `邀请码` 列；脚本会从 `changeEmailapi.txt` 读取模板并替换 `username`。

如果 `muse账号.xls` 正被 WPS/Excel 打开（Windows 会锁文件），步骤5会：

1. 写一份 `muse账号_YYYYMMDD_HHMMSS.xls` 快照；
2. 把行写入 `muse账号.xls.pending.jsonl`；
3. 关闭表格软件后执行以下命令合并回主文件：

```powershell
python -m muse_auto ledger --xls-merge
```

下次追加时也会自动合并。

单独对已注册实例执行：

```powershell
python -m muse_auto change-email --instance "US测试AI" --host 192.168.1.104 --no-scan --no-adb
```

`--no-save` 只换邮箱不写 XLS；`--email` 可指定邮箱而不从池里取。

### 已用真实实例校准的部分

测试实例：`US13X-010`（`192.168.1.104`，Muse 版本由 Play 安装）。

| 页面 | 真机文案/控件 | 代码处理 |
|---|---|---|
| 邮箱页 | `Welcome to Muse`、`Mobile number or email`、`Continue`、`AuraTextInput` | `Page.EMAIL` + `enter_email` |
| Google 弹层 | `Sign in with Google`、`Close sheet` | `Page.SYSTEM_SHEET` + `dismiss_system_sheet` |
| 验证码页 | `Enter your code to sign up`、`We sent your code to …`、`Confirm` | `Page.OTP` + `enter_code` |
| 生日页（官方截图） | `Finish creating your account`、预填 `March 17, 2000`、`Confirm` | 先试 `%B %d, %Y`，再试 `%m/%d/%Y` |
| 年龄页（官方截图） | `Confirm your age`、卡号/MM/YY/CVV、`continue with your Instagram or Facebook account` | `skip_age_gate` |
| 聊天首页（官方截图） | `Muse`、`Invite`、`Message`、`Hey! I'm your personal agent…` | `Page.HOME` + `redeem_invite` |

### 真机测试结果

2026-11-04 在 `US13X-010`（`192.168.1.104`）上完整跑通注册主链路；
步骤2/3 在 `US测试AI`（`192.168.1.104:31097`）上跑通。

```text
邮箱页 → OTP → 账号选择 → 生日滚轮 → 引导页 → 聊天首页
耗时 120 秒，结果 registered
```

| 环节 | 结果 |
|---|---|
| 扫描/连接/启动/截图/dump | ✅ |
| Google credential manager 弹层 | ✅ 自动 Close sheet |
| 邮箱输入 + Continue | ✅ |
| 6 位 OTP 自动提交 | ✅ |
| Meta 账号选择页 | ✅ 自动 Create new account |
| 生日三滚轮（SeekBar） | ✅ 自动拨到 June 15, 1992 |
| 引导页 Get started / 通知权限 | ✅ 点 **ALLOW**（不是 DON'T ALLOW） |
| 聊天首页 | ✅ `Before we get started, what's your name?` |
| 步骤2 换绑定邮箱 | ✅ Settings→Meta Account→Add email→yich8 取码→Email added（真机 3 个邮箱） |
| 步骤5 写 `muse账号.xls` | ✅ 账号 + 创建时间 + 账号-api + 邀请码 + 本号邀请码，逐行追加 |
| 邀请码兑换 | ✅ 已真机跑通；邀请码池按次数轮换 |
| 自选邮箱 API | ✅ 取到 `134016` 并提交成功；部分邮箱 API 只返回 subject（无 6 位码）⚠️ |
| Outlook Graph | ✅ OAuth2 + Graph 读取成功；`SativaAlaiya3720` 6 秒收到码 `890110` 并注册到首页；部分账号可能无邮件 ⚠️ |
| 绑卡/年龄验证 | ⏳ 本次流程未触发 |

服务/邮箱类型：`serviceId=302`（Meta Ai，item 339，sender `email.meta.com`），
`emailTypeId=26`（Gmail_1，$0.04 起）。`emailTypeId=25`（Gmail_test）、`1/3/4` 对 Meta Ai 会返回 41001。

### 注册邮箱来源

「脚本与参数」里的「注册邮箱来源」有三项：

1. `onlineDispoMail`（默认）：沿用邮箱 API 地址/Key，步骤1在线购买 Meta Ai 邮箱；
2. `自选邮箱API`：读取根目录 `registerEmail.txt.txt`，一行：

```text
qfskxabdehk110@gmail.com----https://api-staging.aiford.top/api/mail/uuid/36f8da33-...
```

`----` 前是注册邮箱，后面是取验证码 API。每次注册消耗一行；Provider 会轮询 API，
支持纯文本/HTML/JSON 响应，并用最新的 6 位码继续 OTP。

3. `Outlook邮箱`：读取根目录 `outlookMail.txt`，一行：

```text
邮箱----密码----client_id----refresh_token
```

程序用 refresh_token 调 Microsoft OAuth2 换 access_token，再读 Graph
`/me/messages`，从最新邮件标题/正文提取 6 位码。每次注册消耗一行。

CLI 示例：

```powershell
python -m muse_auto run register --instance "US测试AI" `
  --mail-source "自选邮箱API" --steps 1 --rounds 1

python -m muse_auto run register --instance "US测试AI" `
  --mail-source "Outlook邮箱" --steps 1 --rounds 1
```

自选邮箱 / Outlook 模式不会购买 onlineDispoMail 邮箱，也不要求 API Key。



## 6. 产物与账本

```text
artifacts/
  20261104-193000_PH19L-003/
    smoke.xml / smoke.png / smoke_meta.json
    fail.xml / fail.png / fail.json
    success.xml / success.png
    result.json
data/accounts.jsonl      # 每行一个账号
logs/run_*.log
```

账本状态：

```text
mailbox_bought → email_submitted → otp_verified → registered → invite_redeemed
                                                    ↘ failed / manual_required
```

```powershell
python -m muse_auto ledger
python -m muse_auto ledger --csv accounts.csv
```

## 7. 常见问题

| 现象 | 原因/处理 |
|---|---|
| 年龄验证后出现 `A few things to know` 却一直等 OAuth | 已识别 `ONBOARDING` 并自动点 `Get started`；点击 Instagram 后进入下一页也会立即返回 |
| 年龄验证页没有 `Continue with Facebook` | 实际文案常是 `Instagram or Facebook profile/account`；已加通用入口和 3 次页面检查，若页面已进入引导页直接继续 |
| 第 2 轮开始就显示 `already_signed_in` | 上一轮可能已注册/停在首页；现在步骤1会先检测已有登录态并跳过，不再重复买邮箱 |
| `Finish creating your account` 出现 First/Last name 输入框 | 自动填随机 First/Last name + 生日，点 Confirm 后继续；不再清数据跳过 |
| `Confirm your age` 一直不跳转 | 点社媒入口/重试后仍停留年龄页，会 `pm clear` 并结束当前轮，下一轮重新注册 |
| 步骤2 等待 `account settings` 超时 / 点不到邮箱 | 新版 Meta Account 页改为 `Login and security` / `Default contact info`；Add or edit 左点无效时自动改中间点击 |
| 邀请码页已兑换成功但日志报 `输入文本失败` 并重复填写 | 输入邀请码不再用 UIAutomator 回读校验（自动跳转/清空会误报）；改为检测 Success/错误文案，成功一次即结束 |
| 生日前后页面误判 | 识别顺序新增 `ONBOARDING`，优先于生日/年龄/首页；日志会打印“进入生日页”；失败最多重试 3 次 |
| `邮箱接口 41001 Invalid parameter` | 邮箱类型 ID 被改成 25（Gmail_test）或 1/3/4；改回 **26（Gmail_1）** |
| `没有发现 VMOS 主机` | 不在同一私网 / 端口 18182 不通 / 用 `--host` 指定 |
| `实例未运行` | 勾选 `vmos.start_offline=true`，或先手动开机 |
| `实例未安装 com.facebook.aura` | 该镜像没装 Muse，先安装 |
| `页面=unknown` | 跑 `inspect --tree`，把真实文案补进 `selectors.py`/`pages.py` |
| 系统权限弹窗 `Allow Muse to send notifications?` | 自动点 **ALLOW**（精确匹配，避免误点 DON'T ALLOW） |
| 验证码提交后日志仍说 OTP | 旧版本缓存导致；已改为强制刷新 dump，重启 GUI 后生效 |
| 验证码一直不到 | `mail.service` 改成 `Facebook` 试试；`email_type_id` 用 26（Gmail_1）；余额/库存 |
| 生日滚轮不生效 | 先 `inspect --tree`；当前按 100px 一格校准，见 `components.py` 的 `_set_birthday_wheels` |
| App 显示 `No connection` | 实例没有 Meta HTTPS 出口；`ping` 通不代表 443 通，先配代理/软路由 |
| 年龄验证卡住 | 实例里的 IG/FB 未登录；先人工登录，或改用绑卡（MVP 不做） |
| 注册成功但邀请码没兑换 | 设置入口文案不同；用 `inspect` 看 Settings 页，改 `INVITE_ENTRY` |
| Cloudflare 403 | 已用 `User-Agent` 绕过；若服务商改策略，更新 `transport.py` 的 UA |
| 中文/空格输入失败 | 新版 `input/text` 接口支持中文；旧镜像会回退 shell，可能丢字 |

## 8. 测试

```powershell
python -m unittest discover -s tests -v
```

89 个离线测试，不需要设备、不消耗邮箱余额：

- UI 解析/选择器/可点击祖先；
- 页面识别优先级；
- 验证码提取、服务解析、pending；
- 账本；
- 配置校验；
- 用 FakeDevice + FakeMail 跑完整注册状态机。

## 9. 设计文档

- [参考项目分析](docs/reference-analysis.md)：2,897 行单体的问题、可保留经验、旧→新映射；
- [架构设计](docs/architecture.md)：分层、调用链、扩展指南、已知限制。

## 10. 注意

- 只用于你有权操作的账号/设备；批量注册可能违反 Muse 的服务条款；
- VMOS 的 `18182` 无鉴权，只在可信内网使用，不要暴露公网；
- 邮箱 API key 不要提交到仓库；`config/settings.json` 已加入 `.gitignore`；
- 第一次真跑先用 `--limit 1`，确认余额和页面都正确再放量。
