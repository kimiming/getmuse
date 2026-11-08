"""Batch registration flow for Muse.

The flow is a small state machine over :class:`Page`. Each state delegates to a
component (email form, OTP form, birthday form, age gate, invite redemption).
When a page is not recognised the flow saves the dump/screenshot and stops with
a precise error instead of guessing coordinates.

Order of operations matters for cost: the app is launched and inspected *before*
a mailbox is bought, so an already-signed-in instance does not consume balance.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from muse_auto.apps.muse.account_center import AccountCenter
from muse_auto.apps.muse.flows.base import FlowResult
from muse_auto.apps.muse.pages import Page, PageMatch, MusePages
from muse_auto.core.errors import (
    DeviceError,
    FlowError,
    MailError,
    MuseError,
    ResetRequired,
    Stopped,
    UiError,
    UnknownPage,
)
from muse_auto.runner.context import FlowContext
from muse_auto.services.account_store import MuseAccountStore
from muse_auto.services.email_pool import EmailPool
from muse_auto.services.ledger import (
    STATUS_EMAIL,
    STATUS_FAILED,
    STATUS_INVITED,
    STATUS_MAILBOX,
    STATUS_MANUAL,
    STATUS_OTP,
    STATUS_REGISTERED,
    AccountRecord,
    Ledger,
)
from muse_auto.services.mail import MailClient
from muse_auto.services.yich8_mail import Yich8MailClient

MAX_STEPS = 80
MAX_SAME_PAGE = 5


class RegisterFlow:
    def __init__(self, *, settings, mail_client: MailClient, ledger: Ledger) -> None:
        self.settings = settings
        self.mail = mail_client
        self.ledger = ledger

    # -- public ------------------------------------------------------------

    def run(self, ctx: FlowContext) -> FlowResult:
        mailbox = None
        record: AccountRecord | None = None
        page = "unknown"
        try:
            if not ctx.app.installed():
                return FlowResult(False, "app_missing", f"实例未安装 {self.settings.app.package}")

            if self.settings.app.clear_data_before_register:
                ctx.logger.info("清理 %s 数据……", ctx.app.package)
                ctx.app.clear_data()

            ctx.app.launch()
            ready = self._wait_ready(ctx, timeout=30.0)
            for _ in range(5):
                if ready.page is Page.PERMISSION:
                    ctx.components.dismiss_permission()
                elif ready.page is Page.SYSTEM_SHEET:
                    ctx.components.dismiss_system_sheet()
                elif ready.page is Page.LOADING:
                    ctx.stop.sleep(2.0)
                else:
                    break
                ready = self._wait_ready(ctx, timeout=15.0)
            page = ready.page.value
            if ready.page in {Page.HOME, Page.SETTINGS, Page.ACCOUNT_CHOOSER}:
                return FlowResult(
                    False,
                    "already_signed_in",
                    "Muse 已登录；请换新实例，或开启 app.clear_data_before_register",
                    page=page,
                )
            if ready.page is Page.UNKNOWN:
                raise UnknownPage(ready.reason, str(ctx.artifacts))
            if ready.page in {Page.OTP, Page.BIRTHDAY, Page.AGE_GATE, Page.INVITE}:
                return FlowResult(
                    False,
                    STATUS_MANUAL,
                    f"实例停留在上一次注册流程（{ready.page.value}）；请开启 clear_data 后重试",
                    page=ready.page.value,
                )

            # Buying is the first paid operation; do it only after the app is usable.
            balance = self.mail.balance()
            if getattr(self.mail, "provider_name", "") == "自选邮箱API":
                ctx.logger.info(
                    "自选邮箱剩余 %.0f 个，取用邮箱……", balance
                )
            else:
                ctx.logger.info(
                    "邮箱余额 %.2f，购买 %s 邮箱……", balance, self.settings.mail.service
                )
            mailbox = self.mail.buy_mailbox(
                service=self.settings.mail.service,
                email_type_id=self.settings.mail.email_type_id,
            )
            record = self.ledger.upsert(
                AccountRecord(
                    email=mailbox.email,
                    order_id=mailbox.order_id,
                    status=STATUS_MAILBOX,
                    instance=ctx.instance.name,
                    host=ctx.instance.host.ip,
                    db_id=ctx.instance.db_id,
                    note="mailbox bought",
                )
            )
            ctx.logger.info("邮箱=%s orderId=%s", mailbox.email, mailbox.order_id)

            baseline = self.mail.latest_code(mailbox.order_id)
            baseline_code = baseline.code if baseline else None

            email_submitted = False
            otp_verified = False
            last_signature = ""
            same_count = 0
            unknown_count = 0

            for step in range(1, MAX_STEPS + 1):
                self._check(ctx)
                match = self._detect(ctx)
                page = match.page.value
                signature = f"{page}|{ctx.session.summary(limit=90)}"
                same_count = same_count + 1 if signature == last_signature else 0
                last_signature = signature

                ctx.logger.info("步骤 %s/%s 页面=%s", step, MAX_STEPS, MusePages.describe(match))
                if match.page is Page.LOADING:
                    last_signature = ""
                    ctx.stop.sleep(2.0)
                    continue

                if match.page is not Page.UNKNOWN:
                    unknown_count = 0
                if same_count >= MAX_SAME_PAGE:
                    if ctx.components.dismiss_soft_popup():
                        same_count = 0
                        continue
                    raise FlowError(f"页面连续 {same_count + 1} 次没有变化：{match.reason}")

                if match.page is Page.PERMISSION:
                    ctx.components.dismiss_permission()
                    continue

                if match.page is Page.SYSTEM_SHEET:
                    ctx.components.dismiss_system_sheet()
                    continue

                if match.page is Page.ERROR:
                    summary = ctx.session.summary(limit=180)
                    ctx.components.acknowledge_error()
                    raise MuseError(f"Muse 无法连接网络或服务异常：{summary}")

                if match.page is Page.ACCOUNT_CHOOSER:
                    ctx.components.choose_new_account()
                    # A fresh "create account" step can ask for the same email
                    # code again; allow the latest code instead of treating the
                    # previous one as a stale baseline.
                    baseline_code = None
                    record = self.ledger.mark(
                        mailbox.email, STATUS_OTP, note="chose create new account"
                    )
                    continue

                if match.page in (Page.WELCOME, Page.ONBOARDING):
                    if not ctx.components.advance_welcome():
                        raise FlowError("欢迎页没有找到邮箱注册入口")
                    if match.page is Page.ONBOARDING:
                        ctx.logger.info("已通过 A few things to know 引导页")
                    continue

                if match.page is Page.EMAIL:
                    ctx.components.enter_email(mailbox.email)
                    email_submitted = True
                    record = self.ledger.mark(
                        mailbox.email, STATUS_EMAIL, note="email submitted"
                    )
                    continue

                if match.page is Page.OTP:
                    code = self.mail.wait_for_code(
                        mailbox.order_id,
                        timeout=self.settings.mail.poll_timeout,
                        interval=self.settings.mail.poll_interval,
                        baseline=baseline_code,
                    )
                    ctx.components.enter_code(code)
                    baseline_code = code
                    otp_verified = True
                    record = self.ledger.mark(mailbox.email, STATUS_OTP, note="otp verified")
                    continue

                if match.page is Page.BIRTHDAY:
                    ctx.logger.info("进入生日页（%s），开始设置生日", match.reason)
                    last_error: Exception | None = None
                    for attempt in range(1, 4):
                        try:
                            ctx.components.enter_birthday(
                                self.settings.run.birthday,
                                self.settings.run.first_names,
                                self.settings.run.last_names,
                            )
                            last_error = None
                            break
                        except ResetRequired:
                            raise
                        except FlowError as exc:
                            # If the page advanced despite a stale read, treat it
                            # as success rather than restarting the birthday.
                            if self._detect(ctx).page is not Page.BIRTHDAY:
                                ctx.logger.warning(
                                    "生日操作后页面已离开生日页，继续下一步：%s", exc
                                )
                                last_error = None
                                break
                            last_error = exc
                            if attempt < 3:
                                ctx.logger.warning(
                                    "生日设置失败（第 %s/3 次），2 秒后重试：%s",
                                    attempt,
                                    exc,
                                )
                                ctx.stop.sleep(2.0)
                    if last_error is not None:
                        raise last_error
                    continue

                if match.page is Page.AGE_GATE:
                    ctx.logger.info("进入年龄验证，尝试用 %s 跳过绑卡", self.settings.run.age_gate)
                    ctx.components.skip_age_gate(self.settings.run.age_gate)
                    record = self.ledger.mark(
                        mailbox.email, STATUS_OTP, note=f"age gate via {self.settings.run.age_gate}"
                    )
                    continue

                if match.page is Page.INVITE:
                    if self.settings.run.invite_code:
                        ctx.components.redeem_invite(self.settings.run.invite_code)
                    # Leave the invite screen; the next loop decides whether we are home.
                    ctx.session.back(settle=1.0)
                    continue

                if match.page is Page.SETTINGS:
                    if self.settings.run.invite_code:
                        ctx.components.redeem_invite(self.settings.run.invite_code)
                    ctx.session.back(settle=1.0)
                    continue

                if match.page is Page.HOME:
                    if not email_submitted:
                        return FlowResult(
                            False,
                            "already_signed_in",
                            "进入首页时尚未提交本次邮箱，实例可能已有登录态",
                            page=page,
                            email=mailbox.email,
                            order_id=mailbox.order_id,
                        )
                    record = self.ledger.mark(
                        mailbox.email,
                        STATUS_REGISTERED,
                        note="home reached" if otp_verified else "home reached (no otp flag)",
                    )
                    new_email = ""
                    if self.settings.run.change_email:
                        new_email = self._change_email_and_save(ctx, mailbox.email)
                        if new_email:
                            record = self.ledger.mark(
                                mailbox.email,
                                record.status,
                                note=f"email changed to {new_email}",
                            )

                    invite_ok = False
                    if self.settings.run.invite_code:
                        if new_email and not self._return_home(ctx):
                            ctx.logger.warning("换邮箱后没有回到首页，跳过邀请码")
                        else:
                            invite_ok = ctx.components.redeem_invite(
                                self.settings.run.invite_code
                            )
                            if invite_ok:
                                record = self.ledger.mark(
                                    mailbox.email,
                                    STATUS_INVITED,
                                    note=(
                                        f"invite redeemed; email changed to {new_email}"
                                        if new_email
                                        else "invite redeemed"
                                    ),
                                    invite_redeemed=True,
                                )

                    saved = ctx.session.save_artifacts(ctx.artifacts, "success")
                    self._write_result(ctx, record, match)
                    message = "注册完成"
                    if new_email:
                        message = f"注册并更换邮箱完成：{new_email}"
                    elif invite_ok:
                        message = "注册完成，邀请码已兑换"
                    return FlowResult(
                        True,
                        STATUS_INVITED if invite_ok else STATUS_REGISTERED,
                        message,
                        page=page,
                        email=new_email or mailbox.email,
                        order_id=mailbox.order_id,
                        artifacts=saved,
                        data={
                            "invite_redeemed": invite_ok,
                            "new_email": new_email,
                        },
                    )

                if match.page is Page.UNKNOWN:
                    unknown_count += 1
                    if unknown_count <= 3:
                        ctx.logger.warning("页面暂未识别，等待过渡：%s", match.reason[:120])
                        ctx.stop.sleep(2.0)
                        continue
                    raise UnknownPage(match.reason, str(ctx.artifacts))

                raise UnknownPage(match.reason, str(ctx.artifacts))

            raise FlowError(f"超过最大步骤数 {MAX_STEPS}，最后页面：{page}")

        except Stopped:
            if record is not None:
                try:
                    self.ledger.mark(record.email, STATUS_FAILED, note="stopped")
                except Exception:  # noqa: BLE001
                    pass
            raise
        except UnknownPage as exc:
            self._fail(ctx, mailbox, record, STATUS_FAILED, f"未识别页面：{exc.summary}")
            return FlowResult(
                False,
                "unknown_page",
                f"未识别页面：{exc.summary}",
                page=page,
                email=mailbox.email if mailbox else "",
                order_id=mailbox.order_id if mailbox else "",
            )
        except FlowError as exc:
            self._fail(ctx, mailbox, record, STATUS_MANUAL, str(exc))
            return FlowResult(
                False,
                STATUS_MANUAL,
                str(exc),
                page=page,
                email=mailbox.email if mailbox else "",
                order_id=mailbox.order_id if mailbox else "",
            )
        except (MailError, DeviceError, UiError, MuseError) as exc:
            self._fail(ctx, mailbox, record, STATUS_FAILED, str(exc))
            return FlowResult(
                False,
                "failed",
                str(exc),
                page=page,
                email=mailbox.email if mailbox else "",
                order_id=mailbox.order_id if mailbox else "",
            )
        except Exception as exc:  # noqa: BLE001 - never kill the batch worker silently
            self._fail(ctx, mailbox, record, STATUS_FAILED, f"{type(exc).__name__}: {exc}")
            return FlowResult(
                False,
                "failed",
                f"{type(exc).__name__}: {exc}",
                page=page,
                email=mailbox.email if mailbox else "",
                order_id=mailbox.order_id if mailbox else "",
            )

    # -- helpers -----------------------------------------------------------

    def _project_path(self, value: str) -> Path:
        path = Path(str(value or "").strip())
        return path if path.is_absolute() else self.settings.project_root / path

    def _change_email_and_save(self, ctx: FlowContext, signup_email: str) -> str:
        """Step 2 + step 3: change the bound email, then append to muse账号.xls."""
        pool = EmailPool(self._project_path(self.settings.run.email_pool_path))
        new_email = pool.take()
        if not new_email:
            ctx.logger.warning(
                "替换邮箱池为空（%s），跳过换邮箱；账号仍为 %s",
                self.settings.run.email_pool_path,
                signup_email,
            )
            return ""

        api_file = self._project_path(self.settings.run.email_api_path)
        try:
            mail = Yich8MailClient.from_file(api_file, stop=ctx.stop)
            baseline = mail.max_mbox_id(new_email)
            ctx.logger.info("步骤2 更换邮箱：%s → %s", signup_email, new_email)
            AccountCenter(
                ctx.session,
                ctx.app,
                stop=ctx.stop,
                logger=ctx.logger,  # type: ignore[arg-type]
            ).change_email(new_email, mail, baseline)
        except Exception:
            pool.restore(new_email)
            raise

        # Email is now changed; never restore it if only the XLS write fails.
        xls_path = self._project_path(self.settings.run.account_xls_path)
        MuseAccountStore(xls_path, api_template=mail.api_url).append(new_email)
        ctx.logger.info("步骤3 已保存账号到 %s：%s", xls_path, new_email)
        return new_email

    def _return_home(self, ctx: FlowContext) -> bool:
        for _ in range(5):
            match = MusePages.detect(
                ctx.session.dump(force=True),
                ctx.session.top_activity().get("package_name", ""),
            )
            if match.page is Page.HOME:
                return True
            ctx.session.back(settle=1.5)
        return False

    def _check(self, ctx: FlowContext) -> None:
        ctx.stop.check()

    def _detect(self, ctx: FlowContext) -> PageMatch:
        tree = ctx.session.dump(force=True)
        top = ctx.session.top_activity()
        return MusePages.detect(tree, top.get("package_name", ""))

    def _wait_ready(self, ctx: FlowContext, timeout: float) -> PageMatch:
        deadline = time.monotonic() + timeout
        last = PageMatch(Page.UNKNOWN, "等待 Muse 首页")
        while time.monotonic() < deadline:
            self._check(ctx)
            try:
                last = self._detect(ctx)
            except (UiError, DeviceError) as exc:
                last = PageMatch(Page.UNKNOWN, f"读取控件树失败：{exc}")
                ctx.stop.sleep(1.5)
                continue
            if last.page is not Page.UNKNOWN:
                return last
            ctx.stop.sleep(1.5)
        return last

    def _fail(
        self,
        ctx: FlowContext,
        mailbox,
        record: AccountRecord | None,
        status: str,
        message: str,
    ) -> None:
        ctx.logger.error("注册失败：%s", message)
        try:
            ctx.session.save_artifacts(ctx.artifacts, "fail")
        except Exception:  # noqa: BLE001
            pass
        if record is not None and mailbox is not None:
            try:
                self.ledger.mark(mailbox.email, status, note=message[:400])
            except Exception:  # noqa: BLE001
                ctx.logger.warning("账本更新失败", exc_info=True)

    def _write_result(self, ctx: FlowContext, record: AccountRecord | None, match: PageMatch) -> None:
        if record is None:
            return
        try:
            (ctx.artifacts / "result.json").write_text(
                json.dumps(
                    {
                        "email": record.email,
                        "order_id": record.order_id,
                        "status": record.status,
                        "invite_redeemed": record.invite_redeemed,
                        "page": match.page.value,
                        "instance": ctx.instance.name,
                        "db_id": ctx.instance.db_id,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except OSError:
            pass
