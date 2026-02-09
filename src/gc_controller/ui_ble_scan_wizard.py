"""
UI BLE Scan Wizard - Differential Scan for BLE Controller Discovery

Two-step wizard: baseline scan (controller off) then pairing scan
(controller advertising). The diff identifies the controller.
"""

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

import customtkinter

from . import ui_theme as T


class BLEScanWizard:
    """Modal two-step differential scan wizard.

    Step 1: Baseline scan — captures nearby devices while the controller is OFF.
    Step 2: Pairing scan — captures devices while the controller is advertising.
    The diff (new devices in step 2) identifies the controller.

    Args:
        parent: The parent window (CTk or Tk).
        on_scan: Callback to trigger a BLE scan. Accepts a completion callback
                 that receives list[dict] with address/name/rssi keys.
    """

    def __init__(self, parent,
                 on_scan: Callable[[Callable[[list[dict]], None]], None]):
        self._result: Optional[str] = None
        self._on_scan = on_scan
        self._baseline: dict[str, dict] = {}  # address -> device dict
        self._pairing_results: list[dict] = []

        self._dlg = customtkinter.CTkToplevel(parent)
        self._dlg.title("Wireless Controller Setup")
        self._dlg.resizable(False, False)
        self._dlg.transient(parent)
        self._dlg.configure(fg_color=T.GC_PURPLE_DARK)

        self._outer = customtkinter.CTkFrame(
            self._dlg, fg_color=T.GC_PURPLE_DARK)
        self._outer.pack(fill=tk.BOTH, expand=True, padx=20, pady=20)

        # Content area — swapped per step
        self._content = customtkinter.CTkFrame(
            self._outer, fg_color="transparent")
        self._content.pack(fill=tk.BOTH, expand=True)

        # Button bar
        self._btn_bar = customtkinter.CTkFrame(
            self._outer, fg_color="transparent")
        self._btn_bar.pack(fill=tk.X, pady=(16, 0))

        self._show_step1()

        self._dlg.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Center on parent
        self._dlg.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        dw = self._dlg.winfo_width()
        dh = self._dlg.winfo_height()
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        self._dlg.geometry(f"+{x}+{y}")

        self._dlg.after(10, self._dlg.grab_set)

    def _clear_content(self):
        """Remove all widgets from content and button bar."""
        for w in self._content.winfo_children():
            w.destroy()
        for w in self._btn_bar.winfo_children():
            w.destroy()

    # ── Step 1: Baseline Scan ──────────────────────────────────────

    def _show_step1(self):
        self._clear_content()

        customtkinter.CTkLabel(
            self._content, text="Step 1 of 2: Environment Scan",
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        customtkinter.CTkLabel(
            self._content,
            text=(
                "Make sure your controller is OFF or not in pairing mode.\n"
                "This scan captures nearby Bluetooth devices."
            ),
            text_color=T.TEXT_SECONDARY,
            font=(T.FONT_FAMILY, 13),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 12))

        self._progress = customtkinter.CTkProgressBar(
            self._content,
            fg_color=T.SURFACE_DARK,
            progress_color=T.GC_PURPLE_LIGHT,
            width=400,
        )
        self._progress.pack(pady=(0, 8))
        self._progress.set(0)
        self._progress.pack_forget()  # hidden until scan starts

        self._status_label = customtkinter.CTkLabel(
            self._content, text="",
            text_color=T.TEXT_SECONDARY,
            font=(T.FONT_FAMILY, 12),
        )
        self._status_label.pack(anchor=tk.W)

        # Buttons
        self._scan_btn = customtkinter.CTkButton(
            self._btn_bar, text="Scan",
            command=self._do_baseline_scan,
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=36, width=120,
            font=(T.FONT_FAMILY, 14),
        )
        self._scan_btn.pack(side=tk.RIGHT, padx=(8, 0))

        customtkinter.CTkButton(
            self._btn_bar, text="Cancel",
            command=self._on_cancel,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=100,
            font=(T.FONT_FAMILY, 14),
        ).pack(side=tk.RIGHT)

    def _do_baseline_scan(self):
        self._scan_btn.configure(state="disabled")
        self._progress.pack(pady=(0, 8))
        self._progress.configure(mode="indeterminate")
        self._progress.start()
        self._status_label.configure(text="Scanning environment...")

        self._on_scan(self._on_baseline_complete)

    def _on_baseline_complete(self, devices: list[dict]):
        """Called when the baseline scan finishes."""
        self._progress.stop()
        self._progress.pack_forget()
        self._baseline = {d['address']: d for d in devices}
        self._status_label.configure(
            text=f"Found {len(devices)} nearby device(s).")
        # Auto-advance to step 2 after a brief pause
        self._dlg.after(500, self._show_step2)

    # ── Step 2: Pairing Scan ───────────────────────────────────────

    def _show_step2(self):
        self._clear_content()

        customtkinter.CTkLabel(
            self._content, text="Step 2 of 2: Controller Scan",
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        customtkinter.CTkLabel(
            self._content,
            text=(
                "Now press and hold the pairing button on your controller.\n"
                "Wait for the LED to flash, then click Scan."
            ),
            text_color=T.TEXT_SECONDARY,
            font=(T.FONT_FAMILY, 13),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 12))

        self._progress = customtkinter.CTkProgressBar(
            self._content,
            fg_color=T.SURFACE_DARK,
            progress_color=T.GC_PURPLE_LIGHT,
            width=400,
        )
        self._progress.set(0)
        self._progress.pack_forget()

        self._status_label = customtkinter.CTkLabel(
            self._content, text="",
            text_color=T.TEXT_SECONDARY,
            font=(T.FONT_FAMILY, 12),
        )
        self._status_label.pack(anchor=tk.W)

        # Buttons
        self._scan_btn = customtkinter.CTkButton(
            self._btn_bar, text="Scan",
            command=self._do_pairing_scan,
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=36, width=120,
            font=(T.FONT_FAMILY, 14),
        )
        self._scan_btn.pack(side=tk.RIGHT, padx=(8, 0))

        customtkinter.CTkButton(
            self._btn_bar, text="Cancel",
            command=self._on_cancel,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=100,
            font=(T.FONT_FAMILY, 14),
        ).pack(side=tk.RIGHT)

        customtkinter.CTkButton(
            self._btn_bar, text="Back",
            command=self._show_step1,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=100,
            font=(T.FONT_FAMILY, 14),
        ).pack(side=tk.RIGHT, padx=(0, 8))

    def _do_pairing_scan(self):
        self._scan_btn.configure(state="disabled")
        self._progress.pack(pady=(0, 8))
        self._progress.configure(mode="indeterminate")
        self._progress.start()
        self._status_label.configure(text="Scanning for new devices...")

        self._on_scan(self._on_pairing_complete)

    def _on_pairing_complete(self, devices: list[dict]):
        """Called when the pairing scan finishes."""
        self._progress.stop()
        self._progress.pack_forget()

        # Compute diff: new devices not in baseline
        new_devices = [d for d in devices
                       if d['address'] not in self._baseline]
        self._pairing_results = new_devices

        if len(new_devices) == 1:
            # Auto-connect the single new device
            self._result = new_devices[0]['address']
            self._dlg.destroy()
        elif len(new_devices) == 0:
            self._show_no_results()
        else:
            self._show_picker(new_devices)

    # ── Results: no devices found ──────────────────────────────────

    def _show_no_results(self):
        self._clear_content()

        customtkinter.CTkLabel(
            self._content, text="No New Devices Detected",
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        customtkinter.CTkLabel(
            self._content,
            text=(
                "No new Bluetooth devices appeared between scans.\n"
                "Make sure your controller is in pairing mode\n"
                "(LED should be flashing) and try again."
            ),
            text_color=T.TEXT_SECONDARY,
            font=(T.FONT_FAMILY, 13),
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 12))

        customtkinter.CTkButton(
            self._btn_bar, text="Retry",
            command=self._show_step1,
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=36, width=120,
            font=(T.FONT_FAMILY, 14),
        ).pack(side=tk.RIGHT, padx=(8, 0))

        customtkinter.CTkButton(
            self._btn_bar, text="Cancel",
            command=self._on_cancel,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=100,
            font=(T.FONT_FAMILY, 14),
        ).pack(side=tk.RIGHT)

    # ── Results: multiple devices (picker) ─────────────────────────

    def _show_picker(self, devices: list[dict]):
        self._clear_content()

        customtkinter.CTkLabel(
            self._content, text="Multiple New Devices Found",
            text_color=T.TEXT_PRIMARY,
            font=(T.FONT_FAMILY, 16, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        customtkinter.CTkLabel(
            self._content,
            text="Select your controller from the new devices:",
            text_color=T.TEXT_SECONDARY,
            font=(T.FONT_FAMILY, 13),
        ).pack(anchor=tk.W, pady=(0, 8))

        # Treeview (same styling as BLEDevicePickerDialog)
        style = ttk.Style()
        style.theme_use('default')
        style.configure('WizBLE.Treeview',
                        background=T.SURFACE_DARK,
                        foreground=T.TEXT_PRIMARY,
                        fieldbackground=T.SURFACE_DARK,
                        borderwidth=0,
                        font=("", 11))
        style.configure('WizBLE.Treeview.Heading',
                        background=T.GC_PURPLE_MID,
                        foreground=T.TEXT_PRIMARY,
                        borderwidth=0,
                        font=("", 11, "bold"))
        style.map('WizBLE.Treeview',
                  background=[('selected', T.GC_PURPLE_LIGHT)],
                  foreground=[('selected', T.TEXT_PRIMARY)])

        cols = ("name", "address", "signal")
        self._tree = ttk.Treeview(
            self._content, columns=cols, show="headings",
            height=min(len(devices), 8),
            style='WizBLE.Treeview')
        self._tree.heading("name", text="Name")
        self._tree.heading("address", text="Address")
        self._tree.heading("signal", text="Signal")
        self._tree.column("name", width=180)
        self._tree.column("address", width=160)
        self._tree.column("signal", width=60, anchor=tk.CENTER)

        sorted_devices = sorted(devices, key=lambda d: d.get('rssi', -999),
                                reverse=True)
        for dev in sorted_devices:
            rssi = dev.get('rssi', -999)
            signal = f"{rssi} dBm" if rssi > -999 else "?"
            name = dev.get('name', '') or '(unknown)'
            self._tree.insert("", tk.END, values=(
                name, dev['address'], signal))

        self._tree.pack(fill=tk.BOTH, expand=True)
        self._tree.bind("<Double-1>", lambda _: self._on_picker_connect())

        # Buttons
        self._connect_btn = customtkinter.CTkButton(
            self._btn_bar, text="Connect",
            command=self._on_picker_connect,
            fg_color=T.BTN_FG,
            hover_color=T.BTN_HOVER,
            text_color=T.BTN_TEXT,
            corner_radius=12, height=36, width=120,
            font=(T.FONT_FAMILY, 14),
        )
        self._connect_btn.pack(side=tk.RIGHT, padx=(8, 0))

        customtkinter.CTkButton(
            self._btn_bar, text="Cancel",
            command=self._on_cancel,
            fg_color=T.GC_PURPLE_SURFACE,
            hover_color=T.GC_PURPLE_LIGHT,
            text_color=T.TEXT_PRIMARY,
            corner_radius=12, height=36, width=100,
            font=(T.FONT_FAMILY, 14),
        ).pack(side=tk.RIGHT)

    def _on_picker_connect(self):
        sel = self._tree.selection()
        if sel:
            values = self._tree.item(sel[0], "values")
            self._result = values[1]  # address column
            self._dlg.destroy()

    # ── Common ─────────────────────────────────────────────────────

    def _on_cancel(self):
        self._result = None
        self._dlg.destroy()

    def show(self) -> Optional[str]:
        """Show the wizard and block until closed. Returns address or None."""
        self._dlg.wait_window()
        return self._result
