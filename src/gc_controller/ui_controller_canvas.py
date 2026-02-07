"""
UI Controller Canvas - GameCube Controller Visual

Draws a GameCube controller on a tk.Canvas with real-time button highlighting,
moving stick dots, and proportional trigger fills.
"""

import math
import tkinter as tk
from typing import Optional

from . import ui_theme as T
from .controller_constants import normalize


class GCControllerVisual:
    """Draws and manages a GameCube controller visual on a tk.Canvas."""

    CANVAS_W = 520
    CANVAS_H = 380

    # Stick gate geometry
    STICK_GATE_RADIUS = 28
    STICK_DOT_RADIUS = 5

    # Left stick center on canvas
    LSTICK_CX, LSTICK_CY = 150, 165
    # C-stick center on canvas
    CSTICK_CX, CSTICK_CY = 345, 225

    # Trigger geometry
    TRIGGER_W = 80
    TRIGGER_H = 16

    def __init__(self, parent, **kwargs):
        self.canvas = tk.Canvas(
            parent,
            width=self.CANVAS_W,
            height=self.CANVAS_H,
            bg=T.GC_PURPLE_DARK,
            highlightthickness=0,
            **kwargs,
        )

        self._draw_controller_body()
        self._draw_triggers()
        self._draw_dpad()
        self._draw_sticks()
        self._draw_face_buttons()
        self._draw_center_buttons()
        self._draw_nso_buttons()

    # ── Drawing primitives ────────────────────────────────────────

    def _rounded_rect(self, x1, y1, x2, y2, r, **kw):
        """Draw a rounded rectangle on the canvas."""
        points = [
            x1 + r, y1,
            x2 - r, y1,
            x2, y1,
            x2, y1 + r,
            x2, y2 - r,
            x2, y2,
            x2 - r, y2,
            x1 + r, y2,
            x1, y2,
            x1, y2 - r,
            x1, y1 + r,
            x1, y1,
        ]
        return self.canvas.create_polygon(points, smooth=True, **kw)

    # ── Controller body ───────────────────────────────────────────

    def _draw_controller_body(self):
        """Draw the main controller body shape."""
        # Main body - wide rounded shape
        body_points = [
            # Top edge
            60, 60,
            120, 40,
            200, 32,
            260, 30,
            320, 32,
            400, 40,
            460, 60,
            # Right side
            480, 90,
            485, 130,
            480, 170,
            # Right grip
            485, 200,
            490, 240,
            488, 280,
            478, 310,
            460, 335,
            435, 350,
            405, 350,
            385, 340,
            375, 310,
            370, 270,
            365, 230,
            355, 200,
            340, 180,
            # Bottom center
            310, 170,
            260, 168,
            210, 170,
            # Left grip
            180, 180,
            165, 200,
            155, 230,
            150, 270,
            145, 310,
            135, 340,
            115, 350,
            85, 350,
            62, 335,
            42, 310,
            32, 280,
            30, 240,
            35, 200,
            40, 170,
            # Left side
            35, 130,
            40, 90,
        ]
        self.canvas.create_polygon(
            body_points, smooth=True,
            fill=T.GC_PURPLE_MID, outline=T.GC_PURPLE_DARK, width=2,
            tags='body',
        )

        # Inner face plate - slightly lighter area
        inner_points = [
            100, 75,
            170, 55,
            260, 50,
            350, 55,
            420, 75,
            450, 110,
            455, 160,
            440, 200,
            400, 225,
            350, 245,
            260, 250,
            170, 245,
            120, 225,
            80, 200,
            65, 160,
            70, 110,
        ]
        self.canvas.create_polygon(
            inner_points, smooth=True,
            fill=T.GC_PURPLE_SURFACE, outline='', width=0,
            tags='body_inner',
        )

    # ── Triggers (L / R / Z) ─────────────────────────────────────

    def _draw_triggers(self):
        """Draw L/R trigger bars and Z button at the top shoulders."""
        tw, th = self.TRIGGER_W, self.TRIGGER_H

        # Left trigger
        lx, ly = 100, 48
        self._rounded_rect(lx, ly, lx + tw, ly + th, 6,
                           fill=T.BTN_TRIGGER_GRAY, outline=T.GC_PURPLE_DARK,
                           width=1, tags='trigger_L')
        # L trigger fill overlay (hidden initially)
        self.canvas.create_rectangle(
            lx + 2, ly + 2, lx + 2, ly + th - 2,
            fill=T.TRIGGER_FILL, outline='', tags='trigger_L_fill',
        )
        self.canvas.create_text(lx + tw / 2, ly + th / 2, text="L",
                                fill=T.TEXT_PRIMARY, font=("", 9, "bold"),
                                tags='trigger_L_text')

        # Right trigger
        rx, ry = 340, 48
        self._rounded_rect(rx, ry, rx + tw, ry + th, 6,
                           fill=T.BTN_TRIGGER_GRAY, outline=T.GC_PURPLE_DARK,
                           width=1, tags='trigger_R')
        self.canvas.create_rectangle(
            rx + 2, ry + 2, rx + 2, ry + th - 2,
            fill=T.TRIGGER_FILL, outline='', tags='trigger_R_fill',
        )
        self.canvas.create_text(rx + tw / 2, ry + th / 2, text="R",
                                fill=T.TEXT_PRIMARY, font=("", 9, "bold"),
                                tags='trigger_R_text')

        # Z button - right shoulder
        zx, zy = 400, 75
        self._rounded_rect(zx, zy, zx + 45, zy + 18, 6,
                           fill=T.BTN_Z_BLUE, outline=T.GC_PURPLE_DARK,
                           width=1, tags='btn_Z')
        self.canvas.create_text(zx + 22, zy + 9, text="Z",
                                fill=T.TEXT_PRIMARY, font=("", 9, "bold"),
                                tags='btn_Z_text')

    # ── D-pad ─────────────────────────────────────────────────────

    def _draw_dpad(self):
        """Draw the D-pad cross shape."""
        cx, cy = 150, 250
        arm_w, arm_h = 16, 22
        center_r = 8

        # Center
        self.canvas.create_oval(
            cx - center_r, cy - center_r, cx + center_r, cy + center_r,
            fill=T.BTN_DPAD_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='dpad_center',
        )

        # Up
        self.canvas.create_rectangle(
            cx - arm_w / 2, cy - center_r - arm_h,
            cx + arm_w / 2, cy - center_r + 2,
            fill=T.BTN_DPAD_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='dpad_up',
        )
        # Down
        self.canvas.create_rectangle(
            cx - arm_w / 2, cy + center_r - 2,
            cx + arm_w / 2, cy + center_r + arm_h,
            fill=T.BTN_DPAD_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='dpad_down',
        )
        # Left
        self.canvas.create_rectangle(
            cx - center_r - arm_h, cy - arm_w / 2,
            cx - center_r + 2, cy + arm_w / 2,
            fill=T.BTN_DPAD_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='dpad_left',
        )
        # Right
        self.canvas.create_rectangle(
            cx + center_r - 2, cy - arm_w / 2,
            cx + center_r + arm_h, cy + arm_w / 2,
            fill=T.BTN_DPAD_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='dpad_right',
        )

    # ── Analog sticks ─────────────────────────────────────────────

    def _draw_sticks(self):
        """Draw the left stick and C-stick with gates and movable dots."""
        r = self.STICK_GATE_RADIUS
        dr = self.STICK_DOT_RADIUS

        for tag, cx, cy, gate_color, dot_color in [
            ('lstick', self.LSTICK_CX, self.LSTICK_CY, T.STICK_GATE_BG, T.STICK_DOT),
            ('cstick', self.CSTICK_CX, self.CSTICK_CY, T.STICK_GATE_BG, T.CSTICK_YELLOW),
        ]:
            # Gate background circle
            self.canvas.create_oval(
                cx - r - 4, cy - r - 4, cx + r + 4, cy + r + 4,
                fill=gate_color, outline=T.GC_PURPLE_DARK, width=2,
                tags=f'{tag}_gate',
            )

            # Dashed circle outline
            self.canvas.create_oval(
                cx - r, cy - r, cx + r, cy + r,
                outline=T.STICK_CIRCLE, dash=(3, 3),
                tags=f'{tag}_circle',
            )

            # Default octagon
            self._draw_octagon_shape(tag, cx, cy, r, None)

            # Stick dot
            self.canvas.create_oval(
                cx - dr, cy - dr, cx + dr, cy + dr,
                fill=dot_color, outline='',
                tags=f'{tag}_dot',
            )

        # Labels
        self.canvas.create_text(
            self.LSTICK_CX, self.LSTICK_CY - r - 14,
            text="Stick", fill=T.TEXT_SECONDARY, font=("", 8),
            tags='lstick_label',
        )
        self.canvas.create_text(
            self.CSTICK_CX, self.CSTICK_CY - r - 14,
            text="C-Stick", fill=T.TEXT_SECONDARY, font=("", 8),
            tags='cstick_label',
        )

    def _draw_octagon_shape(self, stick_tag, cx, cy, radius, octagon_data,
                            color=None, line_tag=None):
        """Draw an octagon polygon inside a stick gate."""
        tag = line_tag or f'{stick_tag}_octagon'
        self.canvas.delete(tag)

        if color is None:
            color = T.STICK_OCTAGON

        if octagon_data:
            coords = []
            for x_norm, y_norm in octagon_data:
                coords.append(cx + x_norm * radius)
                coords.append(cy - y_norm * radius)
        else:
            coords = []
            for i in range(8):
                angle = math.radians(i * 45)
                coords.append(cx + math.cos(angle) * radius)
                coords.append(cy - math.sin(angle) * radius)

        self.canvas.create_polygon(
            coords, outline=color, fill='', width=2, tags=tag,
        )

    # ── Face buttons (A, B, X, Y) ────────────────────────────────

    def _draw_face_buttons(self):
        """Draw the A, B, X, Y face buttons."""
        # A button - large green circle
        ax, ay = 370, 140
        ar = 22
        self.canvas.create_oval(
            ax - ar, ay - ar, ax + ar, ay + ar,
            fill=T.BTN_A_GREEN, outline=T.GC_PURPLE_DARK, width=2,
            tags='btn_A',
        )
        self.canvas.create_text(ax, ay, text="A",
                                fill=T.TEXT_PRIMARY, font=("", 14, "bold"),
                                tags='btn_A_text')

        # B button - small red circle (below-left of A)
        bx, by = 335, 172
        br = 13
        self.canvas.create_oval(
            bx - br, by - br, bx + br, by + br,
            fill=T.BTN_B_RED, outline=T.GC_PURPLE_DARK, width=2,
            tags='btn_B',
        )
        self.canvas.create_text(bx, by, text="B",
                                fill=T.TEXT_PRIMARY, font=("", 10, "bold"),
                                tags='btn_B_text')

        # X button - horizontal bean/capsule (right of A)
        xx, xy = 418, 132
        self._rounded_rect(xx - 22, xy - 11, xx + 22, xy + 11, 10,
                           fill=T.BTN_XY_GRAY, outline=T.GC_PURPLE_DARK,
                           width=2, tags='btn_X')
        self.canvas.create_text(xx, xy, text="X",
                                fill=T.GC_PURPLE_DARK, font=("", 10, "bold"),
                                tags='btn_X_text')

        # Y button - small gray circle (above-left of A)
        yx, yy = 340, 108
        yr = 13
        self.canvas.create_oval(
            yx - yr, yy - yr, yx + yr, yy + yr,
            fill=T.BTN_XY_GRAY, outline=T.GC_PURPLE_DARK, width=2,
            tags='btn_Y',
        )
        self.canvas.create_text(yx, yy, text="Y",
                                fill=T.GC_PURPLE_DARK, font=("", 10, "bold"),
                                tags='btn_Y_text')

    # ── Center buttons (Start, Home, Capture) ─────────────────────

    def _draw_center_buttons(self):
        """Draw Start/Pause and other center buttons."""
        # Start/Pause - small oval in the center
        sx, sy = 260, 150
        self.canvas.create_oval(
            sx - 12, sy - 8, sx + 12, sy + 8,
            fill=T.BTN_START_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='btn_Start',
        )
        self.canvas.create_text(sx, sy, text="St",
                                fill=T.GC_PURPLE_DARK, font=("", 7, "bold"),
                                tags='btn_Start_text')

    # ── NSO-specific buttons ──────────────────────────────────────

    def _draw_nso_buttons(self):
        """Draw NSO controller-specific buttons (Home, Capture, ZL, GR, GL, Chat)."""
        # Home button
        hx, hy = 238, 180
        self.canvas.create_oval(
            hx - 8, hy - 8, hx + 8, hy + 8,
            fill=T.BTN_START_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='btn_Home',
        )
        self.canvas.create_text(hx, hy, text="H",
                                fill=T.GC_PURPLE_DARK, font=("", 6, "bold"),
                                tags='btn_Home_text')

        # Capture button
        cx, cy = 282, 180
        self.canvas.create_oval(
            cx - 8, cy - 8, cx + 8, cy + 8,
            fill=T.BTN_START_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='btn_Capture',
        )
        self.canvas.create_text(cx, cy, text="C",
                                fill=T.GC_PURPLE_DARK, font=("", 6, "bold"),
                                tags='btn_Capture_text')

        # ZL button - left shoulder area
        zlx, zly = 80, 75
        self._rounded_rect(zlx, zly, zlx + 35, zly + 16, 5,
                           fill=T.BTN_SHOULDER_GRAY, outline=T.GC_PURPLE_DARK,
                           width=1, tags='btn_ZL')
        self.canvas.create_text(zlx + 17, zly + 8, text="ZL",
                                fill=T.TEXT_PRIMARY, font=("", 7, "bold"),
                                tags='btn_ZL_text')

        # GR button
        grx, gry = 450, 98
        self._rounded_rect(grx, gry, grx + 28, gry + 14, 5,
                           fill=T.BTN_SHOULDER_GRAY, outline=T.GC_PURPLE_DARK,
                           width=1, tags='btn_GR')
        self.canvas.create_text(grx + 14, gry + 7, text="GR",
                                fill=T.TEXT_PRIMARY, font=("", 6, "bold"),
                                tags='btn_GR_text')

        # GL button
        glx, gly = 55, 98
        self._rounded_rect(glx, gly, glx + 28, gly + 14, 5,
                           fill=T.BTN_SHOULDER_GRAY, outline=T.GC_PURPLE_DARK,
                           width=1, tags='btn_GL')
        self.canvas.create_text(glx + 14, gly + 7, text="GL",
                                fill=T.TEXT_PRIMARY, font=("", 6, "bold"),
                                tags='btn_GL_text')

        # Chat button
        chx, chy = 260, 200
        self.canvas.create_oval(
            chx - 7, chy - 7, chx + 7, chy + 7,
            fill=T.BTN_START_GRAY, outline=T.GC_PURPLE_DARK, width=1,
            tags='btn_Chat',
        )
        self.canvas.create_text(chx, chy, text="Ch",
                                fill=T.GC_PURPLE_DARK, font=("", 5),
                                tags='btn_Chat_text')

    # ── Public API ────────────────────────────────────────────────

    # Button name → (canvas tag, default fill, pressed fill)
    _BUTTON_MAP = {
        'A':           ('btn_A',       T.BTN_A_GREEN,       T.BTN_A_PRESSED),
        'B':           ('btn_B',       T.BTN_B_RED,         T.BTN_B_PRESSED),
        'X':           ('btn_X',       T.BTN_XY_GRAY,       T.BTN_XY_PRESSED),
        'Y':           ('btn_Y',       T.BTN_XY_GRAY,       T.BTN_XY_PRESSED),
        'Z':           ('btn_Z',       T.BTN_Z_BLUE,        T.BTN_Z_PRESSED),
        'L':           ('trigger_L',   T.BTN_TRIGGER_GRAY,  T.BTN_TRIGGER_PRESSED),
        'R':           ('trigger_R',   T.BTN_TRIGGER_GRAY,  T.BTN_TRIGGER_PRESSED),
        'ZL':          ('btn_ZL',      T.BTN_SHOULDER_GRAY, T.BTN_SHOULDER_PRESSED),
        'Start/Pause': ('btn_Start',   T.BTN_START_GRAY,    T.BTN_START_PRESSED),
        'Home':        ('btn_Home',    T.BTN_START_GRAY,    T.BTN_START_PRESSED),
        'Capture':     ('btn_Capture', T.BTN_START_GRAY,    T.BTN_START_PRESSED),
        'GR':          ('btn_GR',      T.BTN_SHOULDER_GRAY, T.BTN_SHOULDER_PRESSED),
        'GL':          ('btn_GL',      T.BTN_SHOULDER_GRAY, T.BTN_SHOULDER_PRESSED),
        'Chat':        ('btn_Chat',    T.BTN_START_GRAY,    T.BTN_START_PRESSED),
        'Dpad Up':     ('dpad_up',     T.BTN_DPAD_GRAY,     T.BTN_DPAD_PRESSED),
        'Dpad Down':   ('dpad_down',   T.BTN_DPAD_GRAY,     T.BTN_DPAD_PRESSED),
        'Dpad Left':   ('dpad_left',   T.BTN_DPAD_GRAY,     T.BTN_DPAD_PRESSED),
        'Dpad Right':  ('dpad_right',  T.BTN_DPAD_GRAY,     T.BTN_DPAD_PRESSED),
    }

    def update_button_states(self, button_states: dict):
        """Highlight pressed buttons via itemconfig fill.

        Args:
            button_states: dict mapping button name → bool (pressed).
        """
        # Reset all buttons to default first
        for name, (tag, default, pressed) in self._BUTTON_MAP.items():
            self.canvas.itemconfig(tag, fill=default)

        # Highlight pressed buttons
        for name, is_pressed in button_states.items():
            if is_pressed and name in self._BUTTON_MAP:
                tag, default, pressed = self._BUTTON_MAP[name]
                self.canvas.itemconfig(tag, fill=pressed)

    def update_stick_position(self, side: str, x_norm: float, y_norm: float):
        """Move a stick dot to the given normalized position.

        Args:
            side: 'left' or 'right' (C-stick).
            x_norm: normalized X in [-1, 1].
            y_norm: normalized Y in [-1, 1].
        """
        x_norm = max(-1.0, min(1.0, x_norm))
        y_norm = max(-1.0, min(1.0, y_norm))

        if side == 'left':
            cx, cy = self.LSTICK_CX, self.LSTICK_CY
            dot_tag = 'lstick_dot'
        else:
            cx, cy = self.CSTICK_CX, self.CSTICK_CY
            dot_tag = 'cstick_dot'

        r = self.STICK_GATE_RADIUS
        dr = self.STICK_DOT_RADIUS
        x_pos = cx + x_norm * r
        y_pos = cy - y_norm * r

        self.canvas.coords(dot_tag,
                           x_pos - dr, y_pos - dr,
                           x_pos + dr, y_pos + dr)

    def update_trigger_fill(self, side: str, value_0_255: int):
        """Fill trigger shape proportionally.

        Args:
            side: 'left' or 'right'.
            value_0_255: raw trigger value 0–255.
        """
        tw = self.TRIGGER_W
        th = self.TRIGGER_H

        if side == 'left':
            tag = 'trigger_L_fill'
            bx = 100
            by = 48
        else:
            tag = 'trigger_R_fill'
            bx = 340
            by = 48

        fill_w = (value_0_255 / 255.0) * (tw - 4)
        self.canvas.coords(tag,
                           bx + 2, by + 2,
                           bx + 2 + fill_w, by + th - 2)

    def draw_octagon(self, side: str, octagon_data, color: Optional[str] = None):
        """Draw a calibration octagon in the stick gate.

        Args:
            side: 'left' or 'right'.
            octagon_data: list of (x_norm, y_norm) pairs, or None for default.
            color: override color, or None for default.
        """
        if side == 'left':
            tag = 'lstick'
            cx, cy = self.LSTICK_CX, self.LSTICK_CY
        else:
            tag = 'cstick'
            cx, cy = self.CSTICK_CX, self.CSTICK_CY

        r = self.STICK_GATE_RADIUS
        self._draw_octagon_shape(tag, cx, cy, r, octagon_data, color=color)

        # Raise the dot above the octagon
        self.canvas.tag_raise(f'{tag}_dot')

    def draw_octagon_live(self, side: str, dists, points, cx_raw, rx, cy_raw, ry):
        """Draw an in-progress calibration octagon from raw data.

        Args:
            side: 'left' or 'right'.
            dists: list of 8 distances.
            points: list of 8 (raw_x, raw_y) tuples.
            cx_raw, rx, cy_raw, ry: calibration center/range values.
        """
        if side == 'left':
            tag = 'lstick'
            canvas_cx, canvas_cy = self.LSTICK_CX, self.LSTICK_CY
        else:
            tag = 'cstick'
            canvas_cx, canvas_cy = self.CSTICK_CX, self.CSTICK_CY

        r = self.STICK_GATE_RADIUS
        live_tag = f'{tag}_octagon'
        self.canvas.delete(live_tag)

        coords = []
        for i in range(8):
            dist = dists[i]
            if dist > 0:
                raw_x, raw_y = points[i]
                x_norm = normalize(raw_x, cx_raw, rx)
                y_norm = normalize(raw_y, cy_raw, ry)
            else:
                x_norm = 0.0
                y_norm = 0.0
            coords.append(canvas_cx + x_norm * r)
            coords.append(canvas_cy - y_norm * r)

        self.canvas.create_polygon(
            coords, outline=T.STICK_OCTAGON_LIVE, fill='', width=2,
            tags=live_tag,
        )
        self.canvas.tag_raise(f'{tag}_dot')

    def reset(self):
        """Reset all elements to default (unpressed, centered sticks, empty triggers)."""
        # Reset buttons
        for name, (tag, default, pressed) in self._BUTTON_MAP.items():
            self.canvas.itemconfig(tag, fill=default)

        # Center sticks
        for side in ('left', 'right'):
            self.update_stick_position(side, 0.0, 0.0)

        # Empty triggers
        self.update_trigger_fill('left', 0)
        self.update_trigger_fill('right', 0)

    def grid(self, **kwargs):
        """Proxy grid() to the underlying canvas."""
        self.canvas.grid(**kwargs)

    def pack(self, **kwargs):
        """Proxy pack() to the underlying canvas."""
        self.canvas.pack(**kwargs)

    def place(self, **kwargs):
        """Proxy place() to the underlying canvas."""
        self.canvas.place(**kwargs)
