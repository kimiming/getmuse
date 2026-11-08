"""Command line interface.

Examples
--------
    python -m muse_auto discover --running
    python -m muse_auto inspect --instance PH19L-003 --tree
    python -m muse_auto run smoke --instance PH19L-003
    python -m muse_auto run register --instance PH19L-003 --limit 1
    python -m muse_auto mail balance
    python -m muse_auto doctor
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path
from typing import Sequence

from muse_auto import __version__
from muse_auto.apps.muse.flows.smoke import SmokeFlow
from muse_auto.apps.muse.pages import MusePages
from muse_auto.apps.muse.pipeline import MusePipelineFlow, normalize_steps
from muse_auto.config import DEFAULT_CONFIG_PATH, Settings, load_settings
from muse_auto.core.errors import ConfigError, MuseError, Stopped
from muse_auto.core.logging import get_logger, setup_logging
from muse_auto.core.stop import StopToken
from muse_auto.runner.artifacts import ArtifactStore
from muse_auto.runner.batch import BatchRunner, TaskResult
from muse_auto.services.ledger import Ledger
from muse_auto.services.mail import MailClient
from muse_auto.ui.parser import UiTree
from muse_auto.vmos.device import DeviceApi
from muse_auto.vmos.discovery import (
    DiscoveryResult,
    discover_instances,
    select_instances,
)
from muse_auto.vmos.models import VmosInstance

LOGGER = get_logger("muse_auto.cli")


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="muse-auto",
        description="VMOS Edge + Muse (Meta) automation",
    )
    parser.add_argument("--version", action="version", version=f"muse-auto {__version__}")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="配置文件路径")
    parser.add_argument("--log-level", default=None, help="覆盖日志级别（DEBUG/INFO/WARNING）")

    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="发现主机和实例")
    _add_host_options(discover)
    discover.add_argument("--running", action="store_true", help="只显示运行中的实例")
    discover.add_argument("--json", action="store_true", help="输出 JSON")
    discover.add_argument("--limit", type=int, default=0, help="限制输出条数，0=全部")

    inspect = sub.add_parser("inspect", help="抓取指定实例的页面、控件树和截图")
    _add_host_options(inspect)
    inspect.add_argument("--instance", action="append", default=[], help="实例名或 db_id")
    inspect.add_argument("--db-id", default="", help="直接指定 db_id")
    inspect.add_argument("--tree", action="store_true", help="打印控件树")
    inspect.add_argument("--launch", action="store_true", help="先启动 Muse")
    inspect.add_argument("--no-screenshot", action="store_true", help="不保存截图")
    inspect.add_argument("--json", action="store_true", help="输出 JSON")

    run = sub.add_parser("run", help="执行流程")
    run.add_argument(
        "flow",
        choices=["smoke", "register"],
        help="smoke=只检查页面；register=按步骤执行（默认 1→2→3→4）",
    )
    _add_host_options(run)
    run.add_argument("--instance", action="append", default=[], help="实例名或 db_id，可重复")
    run.add_argument("--all-running", action="store_true", help="选择全部运行中的实例")
    run.add_argument("--limit", type=int, default=1, help="最多处理几个实例，0=全部（默认 1）")
    run.add_argument("--concurrency", type=int, default=0, help="覆盖 run.concurrency")
    run.add_argument("--dry-run", action="store_true", help="只检查和打印计划，不买邮箱、不操作 App")
    run.add_argument("--invite-code", default=None, help="注册后兑换的邀请码")
    run.add_argument("--age-gate", choices=["instagram", "facebook", "none"], default=None)
    run.add_argument("--birthday", default=None, help="YYYY-MM-DD，默认读取配置")
    run.add_argument("--clear-data", action="store_true", help="注册前清空 Muse 应用数据")
    run.add_argument(
        "--steps",
        default=None,
        help="执行步骤，逗号分隔：1注册 2换邮箱 3邀请码 4保存XLS 5清缓存；默认 1,2,3,4,5",
    )
    run.add_argument("--flow-name", default=None, help="自定义流程名称，仅用于日志/结果")
    run.add_argument("--rounds", type=int, default=None, help="自动运行轮数，默认读取配置（2）")
    run.add_argument("--interval", type=float, default=None, help="轮间隔秒数，默认读取配置（10）")
    run.add_argument(
        "--mail-source",
        choices=["onlineDispoMail", "自选邮箱API", "Outlook邮箱"],
        default=None,
        help="注册邮箱来源：默认 onlineDispoMail",
    )
    run.add_argument(
        "--register-email-file",
        default=None,
        help="自选邮箱文件，默认 registerEmail.txt.txt",
    )
    run.add_argument(
        "--outlook-mail-file",
        default=None,
        help="Outlook Graph 邮箱文件，默认 outlookMail.txt",
    )

    change_email = sub.add_parser("change-email", help="对已注册实例更换绑定邮箱并保存账号")
    _add_host_options(change_email)
    change_email.add_argument("--instance", action="append", default=[], help="实例名或 db_id")
    change_email.add_argument("--email", default="", help="指定邮箱；默认从 changeEmail.txt 取第一个")
    change_email.add_argument("--xls", default="", help="覆盖 muse账号.xls 路径")
    change_email.add_argument("--no-save", action="store_true", help="只换邮箱，不写 XLS")

    mail = sub.add_parser("mail", help="临时邮箱 API 工具")
    mail.add_argument("action", choices=["balance", "services", "types"], help="查询项")
    mail.add_argument("--filter", default="", help="services 过滤关键字（如 muse/meta）")

    ledger = sub.add_parser("ledger", help="查看/导出账号账本")
    ledger.add_argument("--csv", default="", help="导出 CSV 路径")
    ledger.add_argument("--json", action="store_true", help="输出 JSON")
    ledger.add_argument(
        "--xls-merge",
        action="store_true",
        help="把 muse账号.xls.pending.jsonl 合并回 muse账号.xls（先关闭 WPS/Excel）",
    )
    ledger.add_argument("--xls", default="", help="覆盖 muse账号.xls 路径")

    doctor = sub.add_parser("doctor", help="自检配置、邮箱余额、主机和 App")
    _add_host_options(doctor)

    gui = sub.add_parser("gui", help="打开 tkinter 操作界面")
    gui.add_argument("--no-auto-discover", action="store_true", help="启动时不自动扫描实例")

    return parser


def _add_host_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", action="append", default=[], help="追加 VMOS 主机 IP")
    parser.add_argument("--no-scan", action="store_true", help="不扫描本机私网")
    parser.add_argument("--no-adb", action="store_true", help="不从 adb devices 取主机")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        settings = load_settings(args.config)
    except ConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2

    level = (args.log_level or settings.log_level).upper()
    log_dir = settings.project_root / "logs"
    log_file = log_dir / f"run_{time.strftime('%Y%m%d_%H%M%S')}.log"
    setup_logging(level, log_file)

    stop = StopToken()
    _install_signal_handlers(stop)

    try:
        if args.command == "discover":
            return _cmd_discover(settings, args, stop)
        if args.command == "inspect":
            return _cmd_inspect(settings, args, stop)
        if args.command == "run":
            return _cmd_run(settings, args, stop)
        if args.command == "change-email":
            return _cmd_change_email(settings, args, stop)
        if args.command == "mail":
            return _cmd_mail(settings, args)
        if args.command == "ledger":
            return _cmd_ledger(settings, args)
        if args.command == "doctor":
            return _cmd_doctor(settings, args, stop)
        if args.command == "gui":
            return _cmd_gui(settings, args)
    except KeyboardInterrupt:
        print("\n已中断", file=sys.stderr)
        return 130
    except Stopped:
        print("\n已停止", file=sys.stderr)
        return 130
    except MuseError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        LOGGER.debug("命令失败", exc_info=True)
        return 1
    return 0


def _install_signal_handlers(stop: StopToken) -> None:
    def handler(signum, _frame) -> None:  # noqa: ANN001
        if stop.stopped:
            raise KeyboardInterrupt
        print("\n收到停止信号，等待当前步骤结束（再按一次 Ctrl+C 强制退出）……", file=sys.stderr)
        stop.stop()

    for name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, name, None)
        if sig is not None:
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _discover(settings: Settings, args, stop: StopToken) -> DiscoveryResult:
    hosts = list(settings.vmos.hosts) + list(getattr(args, "host", []) or [])
    scan = settings.vmos.scan and not getattr(args, "no_scan", False)
    use_adb = settings.vmos.use_adb and not getattr(args, "no_adb", False)

    def progress(done: int, total: int) -> None:
        if sys.stderr.isatty():
            print(f"\r扫描 {done}/{total} ……", end="", file=sys.stderr)

    result = discover_instances(
        hosts,
        port=settings.vmos.port,
        scan=scan,
        use_adb=use_adb,
        probe_timeout=settings.vmos.probe_timeout,
        list_timeout=settings.vmos.list_timeout,
        scan_workers=settings.vmos.scan_workers,
        host_workers=settings.vmos.max_host_workers,
        stop=stop,
        progress=progress,
    )
    if sys.stderr.isatty():
        print("\r", end="", file=sys.stderr)
    return result


def _cmd_discover(settings: Settings, args, stop: StopToken) -> int:
    result = _discover(settings, args, stop)
    instances = result.running if args.running else result.instances
    if args.limit and args.limit > 0:
        instances = instances[: args.limit]

    if args.json:
        payload = {
            "hosts": [str(host) for host in result.hosts],
            "failures": result.failures,
            "instances": [
                {
                    "name": item.name,
                    "db_id": item.db_id,
                    "host": item.host.ip,
                    "port": item.host.port,
                    "state": item.state,
                    "adb": item.adb_port,
                }
                for item in instances
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"主机：{len(result.hosts)} 台   实例：{len(result.instances)} 个   "
          f"运行中：{len(result.running)} 个")
    if result.failures:
        print("失败/忽略：")
        for item in result.failures[:20]:
            print(f"  - {item}")
        if len(result.failures) > 20:
            print(f"  ... 另外 {len(result.failures) - 20} 条")

    if instances:
        width = max(12, min(40, max(len(item.name) for item in instances)))
        print(f"{'NAME':<{width}}  {'STATE':<8}  {'DB_ID':<20}  HOST")
        for item in instances:
            print(f"{item.name:<{width}}  {item.state:<8}  {item.db_id:<20}  {item.host.ip}")
    return 0


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------


def _select_one(settings: Settings, args, stop: StopToken) -> VmosInstance:
    result = _discover(settings, args, stop)
    terms = list(getattr(args, "instance", []) or [])
    if getattr(args, "db_id", ""):
        terms.append(args.db_id)
    if not terms:
        raise ConfigError("inspect 需要 --instance 或 --db-id")
    matches = select_instances(result.instances, terms)
    if not matches:
        raise ConfigError(f"没有找到实例：{', '.join(terms)}（共 {len(result.instances)} 个）")
    if len(matches) > 1:
        names = ", ".join(item.label for item in matches[:6])
        raise ConfigError(f"匹配到多个实例，请写完整名称：{names}")
    return matches[0]


def _cmd_inspect(settings: Settings, args, stop: StopToken) -> int:
    instance = _select_one(settings, args, stop)
    device = DeviceApi(instance, timeout=settings.app.dump_timeout, stop=stop)
    store = ArtifactStore(settings.artifact_dir, f"inspect_{instance.name}")

    top = device.top_activity()
    width, height = device.display_info()
    installed = device.is_installed(settings.app.package)
    version = device.app_version(settings.app.package) if installed else ""

    if args.launch:
        from muse_auto.apps.muse.app import MuseApp

        app = MuseApp(device, package=settings.app.package, launch_wait=settings.app.launch_wait, stop=stop)
        if not installed:
            raise ConfigError(f"实例未安装 {settings.app.package}")
        app.launch()
        top = device.top_activity()
        width, height = device.display_info()

    xml = device.dump(timeout=settings.app.dump_timeout)
    from muse_auto.ui.parser import parse_dump

    tree = parse_dump(xml)
    match = MusePages.detect(tree, top.get("package_name", ""))

    saved: dict[str, str] = {}
    saved["xml"] = str(store.save_text("ui.xml", xml))
    screenshot_error = ""
    if not args.no_screenshot:
        try:
            saved["screenshot"] = str(device.screenshot(store.path("screen.png")))
        except MuseError as exc:
            screenshot_error = str(exc)
            print(f"截图失败（不影响控件树）：{exc}", file=sys.stderr)
    meta = {
        "instance": instance.label,
        "host": instance.host.ip,
        "db_id": instance.db_id,
        "state": instance.state,
        "activity": top,
        "display": {"width": width, "height": height},
        "package": settings.app.package,
        "installed": installed,
        "version": version,
        "page": match.page.value,
        "page_reason": match.reason,
        "nodes": len(tree.nodes),
        "summary": tree.summary(limit=500),
        "artifacts": saved,
        "screenshot_error": screenshot_error,
    }
    store.save_text("meta.json", json.dumps(meta, ensure_ascii=False, indent=2))

    if args.json:
        print(json.dumps(meta, ensure_ascii=False, indent=2))
        return 0

    print(f"实例：{instance.label}")
    print(f"前台：{top.get('package_name')}/{top.get('class_name')}")
    print(f"屏幕：{width}x{height}")
    print(f"App ：{settings.app.package} installed={installed} version={version or '-'}")
    print(f"页面：{MusePages.describe(match)}")
    print(f"控件：{len(tree.nodes)} 个")
    print(f"摘要：{tree.summary(limit=220)}")
    print(f"产物：{store.directory}")
    if args.tree:
        print("-" * 78)
        _print_tree(tree)
    return 0


def _print_tree(tree: UiTree, limit: int = 250) -> None:
    printed = 0

    def walk(node, depth: int) -> None:
        nonlocal printed
        if printed >= limit:
            return
        if not node.visible:
            return
        interesting = bool(
            node.text or node.desc or node.resource_id or node.clickable or node.editable
        )
        if interesting:
            parts = []
            if node.text:
                parts.append(f"text={node.text!r}")
            if node.desc:
                parts.append(f"desc={node.desc!r}")
            if node.resource_id:
                parts.append(f"id={node.resource_id.split('/')[-1]!r}")
            if node.editable:
                parts.append("EDIT")
            if node.clickable:
                parts.append("CLICK")
            if node.password:
                parts.append("PASSWORD")
            pos = node.center or (0, 0)
            print("  " * depth + f"{node.class_name.split('.')[-1]} " + " ".join(parts) + f" @{pos}")
            printed += 1
        for child in node.children:
            walk(child, depth + 1 if interesting else depth)

    walk(tree.root, 0)
    if printed >= limit:
        print(f"... 已截断（{limit} 行）")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------


def _cmd_run(settings: Settings, args, stop: StopToken) -> int:
    result = _discover(settings, args, stop)
    terms = list(args.instance or [])
    if terms:
        instances = select_instances(result.instances, terms)
        missing = [term for term in terms if not select_instances(result.instances, [term])]
        if missing:
            print(f"未找到实例：{', '.join(missing)}", file=sys.stderr)
            return 1
    elif args.all_running:
        instances = result.running
    else:
        print("请用 --instance 指定实例，或 --all-running", file=sys.stderr)
        return 2

    if args.limit and args.limit > 0:
        instances = instances[: args.limit]
    if not instances:
        print("没有可处理的实例", file=sys.stderr)
        return 1

    if args.concurrency:
        settings = _with_concurrency(settings, args.concurrency)
    if args.invite_code is not None:
        settings = _with_run(settings, invite_code=args.invite_code)
    if args.age_gate:
        settings = _with_run(settings, age_gate=args.age_gate)
    if args.birthday:
        settings = _with_run(settings, birthday=args.birthday)
    if args.clear_data:
        settings = _with_app(settings, clear_data_before_register=True)
    rounds = settings.run.rounds if args.rounds is None else int(args.rounds)
    interval = (
        settings.run.round_interval if args.interval is None else float(args.interval)
    )
    if rounds < 1:
        print("--rounds 必须 >=1", file=sys.stderr)
        return 2
    if interval < 0:
        print("--interval 不能小于 0", file=sys.stderr)
        return 2

    print(f"流程={args.flow} 实例={len(instances)} 并发={settings.run.concurrency} dry_run={args.dry_run}")
    print(f"轮数={rounds} 轮间隔={interval:g}s")

    if args.dry_run:
        return _dry_run(settings, instances, stop)

    ledger = Ledger(settings.ledger_path)
    mail = None
    if args.flow == "register":
        steps = normalize_steps(args.steps or settings.run.steps)
        flow_name = args.flow_name or settings.run.flow_name
        source = args.mail_source or settings.run.mail_source
        if args.register_email_file:
            settings = _with_run(settings, register_email_path=args.register_email_file)
        if args.outlook_mail_file:
            settings = _with_run(settings, outlook_mail_path=args.outlook_mail_file)
        settings = _with_run(settings, mail_source=source)
        print(f"步骤={steps} 流程名称={flow_name} 注册邮箱来源={source}")
        if 1 in steps:
            if source in ("自选邮箱API", "custom", "registerEmail"):
                from muse_auto.services.registration_mail import CustomMailProvider

                mail_path = Path(settings.run.register_email_path)
                if not mail_path.is_absolute():
                    mail_path = settings.project_root / mail_path
                mail = CustomMailProvider(mail_path, stop=stop)
                print(f"自选邮箱剩余：{mail.remaining()} 个")
            elif source in ("Outlook邮箱", "outlook"):
                from muse_auto.services.outlook_mail import OutlookMailProvider

                mail_path = Path(settings.run.outlook_mail_path)
                if not mail_path.is_absolute():
                    mail_path = settings.project_root / mail_path
                mail = OutlookMailProvider(
                    mail_path,
                    timeout=settings.mail.request_timeout,
                    stop=stop,
                )
                print(f"Outlook 邮箱剩余：{mail.remaining()} 个")
            else:
                if not settings.mail.api_key:
                    print("mail.api_key 未配置，无法执行步骤1注册", file=sys.stderr)
                    return 2
                mail = MailClient(
                    base_url=settings.mail.base_url,
                    api_key=settings.mail.api_key,
                    timeout=settings.mail.request_timeout,
                    stop=stop,
                )
                try:
                    print(f"邮箱余额：{mail.balance():.2f}")
                except MuseError as exc:
                    print(f"邮箱接口不可用：{exc}", file=sys.stderr)
                    return 1
        flow = MusePipelineFlow(
            settings=settings,
            mail_client=mail,  # type: ignore[arg-type]
            ledger=ledger,
            steps=steps,
            flow_name=flow_name,
        )
    else:
        flow = SmokeFlow()

    def task(instance, task_stop, ctx):
        return flow.run(ctx)

    all_results: list[TaskResult] = []
    for round_no in range(1, rounds + 1):
        if stop.stopped:
            break
        if round_no > 1:
            print(f"\n第 {round_no}/{rounds} 轮将在 {interval:g} 秒后开始……")
            stop.sleep(interval)
        print(f"\n===== 第 {round_no}/{rounds} 轮开始 =====")

        def on_result(item: TaskResult, _round=round_no) -> None:
            item.round = _round
            mark = "OK " if item.ok else "ERR"
            print(
                f"[{mark}] 第{_round}轮 {item.instance.name:<24} {item.status:<18} "
                f"{item.email or '-':<34} {item.message[:70]}"
            )

        runner = BatchRunner(settings, stop=stop, on_result=on_result)
        all_results.extend(runner.run(instances, task))

    ok = sum(1 for item in all_results if item.ok)
    print(f"\n完成：{ok}/{len(all_results)} 成功（{rounds} 轮）")
    for item in all_results:
        if not item.ok:
            print(f"  - 第{item.round or '?'}轮 {item.instance.name}: {item.status} {item.message[:100]}")
    return 0 if ok == len(all_results) else 1


def _dry_run(settings: Settings, instances: list[VmosInstance], stop: StopToken) -> int:
    print("dry-run：只检查，不购买邮箱、不点击 App")
    for instance in instances:
        stop.check()
        device = DeviceApi(instance, timeout=settings.app.dump_timeout, stop=stop)
        try:
            installed = device.is_installed(settings.app.package)
            top = device.top_activity()
            print(
                f"  {instance.name:<24} state={instance.state:<8} "
                f"installed={installed} top={top.get('package_name') or '-'}"
            )
        except MuseError as exc:
            print(f"  {instance.name:<24} 检查失败：{exc}")
    print(f"将购买 {len(instances)} 个 {settings.mail.service} 邮箱（dry-run 不实际购买）")
    return 0


# ---------------------------------------------------------------------------
# Mail / ledger / doctor
# ---------------------------------------------------------------------------


def _cmd_change_email(settings: Settings, args, stop: StopToken) -> int:
    from muse_auto.apps.muse.account_center import AccountCenter
    from muse_auto.apps.muse.app import MuseApp
    from muse_auto.apps.muse.components import MuseComponents
    from muse_auto.apps.muse.pages import MusePages
    from muse_auto.runner.artifacts import ArtifactStore
    from muse_auto.services.account_store import MuseAccountStore
    from muse_auto.services.email_pool import EmailPool
    from muse_auto.services.yich8_mail import Yich8MailClient
    from muse_auto.ui.session import UiSession

    result = _discover(settings, args, stop)
    terms = list(args.instance or [])
    if not terms:
        print("change-email 需要 --instance", file=sys.stderr)
        return 2
    matches = select_instances(result.instances, terms)
    if len(matches) != 1:
        print(f"匹配到 {len(matches)} 个实例，请写完整名称", file=sys.stderr)
        return 2
    instance = matches[0]

    project = settings.project_root
    pool_path = (
        Path(settings.run.email_pool_path)
        if Path(settings.run.email_pool_path).is_absolute()
        else project / settings.run.email_pool_path
    )
    api_path = (
        Path(settings.run.email_api_path)
        if Path(settings.run.email_api_path).is_absolute()
        else project / settings.run.email_api_path
    )
    xls_path = (
        Path(args.xls)
        if args.xls
        else (
            Path(settings.run.account_xls_path)
            if Path(settings.run.account_xls_path).is_absolute()
            else project / settings.run.account_xls_path
        )
    )

    device = DeviceApi(instance, timeout=settings.app.dump_timeout, stop=stop)
    session = UiSession(
        device,
        stop=stop,
        action_delay=settings.app.action_delay,
        dump_retries=settings.app.dump_retries,
    )
    app = MuseApp(device, package=settings.app.package, stop=stop)
    pool = EmailPool(pool_path)
    taken_from_pool = not bool(args.email)
    email = args.email.strip() or pool.take()
    if not email:
        print(f"邮箱池为空：{pool_path}", file=sys.stderr)
        return 2

    print(f"实例：{instance.name}  目标邮箱：{email}")
    try:
        app.launch(force_stop=False)
        components = MuseComponents(session, app, stop=stop)
        components.dismiss_permission()
        for _ in range(5):
            page = MusePages.detect(
                session.dump(force=True),
                session.top_activity().get("package_name", ""),
            )
            if page.page.value == "permission":
                components.dismiss_permission()
                stop.sleep(1.0)
                continue
            if page.page.value == "home":
                break
            session.back(settle=2.0)
            stop.sleep(1.0)
        else:
            raise MuseError("实例没有回到 Muse 首页，请先人工回到首页")

        mail = Yich8MailClient.from_file(api_path, stop=stop)
        baseline = mail.max_mbox_id(email)
        print(f"邮箱基线 mbox_id={baseline}，开始更换……")
        AccountCenter(session, app, stop=stop).change_email(email, mail, baseline)
        if args.no_save:
            print("换邮箱成功（--no-save，未写 XLS）")
        else:
            MuseAccountStore(xls_path, api_template=mail.api_url).append(email)
            print(f"换邮箱成功，已追加到 {xls_path}")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"换邮箱失败：{exc}", file=sys.stderr)
        if taken_from_pool:
            pool.restore(email)
        try:
            store = ArtifactStore(settings.artifact_dir, f"change_email_{instance.name}")
            session.save_artifacts(store.directory, "fail")
            print(f"现场已保存：{store.directory}", file=sys.stderr)
        except Exception:  # noqa: BLE001
            pass
        return 1


def _cmd_mail(settings: Settings, args) -> int:
    if not settings.mail.api_key:
        print("mail.api_key 未配置", file=sys.stderr)
        return 2
    client = MailClient(
        base_url=settings.mail.base_url,
        api_key=settings.mail.api_key,
        timeout=settings.mail.request_timeout,
    )
    if args.action == "balance":
        print(f"余额：{client.balance():.2f}")
        return 0
    if args.action == "services":
        needle = (args.filter or "").casefold()
        rows = client.services()
        for item in rows:
            name = str(item.get("serviceName") or "")
            if needle and needle not in name.casefold():
                continue
            print(f"{item.get('serviceId'):>5}  {name}")
        return 0
    if args.action == "types":
        for item in client.types():
            print(f"{item.get('id'):>3}  {item.get('name')}")
        return 0
    return 2


def _cmd_ledger(settings: Settings, args) -> int:
    if args.xls_merge:
        from muse_auto.services.account_store import MuseAccountStore
        from muse_auto.services.yich8_mail import read_api_template

        path = Path(args.xls) if args.xls else (
            Path(settings.run.account_xls_path)
            if Path(settings.run.account_xls_path).is_absolute()
            else settings.project_root / settings.run.account_xls_path
        )
        api_path = (
            Path(settings.run.email_api_path)
            if Path(settings.run.email_api_path).is_absolute()
            else settings.project_root / settings.run.email_api_path
        )
        try:
            api_template = read_api_template(api_path)
        except Exception as exc:  # noqa: BLE001
            print(f"读取邮箱 API 模板失败：{exc}", file=sys.stderr)
            api_template = ""
        store = MuseAccountStore(path, api_template=api_template)
        target = store.flush()
        rows = store.read_all()
        print(f"muse账号：{target}  共 {len(rows)} 条")
        if store.pending_path.exists():
            print(
                f"仍有待合并日志：{store.pending_path}（请关闭 WPS/Excel 后再执行一次）",
                file=sys.stderr,
            )
            return 1
        return 0

    ledger = Ledger(settings.ledger_path)
    records = ledger.all()
    if args.csv:
        target = ledger.export_csv(args.csv)
        print(f"已导出 {len(records)} 条到 {target}")
        return 0
    if args.json:
        print(json.dumps([record.to_dict() for record in records], ensure_ascii=False, indent=2))
        return 0
    print(f"账本：{ledger.path}  共 {len(records)} 条")
    for status, count in sorted(ledger.counts().items()):
        print(f"  {status}: {count}")
    for record in records[-10:]:
        print(f"  {record.updated_at}  {record.email:<36} {record.status:<18} {record.note[:50]}")
    return 0


def _cmd_gui(settings: Settings, args) -> int:
    try:
        from muse_auto.gui.app import run_gui
    except Exception as exc:  # noqa: BLE001 - tkinter may be absent
        print(f"无法加载 GUI：{exc}", file=sys.stderr)
        return 1
    try:
        return run_gui(settings, auto_discover=not args.no_auto_discover)
    except Exception as exc:  # noqa: BLE001 - no display / Tcl error
        print(f"GUI 启动失败：{exc}", file=sys.stderr)
        return 1


def _cmd_doctor(settings: Settings, args, stop: StopToken) -> int:
    print(f"muse-auto {__version__}")
    print(f"配置：{settings.config_path}")
    print(f"项目根：{settings.project_root}")
    print(f"App：{settings.app.package}")
    print(f"邮箱：{settings.mail.base_url}  key={settings.masked_api_key}  service={settings.mail.service}")

    healthy = True
    if settings.mail.api_key:
        try:
            print(f"邮箱余额：{MailClient(base_url=settings.mail.base_url, api_key=settings.mail.api_key).balance():.2f}")
        except MuseError as exc:
            print(f"邮箱接口：失败（{exc}）")
            healthy = False
    else:
        print("邮箱接口：未配置 API key")
        healthy = False

    result = _discover(settings, args, stop)
    print(f"VMOS：主机 {len(result.hosts)} 台，实例 {len(result.instances)} 个，运行中 {len(result.running)} 个")
    if result.failures:
        print(f"发现失败：{len(result.failures)} 条（前 3 条：{'; '.join(result.failures[:3])}）")
    if not result.hosts:
        print("没有发现 VMOS 主机：请确认与云机在同一私网，或配置 vmos.hosts")
        healthy = False

    probe = next((item for item in result.running if item.state == "running"), None)
    if probe is not None:
        device = DeviceApi(probe, timeout=settings.app.dump_timeout, stop=stop)
        try:
            installed = device.is_installed(settings.app.package)
            version = device.app_version(settings.app.package) if installed else ""
            top = device.top_activity()
            print(
                f"探测实例：{probe.name} installed={installed} "
                f"version={version or '-'} top={top.get('package_name') or '-'}"
            )
            if not installed:
                print(f"警告：{probe.name} 未安装 {settings.app.package}")

            try:
                ping = device.shell("ping -c 1 -W 2 8.8.8.8", timeout=10)
                print(f"实例网络：ping {'OK' if '1 received' in ping or '1 packets received' in ping else '失败'}")
            except MuseError as exc:
                print(f"实例网络：ping 失败（{exc}）")
            try:
                device.shell("curl -sS -m 8 https://ipinfo.io/json", timeout=15)
                print("实例网络：HTTPS 出口 OK")
            except MuseError as exc:
                print(f"实例网络：HTTPS 出口失败（{str(exc)[:120]}）")
                print("  → Muse 注册需要访问 Meta HTTPS，请给实例配置代理/软路由")
                healthy = False
        except MuseError as exc:
            print(f"探测实例失败：{exc}")
            healthy = False
    else:
        print("没有运行中的实例可探测")
    return 0 if healthy else 1


# ---------------------------------------------------------------------------
# Small immutable-settings helpers
# ---------------------------------------------------------------------------


def _with_concurrency(settings: Settings, value: int) -> Settings:
    from dataclasses import replace

    return replace(settings, run=replace(settings.run, concurrency=max(1, value)))


def _with_run(settings: Settings, **changes) -> Settings:
    from dataclasses import replace

    return replace(settings, run=replace(settings.run, **changes))


def _with_app(settings: Settings, **changes) -> Settings:
    from dataclasses import replace

    return replace(settings, app=replace(settings.app, **changes))
