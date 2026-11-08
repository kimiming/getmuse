"""Page inspection module."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from muse_auto.gui.theme import MUTED, TEXT


class InspectView(ttk.Frame):
    def __init__(self, app, master: tk.Misc) -> None:
        super().__init__(master, padding=10)
        self.app = app
        self._build()

    def _build(self) -> None:
        tools = ttk.Frame(self)
        tools.pack(fill="x", pady=(0, 6))
        ttk.Button(tools, text="检查选中实例", command=self.app.inspect_selected).pack(side="left")
        ttk.Button(tools, text="打开产物目录", command=self.app.open_artifacts).pack(
            side="left", padx=(6, 0)
        )
        ttk.Label(
            tools,
            text="前台 Activity / 屏幕 / 安装状态 / 页面识别 / 控件树摘要",
            foreground=MUTED,
        ).pack(side="right")

        wrap = ttk.Frame(self)
        wrap.pack(fill="both", expand=True)
        self.text = tk.Text(
            wrap,
            wrap="word",
            bg="white",
            fg=TEXT,
            relief="flat",
            padx=12,
            pady=10,
            font=(self.app.mono_font, 9),
            state="disabled",
        )
        scroll = ttk.Scrollbar(wrap, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def set_text(self, value: str) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", value)
        self.text.configure(state="disabled")
