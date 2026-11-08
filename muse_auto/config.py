"""Configuration loading and validation.

The project deliberately uses JSON from the standard library: no PyYAML or
pydantic dependency, so the tool runs on a clean Python install. Unknown keys
are rejected instead of silently ignored, which catches typos early.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, Mapping, TypeVar

from muse_auto.core.errors import ConfigError

T = TypeVar("T")

DEFAULT_CONFIG_PATH = Path("config/settings.json")


def app_root() -> Path:
    """Directory of the exe when frozen, otherwise the current directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


@dataclass(frozen=True)
class VmosConfig:
    hosts: tuple[str, ...] = ()
    port: int = 18182
    scan: bool = True
    use_adb: bool = True
    probe_timeout: float = 0.6
    list_timeout: float = 10.0
    max_host_workers: int = 16
    scan_workers: int = 128
    start_offline: bool = False
    start_timeout: float = 90.0


@dataclass(frozen=True)
class AppConfig:
    package: str = "com.facebook.aura"
    launch_wait: float = 8.0
    action_delay: float = 0.6
    dump_retries: int = 3
    dump_timeout: float = 20.0
    clear_data_before_register: bool = False


@dataclass(frozen=True)
class MailConfig:
    base_url: str = "https://api.online-disposablemail.com"
    api_key: str = ""
    service: str = "Meta Ai"
    email_type_id: int = 26
    request_timeout: float = 20.0
    poll_interval: float = 5.0
    poll_timeout: float = 180.0


@dataclass(frozen=True)
class RunConfig:
    concurrency: int = 2
    artifact_dir: str = "artifacts"
    ledger_path: str = "data/accounts.jsonl"
    mail_source: str = "onlineDispoMail"
    register_email_path: str = "registerEmail.txt.txt"
    outlook_mail_path: str = "outlookMail.txt"
    invite_code: str = ""
    invite_pool_path: str = "inviteCode.txt"
    invite_uses_per_code: int = 30
    age_gate: str = "instagram"
    birthday: str = "1992-06-15"
    stop_on_error: bool = False
    change_email: bool = True
    email_pool_path: str = "changeEmailInfo/changeEmail.txt"
    email_api_path: str = "changeEmailInfo/changeEmailapi.txt"
    account_xls_path: str = "muse账号.xls"
    first_names: str = ""
    last_names: str = ""
    steps: str = "1,2,3,4,5,6"
    flow_name: str = "默认全流程"
    rounds: int = 2
    round_interval: float = 10.0


@dataclass(frozen=True)
class Settings:
    vmos: VmosConfig
    app: AppConfig
    mail: MailConfig
    run: RunConfig
    log_level: str
    project_root: Path
    config_path: Path

    @property
    def artifact_dir(self) -> Path:
        path = Path(self.run.artifact_dir)
        return path if path.is_absolute() else self.project_root / path

    @property
    def ledger_path(self) -> Path:
        path = Path(self.run.ledger_path)
        return path if path.is_absolute() else self.project_root / path

    @property
    def masked_api_key(self) -> str:
        key = self.mail.api_key
        if not key:
            return "(not set)"
        if len(key) <= 8:
            return "*" * len(key)
        return f"{key[:4]}...{key[-4:]}"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _section(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, Mapping):
        raise ConfigError(f"配置项 {name!r} 必须是对象")
    return value


def _build(cls: type[T], data: Mapping[str, Any], section: str) -> T:
    allowed = {item.name for item in fields(cls)}  # type: ignore[arg-type]
    unknown = sorted(set(data) - allowed)
    if unknown:
        raise ConfigError(f"配置项 {section!r} 存在未知字段：{', '.join(unknown)}")
    try:
        return cls(**dict(data))  # type: ignore[call-arg]
    except TypeError as exc:
        raise ConfigError(f"配置项 {section!r} 字段类型不匹配：{exc}") from exc


def _env_overrides(raw: dict[str, Any]) -> None:
    """Environment variables win over the file (useful for secrets/CI)."""
    key = os.environ.get("MUSE_MAIL_API_KEY")
    if key:
        raw.setdefault("mail", {})["api_key"] = key

    hosts = os.environ.get("MUSE_VMOS_HOSTS")
    if hosts:
        raw.setdefault("vmos", {})["hosts"] = [
            item.strip() for item in hosts.split(",") if item.strip()
        ]

    level = os.environ.get("MUSE_LOG_LEVEL")
    if level:
        raw.setdefault("logging", {})["level"] = level

    pool = os.environ.get("MUSE_INVITE_POOL")
    if pool:
        raw.setdefault("run", {})["invite_pool_path"] = pool

    uses = os.environ.get("MUSE_INVITE_USES")
    if uses:
        raw.setdefault("run", {})["invite_uses_per_code"] = int(uses)


def _validate(settings: Settings) -> None:
    vmos = settings.vmos
    if not 1 <= vmos.port <= 65535:
        raise ConfigError("vmos.port 必须在 1..65535")
    if vmos.probe_timeout <= 0 or vmos.list_timeout <= 0:
        raise ConfigError("vmos 超时时间必须大于 0")
    if vmos.max_host_workers < 1 or vmos.scan_workers < 1:
        raise ConfigError("vmos 线程数必须 >= 1")
    for host in vmos.hosts:
        if host.count(".") != 3:
            raise ConfigError(f"vmos.hosts 中的地址不合法：{host!r}")

    app = settings.app
    if not app.package or "." not in app.package:
        raise ConfigError(f"app.package 不合法：{app.package!r}")
    if app.action_delay < 0:
        raise ConfigError("app.action_delay 不能为负数")

    mail = settings.mail
    if not mail.email_type_id:
        raise ConfigError("mail.email_type_id 不能为空")
    if mail.poll_interval < 1:
        raise ConfigError("mail.poll_interval 必须 >= 1 秒")
    if mail.poll_timeout < mail.poll_interval:
        raise ConfigError("mail.poll_timeout 必须大于 poll_interval")

    run = settings.run
    if run.concurrency < 1:
        raise ConfigError("run.concurrency 必须 >= 1")
    if run.age_gate not in {"instagram", "facebook", "none"}:
        raise ConfigError("run.age_gate 只能是 instagram / facebook / none")
    try:
        year, month, day = (int(part) for part in run.birthday.split("-"))
        import datetime

        birth = datetime.date(year, month, day)
        today = datetime.date.today()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
        if age < 18:
            raise ValueError
    except Exception as exc:  # noqa: BLE001 - converted to ConfigError
        raise ConfigError("run.birthday 必须是 YYYY-MM-DD 且年龄 >= 18") from exc


def load_settings(path: str | Path | None = None) -> Settings:
    base = app_root()
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = base / config_path
    if not config_path.exists():
        raise ConfigError(
            f"配置文件不存在：{config_path}\n"
            "请从 config/settings.json 开始，或运行 python -m muse_auto --help"
        )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"读取配置失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError("配置文件根节点必须是对象")

    raw = json.loads(json.dumps(raw))  # deep copy before env overrides
    _env_overrides(raw)

    root = config_path.parent.parent if config_path.parent.name == "config" else base
    log_level = str(_section(raw, "logging").get("level", "INFO")).upper()

    settings = Settings(
        vmos=_build(VmosConfig, _section(raw, "vmos"), "vmos"),
        app=_build(AppConfig, _section(raw, "app"), "app"),
        mail=_build(MailConfig, _section(raw, "mail"), "mail"),
        run=_build(RunConfig, _section(raw, "run"), "run"),
        log_level=log_level,
        project_root=root,
        config_path=config_path,
    )
    _validate(settings)
    return settings
