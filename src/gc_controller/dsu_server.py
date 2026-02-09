"""
DSU (Cemuhook) Protocol Server + VirtualGamepad Implementation

Provides a UDP-based input server compatible with Dolphin, Cemu, Yuzu, Ryujinx,
and other emulators that support the cemuhook DSU protocol.

Protocol reference: https://v1993.github.io/cemern-protocol/
"""

import socket
import struct
import threading
import time
import zlib
from typing import Optional, Callable

from .virtual_gamepad import VirtualGamepad, GamepadButton

# ── DSU Protocol Constants ──────────────────────────────────────────

DSUS_MAGIC = b'DSUS'
DSUC_MAGIC = b'DSUC'
DSU_PROTOCOL_VERSION = 1001

# Server → Client message types
MSG_TYPE_VERSION = 0x00100000
MSG_TYPE_PORTS = 0x00100001
MSG_TYPE_DATA = 0x00100002

# Client → Server message types
MSG_TYPE_REQ_VERSION = 0x00100000
MSG_TYPE_REQ_PORTS = 0x00100001
MSG_TYPE_REQ_DATA = 0x00100002

# Controller model
MODEL_DS4 = 2  # DualShock 4
CONN_TYPE_USB = 1
BATTERY_FULL = 0x05

# Header size (magic:4 + version:2 + length:2 + crc32:4 + server_id:4 = 16)
HEADER_SIZE = 16


# ── DSU Packet Builder ──────────────────────────────────────────────

def _build_header(msg_type: int, payload_len: int, server_id: int) -> bytearray:
    """Build a 16-byte DSU header. CRC32 is zeroed for later computation."""
    buf = bytearray(HEADER_SIZE)
    buf[0:4] = DSUS_MAGIC
    struct.pack_into('<H', buf, 4, DSU_PROTOCOL_VERSION)
    struct.pack_into('<H', buf, 6, payload_len)
    # CRC32 at offset 8 stays 0 for now
    struct.pack_into('<I', buf, 12, server_id)
    return buf


def _finalize_crc(packet: bytearray) -> None:
    """Compute CRC32 over the full packet (with CRC field zeroed) and write it in."""
    packet[8:12] = b'\x00\x00\x00\x00'
    crc = zlib.crc32(packet) & 0xFFFFFFFF
    struct.pack_into('<I', packet, 8, crc)


def _build_version_response(server_id: int) -> bytearray:
    """Build a version info response packet (22 bytes total)."""
    # Payload: message_type(4) + max_protocol_version(2) = 6 bytes
    payload = struct.pack('<IH', MSG_TYPE_VERSION, DSU_PROTOCOL_VERSION)
    header = _build_header(MSG_TYPE_VERSION, len(payload), server_id)
    packet = header + payload
    _finalize_crc(packet)
    return packet


def _build_port_info(server_id: int, slot: int, connected: bool) -> bytearray:
    """Build a controller port info response."""
    # Payload: message_type(4) + pad_id(1) + state(1) + model(1)
    #        + connection_type(1) + mac(6) + battery(1) + padding(1) = 16
    payload = bytearray(16)
    struct.pack_into('<I', payload, 0, MSG_TYPE_PORTS)
    payload[4] = slot & 0xFF  # pad id / slot
    payload[5] = 0x02 if connected else 0x00  # state: connected / disconnected
    payload[6] = MODEL_DS4
    payload[7] = CONN_TYPE_USB
    # MAC address: use slot-based fake MAC
    payload[8] = 0x00
    payload[9] = 0x00
    payload[10] = 0x00
    payload[11] = 0x00
    payload[12] = 0x00
    payload[13] = slot & 0xFF
    payload[14] = BATTERY_FULL
    payload[15] = 0x00  # padding

    header = _build_header(MSG_TYPE_PORTS, len(payload), server_id)
    packet = header + payload
    _finalize_crc(packet)
    return packet


# ── DSUServer Singleton ─────────────────────────────────────────────

_server_instance: Optional['DSUServer'] = None
_server_refcount: int = 0
_server_lock = threading.Lock()


def _acquire_server() -> 'DSUServer':
    """Increment refcount and start the server if it's the first user."""
    global _server_instance, _server_refcount
    with _server_lock:
        if _server_instance is None:
            _server_instance = DSUServer()
            _server_instance.start()
        _server_refcount += 1
        return _server_instance


def _release_server() -> None:
    """Decrement refcount and stop the server if no users remain."""
    global _server_instance, _server_refcount
    with _server_lock:
        _server_refcount -= 1
        if _server_refcount <= 0:
            _server_refcount = 0
            if _server_instance is not None:
                _server_instance.stop()
                _server_instance = None


