"""Tkinter control panel for muse-auto.

Module boundaries mirror the CLI:

    InstancesView  -> scan / search / filter / assign script
    ScriptsView    -> script registry + script-owned parameters
    RunView        -> execution parameters + live results/log
    InspectView    -> page diagnostics
    MuseAutoApp    -> wiring, background tasks, event queue
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import replace
from pathlib import Path
from tkinter import messagebox, ttk

from muse_auto import __version__
from muse_auto.apps.muse.pages import MusePages
from muse_auto.apps.muse.pipeline import normalize_steps
from muse_auto.config import Settings
from muse_auto.core.errors import MuseError, Stopped
from muse_auto.core.logging import get_logger
from muse_auto.core.stop import StopToken
from muse_auto.gui.inspect_view import InspectView
from muse_auto.gui.instances_view import InstancesView
from muse_auto.gui.logging_bridge import QueueLogHandler
from muse_auto.gui.run_view import RunView
from muse_auto.gui.scripts_view import ScriptsView
from muse_auto.gui.theme import (
    ACCENT,
    ACCENT_DARK,
    BG,
    CARD,
    DANGER,
    LOG_BG,
    LOG_FG,
    MUTED,
    PANEL,
    TEXT,
)
from muse_auto.runner.artifacts import ArtifactStore
from muse_auto.runner.batch import BatchRunner, TaskResult
from muse_auto.scripts import all_scripts, default_script_id, get_script
from muse_auto.scripts.base import PreparedScript, ScriptSpec
from muse_auto.services.gui_store import GuiStore

LOGGER = get_logger("muse_auto.gui")


class MuseAutoApp:
    def __init__(
        self,
        root: tk.Tk,
        settings: Settings,
        *,
        auto_discover: bool = True,
        auto_balance: bool = True,
    ) -> None:
        self.root = root
        self.settings = settings
        self.store = GuiStore(settings.project_root / "data" / "gui_state.json")
        self._scripts: list[ScriptSpec] = all_scripts()
        self.current_script_id = default_script_id()

        self.instances: list = []
        self.events: queue.Queue[tuple] = queue.Queue()
        self.log_queue: queue.Queue[tuple] = queue.Queue()
        self.stop = StopToken()
        self.run_stop: StopToken | None = None
        self._discovering = False
        self._running = False
        self._inspecting = False
        self._closing = False
        self._worker: threading.Thread | None = None
        self._log_handler: QueueLogHandler | None = None
        self._balance: float | None = None

        self._choose_font()
        self._build_style()
        self._build_ui()
        self._install_log_handler()
        self._bind_shortcuts()
        self.update_status()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll)
        self.root.after(160, self._focus_window)
        if auto_balance:
            self.root.after(300, self.refresh_balance)
        if auto_discover:
            self.root.after(500, self.refresh_instances)

    # ------------------------------------------------------------------
    # Shell
    # ------------------------------------------------------------------

    def _choose_font(self) -> None:
        families = set(tkfont.families(self.root))
        self.ui_font = "Microsoft YaHei UI" if "Microsoft YaHei UI" in families else "Segoe UI"
        self.mono_font = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"

    def _build_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=(self.ui_font, 10), background=PANEL)
        style.configure("TButton", padding=(9, 5))
        style.configure("Accent.TButton", background=ACCENT, foreground="white", borderwidth=0)
        style.map(
            "Accent.TButton",
            background=[("active", ACCENT_DARK), ("disabled", "#e2e8f0")],
            foreground=[("disabled", "#64748b")],
        )
        style.configure("Danger.TButton", background=DANGER, foreground="white", borderwidth=0)
        style.map(
            "Danger.TButton",
            background=[("active", "#b91c1c"), ("disabled", "#fecaca")],
            foreground=[("disabled", "#7f1d1d")],
        )
        style.configure("Treeview", rowheight=27, font=(self.ui_font, 10))
        style.configure("Treeview.Heading", font=(self.ui_font, 10, "bold"))
        style.configure("TNotebook.Tab", padding=(18, 8), font=(self.ui_font, 10))
        style.configure("TLabel", background=PANEL)
        style.configure("TFrame", background=PANEL)
        style.configure("TLabelframe", background=PANEL)
        style.configure("TLabelframe.Label", background=PANEL, font=(self.ui_font, 10, "bold"))

    def _build_ui(self) -> None:
        self.root.title(f"Muse Auto {__version__} · VMOS Edge")
        self.root.geometry("1420x880")
        self.root.minsize(1160, 700)
        self.root.configure(bg=PANEL)

        self._build_header()
        self._build_statusbar()
        self._build_menu()

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(6, 2))

        self.instances_view = InstancesView(self, self.notebook)
        self.scripts_view = ScriptsView(self, self.notebook)
        self.run_view = RunView(self, self.notebook)
        self.inspect_view = InspectView(self, self.notebook)
        self.guide_view = self._build_guide(self.notebook)

        self.notebook.add(self.instances_view, text="实例")
        self.notebook.add(self.scripts_view, text="脚本与参数")
        self.notebook.add(self.run_view, text="运行")
        self.notebook.add(self.inspect_view, text="页面检查")
        self.notebook.add(self.guide_view, text="说明")
        self.notebook.select(self.instances_view)

    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=BG, height=72)
        header.pack(fill="x")
        header.pack_propagate(False)
        left = tk.Frame(header, bg=BG)
        left.pack(side="left", padx=18, pady=10)
        tk.Label(
            left,
            text="Muse Auto",
            bg=BG,
            fg="white",
            font=(self.ui_font, 19, "bold"),
        ).pack(anchor="w")
        tk.Label(
            left,
            text="VMOS Edge · 实例 / 脚本 / 运行 分离",
            bg=BG,
            fg="#94a3b8",
            font=(self.ui_font, 9),
        ).pack(anchor="w")

        right = tk.Frame(header, bg=BG)
        right.pack(side="right", padx=18, pady=10)
        self.header_balance = tk.Label(
            right, text="邮箱余额：--", bg=BG, fg="#e2e8f0", font=(self.ui_font, 10)
        )
        self.header_balance.pack(anchor="e")
        self.header_instances = tk.Label(
            right, text="实例 0 · 运行 0", bg=BG, fg="#94a3b8", font=(self.ui_font, 9)
        )
        self.header_instances.pack(anchor="e")

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self.root, padding=(10, 3, 10, 5))
        bar.pack(fill="x", side="bottom")
        self.status_var = tk.StringVar(value="就绪")
        self.selection_var = tk.StringVar(value="已选 0 个")
        self.balance_var = tk.StringVar(value="余额 --")
        ttk.Label(bar, textvariable=self.status_var).pack(side="left")
        ttk.Label(bar, textvariable=self.selection_var, foreground=MUTED).pack(
            side="left", padx=(18, 0)
        )
        ttk.Label(bar, textvariable=self.balance_var, foreground=MUTED).pack(side="right")

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="刷新实例", command=self.refresh_instances)
        file_menu.add_command(label="打开配置文件", command=self.open_config)
        file_menu.add_command(label="打开产物目录", command=self.open_artifacts)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="文件", menu=file_menu)

        action = tk.Menu(menubar, tearoff=0)
        action.add_command(label="检查选中", command=self.inspect_selected)
        action.add_command(label="开始运行", command=self.start_run)
        action.add_command(label="停止", command=self.stop_run)
        menubar.add_cascade(label="操作", menu=action)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="快速说明", command=lambda: self.notebook.select(self.guide_view))
        help_menu.add_command(label="关于", command=self.show_about)
        menubar.add_cascade(label="帮助", menu=help_menu)
        self.root.configure(menu=menubar)

    def _build_guide(self, master: tk.Misc) -> ttk.Frame:
        frame = ttk.Frame(master, padding=10)
        text = tk.Text(
            frame,
            wrap="word",
            bg="white",
            fg=TEXT,
            relief="flat",
            padx=16,
            pady=12,
            font=(self.ui_font, 10),
            state="normal",
        )
        text.pack(fill="both", expand=True)
        text.insert("1.0", self._guide_content())
        text.configure(state="disabled")
        return frame

    def _guide_content(self) -> str:
        return f"""Muse Auto 的四个模块

