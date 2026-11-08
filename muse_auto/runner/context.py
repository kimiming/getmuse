"""Per-instance runtime context.

Builds the device/session/app/components graph exactly once and gives flows a
single object to work with. Nothing in this module knows about registration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from muse_auto.apps.muse.app import MuseApp
from muse_auto.apps.muse.components import MuseComponents
from muse_auto.config import Settings
from muse_auto.core.logging import InstanceLogger
from muse_auto.core.stop import StopToken
from muse_auto.ui.session import UiSession
from muse_auto.vmos.device import DeviceApi
from muse_auto.vmos.models import VmosInstance


@dataclass
class FlowContext:
    instance: VmosInstance
    device: DeviceApi
    session: UiSession
    app: MuseApp
    components: MuseComponents
    settings: Settings
    stop: StopToken
    logger: InstanceLogger
    artifacts: Path

    @property
    def label(self) -> str:
        return self.instance.name


def build_context(
    instance: VmosInstance,
    settings: Settings,
    stop: StopToken,
    artifacts: Path,
) -> FlowContext:
    logger = InstanceLogger(
        logging.getLogger("muse_auto.flow"),
        instance.name,
    )
    device = DeviceApi(instance, timeout=settings.app.dump_timeout, stop=stop)
    session = UiSession(
        device,
        stop=stop,
        logger=logger,
        action_delay=settings.app.action_delay,
        dump_retries=settings.app.dump_retries,
        dump_timeout=settings.app.dump_timeout,
    )
    app = MuseApp(
        device,
        package=settings.app.package,
        launch_wait=settings.app.launch_wait,
        stop=stop,
    )
    components = MuseComponents(session, app, stop=stop, logger=logger)
    return FlowContext(
        instance=instance,
        device=device,
        session=session,
        app=app,
        components=components,
        settings=settings,
        stop=stop,
        logger=logger,
        artifacts=artifacts,
    )
