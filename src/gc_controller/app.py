#!/usr/bin/env python3
"""
GameCube Controller Enabler - Python/Tkinter Version

Converts GameCube controllers to work with Steam and other applications.
Handles USB initialization, HID communication, and Xbox 360 controller emulation.

Requirements:
    pip install hidapi pyusb

Note: Windows users need ViGEmBus driver for Xbox 360 emulation
"""

import argparse
import errno
import os
import signal
import sys
import threading

try:
    import hid
    import usb.core
    import usb.util
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install hidapi pyusb")
    sys.exit(1)

from .virtual_gamepad import (
    is_emulation_available, get_emulation_unavailable_reason, ensure_dolphin_pipe,
)
from .controller_constants import DEFAULT_CALIBRATION
from .settings_manager import SettingsManager
from .calibration import CalibrationManager
from .connection_manager import ConnectionManager
from .emulation_manager import EmulationManager
from .input_processor import InputProcessor

# Create the Dolphin pipe FIFO early so it shows up in Dolphin's device list
if sys.platform in ('darwin', 'linux'):
    try:
        ensure_dolphin_pipe()
    except Exception as e:
        print(f"Note: Could not create Dolphin pipe: {e}")


class GCControllerEnabler:
    """Main application orchestrator for GameCube Controller Enabler"""

    def __init__(self):
        import tkinter as tk
        from tkinter import messagebox
        from .controller_ui import ControllerUI

        self._tk = tk
        self._messagebox = messagebox

        self.root = tk.Tk()
        self.root.title("GameCube Controller Enabler")
        self.root.resizable(False, False)

        # Shared calibration dict (passed by reference to all managers)
        self.calibration = dict(DEFAULT_CALIBRATION)

        # Settings
        self.settings_mgr = SettingsManager(self.calibration, os.getcwd())
        self.settings_mgr.load()

        # Calibration
        self.cal_mgr = CalibrationManager(self.calibration)

        # Connection
        self.conn_mgr = ConnectionManager(
            on_status=self._schedule_status,
            on_progress=self._schedule_progress,
        )

        # Emulation
        self.emu_mgr = EmulationManager(self.cal_mgr)

        # UI
        self.ui = ControllerUI(
            self.root, self.calibration, self.cal_mgr,
            on_connect=self.connect_controller,
            on_emulate=self.toggle_emulation,
            on_stick_cal=self.toggle_stick_calibration,
            on_trigger_cal=self.trigger_cal_step,
            on_save=self.save_settings,
        )

        # Input processor
        self.input_proc = InputProcessor(
            device_getter=lambda: self.conn_mgr.device,
            calibration=self.calibration,
            cal_mgr=self.cal_mgr,
            emu_mgr=self.emu_mgr,
            on_ui_update=self._schedule_ui_update,
            on_error=lambda msg: self.root.after(0, lambda: self.ui.update_status(msg)),
            on_disconnect=lambda: self.root.after(0, self._on_unexpected_disconnect),
        )

        # Handle window closing
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # Auto-connect if enabled
        if self.calibration['auto_connect']:
            self.root.after(100, self.auto_connect_and_emulate)

    # ── Connection ───────────────────────────────────────────────────

    def connect_controller(self):
        """Connect to GameCube controller."""
        if self.input_proc.is_reading:
            self.disconnect_controller()
            return

        self.ui.progress['value'] = 0

        if not self.conn_mgr.connect():
            return

        self.input_proc.start()

        self.ui.connect_btn.config(text="Disconnect")
        self.ui.emulate_btn.config(state='normal')

    def disconnect_controller(self):
        """Disconnect from controller."""
        self.input_proc.stop()
        self.emu_mgr.stop()

        self.conn_mgr.disconnect()

        self.ui.connect_btn.config(text="Connect")
        self.ui.emulate_btn.config(state='disabled')
        self.ui.emulate_btn.config(text="Start Emulation")
        self.ui.progress['value'] = 0
        self.ui.update_status("Disconnected")
        self.ui.reset_ui_elements()

    def auto_connect_and_emulate(self):
        """Auto-connect and start emulation on startup."""
        self.connect_controller()
        if self.input_proc.is_reading:
            self.toggle_emulation()

    # ── Auto-reconnect ──────────────────────────────────────────────

    def _on_unexpected_disconnect(self):
        """Handle an unexpected controller disconnect by attempting to reconnect."""
        if self.conn_mgr.device:
            try:
                self.conn_mgr.device.close()
            except Exception:
                pass
            self.conn_mgr.device = None

        was_emulating = self.emu_mgr.is_emulating

        if self.emu_mgr.is_emulating:
            self.emu_mgr.stop()

        self.ui.update_status("Controller disconnected — reconnecting...")
        self.ui.connect_btn.config(text="Connect")
        self.ui.emulate_btn.config(state='disabled')
        self.ui.progress['value'] = 0

        self._reconnect_was_emulating = was_emulating
        self._attempt_reconnect()

    def _attempt_reconnect(self):
        """Try to reconnect to the controller. Retries every 2 seconds."""
        # User clicked Disconnect while we were waiting — abort.
        if self.input_proc.stop_event.is_set():
            self.ui.update_status("Disconnected")
            self.ui.reset_ui_elements()
            return

        if self.conn_mgr.connect():
            self.input_proc.start()
            self.ui.connect_btn.config(text="Disconnect")
            self.ui.emulate_btn.config(state='normal')
            self.ui.update_status("Reconnected")

            if getattr(self, '_reconnect_was_emulating', False):
                self._reconnect_was_emulating = False
                self.toggle_emulation()
            return

        # Failed — retry after a delay
        self.ui.update_status("Controller disconnected — reconnecting...")
        self.ui.progress['value'] = 0
        self.root.after(2000, self._attempt_reconnect)

    # ── Emulation ────────────────────────────────────────────────────

    def toggle_emulation(self):
        """Start or stop controller emulation in the selected mode."""
        if self.emu_mgr.is_emulating:
            self.emu_mgr.stop()
            self.ui.emulate_btn.config(text="Start Emulation")
            if self.input_proc.is_reading:
                self.ui.update_status("Connected via HID")
            else:
                self.ui.update_status("Ready to connect")
        else:
            mode = self.ui.emu_mode_var.get()

            if not is_emulation_available(mode):
                self._messagebox.showerror(
                    "Error",
                    f"Emulation not available for mode '{mode}'.\n"
                    + get_emulation_unavailable_reason(mode))
                return

            try:
                self.emu_mgr.start(mode)
                self.ui.emulate_btn.config(text="Stop Emulation")
                if mode == 'dolphin_pipe':
                    self.ui.update_status("Dolphin pipe emulation active")
                else:
                    self.ui.update_status("Xbox 360 emulation active")
            except OSError as e:
                if e.errno == errno.ENXIO:
                    self._messagebox.showerror(
                        "Emulation Error",
                        "Dolphin is not reading the pipe.\n\n"
                        "You may need to restart Dolphin if this is the first "
                        "time you've launched this tool.\n\n"
                        "To configure the pipe controller in Dolphin:\n"
                        "1. Open Controllers (top menu bar)\n"
                        "2. Under GameCube, set Port 1 to 'Standard Controller'\n"
                        "3. Click 'Configure' next to Port 1\n"
                        "4. In the Device dropdown, select 'Pipe/0/gc_controller'\n"
                        "5. Update your button/stick/trigger bindings for the pipe device\n"
                        "6. Click Close, then try Start Emulation again")
                else:
                    self._messagebox.showerror("Emulation Error",
                                               f"Failed to start emulation: {e}")
            except Exception as e:
                self._messagebox.showerror("Emulation Error",
                                           f"Failed to start emulation: {e}")

    # ── Stick calibration ────────────────────────────────────────────

    def toggle_stick_calibration(self):
        """Toggle stick calibration on/off."""
        if self.cal_mgr.stick_calibrating:
            self.cal_mgr.finish_stick_calibration()
            self.ui.redraw_octagons()
            self.ui.stick_cal_btn.config(text="Calibrate Sticks")
            self.ui.stick_cal_status.config(text="Calibration complete!")
        else:
            self.cal_mgr.start_stick_calibration()
            self.ui.stick_cal_btn.config(text="Finish Calibration")
            self.ui.stick_cal_status.config(text="Move sticks to all extremes...")

    # ── Trigger calibration ──────────────────────────────────────────

    def trigger_cal_step(self):
        """Advance the trigger calibration wizard one step."""
        result = self.cal_mgr.trigger_cal_next_step()
        if result is not None:
            step, btn_text, status_text = result
            self.ui.trigger_cal_btn.config(text=btn_text)
            self.ui.trigger_cal_status.config(text=status_text)
            if step == 0:
                # Wizard finished — redraw markers
                self.ui.draw_trigger_markers()

    # ── Settings ─────────────────────────────────────────────────────

    def update_calibration_from_ui(self):
        """Update calibration values from UI variables."""
        self.calibration['trigger_bump_100_percent'] = self.ui.trigger_mode_var.get()
        self.calibration['emulation_mode'] = self.ui.emu_mode_var.get()
        self.calibration['auto_connect'] = self.ui.auto_connect_var.get()
        self.cal_mgr.refresh_cache()

    def save_settings(self):
        """Save calibration settings to file."""
        self.update_calibration_from_ui()
        try:
            self.settings_mgr.save()
            self._messagebox.showinfo("Settings", "Settings saved successfully!")
        except Exception as e:
            self._messagebox.showerror("Error", f"Failed to save settings: {e}")

    # ── Thread-safe bridges ──────────────────────────────────────────

    def _schedule_status(self, message: str):
        """Thread-safe status update via root.after."""
        self.root.after(0, lambda: self.ui.update_status(message))

    def _schedule_progress(self, value: int):
        """Thread-safe progress bar update via root.after."""
        self.root.after(0, lambda: self.ui.progress.configure(value=value))

    def _schedule_ui_update(self, left_x, left_y, right_x, right_y,
                            left_trigger, right_trigger, button_states,
                            stick_calibrating):
        """Schedule a UI update from the input thread."""
        self.root.after(0, lambda: self._apply_ui_update(
            left_x, left_y, right_x, right_y,
            left_trigger, right_trigger, button_states,
            stick_calibrating))

    def _apply_ui_update(self, left_x, left_y, right_x, right_y,
                         left_trigger, right_trigger, button_states,
                         stick_calibrating):
        """Apply UI updates on the main thread."""
        self.ui.update_stick_position(
            self.ui.left_stick_canvas, self.ui.left_stick_dot, left_x, left_y)
        self.ui.update_stick_position(
            self.ui.right_stick_canvas, self.ui.right_stick_dot, right_x, right_y)
        self.ui.update_trigger_display(left_trigger, right_trigger)
        self.ui.update_button_display(button_states)

        if stick_calibrating:
            self.ui.draw_octagon_live(
                self.ui.left_stick_canvas, self.ui.left_stick_dot, 'left')
            self.ui.draw_octagon_live(
                self.ui.right_stick_canvas, self.ui.right_stick_dot, 'right')

    # ── Lifecycle ────────────────────────────────────────────────────

    def on_closing(self):
        """Handle application closing."""
        self.disconnect_controller()
        self.root.destroy()

    def run(self):
        """Start the application."""
        self.root.mainloop()