class DSUServer:
    """UDP server implementing the cemuhook DSU protocol.

    Listens on 127.0.0.1:26760 (with fallback ports) and streams
    controller state to subscribed clients.
    """

    BASE_PORT = 26760
    MAX_PORT_ATTEMPTS = 5

    def __init__(self):
        self._server_id = int(time.time()) & 0xFFFFFFFF
        self._sock: Optional[socket.socket] = None
        self._port: int = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

        # Per-slot state: up to 4 controllers
        self._slot_connected = [False] * 4
        self._slot_packet_counter = [0] * 4

        # Per-slot pad data buffers (pre-allocated for hot path)
        # Each buffer holds the full controller state for one slot
        self._slot_states = [self._make_empty_state() for _ in range(4)]

        # Subscribed clients: set of (addr, port) tuples with expiry
        self._subscribers: dict[tuple, float] = {}
        self._sub_lock = threading.Lock()

        # Per-slot rumble callbacks
        self._rumble_callbacks: list[Optional[Callable]] = [None] * 4

    @staticmethod
    def _make_empty_state() -> dict:
        """Create a neutral controller state dict."""
        return {
            'buttons1': 0,
            'buttons2': 0,
            'ps_button': 0,
            'touch_button': 0,
            'lx': 128,
            'ly': 128,
            'rx': 128,
            'ry': 128,
            'dpad_left': 0,
            'dpad_down': 0,
            'dpad_right': 0,
            'dpad_up': 0,
            'square': 0,
            'cross': 0,
            'circle': 0,
            'triangle': 0,
            'r1': 0,
            'l1': 0,
            'r2': 0,
            'l2': 0,
            'l_trigger': 0,
            'r_trigger': 0,
        }

    @property
    def port(self) -> int:
        return self._port

    def start(self) -> None:
        """Bind the UDP socket and start the listener thread."""
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        for offset in range(self.MAX_PORT_ATTEMPTS):
            port = self.BASE_PORT + offset
            try:
                self._sock.bind(('127.0.0.1', port))
                self._port = port
                break
            except OSError:
                continue
        else:
            raise RuntimeError(
                f"Could not bind DSU server to any port in range "
                f"{self.BASE_PORT}-{self.BASE_PORT + self.MAX_PORT_ATTEMPTS - 1}")

        self._sock.settimeout(0.5)
        self._running = True
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()
        print(f"DSU server listening on 127.0.0.1:{self._port}")

    def stop(self) -> None:
        """Stop the listener thread and close the socket."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None
        print("DSU server stopped.")

    def set_slot_connected(self, slot: int, connected: bool) -> None:
        """Mark a slot as connected/disconnected."""
        self._slot_connected[slot] = connected
        if not connected:
            self._slot_states[slot] = self._make_empty_state()
            self._slot_packet_counter[slot] = 0

    def set_rumble_callback(self, slot: int, callback: Optional[Callable]) -> None:
        """Register a rumble callback for a slot."""
        self._rumble_callbacks[slot] = callback

    def update_slot(self, slot: int, state: dict) -> None:
        """Push new controller state for a slot and send to all subscribers."""
        self._slot_states[slot] = state
        self._slot_packet_counter[slot] += 1
        self._send_data_to_subscribers(slot)

    def _listen_loop(self) -> None:
        """Main listener loop — handles incoming DSU client requests."""
        seen_clients: set[tuple] = set()

        while self._running:
            try:
                data, addr = self._sock.recvfrom(1024)
            except socket.timeout:
                continue
            except OSError:
                if self._running:
                    continue
                break

            if len(data) < HEADER_SIZE:
                continue
            magic = data[0:4]
            if magic != DSUC_MAGIC:
                continue

            if addr not in seen_clients:
                seen_clients.add(addr)
                print(f"DSU: client connected from {addr[0]}:{addr[1]}")

            msg_type = struct.unpack_from('<I', data, 16)[0] if len(data) > 16 else 0

            if msg_type == MSG_TYPE_REQ_VERSION:
                resp = _build_version_response(self._server_id)
                self._sock.sendto(resp, addr)

            elif msg_type == MSG_TYPE_REQ_PORTS:
                self._handle_port_request(data, addr)

            elif msg_type == MSG_TYPE_REQ_DATA:
                self._handle_data_request(data, addr)

    def _handle_port_request(self, data: bytes, addr: tuple) -> None:
        """Respond to a port/controller info request."""
        if len(data) < 24:
            return
        num_pads = struct.unpack_from('<I', data, 20)[0]
        for i in range(min(num_pads, 4)):
            if 24 + i < len(data):
                slot = data[24 + i]
                if 0 <= slot < 4:
                    resp = _build_port_info(
                        self._server_id, slot, self._slot_connected[slot])
                    self._sock.sendto(resp, addr)

    def _handle_data_request(self, data: bytes, addr: tuple) -> None:
        """Register a client subscription for pad data."""
        with self._sub_lock:
            # Subscriptions expire after 5 seconds if not renewed
            self._subscribers[addr] = time.monotonic() + 5.0

    def _send_data_to_subscribers(self, slot: int) -> None:
        """Build and send a pad data packet to all active subscribers."""
        if not self._sock:
            return

        now = time.monotonic()
        # Build packet once, send to all subscribers
        packet = self._build_data_packet(slot)

        with self._sub_lock:
            # Prune expired subscribers and send to active ones
            expired = [addr for addr, exp in self._subscribers.items() if exp < now]
            for addr in expired:
                del self._subscribers[addr]

            for addr in self._subscribers:
                try:
                    self._sock.sendto(packet, addr)
                except OSError:
                    pass

    def _build_data_packet(self, slot: int) -> bytearray:
        """Build a full pad data response packet for a slot (100 bytes total).

        Payload layout (84 bytes, offsets relative to payload start):
          0- 3: Message type (uint32)
          4-14: Shared response (slot, state, model, conn_type, MAC[6], battery)
            15: Connected/active flag
         16-19: Packet number (uint32)
            20: Buttons byte 1 (Share, L3, R3, Options, DPad)
            21: Buttons byte 2 (face buttons, shoulders)
            22: PS button
            23: Touch button
         24-27: Sticks (LX, LY, RX, RY) as 0-255
         28-39: Analog button pressure (12 bytes)
         40-51: Touch data (2x 6-byte touch points)
         52-59: Motion timestamp (uint64, microseconds)
         60-71: Accelerometer XYZ (3x float32)
         72-83: Gyroscope pitch/yaw/roll (3x float32)
        """
        state = self._slot_states[slot]
        connected = self._slot_connected[slot]

        payload = bytearray(84)

        # Message type
        struct.pack_into('<I', payload, 0, MSG_TYPE_DATA)

        # Controller info (shared response)
        payload[4] = slot & 0xFF  # pad id
        payload[5] = 0x02 if connected else 0x00  # state
        payload[6] = MODEL_DS4  # model
        payload[7] = CONN_TYPE_USB  # connection type
        # MAC (6 bytes) — slot-based fake MAC
        payload[13] = slot & 0xFF
        payload[14] = BATTERY_FULL
        payload[15] = 0x01 if connected else 0x00  # is connected (active)

        # Packet number
        struct.pack_into('<I', payload, 16, self._slot_packet_counter[slot])

        # Buttons byte 0: Share(0), L3(1), R3(2), Options(3),
        #                  DPadUp(4), DPadRight(5), DPadDown(6), DPadLeft(7)
        payload[20] = state['buttons1']

        # Buttons byte 1 bits: L2(0), R2(1), L1(2), R1(3),
        #                       Triangle(4), Circle(5), Cross(6), Square(7)
        payload[21] = state['buttons2']

        # PS / Touch buttons
        payload[22] = state['ps_button']
        payload[23] = state['touch_button']

        # Sticks
        payload[24] = state['lx'] & 0xFF
        payload[25] = state['ly'] & 0xFF
        payload[26] = state['rx'] & 0xFF
        payload[27] = state['ry'] & 0xFF

        # Analog button pressure (DPad + face buttons as 0 or 255)
        payload[28] = state['dpad_left']
        payload[29] = state['dpad_down']
        payload[30] = state['dpad_right']
        payload[31] = state['dpad_up']
        payload[32] = state['square']
        payload[33] = state['cross']
        payload[34] = state['circle']
        payload[35] = state['triangle']
        payload[36] = state['r1']
        payload[37] = state['l1']

        # Analog triggers
        payload[38] = state['r_trigger'] & 0xFF
        payload[39] = state['l_trigger'] & 0xFF

        # Touch data (bytes 40-51) — zeroed, not applicable for GC

        # Motion timestamp (microseconds) at offset 52
        struct.pack_into('<Q', payload, 52, int(time.time() * 1_000_000))

        # Accelerometer / Gyroscope (bytes 60-83) — zeroed, not applicable for GC

        header = _build_header(MSG_TYPE_DATA, len(payload), self._server_id)
        packet = header + payload
        _finalize_crc(packet)
        return packet


# ── DSUGamepad (VirtualGamepad) ─────────────────────────────────────

# Button mapping: GamepadButton → (state_key, bit_position_or_pressure_key)
# DSU buttons byte 0 bits: Share(0), L3(1), R3(2), Options(3),
#                           DPadUp(4), DPadRight(5), DPadDown(6), DPadLeft(7)
# DSU buttons byte 1 bits: L2(0), R2(1), L1(2), R1(3),
#                           Triangle(4), Circle(5), Cross(6), Square(7)
# DSU byte 2 bits: PS(0), Touch(1)

_BUTTON_ACTIONS: dict[GamepadButton, list[tuple[str, int, Optional[str]]]] = {
    # (state_dict_key, bit_value, optional_pressure_key)
    # Byte 0 buttons
    GamepadButton.BACK:           [('buttons1', 1 << 0, None)],        # Share
    GamepadButton.START:          [('buttons1', 1 << 3, None)],        # Options
    GamepadButton.DPAD_UP:        [('buttons1', 1 << 4, 'dpad_up')],
    GamepadButton.DPAD_RIGHT:     [('buttons1', 1 << 5, 'dpad_right')],
    GamepadButton.DPAD_DOWN:      [('buttons1', 1 << 6, 'dpad_down')],
    GamepadButton.DPAD_LEFT:      [('buttons1', 1 << 7, 'dpad_left')],
    # Byte 1 buttons
    GamepadButton.LEFT_SHOULDER:  [('buttons2', 1 << 2, 'l1')],       # L1
    GamepadButton.RIGHT_SHOULDER: [('buttons2', 1 << 3, 'r1')],       # R1
    GamepadButton.Y:              [('buttons2', 1 << 4, 'triangle')],  # Triangle
    GamepadButton.B:              [('buttons2', 1 << 5, 'circle')],    # Circle
    GamepadButton.A:              [('buttons2', 1 << 6, 'cross')],     # Cross
    GamepadButton.X:              [('buttons2', 1 << 7, 'square')],    # Square
    # Byte 2
    GamepadButton.GUIDE:          [('ps_button', 1 << 0, None)],       # PS
    # Unused on GC but defined for completeness
    GamepadButton.LEFT_THUMB:     [('buttons1', 1 << 1, None)],        # L3
    GamepadButton.RIGHT_THUMB:    [('buttons1', 1 << 2, None)],        # R3
}


class DSUGamepad(VirtualGamepad):
    """Per-slot virtual gamepad that streams state via the shared DSU server."""

    def __init__(self, slot_index: int = 0):
        self._slot = slot_index
        self._server = _acquire_server()
        self._server.set_slot_connected(self._slot, True)
        self._state = DSUServer._make_empty_state()
        self._rumble_callback: Optional[Callable] = None
        self._closed = False

    @property
    def port(self) -> int:
        """The UDP port the DSU server is listening on."""
        return self._server.port

    def left_joystick(self, x_value: int, y_value: int) -> None:
        # Convert [-32767, 32767] → [0, 255] centered at 128
        self._state['lx'] = max(0, min(255, (x_value + 32767) * 255 // 65534))
        # DSU Y axis: positive = down, our input: positive = up → invert
        self._state['ly'] = max(0, min(255, (-y_value + 32767) * 255 // 65534))

    def right_joystick(self, x_value: int, y_value: int) -> None:
        self._state['rx'] = max(0, min(255, (x_value + 32767) * 255 // 65534))
        self._state['ry'] = max(0, min(255, (-y_value + 32767) * 255 // 65534))

    def left_trigger(self, value: int) -> None:
        self._state['l_trigger'] = max(0, min(255, value))

    def right_trigger(self, value: int) -> None:
        self._state['r_trigger'] = max(0, min(255, value))

    def press_button(self, button: GamepadButton) -> None:
        actions = _BUTTON_ACTIONS.get(button)
        if not actions:
            return
        for key, bit, pressure_key in actions:
            self._state[key] |= bit
            if pressure_key:
                self._state[pressure_key] = 255

    def release_button(self, button: GamepadButton) -> None:
        actions = _BUTTON_ACTIONS.get(button)
        if not actions:
            return
        for key, bit, pressure_key in actions:
            self._state[key] &= ~bit
            if pressure_key:
                self._state[pressure_key] = 0

    def update(self) -> None:
        if not self._closed:
            self._server.update_slot(self._slot, self._state)

    def reset(self) -> None:
        self._state = DSUServer._make_empty_state()
        if not self._closed:
            self._server.update_slot(self._slot, self._state)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._server.set_slot_connected(self._slot, False)
        self._server.set_rumble_callback(self._slot, None)
        _release_server()

    def set_rumble_callback(self, callback) -> None:
        self._rumble_callback = callback
        self._server.set_rumble_callback(self._slot, callback)

    def stop_rumble_listener(self) -> None:
        if self._server:
            self._server.set_rumble_callback(self._slot, None)
