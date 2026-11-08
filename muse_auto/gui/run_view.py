"""Execution module: run parameters + live results + log."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import messagebox, ttk

from muse_auto.gui.theme import LOG_BG, LOG_FG, MUTED, PANEL
from muse_auto.runner.batch import TaskResult


class RunView(ttk.Frame):
    def __init__(self, app, master: tk.Misc) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self.result_paths: dict[str, str] = {}
        self._build()

    def _build(self) -> None:
        params = ttk.LabelFrame(self, text="运行参数", padding=(10, 8))
        params.pack(fill="x", pady=(0, 6))

        row1 = ttk.Frame(params)
        row1.pack(fill="x")
        ttk.Label(row1, text="并发").pack(side="left")
        self.concurrency_var = tk.StringVar(value=str(self.app.settings.run.concurrency))
        ttk.Spinbox(row1, from_=1, to=32, width=4, textvariable=self.concurrency_var).pack(
            side="left", padx=(4, 14)
        )
        ttk.Label(row1, text="最多实例").pack(side="left")
        self.limit_var = tk.StringVar(value="1")
        ttk.Spinbox(row1, from_=0, to=9999, width=5, textvariable=self.limit_var).pack(
            side="left", padx=(4, 2)
        )
        ttk.Label(row1, text="0=全部", foreground=MUTED).pack(side="left", padx=(0, 14))
        self.stop_on_error_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row1, text="出错停止", variable=self.stop_on_error_var).pack(side="left")

        row2 = ttk.Frame(params)
        row2.pack(fill="x", pady=(6, 0))
        ttk.Label(row2, text="自动轮数").pack(side="left")
        self.rounds_var = tk.StringVar(value=str(self.app.settings.run.rounds))
        ttk.Spinbox(row2, from_=1, to=100, width=4, textvariable=self.rounds_var).pack(
            side="left", padx=(4, 16)
        )
        ttk.Label(row2, text="每轮等待(秒)").pack(side="left")
        self.interval_var = tk.StringVar(value=str(self.app.settings.run.round_interval))
        ttk.Spinbox(
            row2, from_=0, to=3600, width=5, textvariable=self.interval_var
        ).pack(side="left", padx=(4, 0))
        ttk.Label(
            row2,
            text="默认 2 轮，每轮结束等待 10 秒",
            foreground=MUTED,
        ).pack(side="left", padx=(16, 0))

        self.start_btn = ttk.Button(
            row1, text="开始运行", style="Accent.TButton", command=self.app.start_run
        )
        self.start_btn.pack(side="right", padx=(6, 0))
        self.stop_btn = ttk.Button(
            row1, text="停止", style="Danger.TButton", command=self.app.stop_run, state="disabled"
        )
        self.stop_btn.pack(side="right")

        self.summary_var = tk.StringVar(value="尚未选择实例")
        ttk.Label(params, textvariable=self.summary_var, foreground=MUTED).pack(
            anchor="w", pady=(6, 0)
        )
        ttk.Label(
            params,
            text="脚本由“实例”页的脚本列决定；不同脚本会按组依次执行。",
            foreground=MUTED,
        ).pack(anchor="w", pady=(2, 0))

        paned = ttk.Panedwindow(self, orient="vertical")
        paned.pack(fill="both", expand=True)

        results = ttk.LabelFrame(paned, text="任务结果", padding=(6, 4))
        paned.add(results, weight=1)
        columns = ("round", "instance", "script", "status", "email", "note")
        self.result_tree = ttk.Treeview(results, columns=columns, show="headings", height=7)
        headings = {
            "round": ("轮", 42),
            "instance": ("实例", 160),
            "script": ("脚本", 150),
            "status": ("状态", 100),
            "email": ("邮箱", 220),
            "note": ("说明", 380),
        }
        for key, (title, width) in headings.items():
            self.result_tree.heading(key, text=title)
            self.result_tree.column(key, width=width, anchor="w")
        self.result_tree.tag_configure("ok", background="#e9f8ef", foreground="#166534")
        self.result_tree.tag_configure("err", background="#fef2f2", foreground="#991b1b")
        scroll = ttk.Scrollbar(results, orient="vertical", command=self.result_tree.yview)
        self.result_tree.configure(yscrollcommand=scroll.set)
        self.result_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.result_tree.bind("<Double-1>", lambda _event: self.open_selected_result())

        log_frame = ttk.LabelFrame(paned, text="运行日志", padding=(6, 4))
        paned.add(log_frame, weight=2)
        tools = ttk.Frame(log_frame)
        tools.pack(fill="x", pady=(0, 4))
        ttk.Button(tools, text="清空", command=self.clear_log).pack(side="left")
        ttk.Button(tools, text="复制", command=self.copy_log).pack(side="left", padx=(6, 0))
        self.autoscroll_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(tools, text="自动滚动", variable=self.autoscroll_var).pack(
            side="left", padx=(10, 0)
        )

        text_wrap = ttk.Frame(log_frame)
        text_wrap.pack(fill="both", expand=True)
        self.log_text = tk.Text(
            text_wrap,
            wrap="word",
            bg=LOG_BG,
            fg=LOG_FG,
            insertbackground=LOG_FG,
            relief="flat",
            padx=10,
            pady=8,
            font=(self.app.mono_font, 9),
            state="disabled",
        )
        scrollbar = ttk.Scrollbar(text_wrap, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.log_text.tag_configure("INFO", foreground=LOG_FG)
        self.log_text.tag_configure("DEBUG", foreground="#64748b")
        self.log_text.tag_configure("WARNING", foreground="#fbbf24")
        self.log_text.tag_configure("ERROR", foreground="#f87171")
        self.log_text.tag_configure("SUCCESS", foreground="#4ade80")

    # ------------------------------------------------------------------
    # Parameters
    # ------------------------------------------------------------------

    def params(self) -> tuple[int, int, bool, int, float]:
        try:
            concurrency = int(self.concurrency_var.get())
            limit = int(self.limit_var.get())
            rounds = int(self.rounds_var.get())
            interval = float(self.interval_var.get())
        except ValueError as exc:
            raise ValueError("并发、最多实例、轮数、间隔必须是数字") from exc
        if concurrency < 1 or limit < 0:
            raise ValueError("并发必须 >=1，“最多实例”必须 >=0")
        if rounds < 1:
            raise ValueError("轮数必须 >=1")
        if interval < 0:
            raise ValueError("间隔不能小于 0")
        return concurrency, limit, bool(self.stop_on_error_var.get()), rounds, interval

    def set_running(self, running: bool) -> None:
        self.start_btn.configure(state="disabled" if running else "normal")
        self.stop_btn.configure(state="normal" if running else "disabled")

    def set_summary(self, text: str) -> None:
        self.summary_var.set(text)

    # ------------------------------------------------------------------
    # Results / log
    # ------------------------------------------------------------------

    def clear_results(self) -> None:
        self.result_tree.delete(*self.result_tree.get_children())
        self.result_paths.clear()

    def add_result(self, item: TaskResult, script_name: str) -> None:
        iid = f"r{len(self.result_paths) + 1}-{item.instance.key}"
        tag = "ok" if item.ok else "err"
        self.result_tree.insert(
            "",
            "end",
            iid=iid,
            values=(
                item.round or "-",
                item.instance.name,
                script_name,
                item.status,
                item.email or "-",
                item.message[:200],
            ),
            tags=(tag,),
        )
        self.result_paths[iid] = str(item.artifacts or "")

    def open_selected_result(self) -> None:
        selected = self.result_tree.selection()
        if not selected:
            return
        path = self.result_paths.get(selected[0], "")
        if path:
            self.app.open_path(path)
        else:
            messagebox.showinfo("打开产物", "该结果没有产物目录。")

    def append_log(self, level: int, text: str) -> None:
        tag = "INFO"
        if level >= logging.ERROR:
            tag = "ERROR"
        elif level >= logging.WARNING:
            tag = "WARNING"
        elif level == 25:
            tag = "SUCCESS"
        elif level <= logging.DEBUG:
            tag = "DEBUG"
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n", tag)
        lines = int(self.log_text.index("end-1c").split(".")[0])
        if lines > 6000:
            self.log_text.delete("1.0", "1000.0")
        if self.autoscroll_var.get():
            self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def copy_log(self) -> None:
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(self.log_text.get("1.0", "end-1c"))
