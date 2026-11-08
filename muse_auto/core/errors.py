"""Typed exceptions.

Every layer raises its own exception type so callers can decide whether a
failure is retryable, a bad configuration, or a page they have never seen.
"""

from __future__ import annotations


class MuseError(Exception):
    """Base class for all errors raised by this project."""


class ConfigError(MuseError):
    """The configuration file is missing, malformed, or inconsistent."""


# ---------------------------------------------------------------------------
# VMOS
# ---------------------------------------------------------------------------


class VmosError(MuseError):
    def __init__(self, message: str, *, url: str = "") -> None:
        super().__init__(message)
        self.url = url


class VmosConnectionError(VmosError):
    """The host or instance could not be reached."""


class VmosApiError(VmosError):
    """VMOS answered, but with an HTTP error or a non-200 business code."""

    def __init__(self, message: str, *, code: int | None = None, url: str = "") -> None:
        super().__init__(message, url=url)
        self.code = code


class DeviceError(VmosError):
    """A device control command failed at the Android layer."""


# ---------------------------------------------------------------------------
# UI automation
# ---------------------------------------------------------------------------


class UiError(MuseError):
    """Generic UI automation failure."""


class NodeNotFound(UiError):
    def __init__(self, selector: object, timeout: float = 0.0) -> None:
        super().__init__(f"控件未找到：{selector!r}（等待 {timeout:g}s）")
        self.selector = selector
        self.timeout = timeout


class UnknownPage(UiError):
    """The current screen does not match any known page definition."""

    def __init__(self, summary: str, artifacts: str = "") -> None:
        super().__init__(f"未识别页面：{summary}")
        self.summary = summary
        self.artifacts = artifacts


# ---------------------------------------------------------------------------
# Services and flows
# ---------------------------------------------------------------------------


class MailError(MuseError):
    """The mailbox provider returned an error."""


class MailPending(MailError):
    """No verification code has arrived yet (provider code 42001)."""


class FlowError(MuseError):
    """A business flow cannot continue on the current page."""


class ResetRequired(FlowError):
    """The instance is in a bad onboarding state; clear data and skip round."""


class Stopped(MuseError):
    """The user requested a stop; unwinds the current instance task."""
