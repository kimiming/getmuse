"""Scripts module: registry list + per-script parameter form.

MuseAI is just one entry in ``muse_auto.scripts.registry``. A future app script
adds a ``ScriptSpec`` with fields and a flow factory; this view renders it
without hard-coding the app's parameters.
"""

from __future__ import annotations

import datetime as dt
import threading
import tkinter as tk
from tkinter import messagebox, ttk

from muse_auto.gui.theme import MUTED, PANEL
from muse_auto.gui.widgets import ScrollableFrame, labeled_row
from muse_auto.scripts.base import ScriptField, ScriptSpec


class ScriptsView(ttk.Frame):
    def __init__(self, app, master: tk.Misc) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.specs: list[ScriptSpec] = app.scripts()
        self.current: ScriptSpec = self.specs[0]
        self.vars: dict[str, tk.Variable] = {}
        self.step_vars: dict[str, dict[int, tk.BooleanVar]] = {}
        self.entries: dict[str, ttk.Widget] = {}
        self.secret_entries: list[ttk.Entry] = []
        self._balance_loading = False
        self._build()

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def _build(self) -> None:
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body, padding=(0, 0, 8, 0), width=250)
        body.add(left, weight=0)
        ttk.Label(left, text="可用脚本", font=(self.app.ui_font, 11, "bold")).pack(
            anchor="w", pady=(0, 6)
        )
        self.script_list = ttk.Treeview(
            left, columns=("name", "app"), show="headings", selectmode="browse", height=18
        )
        self.script_list.heading("name", text="脚本")
        self.script_list.heading("app", text="App")
        self.script_list.column("name", width=150, anchor="w")
        self.script_list.column("app", width=110, anchor="w")
        for spec in self.specs:
            self.script_list.insert("", "end", iid=spec.id, values=(spec.name, spec.app_name))
        self.script_list.pack(fill="both", expand=True)
        self.script_list.bind("<<TreeviewSelect>>", lambda _event: self._on_select())
        ttk.Label(
            left,
            text="新增脚本：muse_auto/scripts/\n添加 ScriptSpec 后自动出现",
            foreground=MUTED,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        right = ttk.Frame(body, padding=(8, 0, 0, 0))
        body.add(right, weight=1)
        header = ttk.Frame(right)
        header.pack(fill="x", pady=(0, 6))
        self.title_label = ttk.Label(header, text="", font=(self.app.ui_font, 14, "bold"))
        self.title_label.pack(anchor="w")
        self.desc_label = ttk.Label(
            header, text="", foreground=MUTED, wraplength=760, justify="left"
        )
        self.desc_label.pack(anchor="w", pady=(4, 0))
        self.meta_label = ttk.Label(header, text="", foreground=MUTED)
        self.meta_label.pack(anchor="w", pady=(4, 0))

        self.form_scroll = ScrollableFrame(right)
        self.form_scroll.pack(fill="both", expand=True, pady=(6, 6))
        self.form = self.form_scroll.inner

        buttons = ttk.Frame(right)
        buttons.pack(fill="x", pady=(0, 4))
        ttk.Button(buttons, text="保存参数", command=self.save).pack(side="left")
        ttk.Button(buttons, text="恢复默认", command=self.reset_defaults).pack(
            side="left", padx=(6, 0)
        )
        ttk.Button(buttons, text="分配到选中实例", command=self.assign_selected).pack(
            side="left", padx=(12, 0)
        )
        self.show_secret_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            buttons, text="显示密钥", variable=self.show_secret_var, command=self._toggle_secret
        ).pack(side="right")

        self.script_list.selection_set(self.current.id)
        self._build_form(self.current)

    # ------------------------------------------------------------------
    # Script selection / form
    # ------------------------------------------------------------------

    def _on_select(self) -> None:
        selected = self.script_list.selection()
        if not selected:
            return
        script_id = selected[0]
        if script_id == self.current.id:
            return
        self._save_current(silent=True)
        self.current = self.app.script(script_id)
        self._build_form(self.current)
        self.app.set_current_script(script_id)

    def _build_form(self, spec: ScriptSpec) -> None:
        for child in self.form.winfo_children():
            child.destroy()
        self.vars.clear()
        self.step_vars.clear()
        self.entries.clear()
        self.secret_entries.clear()
        self.balance_label = None
        self.balance_btn = None
        self.current = spec
        self.title_label.configure(text=spec.name)
        self.desc_label.configure(text=spec.description)
        self.meta_label.configure(
            text=(
                f"App：{spec.app_package or '-'}   ·   版本 {spec.version}   ·   "
                f"{'计费脚本' if spec.billable else '不计费'}"
                + (f"   ·   {spec.cost_hint}" if spec.cost_hint else "")
            )
        )

        defaults = self.app.store.params(spec.id, spec.defaults(self.app.settings))
        if not spec.fields:
            ttk.Label(
                self.form,
                text="此脚本没有可配置参数。",
                foreground=MUTED,
            ).pack(anchor="w", padx=6, pady=10)
            return

        groups: dict[str, list[ScriptField]] = {}
        for field in sorted(
            spec.fields,
            key=lambda item: 0 if item.group == "执行步骤" else 1,
        ):
            groups.setdefault(field.group, []).append(field)

        for group, fields in groups.items():
            card = ttk.LabelFrame(self.form, text=group, padding=(10, 6))
            card.pack(fill="x", padx=2, pady=(0, 8))
            for field in fields:
                self._build_field(card, field, defaults.get(field.key, field.default))
            if group == "随机名字":
                ttk.Button(
                    card,
                    text="随机生成 20 个 First/Last name",
                    command=self.generate_names,
                ).pack(anchor="w", pady=(6, 0))

        if any(field.group == "邮箱 API" for field in spec.fields):
            card = ttk.LabelFrame(self.form, text="邮箱 API 状态", padding=(10, 8))
            card.pack(fill="x", padx=2, pady=(0, 8))
            row = ttk.Frame(card)
            row.pack(fill="x")
            self.balance_label = ttk.Label(row, text="余额：--")
            self.balance_label.pack(side="left")
            self.balance_btn = ttk.Button(row, text="查询余额", command=self.query_balance)
            self.balance_btn.pack(side="left", padx=(10, 0))
            ttk.Label(
                card,
                text="查询使用上方“邮箱 API 地址 / API Key”，不会保存到配置文件。",
                foreground=MUTED,
            ).pack(anchor="w", pady=(6, 0))

    def _build_field(self, parent: ttk.Frame, field: ScriptField, value) -> None:
        if field.kind == "steps":
            self._build_steps_field(parent, field, value)
            return
        if field.kind == "bool":
            variable: tk.Variable = tk.BooleanVar(value=bool(value))
        else:
            variable = tk.StringVar(value="" if value is None else str(value))
        self.vars[field.key] = variable
        widget = labeled_row(
            parent,
            field.label,
            variable,
            kind=field.kind,
            choices=field.choices,
            width=field.width,
            help_text=field.help,
            secret=field.secret,
        )
        self.entries[field.key] = widget
        if field.secret and isinstance(widget, ttk.Entry):
            self.secret_entries.append(widget)

    def _build_steps_field(self, parent: ttk.Frame, field: ScriptField, value) -> None:
        selected = {
            part.strip()
            for part in str(value or field.default).split(",")
            if part.strip().isdigit()
        }
        variable = tk.StringVar(value=",".join(sorted(selected, key=int)))
        self.vars[field.key] = variable
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=field.label, width=22, anchor="w").pack(side="left")
        checks: dict[int, tk.BooleanVar] = {}
        labels = {
            1: "1 注册",
            2: "2 换邮箱",
            3: "3 邀请码",
            4: "4 本号邀请码",
            5: "5 保存XLS",
            6: "6 清缓存/存储",
        }
        for number in (1, 2, 3, 4, 5, 6):
            check_var = tk.BooleanVar(value=str(number) in selected)
            checks[number] = check_var

            def update(
                _key: str = field.key,
                _checks: dict[int, tk.BooleanVar] = checks,
                _target: tk.StringVar = variable,
            ) -> None:
                _target.set(",".join(str(n) for n in sorted(_checks) if _checks[n].get()))

            ttk.Checkbutton(
                row,
                text=labels[number],
                variable=check_var,
                command=update,
            ).pack(side="left", padx=(0, 10))
        self.step_vars[field.key] = checks
        if field.help:
            ttk.Label(row, text=field.help, foreground="#64748b").pack(
                side="left", fill="x", expand=True
            )

        def set_all(value: bool) -> None:
            for check in checks.values():
                check.set(value)
            variable.set(",".join(str(n) for n in sorted(checks) if checks[n].get()))

        ttk.Button(row, text="全选", width=5, command=lambda: set_all(True)).pack(
            side="left", padx=(4, 0)
        )
        ttk.Button(row, text="清空", width=5, command=lambda: set_all(False)).pack(
            side="left", padx=(4, 0)
        )

    def _sync_step_checks(self, key: str, value: str) -> None:
        checks = self.step_vars.get(key)
        if not checks:
            return
        selected = {part.strip() for part in str(value or "").split(",")}
        for number, check in checks.items():
            check.set(str(number) in selected)

    def generate_names(self) -> None:
        from muse_auto.services.identity import names_text

        first, last = names_text(20)
        if "first_names" in self.vars:
            self.vars["first_names"].set(first)
        if "last_names" in self.vars:
            self.vars["last_names"].set(last)
        self.app.log("INFO", "已随机生成 20 个 First name 和 20 个 Last name")

    def _toggle_secret(self) -> None:
        show = "" if self.show_secret_var.get() else "*"
        for entry in self.secret_entries:
            entry.configure(show=show)

    # ------------------------------------------------------------------
    # Values / save
    # ------------------------------------------------------------------

    def values(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for field in self.current.fields:
            variable = self.vars.get(field.key)
            if variable is None:
                continue
            if field.kind == "bool":
                result[field.key] = bool(variable.get())
            elif field.kind == "int":
                raw = str(variable.get()).strip()
                try:
                    result[field.key] = int(raw or field.default or 0)
                except ValueError as exc:
                    raise ValueError(f"{field.label} 必须是整数") from exc
            else:
                result[field.key] = str(variable.get()).strip()
        return result

    def _validate(self) -> dict[str, object]:
        values = self.values()
        for field in self.current.fields:
            if field.required and not str(values.get(field.key, "")).strip():
                raise ValueError(f"{field.label} 不能为空")
            if field.kind == "steps" and not str(values.get(field.key, "")).strip():
                raise ValueError("至少选择一个执行步骤")
            if field.kind == "date" and values.get(field.key):
                try:
                    birth = dt.date.fromisoformat(str(values[field.key]))
                except ValueError as exc:
                    raise ValueError(f"{field.label} 格式应为 YYYY-MM-DD") from exc
                today = dt.date.today()
                age = today.year - birth.year - (
                    (today.month, today.day) < (birth.month, birth.day)
                )
                if age < 18:
                    raise ValueError(f"{field.label} 需要 >= 18 岁")
        return values

    def save(self) -> bool:
        return self._save_current(silent=False)

    def _save_current(self, *, silent: bool) -> bool:
        try:
            values = self._validate()
        except ValueError as exc:
            if not silent:
                messagebox.showerror("参数错误", str(exc))
            return False
        self.app.store.set_params(self.current.id, values)
        if not silent:
            self.app.log("INFO", f"已保存脚本参数：{self.current.name}")
            self.app.update_status()
        return True

    def reset_defaults(self) -> None:
        defaults = self.current.defaults(self.app.settings)
        for field in self.current.fields:
            variable = self.vars.get(field.key)
            if variable is None:
                continue
            value = defaults.get(field.key, field.default)
            if field.kind == "bool":
                variable.set(bool(value))
            else:
                variable.set("" if value is None else str(value))
            if field.kind == "steps":
                self._sync_step_checks(field.key, str(value or ""))

    def commit(self) -> bool:
        """Called by the runner before start; saves the active form."""
        return self._save_current(silent=False)

    def assign_selected(self) -> None:
        if not self.commit():
            return
        selected = self.app.instances_view.selected_keys()
        if not selected:
            messagebox.showinfo("分配脚本", "请先在“实例”页选择实例。")
            return
        self.app.assign_script(selected, self.current.id)
        self.app.instances_view.refresh_display()
        self.app.log("INFO", f"已把 {len(selected)} 个实例分配给：{self.current.name}")

    # ------------------------------------------------------------------
    # Balance
    # ------------------------------------------------------------------

    def query_balance(self) -> None:
        if self._balance_loading:
            return
        values = self.values()
        base = str(values.get("mail_base_url") or "").strip()
        key = str(values.get("mail_api_key") or "").strip()
        if not base or not key:
            messagebox.showinfo("查询余额", "请先填写邮箱 API 地址和 API Key。")
            return
        self._balance_loading = True
        if self.balance_btn is not None:
            self.balance_btn.configure(state="disabled")
        if self.balance_label is not None:
            self.balance_label.configure(text="余额：查询中……", foreground=MUTED)

        def work() -> None:
            try:
                from muse_auto.services.mail import MailClient

                value = MailClient(base_url=base, api_key=key).balance()
                self.app.events.put(("script_balance", value, None))
            except Exception as exc:  # noqa: BLE001
                self.app.events.put(("script_balance", None, exc))

        threading.Thread(target=work, daemon=True, name="script-balance").start()

    def set_balance(self, value: float | None, error: Exception | None) -> None:
        self._balance_loading = False
        if self.balance_btn is not None and self.balance_btn.winfo_exists():
            self.balance_btn.configure(state="normal")
        if self.balance_label is None or not self.balance_label.winfo_exists():
            return
        if error is not None:
            self.balance_label.configure(text=f"余额：失败（{error}）", foreground="#b91c1c")
            return
        self.balance_label.configure(
            text=f"余额：${float(value):.2f}",
            foreground="#166534",
        )

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for child in self.winfo_children():
            self._set_state_recursive(child, state)

    def _set_state_recursive(self, widget: tk.Misc, state: str) -> None:
        if isinstance(widget, (ttk.Button, ttk.Entry, ttk.Combobox, ttk.Checkbutton)):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass
        for child in widget.winfo_children():
            self._set_state_recursive(child, state)
