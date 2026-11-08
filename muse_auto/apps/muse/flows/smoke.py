"""Smoke flow: launch Muse, identify the current page, save a dump + screenshot.

This is the first command to run against a new image. It proves the whole
vertical slice (host -> device -> UI parser -> page detector) without touching
mailboxes or accounts.
"""

from __future__ import annotations

import json

from muse_auto.apps.muse.flows.base import FlowResult
from muse_auto.apps.muse.pages import MusePages
from muse_auto.core.errors import MuseError, Stopped
from muse_auto.runner.context import FlowContext


class SmokeFlow:
    def run(self, ctx: FlowContext) -> FlowResult:
        try:
            if not ctx.app.installed():
                return FlowResult(
                    ok=False,
                    status="app_missing",
                    message=f"实例未安装 {ctx.settings.app.package}",
                )

            ctx.logger.info("启动 %s……", ctx.app.package)
            ctx.app.launch()
            tree = ctx.session.dump(force=True)
            top = ctx.session.top_activity()
            match = MusePages.detect(tree, top.get("package_name", ""))
            width, height = ctx.session.display_size()
            ctx.logger.info(
                "页面=%s 控件=%s 分辨率=%sx%s activity=%s/%s",
                match.page.value,
                len(tree.nodes),
                width,
                height,
                top.get("package_name"),
                top.get("class_name"),
            )

            saved = ctx.session.save_artifacts(ctx.artifacts, "smoke")
            meta = {
                "instance": ctx.instance.label,
                "app_version": ctx.app.version(),
                "activity": top,
                "display": [width, height],
                "page": match.page.value,
                "page_reason": match.reason,
                "nodes": len(tree.nodes),
                "summary": tree.summary(limit=500),
            }
            ctx.artifacts.mkdir(parents=True, exist_ok=True)
            (ctx.artifacts / "smoke_meta.json").write_text(
                json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return FlowResult(
                ok=True,
                status="smoke_ok",
                message=f"page={match.page.value}",
                page=match.page.value,
                artifacts=saved,
                data=meta,
            )
        except Stopped:
            raise
        except MuseError as exc:
            ctx.logger.error("smoke 失败：%s", exc)
            try:
                ctx.session.save_artifacts(ctx.artifacts, "fail")
            except Exception:  # noqa: BLE001 - best effort
                pass
            return FlowResult(ok=False, status="smoke_failed", message=str(exc))
