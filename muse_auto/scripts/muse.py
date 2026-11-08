"""Built-in Muse (Meta) scripts."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping

from muse_auto.apps.muse.flows.smoke import SmokeFlow
from muse_auto.apps.muse.pipeline import MusePipelineFlow, normalize_steps
from muse_auto.config import Settings
from muse_auto.core.stop import StopToken
from muse_auto.scripts.base import PreparedScript, ScriptField, ScriptSpec
from muse_auto.services.identity import names_text
from muse_auto.services.ledger import Ledger
from muse_auto.services.mail import MailClient
from muse_auto.services.outlook_mail import OutlookMailProvider
from muse_auto.services.registration_mail import CustomMailProvider

MUSE_PACKAGE = "com.facebook.aura"


def _register_defaults(settings: Settings) -> dict[str, Any]:
    first_names = settings.run.first_names
    last_names = settings.run.last_names
    if not first_names or not last_names:
        generated_first, generated_last = names_text(20)
        first_names = first_names or generated_first
        last_names = last_names or generated_last
    return {
        "mail_base_url": settings.mail.base_url,
        "mail_api_key": settings.mail.api_key,
        "mail_service": settings.mail.service,
        "email_type_id": settings.mail.email_type_id,
        "mail_source": settings.run.mail_source,
        "register_email_path": settings.run.register_email_path,
        "outlook_mail_path": settings.run.outlook_mail_path,
        "first_names": first_names,
        "last_names": last_names,
        "invite_pool_path": settings.run.invite_pool_path,
        "invite_uses_per_code": settings.run.invite_uses_per_code,
        "birthday": settings.run.birthday,
        "age_gate": settings.run.age_gate,
        "clear_data": settings.app.clear_data_before_register,
        "change_email": settings.run.change_email,
        "email_pool_path": settings.run.email_pool_path,
        "email_api_path": settings.run.email_api_path,
        "account_xls_path": settings.run.account_xls_path,
        "steps": settings.run.steps,
        "flow_name": settings.run.flow_name,
    }


def _register_factory(
    settings: Settings,
    params: Mapping[str, Any],
    stop: StopToken,
) -> PreparedScript:
    source = str(params.get("mail_source") or settings.run.mail_source).strip()
    custom_mail = source in ("自选邮箱API", "custom", "registerEmail")
    outlook_mail = source in ("Outlook邮箱", "outlook")
    api_key = str(params.get("mail_api_key") or "").strip()
    if not custom_mail and not outlook_mail and not api_key:
        raise ValueError("onlineDispoMail 邮箱 API Key 不能为空")
    email_type = int(params.get("email_type_id") or 26)
    run_settings = replace(
        settings,
        mail=replace(
            settings.mail,
            base_url=str(params.get("mail_base_url") or settings.mail.base_url).strip(),
            api_key=api_key or settings.mail.api_key,
            service=str(params.get("mail_service") or settings.mail.service).strip(),
            email_type_id=email_type,
        ),
        run=replace(
            settings.run,
            mail_source=source,
            register_email_path=str(
                params.get("register_email_path") or settings.run.register_email_path
            ).strip(),
            outlook_mail_path=str(
                params.get("outlook_mail_path") or settings.run.outlook_mail_path
            ).strip(),
            invite_code="",
            invite_pool_path=str(
                params.get("invite_pool_path") or settings.run.invite_pool_path
            ).strip(),
            invite_uses_per_code=int(
                params.get("invite_uses_per_code") or settings.run.invite_uses_per_code
            ),
            birthday=str(params.get("birthday") or settings.run.birthday).strip(),
            first_names=str(params.get("first_names") or settings.run.first_names).strip(),
            last_names=str(params.get("last_names") or settings.run.last_names).strip(),
            age_gate=str(params.get("age_gate") or settings.run.age_gate).strip(),
            change_email=False,
            email_pool_path=str(
                params.get("email_pool_path") or settings.run.email_pool_path
            ).strip(),
            email_api_path=str(
                params.get("email_api_path") or settings.run.email_api_path
            ).strip(),
            account_xls_path=str(
                params.get("account_xls_path") or settings.run.account_xls_path
            ).strip(),
            steps=str(params.get("steps") or settings.run.steps),
            flow_name=str(params.get("flow_name") or settings.run.flow_name),
        ),
        app=replace(
            settings.app,
            clear_data_before_register=bool(params.get("clear_data")),
        ),
    )
    if custom_mail:
        mail = CustomMailProvider(
            run_settings.project_root / run_settings.run.register_email_path,
            stop=stop,
        )
    elif outlook_mail:
        mail = OutlookMailProvider(
            run_settings.project_root / run_settings.run.outlook_mail_path,
            timeout=run_settings.mail.request_timeout,
            stop=stop,
        )
    else:
        mail = MailClient(
            base_url=run_settings.mail.base_url,
            api_key=run_settings.mail.api_key,
            timeout=run_settings.mail.request_timeout,
            stop=stop,
        )
    flow = MusePipelineFlow(
        settings=run_settings,
        mail_client=mail,
        ledger=Ledger(run_settings.ledger_path),
        steps=normalize_steps(params.get("steps")),
        flow_name=str(params.get("flow_name") or run_settings.run.flow_name),
    )
    return PreparedScript(
        settings=run_settings,
        flow=flow,
        app_package=MUSE_PACKAGE,
        billable=(not custom_mail and not outlook_mail) and (1 in flow.steps),
    )


def _smoke_factory(
    settings: Settings,
    _params: Mapping[str, Any],
    _stop: StopToken,
) -> PreparedScript:
    return PreparedScript(
        settings=settings,
        flow=SmokeFlow(),
        app_package=MUSE_PACKAGE,
        billable=False,
    )


MUSE_REGISTER = ScriptSpec(
    id="muse.register",
    name="MuseAI 批量注册",
    description=(
        "在 VMOS 实例上注册 Muse（Meta）账号：邮箱 → OTP → 账号选择 → 生日滚轮 → "
        "引导页 → 聊天首页。注册邮箱可选在线购买或自选邮箱 API。"
    ),
    app_package=MUSE_PACKAGE,
    version="1.0",
    billable=True,
    cost_hint="仅步骤1会购买 Meta Ai 邮箱（Gmail_1，约 $0.04 起）",
    fields=(
        ScriptField(
            "mail_source",
            "注册邮箱来源",
            kind="choice",
            choices=("onlineDispoMail", "自选邮箱API", "Outlook邮箱"),
            group="邮箱 API",
            default="onlineDispoMail",
            width=20,
            help="默认 onlineDispoMail；可选自选邮箱文件或 Outlook Graph",
        ),
        ScriptField(
            "mail_base_url",
            "邮箱 API 地址",
            group="邮箱 API",
            required=False,
            width=34,
            help="仅 onlineDispoMail 使用",
        ),
        ScriptField(
            "mail_api_key",
            "API Key",
            kind="password",
            group="邮箱 API",
            secret=True,
            required=False,
            width=34,
            help="仅 onlineDispoMail 使用；自选邮箱API 可留空",
        ),
        ScriptField(
            "register_email_path",
            "自选邮箱文件",
            group="邮箱 API",
            default="registerEmail.txt.txt",
            width=32,
            help="格式：邮箱----取码API，一行一个；每注册一次消耗一行",
        ),
        ScriptField(
            "outlook_mail_path",
            "Outlook 邮箱文件",
            group="邮箱 API",
            default="outlookMail.txt",
            width=32,
            help="格式：邮箱----密码----client_id----refresh_token；每注册消耗一行",
        ),
        ScriptField(
            "mail_service",
            "邮箱服务",
            group="邮箱 API",
            default="Meta Ai",
            width=22,
            help="Muse 使用 Meta Ai（serviceId=302）",
        ),
        ScriptField(
            "email_type_id",
            "邮箱类型 ID",
            kind="choice",
            choices=("26",),
            group="邮箱 API",
            default="26",
            width=10,
            help="Meta Ai 只能选 26=Gmail_1；25=Gmail_test、1/3/4 都会 41001",
        ),
        ScriptField(
            "invite_pool_path",
            "邀请码文件",
            group="注册参数",
            default="inviteCode.txt",
            width=28,
            help="一行一个邀请码；步骤3自动取用并回写用了N次",
        ),
        ScriptField(
            "invite_uses_per_code",
            "每个邀请码可用次数",
            kind="int",
            group="注册参数",
            default=30,
            width=8,
            help="默认 30 次；用满后自动换下一行",
        ),
        ScriptField(
            "birthday",
            "生日",
            kind="date",
            group="注册参数",
            default="1992-06-15",
            width=14,
            help="YYYY-MM-DD，年龄必须 >= 18",
        ),
        ScriptField(
            "first_names",
            "First names",
            group="随机名字",
            default="",
            width=64,
            help="逗号分隔；运行到需要姓名的页面时随机取一个",
        ),
        ScriptField(
            "last_names",
            "Last names",
            group="随机名字",
            default="",
            width=64,
            help="逗号分隔；点击生成按钮可各生成 20 个",
        ),
        ScriptField(
            "age_gate",
            "年龄验证",
            kind="choice",
            group="注册参数",
            default="instagram",
            choices=("instagram", "facebook", "none"),
            width=12,
            help="若出现 Confirm your age，用哪个社媒跳过绑卡",
        ),
        ScriptField(
            "clear_data",
            "注册前清空 Muse 数据",
            kind="bool",
            group="注册参数",
            default=False,
            help="已登录/上次中断的实例需要勾选；会清空该应用数据",
        ),
        ScriptField(
            "flow_name",
            "流程名称",
            group="执行步骤",
            default="默认全流程",
            width=30,
            help="给这次自定义流程起名，例如：只换邮箱、注册+清理",
        ),
        ScriptField(
            "steps",
            "执行步骤",
            kind="steps",
            group="执行步骤",
            default="1,2,3,4,5,6",
            help="1注册 2换邮箱 3兑换邀请码 4本号邀请码 5保存XLS 6清缓存；默认全选；取消6可保留登录",
        ),
        ScriptField(
            "email_pool_path",
            "替换邮箱文件",
            group="邮箱变更",
            default="changeEmailInfo/changeEmail.txt",
            width=34,
            help="一行一个邮箱，用掉一个删一个",
        ),
        ScriptField(
            "email_api_path",
            "取码 API 文件",
            group="邮箱变更",
            default="changeEmailInfo/changeEmailapi.txt",
            width=34,
            help="yich8 IMAP HTTP API 模板",
        ),
        ScriptField(
            "account_xls_path",
            "账号 XLS",
            group="账号保存",
            default="muse账号.xls",
            width=30,
            help="变更成功后追加：账号 + 创建时间",
        ),
    ),
    defaults=_register_defaults,
    factory=_register_factory,
)


MUSE_SMOKE = ScriptSpec(
    id="muse.smoke",
    name="MuseAI 冒烟检查",
    description="启动 Muse，识别当前页面并保存截图/控件树。不买邮箱、不注册。",
    app_package=MUSE_PACKAGE,
    version="1.0",
    billable=False,
    fields=(),
    defaults=lambda _settings: {},
    factory=_smoke_factory,
)