1. 实例
   · 只负责 VMOS 实例：扫描、搜索、IP 筛选、状态筛选、选择。
   · “脚本”列表示该实例运行哪个脚本；用“分配脚本”批量修改。
   · 双击实例 → 页面检查。

2. 脚本与参数
   · 左侧是脚本注册表：当前有 MuseAI 批量注册、MuseAI 冒烟检查。
   · 右侧是当前脚本自己的参数（邮箱 API、邀请码、生日、年龄验证等）。
   · 邮箱 API 地址 / Key / service / emailTypeId 都在这里；可查询余额。
   · “分配到选中实例”把当前脚本绑定到“实例”页选中的实例。
   · 加新 App：在 muse_auto/scripts/ 添加 ScriptSpec，界面自动出现。

3. 运行
   · 并发、最多实例、出错停止属于运行参数，不属于脚本。
   · 开始后按实例的脚本分组执行；不同脚本依次跑。
   · 结果表、实时日志、停止按钮都在这里。

4. 页面检查
   · 前台 Activity、屏幕、安装状态、页面识别、控件树摘要。
   · 产物保存到 artifacts/。

配置
  配置文件：{self.settings.config_path}
   包名：{self.settings.app.package}
   账本：{self.settings.ledger_path}
   产物：{self.settings.artifact_dir}
   邮箱：Meta Ai / Gmail_1（serviceId 302 / emailTypeId 26）

