"""Composable Muse execution pipeline.

Steps are numbered and ordered:

    1  register account
    2  change bound email
    3  redeem referral code
    4  append account to muse账号.xls
    5  clear Muse cache/storage (pm clear)

A custom flow is just a named subset, e.g. ``[1, 4]`` or ``[2, 3]``.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from muse_auto.apps.muse.account_center import AccountCenter
from muse_auto.apps.muse.flows.base import FlowResult
from muse_auto.apps.muse.flows.register import RegisterFlow
from muse_auto.apps.muse.invite_center import InviteCenter
from muse_auto.apps.muse.pages import MusePages, Page
from muse_auto.config import Settings
from muse_auto.core.errors import FlowError, MuseError, Stopped
from muse_auto.runner.context import FlowContext
from muse_auto.services.account_store import MuseAccountStore
from muse_auto.services.email_pool import EmailPool
from muse_auto.services.invite_pool import InviteCodePool, InvitePoolExhausted
from muse_auto.services.ledger import Ledger
from muse_auto.services.mail import MailClient
from muse_auto.services.yich8_mail import Yich8MailClient, read_api_template

DEFAULT_STEPS = (1, 2, 3, 4, 5, 6)
MAX_STEP_ATTEMPTS = 3
STEP_NAMES = {
    1: "注册账号",
    2: "更换绑定邮箱",
    3: "兑换邀请码",
    4: "获取本号邀请码",
    5: "保存 muse账号.xls",
    6: "清除 Muse 缓存/存储",
}


def normalize_steps(steps: str | list[int] | tuple[int, ...] | None) -> tuple[int, ...]:
    if steps is None or steps == "":
        return DEFAULT_STEPS
    if isinstance(steps, str):
        values = []
        for part in steps.replace("，", ",").split(","):
            part = part.strip()
            if part.isdigit():
                values.append(int(part))
    else:
        values = [int(value) for value in steps]
    result = tuple(sorted({value for value in values if value in STEP_NAMES}))
    return result or DEFAULT_STEPS


def steps_label(steps: tuple[int, ...]) -> str:
    return " → ".join(f"{value}.{STEP_NAMES[value]}" for value in steps)


class MusePipelineFlow:
    def __init__(
        self,
        *,
        settings: Settings,
        mail_client: MailClient,
        ledger: Ledger,
        steps: str | list[int] | tuple[int, ...] | None = None,
        flow_name: str = "",
    ) -> None:
        self.settings = settings
        self.mail = mail_client
        self.ledger = ledger
        self.steps = normalize_steps(steps)
        self.flow_name = flow_name.strip() or "默认全流程"

    def run(self, ctx: FlowContext) -> FlowResult:
        state: dict[str, str] = {
            "signup_email": "",
            "new_email": "",
            "saved_email": "",
            "invite_code": "",
            "own_invite_code": "",
        }
        ctx.logger.info("流程「%s」步骤：%s", self.flow_name, steps_label(self.steps))
        try:
            if 1 in self.steps:
                result = self._step_register(ctx, state)
                if not result.ok and result.status == "already_signed_in":
                    ctx.logger.warning(
                        "注册阶段发现已有登录态，跳过步骤1并继续后续步骤"
                    )
                elif not result.ok:
                    return result
            if 2 in self.steps:
                self._step_change_email(ctx, state)
            if 3 in self.steps:
                self._step_redeem_invite(ctx, state)
            if 4 in self.steps:
                self._step_own_invite(ctx, state)
            if 5 in self.steps:
                self._step_save_account(ctx, state)
            if 6 in self.steps:
                self._step_clear(ctx, state)

            email = state["saved_email"] or state["new_email"] or state["signup_email"]
            return FlowResult(
                True,
                "pipeline_done",
                f"流程「{self.flow_name}」完成：{steps_label(self.steps)}",
                page="pipeline",
                email=email,
                data={"flow_name": self.flow_name, "steps": list(self.steps), **state},
            )
        except Stopped:
            raise
        except FlowError as exc:
            ctx.logger.error("流程失败：%s", exc)
            try:
                ctx.session.save_artifacts(ctx.artifacts, "fail")
            except Exception:  # noqa: BLE001
                pass
            return FlowResult(
                False,
                "manual_required",
                str(exc),
                page="pipeline",
                email=state["signup_email"] or state["new_email"],
                data={"flow_name": self.flow_name, "steps": list(self.steps), **state},
            )
        except MuseError as exc:
            ctx.logger.error("流程失败：%s", exc)
            try:
                ctx.session.save_artifacts(ctx.artifacts, "fail")
            except Exception:  # noqa: BLE001
                pass
            return FlowResult(
                False,
                "failed",
                str(exc),
                page="pipeline",
                email=state["signup_email"] or state["new_email"],
                data={"flow_name": self.flow_name, "steps": list(self.steps), **state},
            )
        except Exception as exc:  # noqa: BLE001
            ctx.logger.exception("流程未捕获异常")
            return FlowResult(
                False,
                "failed",
                f"{type(exc).__name__}: {exc}",
                page="pipeline",
                email=state["signup_email"] or state["new_email"],
                data={"flow_name": self.flow_name, "steps": list(self.steps), **state},
            )

    # ------------------------------------------------------------------
    # Steps
    # ------------------------------------------------------------------

    def _step_register(self, ctx: FlowContext, state: dict[str, str]) -> FlowResult:
        ctx.logger.info("步骤1 注册账号……")
        if not self.settings.app.clear_data_before_register and self._has_existing_session(ctx):
            ctx.logger.warning("实例已有登录态，跳过步骤1，直接继续后续步骤")
            return FlowResult(
                True,
                "already_signed_in",
                "实例已有登录态，跳过注册",
                page="home",
            )
        if self.mail is None:
            raise FlowError("步骤1 需要邮箱 API 客户端")
        # The pipeline owns steps 2/3; disable RegisterFlow's built-in post steps
        # and invite redemption.
        register_settings = replace(
            self.settings,
            run=replace(self.settings.run, change_email=False, invite_code=""),
        )
        flow = RegisterFlow(
            settings=register_settings,
            mail_client=self.mail,
            ledger=self.ledger,
        )
        result = flow.run(ctx)
        if result.ok:
            state["signup_email"] = result.email
            state["new_email"] = result.email
            # The notification dialog often appears one frame after HOME.
            ctx.stop.sleep(1.2)
            ctx.components.dismiss_permission_retry(attempts=3, interval=2.0)
        return result

    def _step_change_email(self, ctx: FlowContext, state: dict[str, str]) -> None:
        ctx.logger.info("步骤2 更换绑定邮箱……")
        self._ensure_home(ctx)
        pool = EmailPool(self._project_path(self.settings.run.email_pool_path))
        new_email = pool.take()
        if not new_email:
            ctx.logger.warning(
                "替换邮箱池为空（%s），跳过步骤2，继续后续步骤",
                self.settings.run.email_pool_path,
            )
            return
        last_error: Exception | None = None
        try:
            mail = Yich8MailClient.from_file(
                self._project_path(self.settings.run.email_api_path),
                stop=ctx.stop,
            )
            baseline = mail.max_mbox_id(new_email)
            for attempt in range(1, MAX_STEP_ATTEMPTS + 1):
                if attempt > 1:
                    ctx.logger.warning(
                        "步骤2 第 %s/%s 次尝试，重启 Muse 后重试：%s",
                        attempt,
                        MAX_STEP_ATTEMPTS,
                        last_error,
                    )
                    try:
                        self._restart_app(ctx)
                        # The previous attempt may have changed the email even
                        # though the UI reported an error.
                        current = self._read_current_email(ctx)
                        if current and current.casefold() == new_email.casefold():
                            ctx.logger.info("步骤2 已生效：%s", new_email)
                            state["new_email"] = new_email
                            return
                        self._ensure_home(ctx)
                    except Exception as exc:  # noqa: BLE001
                        last_error = exc
                        continue
                try:
                    AccountCenter(
                        ctx.session,
                        ctx.app,
                        stop=ctx.stop,
                        logger=ctx.logger,  # type: ignore[arg-type]
                    ).change_email(new_email, mail, baseline)
                    state["new_email"] = new_email
                    return
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    if attempt < MAX_STEP_ATTEMPTS:
                        ctx.stop.sleep(2.0)
            pool.restore(new_email)
            raise FlowError(f"步骤2 重试 {MAX_STEP_ATTEMPTS} 次仍失败：{last_error}")
        except Exception:
            # The loop restores on its own final failure; restore here only for
            # errors before the loop (e.g. API template missing).
            if last_error is None:
                pool.restore(new_email)
            raise
    def _step_redeem_invite(self, ctx: FlowContext, state: dict[str, str]) -> None:
        ctx.logger.info("步骤3 兑换邀请码……")
        try:
            lease = self._invite_pool().acquire()
        except InvitePoolExhausted as exc:
            raise FlowError(str(exc)) from exc
        code = lease.code
        state["invite_code"] = code
        ctx.logger.info(
            "使用邀请码 %s（本码第 %s/%s 次）",
            code,
            lease.used,
            lease.limit,
        )
        self._ensure_home(ctx)
        last_error: Exception | None = None
        for attempt in range(1, MAX_STEP_ATTEMPTS + 1):
            if attempt > 1:
                ctx.logger.warning(
                    "步骤3 第 %s/%s 次尝试，重启 Muse 后重试：%s",
                    attempt,
                    MAX_STEP_ATTEMPTS,
                    last_error,
                )
                try:
                    self._restart_app(ctx)
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
                    continue
            try:
                used_new = InviteCenter(
                    ctx.session,
                    ctx.app,
                    stop=ctx.stop,
                    logger=ctx.logger,  # type: ignore[arg-type]
                ).redeem(code)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < MAX_STEP_ATTEMPTS:
                    ctx.stop.sleep(2.0)
                continue
            if used_new:
                return
            if attempt == 1:
                # This account already had a referral code before any retry;
                # do not consume a slot.
                self._invite_pool().rollback(code)
                state["invite_code"] = ""
                return
            # A previous attempt may have redeemed the code but errored while
            # detecting the success page; treat this as success.
            ctx.logger.info("步骤3 重试时检测到邀请码已兑换，按成功处理")
            return
        ctx.logger.warning(
            "步骤3 重试全部失败；邀请码 %s 已占用一次，不回滚，避免超过 30 次仍被调用",
            code,
        )
        state["invite_code"] = code
        raise FlowError(f"步骤3 重试 {MAX_STEP_ATTEMPTS} 次仍失败：{last_error}")

    def _step_own_invite(self, ctx: FlowContext, state: dict[str, str]) -> None:
        ctx.logger.info("步骤4 获取本号邀请码……")
        last_error: Exception | None = None
        for attempt in range(1, MAX_STEP_ATTEMPTS + 1):
            if attempt > 1:
                ctx.logger.warning(
                    "步骤4 第 %s/%s 次尝试，关闭弹框后重试：%s",
                    attempt,
                    MAX_STEP_ATTEMPTS,
                    last_error,
                )
                try:
                    ctx.session.back(settle=0.8)
                except Exception:  # noqa: BLE001
                    pass
                self._ensure_home(ctx)
                ctx.stop.sleep(2.0)
            else:
                self._ensure_home(ctx)
            try:
                code = InviteCenter(
                    ctx.session,
                    ctx.app,
                    stop=ctx.stop,
                    logger=ctx.logger,  # type: ignore[arg-type]
                ).read_own_code()
            except Stopped:
                raise
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < MAX_STEP_ATTEMPTS:
                    ctx.stop.sleep(2.0)
                continue
            state["own_invite_code"] = code
            ctx.logger.info("本号邀请码已获取：%s", code)
            return
        raise FlowError(f"步骤4 重试 {MAX_STEP_ATTEMPTS} 次仍失败：{last_error}")

    def _step_save_account(self, ctx: FlowContext, state: dict[str, str]) -> None:
        ctx.logger.info("步骤5 保存 muse账号.xls……")
        email = state["new_email"] or state["signup_email"]
        if not email:
            # Step 3 alone is allowed: read the currently bound email in the UI.
            self._ensure_home(ctx)
            email = AccountCenter(
                ctx.session,
                ctx.app,
                stop=ctx.stop,
                logger=ctx.logger,  # type: ignore[arg-type]
            ).read_current_email()
        path = MuseAccountStore(
            self._project_path(self.settings.run.account_xls_path),
            api_template=self._api_template(ctx),
        ).append(
            email,
            invite_code=state.get("invite_code", ""),
            own_invite_code=state.get("own_invite_code", ""),
        )
        state["saved_email"] = email
        ctx.logger.info("已追加账号到 %s：%s", path, email)

    def _step_clear(self, ctx: FlowContext, _state: dict[str, str]) -> None:
        ctx.logger.info("步骤6 清除 Muse 缓存/存储……")
        if not ctx.app.installed():
            raise FlowError("步骤6 失败：实例未安装 Muse")
        ok = ctx.app.clear_data()
        if not ok:
            raise FlowError("步骤6 失败：pm clear 未返回 Success")
        ctx.logger.info("已清除 Muse 缓存和存储（pm clear）")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _project_path(self, value: str) -> Path:
        path = Path(str(value or "").strip())
        return path if path.is_absolute() else self.settings.project_root / path

    def _api_template(self, ctx: FlowContext) -> str:
        try:
            return read_api_template(self._project_path(self.settings.run.email_api_path))
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning("读取邮箱 API 模板失败，账号-api 列将为空：%s", exc)
            return ""

    def _restart_app(self, ctx: FlowContext) -> None:
        """Force-stop and relaunch Muse between step retries."""
        try:
            ctx.app.launch(force_stop=True)
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning("重启 Muse 失败：%s", exc)
            return
        ctx.stop.sleep(2.0)
        try:
            ctx.components.dismiss_permission()
        except Exception:  # noqa: BLE001
            pass
        self._ensure_home(ctx)

    def _read_current_email(self, ctx: FlowContext) -> str:
        try:
            return AccountCenter(
                ctx.session,
                ctx.app,
                stop=ctx.stop,
                logger=ctx.logger,  # type: ignore[arg-type]
            ).read_current_email()
        except Exception as exc:  # noqa: BLE001
            ctx.logger.warning("读取当前绑定邮箱失败：%s", exc)
            return ""

    def _invite_pool(self) -> InviteCodePool:
        pool = getattr(self, "_invite_pool_instance", None)
        if pool is None:
            pool = InviteCodePool(
                self._project_path(self.settings.run.invite_pool_path),
                uses_per_code=self.settings.run.invite_uses_per_code,
            )
            self._invite_pool_instance = pool
        return pool

    def _has_existing_session(self, ctx: FlowContext) -> bool:
        """True when Muse is already past registration (home/onboarding)."""
        for _ in range(4):
            try:
                match = MusePages.detect(
                    ctx.session.dump(force=True),
                    ctx.session.top_activity().get("package_name", ""),
                )
            except Exception:  # noqa: BLE001
                return False
            if match.page is Page.PERMISSION:
                ctx.components.dismiss_permission()
                ctx.stop.sleep(1.0)
                continue
            if match.page is Page.HOME:
                return True
            if match.page is Page.ONBOARDING:
                ctx.components.advance_welcome()
                ctx.stop.sleep(1.5)
                continue
            return False
        return False

    def _ensure_home(self, ctx: FlowContext) -> None:
        # Muse often shows the notification permission dialog right after the
        # first HOME frame; it can arrive after RegisterFlow already returned.
        if ctx.components.dismiss_permission():
            ctx.stop.sleep(1.5)
        self._launch_if_needed(ctx)
        for _ in range(8):
            match = MusePages.detect(
                ctx.session.dump(force=True),
                ctx.session.top_activity().get("package_name", ""),
            )
            if match.page is Page.PERMISSION:
                ctx.components.dismiss_permission()
                ctx.stop.sleep(1.0)
                continue
            if match.page is Page.HOME:
                return
            if match.page is Page.ONBOARDING:
                ctx.components.advance_welcome()
                ctx.stop.sleep(1.0)
                continue
            if match.page in {Page.EMAIL, Page.OTP, Page.BIRTHDAY, Page.WELCOME}:
                break
            ctx.session.back(settle=1.5)
            ctx.stop.sleep(0.5)
        # Last resort: a cold relaunch reliably lands on HOME for a logged-in
        # instance; Back sometimes leaves a WebView/settings page on the stack.
        try:
            ctx.app.launch(force_stop=True)
            for _ in range(5):
                ctx.stop.sleep(2.0)
                match = MusePages.detect(
                    ctx.session.dump(force=True),
                    ctx.session.top_activity().get("package_name", ""),
                )
                if match.page is Page.HOME:
                    return
        except Exception:  # noqa: BLE001
            pass
        raise FlowError("步骤2/3/4 需要实例在 Muse 首页；请先人工回到首页或先执行步骤1")

    def _launch_if_needed(self, ctx: FlowContext) -> None:
        try:
            top = ctx.session.top_activity().get("package_name", "")
        except Exception:  # noqa: BLE001
            top = ""
        if top != self.settings.app.package:
            ctx.app.launch(force_stop=False)