def run_headless(mode_override: str = None):
    """Run controller connection and emulation without the GUI."""
    calibration = dict(DEFAULT_CALIBRATION)

    settings_mgr = SettingsManager(calibration, os.getcwd())
    settings_mgr.load()

    # Use explicit --mode if given, otherwise honor the saved setting
    mode = mode_override if mode_override else calibration.get('emulation_mode', 'xbox360')

    if not is_emulation_available(mode):
        print(f"Error: Emulation not available for mode '{mode}'.")
        print(get_emulation_unavailable_reason(mode))
        sys.exit(1)

    cal_mgr = CalibrationManager(calibration)

    conn_mgr = ConnectionManager(
        on_status=lambda msg: print(f"[status] {msg}"),
        on_progress=lambda val: None,
    )

    emu_mgr = EmulationManager(cal_mgr)

    stop_event = threading.Event()
    disconnect_event = threading.Event()

    def _shutdown(signum, frame):
        stop_event.set()
        disconnect_event.set()  # unblock reconnect wait

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    def _on_disconnect():
        disconnect_event.set()

    print("Connecting to GameCube controller...")
    if not conn_mgr.connect():
        print("Failed to connect. Is the controller plugged in?")
        sys.exit(1)

    mode_label = "Dolphin pipe" if mode == 'dolphin_pipe' else "Xbox 360"
    print(f"Starting {mode_label} emulation...")
    try:
        emu_mgr.start(mode)
    except Exception as e:
        print(f"Failed to start emulation: {e}")
        conn_mgr.disconnect()
        sys.exit(1)

    input_proc = InputProcessor(
        device_getter=lambda: conn_mgr.device,
        calibration=calibration,
        cal_mgr=cal_mgr,
        emu_mgr=emu_mgr,
        on_ui_update=lambda *args: None,
        on_error=lambda msg: print(f"[error] {msg}"),
        on_disconnect=_on_disconnect,
    )
    input_proc.start()

    print("Headless mode active. Press Ctrl+C to stop.")

    while not stop_event.is_set():
        disconnect_event.wait()
        disconnect_event.clear()

        if stop_event.is_set():
            break

        # Unexpected disconnect — attempt reconnect
        if conn_mgr.device:
            try:
                conn_mgr.device.close()
            except Exception:
                pass
            conn_mgr.device = None

        was_emulating = emu_mgr.is_emulating
        if emu_mgr.is_emulating:
            emu_mgr.stop()

        print("Controller disconnected — reconnecting...")

        while not stop_event.is_set():
            if conn_mgr.connect():
                input_proc.start()
                print("Reconnected.")
                if was_emulating:
                    try:
                        emu_mgr.start(mode)
                        print(f"{mode_label} emulation resumed.")
                    except Exception as e:
                        print(f"Failed to resume emulation: {e}")
                break
            stop_event.wait(timeout=2.0)

    print("\nShutting down...")
    input_proc.stop()
    emu_mgr.stop()
    conn_mgr.disconnect()
    print("Done.")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="GameCube Controller Enabler - "
                    "converts GC controllers to Xbox 360 for Steam and other apps"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="run without the GUI (connect and emulate in the background)",
    )
    parser.add_argument(
        "--mode",
        choices=["xbox360", "dolphin_pipe"],
        default=None,
        help="emulation mode for headless operation (default: use saved setting)",
    )
    args = parser.parse_args()

    if args.headless:
        run_headless(mode_override=args.mode)
    else:
        app = GCControllerEnabler()
        app.run()


if __name__ == "__main__":
    main()