建议流程
   刷新实例 → 选 1 个实例 → 检查/冒烟 → 脚本页填参数并保存
   → 分配脚本 → 运行页“最多=1”先跑通 → 再批量。
"""

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F5>", lambda _event: self.refresh_instances())
        self.root.bind("<Control-r>", lambda _event: self.refresh_instances())
        self.root.bind("<Control-i>", lambda _event: self.inspect_selected())
        self.root.bind("<Escape>", lambda _event: self.stop_run())

    def _install_log_handler(self) -> None:
        self._log_handler = QueueLogHandler(self.log_queue)
        self._log_handler.setLevel(logging.DEBUG)
        logger = logging.getLogger("muse_auto")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._log_handler)

    def _focus_window(self) -> None:
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
            self.root.attributes("-topmost", True)
            self.root.after(600, lambda: self.root.attributes("-topmost", False))
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Registry helpers
    # ------------------------------------------------------------------

    def scripts(self) -> list[ScriptSpec]:
        return list(self._scripts)

    def script(self, script_id: str) -> ScriptSpec:
        try:
            return get_script(script_id)
        except KeyError:
            return self._scripts[0]

    def script_names(self) -> dict[str, str]:
        return {spec.id: spec.name for spec in self._scripts}

    @property
    def default_script_id(self) -> str:
        return self._scripts[0].id

    def script_params(self, script_id: str) -> dict:
        spec = self.script(script_id)
        return self.store.params(spec.id, spec.defaults(self.settings))

    def set_current_script(self, script_id: str) -> None:
        self.current_script_id = script_id
        self.instances_view.set_current_script(script_id)
        self.update_status()

    def assign_script(self, keys: list[str], script_id: str) -> None:
        self.store.set_assignments(keys, script_id)
        name = self.script(script_id).name
        self.log(logging.INFO, f"已分配 {len(keys)} 个实例到脚本：{name}")
        self.instances_view.refresh_display()
        self.update_status()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def update_status(self) -> None:
        total = len(self.instances)
        running = sum(1 for item in self.instances if item.running)
        selected = len(self.instances_view.selected_instances())
        self.selection_var.set(f"已选 {selected} 个")
        self.header_instances.configure(text=f"实例 {total} · 运行 {running} · 已选 {selected}")
        if not self._running and not self._discovering and not self._inspecting:
            self.status_var.set("就绪")
        groups = self._group_preview(self.instances_view.selected_instances())
        self.run_view.set_summary(groups)
        if not (self._running or self._discovering or self._inspecting):
            self.run_view.start_btn.configure(
                state="normal" if selected else "disabled"
            )
        self.balance_var.set(
            f"余额 ${self._balance:.2f}" if self._balance is not None else "余额 --"
        )

    def _group_preview(self, selected: list) -> str:
        if not selected:
            return "尚未选择实例"
        groups: dict[str, int] = {}
        for instance in selected:
            sid = self.store.assignment(instance.key, self.current_script_id)
            groups[sid] = groups.get(sid, 0) + 1
        parts = [f"{self.script(sid).name} × {count}" for sid, count in groups.items()]
        billable = sum(
            count
            for sid, count in groups.items()
            if self._script_billable(sid)
        )
        suffix = f"；预计购买 {billable} 个邮箱" if billable else ""
        return f"已选 {len(selected)} 个实例： " + "，".join(parts) + suffix

    def _script_billable(self, script_id: str) -> bool:
        spec = self.script(script_id)
        if script_id == "muse.register":
            try:
                params = self.script_params(script_id)
                source = str(params.get("mail_source") or "onlineDispoMail")
                if source not in ("onlineDispoMail", "online"):
                    return False
                steps = normalize_steps(params.get("steps"))
                return 1 in steps
            except Exception:  # noqa: BLE001
                return spec.billable
        return spec.billable

    def log(self, level: int | str, message: str) -> None:
        if isinstance(level, str):
            level = getattr(logging, level.upper(), logging.INFO)
        self.run_view.append_log(level, message)
        LOGGER.log(level, message)

    # ------------------------------------------------------------------
    # Background event loop
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        count = 0
        while count < 400:
            try:
                _kind, level, text = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.run_view.append_log(level, text)
            count += 1

        for _ in range(120):
            try:
                kind, *payload = self.events.get_nowait()
            except queue.Empty:
                break
            try:
                self._handle_event(kind, payload)
            except Exception:  # noqa: BLE001
                LOGGER.exception("GUI 事件处理失败：%s", kind)
        if not self._closing or (self._worker is not None and self._worker.is_alive()):
            self.root.after(120, self._poll)

    def _handle_event(self, kind: str, payload: list) -> None:
        if kind == "progress":
            done, total = payload
            self.status_var.set(f"扫描中 {done}/{total} ……")
        elif kind == "discovered":
            result, error = payload
            self._discovering = False
            self._set_busy()
            if error is not None:
                self.status_var.set("实例发现失败")
                self.log(logging.ERROR, f"实例发现失败：{error}")
                messagebox.showerror("发现失败", str(error))
                return
            self.instances = result.instances
            self.instances_view.set_instances(self.instances)
            self.status_var.set(
                f"主机 {len(result.hosts)} 台 · 实例 {len(result.instances)} 个 · "
                f"运行中 {len(result.running)} 个"
            )
            self.log(
                logging.INFO,
                f"实例刷新完成：主机 {len(result.hosts)}，实例 {len(result.instances)}，"
                f"运行中 {len(result.running)}",
            )
            for failure in result.failures[:20]:
                self.log(logging.WARNING, failure)
            self.update_status()
        elif kind == "balance":
            value, error = payload
            if error is not None:
                self._balance = None
                self._set_balance_label("邮箱余额：--")
                self.log(logging.WARNING, f"查询邮箱余额失败：{error}")
            else:
                self._balance = float(value)
                self._set_balance_label(f"邮箱余额：${self._balance:.2f}")
            self.update_status()
        elif kind == "script_balance":
            value, error = payload
            self.scripts_view.set_balance(value, error)
            if error is None and value is not None:
                self._balance = float(value)
                self._set_balance_label(f"邮箱余额：${self._balance:.2f}")
                self.update_status()
        elif kind == "log":
            level, text = payload
            self.run_view.append_log(level, text)
        elif kind == "inspected":
            instance, text, artifact, error = payload
            self._inspecting = False
            self._set_busy()
            if error is not None:
                self.status_var.set("页面检查失败")
                self.log(logging.ERROR, f"[{instance.name}] 检查失败：{error}")
                messagebox.showerror("检查失败", str(error))
                return
            self.inspect_view.set_text(text)
            self.notebook.select(self.inspect_view)
            self.status_var.set(f"已检查 {instance.name}")
            self.log(logging.INFO, f"[{instance.name}] 检查完成：{artifact}")
        elif kind == "result":
            item, script_name = payload
            self.run_view.add_result(item, script_name)
        elif kind == "run_done":
            results, error = payload
            self._running = False
            self._set_busy()
            if error is not None:
                self.status_var.set("任务失败")
                self.log(logging.ERROR, f"任务失败：{error}")
                messagebox.showerror("任务失败", str(error))
            else:
                ok = sum(1 for item in results if item.ok)
                self.status_var.set(f"完成：{ok}/{len(results)} 成功")
                self.log(
                    logging.INFO if ok == len(results) else logging.WARNING,
                    f"任务结束：{ok}/{len(results)} 成功",
                )
            self.refresh_balance()

    def _set_busy(self) -> None:
        busy = self._running or self._discovering or self._inspecting
        self.instances_view.set_busy(busy)
        self.run_view.set_running(self._running or self._discovering)
        if not busy:
            self.run_view.start_btn.configure(
                state="normal" if self.instances_view.selected_instances() else "disabled"
            )

    def _set_balance_label(self, text: str) -> None:
        self.header_balance.configure(text=text)
        self.balance_var.set(text.replace("邮箱余额：", "余额 "))

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def refresh_instances(self) -> None:
        if self._running or self._discovering or self._inspecting:
            return
        self._discovering = True
        self.stop = StopToken()
        self._set_busy()
        self.status_var.set("正在扫描 VMOS 主机……")
        hosts = list(self.settings.vmos.hosts)
        scan = bool(self.settings.vmos.scan)
        use_adb = bool(self.settings.vmos.use_adb)
        stop = self.stop

        def progress(done: int, total: int) -> None:
            self.events.put(("progress", done, total))

        def work() -> None:
            try:
                from muse_auto.vmos.discovery import discover_instances

                result = discover_instances(
                    hosts,
                    port=self.settings.vmos.port,
                    scan=scan,
                    use_adb=use_adb,
                    probe_timeout=self.settings.vmos.probe_timeout,
                    list_timeout=self.settings.vmos.list_timeout,
                    scan_workers=self.settings.vmos.scan_workers,
                    host_workers=self.settings.vmos.max_host_workers,
                    stop=stop,
                    progress=progress if scan else None,
                )
                self.events.put(("discovered", result, None))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("discovered", None, exc))

        threading.Thread(target=work, daemon=True, name="discover").start()

    # ------------------------------------------------------------------
    # Inspect
    # ------------------------------------------------------------------

    def inspect_selected(self) -> None:
        if self._running or self._discovering or self._inspecting:
            return
        selected = self.instances_view.selected_instances()
        if not selected:
            messagebox.showinfo("检查选中", "请先在“实例”页选择实例。")
            return
        instance = selected[0]
        self._inspecting = True
        self._set_busy()
        self.status_var.set(f"正在检查 {instance.name} ……")
        settings = self.settings

        def work() -> None:
            try:
                from muse_auto.ui.parser import parse_dump
                from muse_auto.vmos.device import DeviceApi

                device = DeviceApi(instance, timeout=settings.app.dump_timeout)
                top = device.top_activity()
                width, height = device.display_info()
                installed = device.is_installed(settings.app.package)
                version = device.app_version(settings.app.package) if installed else ""
                xml = device.dump(timeout=settings.app.dump_timeout)
                tree = parse_dump(xml)
                match = MusePages.detect(tree, top.get("package_name", ""))
                store = ArtifactStore(settings.artifact_dir, f"inspect_{instance.name}")
                store.save_text("ui.xml", xml)
                shot = ""
                try:
                    shot = str(device.screenshot(store.path("screen.png")))
                except MuseError as exc:
                    self.events.put(("log", logging.WARNING, f"截图失败：{exc}"))
                text = (
                    f"实例：{instance.label}\n"
                    f"前台：{top.get('package_name')}/{top.get('class_name')}\n"
                    f"屏幕：{width}x{height}\n"
                    f"App ：{settings.app.package} installed={installed} version={version or '-'}\n"
                    f"页面：{MusePages.describe(match)}\n"
                    f"控件：{len(tree.nodes)} 个\n"
                    f"摘要：{tree.summary(limit=500)}\n"
                    f"产物：{store.directory}\n"
                    f"截图：{shot or '-'}\n"
                )
                self.events.put(("inspected", instance, text, str(store.directory), None))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("inspected", instance, "", "", exc))

        threading.Thread(target=work, daemon=True, name="inspect").start()

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def start_run(self) -> None:
        if self._running or self._discovering or self._inspecting:
            return
        if not self.scripts_view.commit():
            return
        selected = self.instances_view.selected_instances()
        if not selected:
            messagebox.showinfo("开始运行", "请先在“实例”页选择实例。")
            return
        try:
            concurrency, limit, stop_on_error, rounds, interval = self.run_view.params()
        except ValueError as exc:
            messagebox.showerror("运行参数", str(exc))
            return
        if limit:
            selected = selected[:limit]

        groups: dict[str, list] = {}
        for instance in selected:
            sid = self.store.assignment(instance.key, self.current_script_id)
            if sid not in self.script_names():
                sid = self.current_script_id
            groups.setdefault(sid, []).append(instance)

        billable = sum(
            len(group) for sid, group in groups.items() if self._script_billable(sid)
        )
        if billable:
            balance = f"${self._balance:.2f}" if self._balance is not None else "未知"
            if not messagebox.askyesno(
                "确认运行",
                f"将对 {len(selected)} 个实例运行脚本，共 {rounds} 轮。\n\n"
                f"每轮中 {billable} 个实例会购买 Meta Ai 邮箱，"
                f"预计共 {billable * rounds} 个。\n"
                f"当前邮箱余额：{balance}\n\n继续？",
            ):
                return

        base_settings = replace(
            self.settings,
            run=replace(
                self.settings.run,
                concurrency=concurrency,
                stop_on_error=stop_on_error,
            ),
        )
        run_stop = StopToken()
        self.run_stop = run_stop
        self._running = True
        self.run_view.clear_results()
        self._set_busy()
        self.status_var.set("正在启动任务……")
        self.log(
            logging.INFO,
            f"开始运行：{len(selected)} 个实例，{len(groups)} 个脚本组，"
            f"并发 {concurrency}，共 {rounds} 轮，轮间隔 {interval:g} 秒",
        )
        group_items = list(groups.items())
        self._worker = threading.Thread(
            target=self._run_worker,
            args=(base_settings, group_items, run_stop, rounds, interval),
            daemon=True,
            name="batch",
        )
        self._worker.start()

    def _run_worker(
        self,
        base_settings: Settings,
        groups: list[tuple[str, list]],
        run_stop: StopToken,
        rounds: int,
        interval: float,
    ) -> None:
        all_results: list[TaskResult] = []
        try:
            for round_no in range(1, max(1, rounds) + 1):
                if run_stop.stopped:
                    break
                if round_no > 1:
                    self.events.put(
                        (
                            "log",
                            logging.INFO,
                            f"第 {round_no}/{rounds} 轮将在 {interval:g} 秒后开始……",
                        )
                    )
                    run_stop.sleep(interval)
                self.events.put(("log", logging.INFO, f"===== 第 {round_no}/{rounds} 轮开始 ====="))

                for script_id, instances in groups:
                    if run_stop.stopped:
                        break
                    spec = self.script(script_id)
                    params = self.script_params(script_id)
                    prepared: PreparedScript = spec.prepare(base_settings, params, run_stop)
                    flow = prepared.flow
                    self.events.put(
                        (
                            "log",
                            logging.INFO,
                            f"第 {round_no} 轮 · 脚本组 {spec.name}：{len(instances)} 个实例",
                        )
                    )

                    def task(instance, stop, ctx, _flow=flow):
                        return _flow.run(ctx)

                    def on_result(
                        item: TaskResult,
                        _name=spec.name,
                        _round=round_no,
                    ) -> None:
                        item.round = _round
                        self.events.put(("result", item, _name))

                    runner = BatchRunner(prepared.settings, stop=run_stop, on_result=on_result)
                    all_results.extend(runner.run(instances, task))
            self.events.put(("run_done", all_results, None))
        except Stopped:
            self.events.put(("run_done", all_results, None))
        except Exception as exc:  # noqa: BLE001
            self.events.put(("run_done", all_results, exc))

    def stop_run(self) -> None:
        if self._running and self.run_stop is not None:
            self.run_stop.stop()
            self.status_var.set("正在停止：当前步骤结束后退出……")
            self.log(logging.WARNING, "收到停止请求，等待当前步骤结束。")
        elif self._discovering:
            self.stop.stop()
            self.status_var.set("正在停止扫描……")

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def refresh_balance(self) -> None:
        params = self.script_params(self.current_script_id)
        source = str(params.get("mail_source") or "onlineDispoMail")
        if source in ("Outlook邮箱", "outlook"):
            path = params.get("outlook_mail_path") or "outlookMail.txt"
            target = Path(str(path))
            if not target.is_absolute():
                target = self.settings.project_root / target
            count = 0
            try:
                if target.exists():
                    count = len(
                        [
                            line
                            for line in target.read_text(encoding="utf-8").splitlines()
                            if line.strip() and not line.strip().startswith("#")
                        ]
                    )
                self._set_balance_label(f"Outlook 邮箱：{count} 个")
            except Exception as exc:  # noqa: BLE001
                self._set_balance_label(f"Outlook 邮箱读取失败：{exc}")
            return
        if source not in ("onlineDispoMail", "online"):
            path = params.get("register_email_path") or "registerEmail.txt.txt"
            target = Path(str(path))
            if not target.is_absolute():
                target = self.settings.project_root / target
            count = 0
            try:
                if target.exists():
                    count = len(
                        [
                            line
                            for line in target.read_text(encoding="utf-8").splitlines()
                            if line.strip() and not line.strip().startswith("#")
                        ]
                    )
                self._set_balance_label(f"自选邮箱：{count} 个")
            except Exception as exc:  # noqa: BLE001
                self._set_balance_label(f"自选邮箱读取失败：{exc}")
            return

        base = str(params.get("mail_base_url") or self.settings.mail.base_url)
        key = str(params.get("mail_api_key") or self.settings.mail.api_key)
        if not key:
            self._set_balance_label("邮箱余额：未配置")
            return

        def work() -> None:
            try:
                from muse_auto.services.mail import MailClient

                value = MailClient(base_url=base, api_key=key).balance()
                self.events.put(("balance", value, None))
            except Exception as exc:  # noqa: BLE001
                self.events.put(("balance", None, exc))

        threading.Thread(target=work, daemon=True, name="balance").start()

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def open_artifacts(self) -> None:
        self.open_path(str(self.settings.artifact_dir))

    def open_config(self) -> None:
        self.open_path(str(self.settings.config_path))

    def open_path(self, path: str) -> None:
        target = Path(path)
        if not target.exists():
            messagebox.showinfo("打开", f"路径不存在：\n{target}")
            return
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
        except OSError as exc:
            messagebox.showerror("打开失败", str(exc))

    def show_about(self) -> None:
        messagebox.showinfo(
            "关于 Muse Auto",
            f"Muse Auto {__version__}\n\n"
            "VMOS Edge 实例 / 脚本 / 参数分离控制台\n"
            f"实例：VMOS Edge\n"
            f"脚本：{len(self._scripts)} 个（MuseAI 注册 / 冒烟）\n"
            f"邮箱：Meta Ai serviceId=302，Gmail_1 emailTypeId=26",
        )

    # ------------------------------------------------------------------
    # Close
    # ------------------------------------------------------------------

    def _on_close(self) -> None:
        if self._running or self._discovering or self._inspecting:
            if not messagebox.askyesno("退出", "任务仍在运行。停止并退出？"):
                return
            if self.run_stop is not None:
                self.run_stop.stop()
            self.stop.stop()
            self._closing = True
            self.status_var.set("正在停止并退出……")
            self._wait_for_close(time.monotonic())
            return
        self._destroy()

    def _wait_for_close(self, started: float) -> None:
        alive = self._worker is not None and self._worker.is_alive()
        if alive and time.monotonic() - started < 10.0:
            self.root.after(200, lambda: self._wait_for_close(started))
            return
        self._destroy()

    def _destroy(self) -> None:
        if self._log_handler is not None:
            logging.getLogger("muse_auto").removeHandler(self._log_handler)
            self._log_handler = None
        try:
            self.root.destroy()
        except tk.TclError:
            pass


def run_gui(settings: Settings, *, auto_discover: bool = True) -> int:
    root = tk.Tk()
    MuseAutoApp(root, settings, auto_discover=auto_discover)
    root.mainloop()
    return 0
