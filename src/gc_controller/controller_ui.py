"""
Controller UI

All Tkinter widget creation and UI update methods for the GameCube Controller Enabler.
"""

import math
import sys
import tkinter as tk
from tkinter import ttk
from typing import Dict, Callable

from .controller_constants import normalize
from .calibration import CalibrationManager

IS_MACOS = sys.platform == "darwin"


class ControllerUI:
    """Creates and manages all UI widgets for the controller application."""

    def __init__(self, root: tk.Tk, calibration: dict, cal_mgr: CalibrationManager,
                 on_connect: Callable, on_emulate: Callable,
                 on_stick_cal: Callable, on_trigger_cal: Callable,
                 on_save: Callable):
        self._root = root
        self._calibration = calibration
        self._cal_mgr = cal_mgr

        # Tkinter variables (public for orchestrator access)
        self.auto_connect_var = tk.BooleanVar(value=calibration['auto_connect'])
        self.trigger_mode_var = tk.BooleanVar(value=calibration['trigger_bump_100_percent'])

        # Default to dolphin_pipe on macOS if current mode is xbox360 (unavailable)
        emu_default = calibration['emulation_mode']
        if IS_MACOS and emu_default == 'xbox360':
            emu_default = 'dolphin_pipe'
        self.emu_mode_var = tk.StringVar(value=emu_default)

        self._trigger_bar_width = 150
        self._trigger_bar_height = 20

        self._setup(on_connect, on_emulate, on_stick_cal, on_trigger_cal, on_save)

    # ── Setup ────────────────────────────────────────────────────────

    def _setup(self, on_connect, on_emulate, on_stick_cal, on_trigger_cal, on_save):
        """Create the user interface."""
        main_frame = ttk.Frame(self._root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))

        # Connection section
        connection_frame = ttk.LabelFrame(main_frame, text="Connection", padding="10")
        connection_frame.grid(row=0, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=(0, 10))

        self.connect_btn = ttk.Button(connection_frame, text="Connect", command=on_connect)
        self.connect_btn.grid(row=0, column=0, padx=(0, 10))

        self.emulate_btn = ttk.Button(connection_frame, text="Start Emulation",
                                      command=on_emulate, state='disabled')
        self.emulate_btn.grid(row=0, column=1)

        ttk.Checkbutton(connection_frame, text="Connect and Emulate at startup",
                        variable=self.auto_connect_var).grid(row=0, column=2, padx=(10, 0))

        # Progress bar
        self.progress = ttk.Progressbar(connection_frame, length=300, mode='determinate')
        self.progress.grid(row=1, column=0, columnspan=3, pady=(10, 0), sticky=(tk.W, tk.E))

        # Status label
        self.status_label = ttk.Label(connection_frame, text="Ready to connect")
        self.status_label.grid(row=2, column=0, columnspan=3, pady=(5, 0))

        # Left column
        left_column = ttk.Frame(main_frame)
        left_column.grid(row=1, column=0, sticky=(tk.W, tk.E, tk.N), padx=(0, 10))

        # Button visualization
        controller_frame = ttk.LabelFrame(left_column, text="Button Configuration", padding="10")
        controller_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        buttons_frame = ttk.Frame(controller_frame)
        buttons_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        self.button_labels = {}
        button_names = ["A", "B", "X", "Y", "L", "R", "Z", "ZL", "Start/Pause", "Home", "Capture", "Chat"]

        for i, btn_name in enumerate(button_names):
            row = i // 4
            col = i % 4
            label = ttk.Label(buttons_frame, text=btn_name, width=8, relief='raised')
            label.grid(row=row, column=col, padx=2, pady=2)
            self.button_labels[btn_name] = label

        # D-pad
        dpad_frame = ttk.LabelFrame(buttons_frame, text="D-Pad")
        dpad_frame.grid(row=3, column=0, columnspan=4, pady=(10, 0))

        self.dpad_labels = {}
        for direction in ["Up", "Down", "Left", "Right"]:
            label = ttk.Label(dpad_frame, text=direction, width=6, relief='raised')
            self.dpad_labels[direction] = label

        self.dpad_labels["Up"].grid(row=0, column=1)
        self.dpad_labels["Left"].grid(row=1, column=0)
        self.dpad_labels["Right"].grid(row=1, column=2)
        self.dpad_labels["Down"].grid(row=2, column=1)

        # Analog sticks
        sticks_frame = ttk.LabelFrame(left_column, text="Analog Sticks", padding="10")
        sticks_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(10, 0))

        # Right column
        right_column = ttk.Frame(main_frame)
        right_column.grid(row=1, column=1, sticky=(tk.W, tk.E, tk.N))

        # Analog triggers section
        calibration_frame = ttk.LabelFrame(right_column, text="Analog Triggers", padding="10")
        calibration_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        # Left stick
        left_stick_frame = ttk.Frame(sticks_frame)
        left_stick_frame.grid(row=0, column=0, padx=10)
        ttk.Label(left_stick_frame, text="Left Stick").grid(row=0, column=0)
        self.left_stick_canvas = tk.Canvas(left_stick_frame, width=80, height=80, bg='lightgray')
        self.left_stick_canvas.grid(row=1, column=0)
        self.left_stick_dot = self.left_stick_canvas.create_oval(37, 37, 43, 43, fill='red')
        self._init_stick_canvas(self.left_stick_canvas, self.left_stick_dot, 'left')

        # Right stick
        right_stick_frame = ttk.Frame(sticks_frame)
        right_stick_frame.grid(row=0, column=1, padx=10)
        ttk.Label(right_stick_frame, text="Right Stick").grid(row=0, column=0)
        self.right_stick_canvas = tk.Canvas(right_stick_frame, width=80, height=80, bg='lightgray')
        self.right_stick_canvas.grid(row=1, column=0)
        self.right_stick_dot = self.right_stick_canvas.create_oval(37, 37, 43, 43, fill='red')
        self._init_stick_canvas(self.right_stick_canvas, self.right_stick_dot, 'right')

        # Stick calibration
        stick_cal_frame = ttk.LabelFrame(sticks_frame, text="Calibration", padding="5")
        stick_cal_frame.grid(row=1, column=0, columnspan=2, pady=(10, 0), sticky=(tk.W, tk.E))

        self.stick_cal_btn = ttk.Button(stick_cal_frame, text="Calibrate Sticks",
                                        command=on_stick_cal)
        self.stick_cal_btn.grid(row=0, column=0, padx=5, pady=2)

        self.stick_cal_status = ttk.Label(stick_cal_frame, text="Using saved calibration")
        self.stick_cal_status.grid(row=0, column=1, padx=5, pady=2)

        # Trigger visualizers
        triggers_frame = ttk.Frame(calibration_frame)
        triggers_frame.grid(row=0, column=0, sticky=(tk.W, tk.E))

        w = self._trigger_bar_width
        h = self._trigger_bar_height

        ttk.Label(triggers_frame, text="Left Trigger").grid(row=0, column=0)
        self.left_trigger_canvas = tk.Canvas(triggers_frame, width=w, height=h,
                                             bg='#e0e0e0', highlightthickness=1,
                                             highlightbackground='#999999')
        self.left_trigger_canvas.grid(row=0, column=1, padx=(5, 10))
        self.left_trigger_label = ttk.Label(triggers_frame, text="0")
        self.left_trigger_label.grid(row=0, column=2)

        ttk.Label(triggers_frame, text="Right Trigger").grid(row=1, column=0)
        self.right_trigger_canvas = tk.Canvas(triggers_frame, width=w, height=h,
                                              bg='#e0e0e0', highlightthickness=1,
                                              highlightbackground='#999999')
        self.right_trigger_canvas.grid(row=1, column=1, padx=(5, 10))
        self.right_trigger_label = ttk.Label(triggers_frame, text="0")
        self.right_trigger_label.grid(row=1, column=2)

        # Draw initial calibration markers
        self._draw_trigger_markers()

        # Trigger calibration wizard
        trigger_cal_frame = ttk.LabelFrame(calibration_frame, text="Calibration", padding="5")
        trigger_cal_frame.grid(row=1, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        self.trigger_cal_btn = ttk.Button(trigger_cal_frame, text="Calibrate Triggers",
                                          command=on_trigger_cal)
        self.trigger_cal_btn.grid(row=0, column=0, padx=5, pady=2)

        self.trigger_cal_status = ttk.Label(trigger_cal_frame, text="Using saved calibration")
        self.trigger_cal_status.grid(row=0, column=1, padx=5, pady=2)

        # Trigger mode
        mode_frame = ttk.LabelFrame(calibration_frame, text="Trigger Mode", padding="5")
        mode_frame.grid(row=2, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        ttk.Radiobutton(mode_frame, text="100% at bump",
                        variable=self.trigger_mode_var, value=True).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(mode_frame, text="100% at press",
                        variable=self.trigger_mode_var, value=False).grid(row=1, column=0, sticky=tk.W)

        # Emulation mode
        emu_frame = ttk.LabelFrame(right_column, text="Emulation Mode", padding="5")
        emu_frame.grid(row=1, column=0, pady=(10, 0), sticky=(tk.W, tk.E))

        xbox_state = 'disabled' if IS_MACOS else 'normal'
        ttk.Radiobutton(emu_frame, text="Xbox 360",
                        variable=self.emu_mode_var, value='xbox360',
                        state=xbox_state).grid(row=0, column=0, sticky=tk.W)
        ttk.Radiobutton(emu_frame, text="Dolphin (Named Pipe)",
                        variable=self.emu_mode_var, value='dolphin_pipe').grid(row=1, column=0, sticky=tk.W)

        # Save settings button
        ttk.Button(right_column, text="Save Settings",
                   command=on_save).grid(row=2, column=0, pady=(10, 0))

        # Configure grid weights
        main_frame.columnconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)

    # ── Stick canvas helpers ─────────────────────────────────────────

    def _init_stick_canvas(self, canvas, dot, side):
        """Draw dashed circle outline and octagon on a stick canvas, raise dot to top."""
        canvas.create_oval(10, 10, 70, 70, outline='#999999', dash=(3, 3), tag='circle')
        self._draw_octagon(canvas, side)
        canvas.tag_raise(dot)

    def _draw_octagon(self, canvas, side):
        """Draw/redraw the octagon polygon from calibration data on a stick canvas."""
        canvas.delete('octagon')
        cal_key = f'stick_{side}_octagon'
        octagon_data = self._calibration.get(cal_key)

        center = 40
        radius = 30

        if octagon_data:
            coords = []
            for x_norm, y_norm in octagon_data:
                coords.append(center + x_norm * radius)
                coords.append(center - y_norm * radius)
        else:
            coords = []
            for i in range(8):
                angle = math.radians(i * 45)
                coords.append(center + math.cos(angle) * radius)
                coords.append(center - math.sin(angle) * radius)

        canvas.create_polygon(coords, outline='#666666', fill='', width=2, tag='octagon')

    def draw_octagon_live(self, canvas, dot, side):
        """Redraw octagon from in-progress calibration data."""
        canvas.delete('octagon')

        dists, points, cx, rx, cy, ry = self._cal_mgr.get_live_octagon_data(side)

        center = 40
        radius = 30

        coords = []
        for i in range(8):
            dist = dists[i]
            if dist > 0:
                raw_x, raw_y = points[i]
                x_norm = normalize(raw_x, cx, rx)
                y_norm = normalize(raw_y, cy, ry)
            else:
                x_norm = 0.0
                y_norm = 0.0
            coords.append(center + x_norm * radius)
            coords.append(center - y_norm * radius)

        canvas.create_polygon(coords, outline='#00aa00', fill='', width=2, tag='octagon')
        canvas.tag_raise(dot)

    # ── UI update methods ────────────────────────────────────────────

    def update_stick_position(self, canvas, dot, x_norm, y_norm):
        """Update analog stick position on canvas."""
        x_norm = max(-1, min(1, x_norm))
        y_norm = max(-1, min(1, y_norm))

        center_x, center_y = 40, 40
        x_pos = center_x + (x_norm * 30)
        y_pos = center_y - (y_norm * 30)

        canvas.coords(dot, x_pos - 3, y_pos - 3, x_pos + 3, y_pos + 3)

    def update_trigger_display(self, left_trigger, right_trigger):
        """Update trigger canvas bars and labels."""
        w = self._trigger_bar_width
        h = self._trigger_bar_height

        for canvas, raw in [(self.left_trigger_canvas, left_trigger),
                            (self.right_trigger_canvas, right_trigger)]:
            canvas.delete('fill')
            fill_x = (raw / 255.0) * w
            if fill_x > 0:
                canvas.create_rectangle(0, 0, fill_x, h, fill='#06b025',
                                        outline='', tag='fill')
            canvas.tag_raise('bump_line')
            canvas.tag_raise('max_line')

        self.left_trigger_label.config(text=str(left_trigger))
        self.right_trigger_label.config(text=str(right_trigger))

    def update_button_display(self, button_states: Dict[str, bool]):
        """Update button indicators."""
        for label in self.button_labels.values():
            label.config(relief='raised', background='')
        for label in self.dpad_labels.values():
            label.config(relief='raised', background='')

        for button_name, pressed in button_states.items():
            if pressed:
                if button_name in self.button_labels:
                    self.button_labels[button_name].config(relief='sunken', background='lightgreen')
                elif button_name.startswith("Dpad "):
                    direction = button_name.split(" ")[1]
                    if direction in self.dpad_labels:
                        self.dpad_labels[direction].config(relief='sunken', background='lightgreen')

    def _draw_trigger_markers(self):
        """Draw bump and max calibration marker lines on both trigger canvases."""
        w = self._trigger_bar_width
        h = self._trigger_bar_height
        cal = self._calibration

        for canvas, side in [(self.left_trigger_canvas, 'left'),
                             (self.right_trigger_canvas, 'right')]:
            canvas.delete('bump_line')
            canvas.delete('max_line')

            bump = cal[f'trigger_{side}_bump']
            max_val = cal[f'trigger_{side}_max']

            bump_x = (bump / 255.0) * w
            max_x = (max_val / 255.0) * w

            canvas.create_line(bump_x, 0, bump_x, h, fill='#e6a800',
                               width=2, tag='bump_line')
            canvas.create_line(max_x, 0, max_x, h, fill='#cc0000',
                               width=2, tag='max_line')

    def draw_trigger_markers(self):
        """Public wrapper for redrawing trigger markers."""
        self._draw_trigger_markers()

    # ── Reset ────────────────────────────────────────────────────────

    def reset_ui_elements(self):
        """Reset UI elements to default state."""
        for label in self.button_labels.values():
            label.config(relief='raised', background='')
        for label in self.dpad_labels.values():
            label.config(relief='raised', background='')

        self.left_stick_canvas.coords(self.left_stick_dot, 37, 37, 43, 43)
        self.right_stick_canvas.coords(self.right_stick_dot, 37, 37, 43, 43)

        self._draw_octagon(self.left_stick_canvas, 'left')
        self.left_stick_canvas.tag_raise(self.left_stick_dot)
        self._draw_octagon(self.right_stick_canvas, 'right')
        self.right_stick_canvas.tag_raise(self.right_stick_dot)

        self.left_trigger_canvas.delete('fill')
        self.right_trigger_canvas.delete('fill')
        self._draw_trigger_markers()
        self.left_trigger_label.config(text="0")
        self.right_trigger_label.config(text="0")

    def redraw_octagons(self):
        """Redraw both octagon polygons from calibration data."""
        self._draw_octagon(self.left_stick_canvas, 'left')
        self.left_stick_canvas.tag_raise(self.left_stick_dot)
        self._draw_octagon(self.right_stick_canvas, 'right')
        self.right_stick_canvas.tag_raise(self.right_stick_dot)

    # ── Status helpers ───────────────────────────────────────────────

    def update_status(self, message: str):
        """Update the status label text."""
        self.status_label.config(text=message)
