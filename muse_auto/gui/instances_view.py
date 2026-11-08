"""Instances module: scan, search/filter, select, and bind a script per instance."""

from __future__ import annotations

from tkinter import messagebox, ttk
import tkinter as tk

from muse_auto.gui.theme import MUTED, PANEL
from muse_auto.vmos.models import VmosInstance

STATE_FILTERS = ("全部状态", "running", "offline", "starting", "failed", "unknown")
ALL_IPS = "全部 IP"


class InstancesView(ttk.Frame):
    def __init__(self, app, master: tk.Misc) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.instances: list[VmosInstance] = []
        self.visible: list[VmosInstance] = []
        self.by_iid: dict[str, VmosInstance] = {}
        self._script_name_by_id = app.script_names()
        self._script_id_by_name = {name: sid for sid, name in self._script_name_by_id.items()}
        self._build()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        toolbar = ttk.Frame(self)
        toolbar.pack(fill="x", pady=(0, 6))

        self.refresh_btn = ttk.Button(toolbar, text="刷新实例", command=self.app.refresh_instances)
        self.refresh_btn.pack(side="left", padx=(0, 6))
        ttk.Button(toolbar, text="全选运行中", command=self.select_running).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(toolbar, text="全选当前筛选", command=self.select_visible).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(toolbar, text="清空选择", command=self.clear_selection).pack(
            side="left", padx=(0, 12)
        )
        ttk.Button(toolbar, text="检查选中", command=self.app.inspect_selected).pack(
            side="left", padx=(0, 6)
        )

        ttk.Label(toolbar, text="分配脚本").pack(side="left", padx=(12, 4))
        self.script_combo = ttk.Combobox(
            toolbar,
            values=list(self._script_id_by_name),
            state="readonly",
            width=20,
        )
        self.script_combo.pack(side="left", padx=(0, 4))
        self.script_combo.set(self._script_name_by_id.get(self.app.current_script_id, ""))
        ttk.Button(toolbar, text="应用到选中", command=self.assign_selected).pack(side="left")
        ttk.Label(
            toolbar,
            text="双击实例打开页面检查",
            foreground=MUTED,
        ).pack(side="right")

        filters = ttk.Frame(self)
        filters.pack(fill="x", pady=(0, 6))
        ttk.Label(filters, text="搜索").pack(side="left")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self.refresh_display())
        ttk.Entry(filters, textvariable=self.search_var, width=28).pack(
            side="left", padx=(4, 12)
        )

        ttk.Label(filters, text="IP").pack(side="left")
        self.ip_var = tk.StringVar(value=ALL_IPS)
        self.ip_combo = ttk.Combobox(
            filters, textvariable=self.ip_var, values=(ALL_IPS,), state="readonly", width=16
        )
        self.ip_combo.pack(side="left", padx=(4, 12))
        self.ip_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_display())

        ttk.Label(filters, text="状态").pack(side="left")
        self.state_var = tk.StringVar(value=STATE_FILTERS[0])
        self.state_combo = ttk.Combobox(
            filters, textvariable=self.state_var, values=STATE_FILTERS, state="readonly", width=10
        )
        self.state_combo.pack(side="left", padx=(4, 12))
        self.state_combo.bind("<<ComboboxSelected>>", lambda _event: self.refresh_display())

        ttk.Button(filters, text="重置筛选", command=self.reset_filters).pack(side="left")
        self.count_label = ttk.Label(filters, text="0 / 0 个", foreground=MUTED)
        self.count_label.pack(side="right")

        tree_frame = ttk.Frame(self)
        tree_frame.pack(fill="both", expand=True)
        columns = ("name", "state", "db_id", "host", "adb", "script")
        self.tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", selectmode="extended"
        )
        headings = {
            "name": ("实例名", 190),
            "state": ("状态", 68),
            "db_id": ("db_id", 175),
            "host": ("IP / 主机", 120),
            "adb": ("ADB", 55),
            "script": ("脚本", 155),
        }
        for key, (title, width) in headings.items():
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=45, anchor="w", stretch=key == "script")
        self.tree.tag_configure("running", background="#e9f8ef", foreground="#166534")
        self.tree.tag_configure("offline", background="#f3f4f6", foreground="#6b7280")
        self.tree.tag_configure("starting", background="#fef3c7", foreground="#92400e")
        self.tree.tag_configure("failed", background="#fee2e2", foreground="#991b1b")

        yscroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._on_select())
        self.tree.bind("<Double-1>", lambda _event: self.app.inspect_selected())

        footer = ttk.Frame(self)
        footer.pack(fill="x", pady=(6, 0))
        self.selection_label = ttk.Label(footer, text="已选 0 个", foreground=MUTED)
        self.selection_label.pack(side="left")
        ttk.Label(
            footer,
            text="脚本列 = 该实例运行哪个脚本；不设置时使用默认脚本。",
            foreground=MUTED,
        ).pack(side="right")

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def set_instances(self, instances: list[VmosInstance]) -> None:
        self.instances = list(instances)
        ips = sorted({item.host.ip for item in self.instances})
        current = self.ip_var.get()
        self.ip_combo.configure(values=(ALL_IPS, *ips))
        if current not in (ALL_IPS, *ips):
            self.ip_var.set(ALL_IPS)
        self.refresh_display()

    def refresh_display(self) -> None:
        selected = set(self.tree.selection())
        search = self.search_var.get().strip().casefold()
        ip = self.ip_var.get()
        state = self.state_var.get()
        self.visible = []
        for instance in self.instances:
            if search and not (
                search in instance.name.casefold()
                or search in instance.db_id.casefold()
                or search in instance.host.ip.casefold()
            ):
                continue
            if ip != ALL_IPS and instance.host.ip != ip:
                continue
            if state != STATE_FILTERS[0] and instance.state != state:
                continue
            self.visible.append(instance)

        self.tree.delete(*self.tree.get_children())
        self.by_iid.clear()
        for instance in self.visible:
            iid = instance.key
            self.by_iid[iid] = instance
            tag = (
                "running"
                if instance.running
                else "offline"
                if instance.state in {"offline", "failed"}
                else instance.state
            )
            script_id = self.app.store.assignment(instance.key, self.app.default_script_id)
            script_name = self._script_name_by_id.get(script_id, script_id)
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    instance.name,
                    instance.state,
                    instance.db_id,
                    instance.host.ip,
                    instance.adb_port or "-",
                    script_name,
                ),
                tags=(tag,),
            )
        keep = [iid for iid in selected if iid in self.by_iid]
        if keep:
            self.tree.selection_set(keep)
        self.count_label.configure(
            text=f"{len(self.visible)} / {len(self.instances)} 个"
        )
        self._on_select()

    def set_script_choices(self, names: dict[str, str]) -> None:
        self._script_name_by_id = dict(names)
        self._script_id_by_name = {name: sid for sid, name in names.items()}
        self.script_combo.configure(values=list(self._script_id_by_name))
        if self.script_combo.get() not in self._script_id_by_name:
            self.script_combo.set(names.get(self.app.current_script_id, ""))

    def set_current_script(self, script_id: str) -> None:
        name = self._script_name_by_id.get(script_id)
        if name:
            self.script_combo.set(name)

    def reset_filters(self) -> None:
        self.search_var.set("")
        self.ip_var.set(ALL_IPS)
        self.state_var.set(STATE_FILTERS[0])
        self.refresh_display()

    # ------------------------------------------------------------------
    # Selection / actions
    # ------------------------------------------------------------------

    def selected_instances(self) -> list[VmosInstance]:
        return [self.by_iid[iid] for iid in self.tree.selection() if iid in self.by_iid]

    def selected_keys(self) -> list[str]:
        return [iid for iid in self.tree.selection() if iid in self.by_iid]

    def select_running(self) -> None:
        iids = [item.key for item in self.visible if item.running]
        self.tree.selection_set(iids)
        self._on_select()

    def select_visible(self) -> None:
        self.tree.selection_set([item.key for item in self.visible])
        self._on_select()

    def clear_selection(self) -> None:
        self.tree.selection_remove(self.tree.selection())
        self._on_select()

    def _on_select(self) -> None:
        count = len(self.tree.selection())
        self.selection_label.configure(text=f"已选 {count} 个")
        self.app.update_status()

    def assign_selected(self) -> None:
        selected = self.selected_keys()
        if not selected:
            messagebox.showinfo("分配脚本", "请先选择实例。")
            return
        name = self.script_combo.get()
        script_id = self._script_id_by_name.get(name)
        if not script_id:
            messagebox.showinfo("分配脚本", "请选择脚本。")
            return
        self.app.assign_script(selected, script_id)
        self.refresh_display()

    def set_busy(self, busy: bool) -> None:
        self.refresh_btn.configure(state="disabled" if busy else "normal")
