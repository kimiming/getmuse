"""Small Tkinter building blocks shared by the GUI views."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from muse_auto.gui.theme import PANEL


class ScrollableFrame(ttk.Frame):
    """A vertically scrollable container that works inside a notebook tab."""

    def __init__(self, master: tk.Misc, *, bg: str = PANEL) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas, padding=(4, 4, 10, 8))
        self._window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Enter>", self._bind_wheel)
        self.canvas.bind("<Leave>", self._unbind_wheel)

    def _on_inner_configure(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self._window, width=event.width)

    def _bind_wheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_wheel)

    def _unbind_wheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")

    def _on_wheel(self, event: tk.Event) -> None:
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


def labeled_row(
    parent: tk.Misc,
    label: str,
    variable: tk.Variable,
    *,
    kind: str = "text",
    choices: tuple[str, ...] = (),
    width: int = 28,
    help_text: str = "",
    secret: bool = False,
) -> ttk.Widget:
    """Create one form row and return the input widget (for focus/validation)."""
    row = ttk.Frame(parent)
    row.pack(fill="x", pady=3)
    ttk.Label(row, text=label, width=22, anchor="w").pack(side="left")
    if kind == "bool":
        widget = ttk.Checkbutton(row, variable=variable)
    elif kind == "choice":
        widget = ttk.Combobox(
            row, textvariable=variable, values=choices, state="readonly", width=max(8, width - 8)
        )
    elif kind == "int":
        widget = ttk.Spinbox(row, from_=1, to=99999, textvariable=variable, width=10)
    else:
        widget = ttk.Entry(row, textvariable=variable, width=width, show="*" if secret else "")
    widget.pack(side="left", padx=(0, 8))
    if help_text:
        ttk.Label(row, text=help_text, foreground="#64748b").pack(side="left", fill="x", expand=True)
    return widget
