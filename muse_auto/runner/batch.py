"""Run one flow over many instances with bounded concurrency.

Instances are independent; each worker gets its own device/session graph and its
own artifact directory. The ledger and mail client are shared and internally
thread-safe enough for this workload (one mailbox per worker).
"""

from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from muse_auto.apps.muse.flows.base import FlowResult
from muse_auto.config import Settings
from muse_auto.core.errors import MuseError, Stopped
from muse_auto.core.logging import InstanceLogger
from muse_auto.core.stop import StopToken
from muse_auto.runner.artifacts import ArtifactStore
from muse_auto.runner.context import FlowContext, build_context
from muse_auto.vmos.container import ContainerApi
from muse_auto.vmos.models import VmosInstance
from muse_auto.vmos.transport import HttpTransport

LOGGER = logging.getLogger("muse_auto.runner.batch")

Task = Callable[[VmosInstance, StopToken, FlowContext], FlowResult]


@dataclass
class TaskResult:
    instance: VmosInstance
    ok: bool
    status: str
    message: str = ""
    page: str = ""
    email: str = ""
    order_id: str = ""
    artifacts: Path | None = None
    duration: float = 0.0
    round: int = 0
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.instance.name


class BatchRunner:
    def __init__(
        self,
        settings: Settings,
        *,
        stop: StopToken | None = None,
        on_result: Callable[[TaskResult], None] | None = None,
    ) -> None:
        self.settings = settings
        self.stop = stop or StopToken()
        self.on_result = on_result

    def run(self, instances: list[VmosInstance], task: Task) -> list[TaskResult]:
        if not instances:
            return []
        workers = max(1, min(self.settings.run.concurrency, len(instances)))
        results: list[TaskResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._run_one, instance, task): instance for instance in instances
            }
            for future in concurrent.futures.as_completed(futures):
                instance = futures[future]
                try:
                    result = future.result()
                except Stopped:
                    result = TaskResult(instance, False, "stopped", "任务已停止")
                except Exception as exc:  # noqa: BLE001 - one worker must not kill the batch
                    result = TaskResult(
                        instance, False, "failed", f"{type(exc).__name__}: {exc}"
                    )
                results.append(result)
                if self.on_result is not None:
                    self.on_result(result)
                if not result.ok and self.settings.run.stop_on_error:
                    self.stop.stop()
        results.sort(key=lambda item: (item.instance.host.ip, item.instance.name.casefold()))
        return results

    def _run_one(self, instance: VmosInstance, task: Task) -> TaskResult:
        started = time.monotonic()
        logger = InstanceLogger(LOGGER, instance.name)
        store = ArtifactStore(self.settings.artifact_dir, instance.name)

        if self.stop.stopped:
            return TaskResult(instance, False, "stopped", "任务已停止", artifacts=store.directory)

        if not instance.running:
            if not self.settings.vmos.start_offline:
                return TaskResult(
                    instance,
                    False,
                    "offline",
                    "实例未运行（可在配置中开启 vmos.start_offline）",
                    artifacts=store.directory,
                )
            logger.info("实例未运行，正在开机……")
            if not self._ensure_running(instance, logger):
                return TaskResult(
                    instance, False, "offline", "开机超时", artifacts=store.directory
                )

        logger.info("开始任务 host=%s db_id=%s", instance.host.ip, instance.db_id)
        try:
            ctx = build_context(instance, self.settings, self.stop, store.directory)
            result = task(instance, self.stop, ctx)
        except Stopped:
            logger.info("任务被停止")
            return TaskResult(
                instance, False, "stopped", "任务已停止", artifacts=store.directory
            )
        except MuseError as exc:
            logger.error("任务失败：%s", exc)
            return TaskResult(
                instance,
                False,
                "failed",
                str(exc),
                artifacts=store.directory,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("未捕获异常")
            return TaskResult(
                instance,
                False,
                "failed",
                f"{type(exc).__name__}: {exc}",
                artifacts=store.directory,
            )

        duration = time.monotonic() - started
        logger.info("任务结束 status=%s（%.1fs）", result.status, duration)
        return TaskResult(
            instance=instance,
            ok=result.ok,
            status=result.status,
            message=result.message,
            page=result.page,
            email=result.email,
            order_id=result.order_id,
            artifacts=store.directory,
            duration=duration,
            extra=result.data,
        )

    def _ensure_running(self, instance: VmosInstance, logger: InstanceLogger) -> bool:
        api = ContainerApi(
            instance.host,
            transport=HttpTransport(timeout=15.0, retries=1, stop=self.stop),
            timeout=15.0,
        )
        try:
            api.start([instance.db_id], timeout=60.0)
        except MuseError as exc:
            logger.warning("开机请求失败：%s", exc)
            return False

        deadline = time.monotonic() + self.settings.vmos.start_timeout
        while time.monotonic() < deadline:
            self.stop.check()
            try:
                for item in api.list_instances(timeout=15.0):
                    if item.db_id == instance.db_id and item.running:
                        logger.info("实例已开机")
                        self.stop.sleep(3.0)
                        return True
            except MuseError:
                pass
            self.stop.sleep(3.0)
        return False
