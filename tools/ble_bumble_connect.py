#!/usr/bin/env python3
"""
Connect to NSO GameCube Controller via BLE using Google Bumble.

Uses the correct Switch 2 BLE protocol discovered from BlueRetro (darthcloud)
and ndeadly's switch2_input_viewer.py. The SW2 protocol differs from the
original Switch Pro Controller protocol used by NS2-Connect.py.

Key protocol differences from NS2-Connect.py:
  - Commands go to handle 0x0014 (not 0x002A)
  - Command format: [cmd] 0x91 0x01 [subcmd] 0x00 [len] 0x00 0x00 [data...]
  - Must write 0x0100 to handle 0x0005 to enable proprietary service
  - Must send feature enable command (0x0C) before notifications work
  - Proprietary 4-step pairing handshake (cmd 0x15), NOT standard SMP

Prerequisites:
  sudo systemctl stop bluetooth.service
  sudo hciconfig hci0 down

Run:
  sudo tools/bumble_venv/bin/python tools/ble_bumble_connect.py

Flags:
  --debug       Full HCI-level debug logging
  --verbose     Info-level logging
  --scan        Scan only, don't connect
  --no-scan     Skip scan, connect directly
  --no-pair     Skip proprietary pairing handshake
  --no-smp      Skip SMP pairing (default: SMP runs immediately after connect)
  --no-encrypt  Skip LE encryption after pairing (for testing)
"""

import asyncio
import logging
import signal
import struct
import sys
import time

from bumble.core import UUID, ProtocolError
from bumble.device import Device, Peer, ConnectionParametersPreferences
from bumble.gatt import Characteristic
from bumble.hci import Address, HCI_LE_1M_PHY, HCI_LE_Enable_Encryption_Command
from bumble.keys import PairingKeys
from bumble.pairing import PairingConfig, PairingDelegate
from bumble.transport import open_transport
from bumble import smp

# --- Configuration ---
CONTROLLER_MAC = "3C:A9:AB:60:24:BF"
ADAPTER_INDEX = 0  # hci0 (Realtek)
TRANSPORT = f"hci-socket:{ADAPTER_INDEX}"

# --- SW2 BLE Protocol Constants ---
# Fixed ATT handles (from BlueRetro sw2.h and ndeadly's script)
H_SVC1_ENABLE    = 0x0005  # Service 1 Write char — write 0x0100 to enable
H_INPUT_REPORT   = 0x000A  # Input report (Notify) — buttons, sticks, triggers
H_INPUT_CCCD     = 0x000B  # CCCD for input report
H_INPUT_RATE     = 0x000D  # Report rate descriptor (input handle + 3)
H_INPUT2         = 0x000E  # Input report type 2 (compact)
H_VIBRATION      = 0x0012  # Vibration/rumble output
H_CMD_WRITE      = 0x0014  # Command channel (WriteNoResp)
H_CMD_RUMBLE     = 0x0016  # Command + rumble prefix channel
H_CMD_RESPONSE   = 0x001A  # Command response/ACK (Notify)
H_CMD_RESP_CCCD  = 0x001B  # CCCD for command response
H_OUTPUT_LEGACY  = 0x002A  # Legacy output char (NS2-Connect.py uses this)

# SW2 Command IDs
CMD_SPI_READ     = 0x02
CMD_SET_LED      = 0x09
CMD_FEATURE_CTRL = 0x0C
CMD_FW_VERSION   = 0x10
CMD_PAIRING      = 0x15

# SW2 Command format constants
REQ_TYPE         = 0x91  # Request
IFACE_BLE        = 0x01  # BLE interface

# Feature flags for cmd 0x0C
FEAT_BUTTONS     = 0x01
FEAT_STICKS      = 0x02
FEAT_IMU         = 0x04
FEAT_MOUSE       = 0x10
FEAT_CURRENT     = 0x20
FEAT_MAGNETO     = 0x80

# SPI addresses
SPI_DEVICE_INFO  = (0x00, 0x30, 0x01, 0x00)  # 0x00013000
SPI_PAIRING_DATA = (0x00, 0xA0, 0x1F, 0x00)  # 0x001FA000 (full 64-byte pairing block)
SPI_LTK          = (0x1A, 0xA0, 0x1F, 0x00)  # 0x001FA01A
SPI_CAL_LEFT     = (0x80, 0x30, 0x01, 0x00)  # 0x00013080
SPI_CAL_RIGHT    = (0xC0, 0x30, 0x01, 0x00)  # 0x000130C0
SPI_CAL_USER     = (0x40, 0xC0, 0x1F, 0x00)  # 0x001FC040
SPI_CAL_TRIGGER  = (0x40, 0x31, 0x01, 0x00)  # 0x00013140

# LED map
LED_MAP = [0x01, 0x03, 0x05, 0x06, 0x07, 0x09, 0x0A, 0x0B]

# --- Globals ---
notification_count = 0
notification_sources = {}
cmd_responses = asyncio.Queue()
start_time = None


def build_cmd(cmd_id, subcmd, data=b''):
    """Build a SW2 BLE command packet."""
    data_len = len(data)
    pkt = bytearray([
        cmd_id, REQ_TYPE, IFACE_BLE, subcmd,
        0x00, data_len + 1, 0x00, 0x00,  # +1 for the data_len field itself?
    ])
    # Actually, looking at BlueRetro more carefully, the length field varies.
    # Let me match the exact formats from the research.
    return bytes(pkt) + bytes(data)


def build_spi_read(addr_bytes, size):
    """Build SPI flash read command."""
    return bytes([
        CMD_SPI_READ, REQ_TYPE, IFACE_BLE, 0x04,
        0x00, 0x08, 0x00, 0x00,
        size, 0x7E, 0x00, 0x00,
        addr_bytes[0], addr_bytes[1], addr_bytes[2], addr_bytes[3],
    ])


def build_led_cmd(led_mask):
    """Build LED command."""
    return bytes([
        CMD_SET_LED, REQ_TYPE, IFACE_BLE, 0x07,
        0x00, 0x08, 0x00, 0x00,
        led_mask, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ])


def build_feature_configure(flags):
    """Build feature configure command (declare available features)."""
    return bytes([
        CMD_FEATURE_CTRL, REQ_TYPE, IFACE_BLE, 0x02,
        0x00, 0x04, 0x00, 0x00,
        flags, 0x00, 0x00, 0x00,
    ])


def build_feature_enable(flags):
    """Build feature enable command (activate features)."""
    return bytes([
        CMD_FEATURE_CTRL, REQ_TYPE, IFACE_BLE, 0x04,
        0x00, 0x04, 0x00, 0x00,
        flags, 0x00, 0x00, 0x00,
    ])


def build_pair_step1(local_addr_bytes):
    """Build pairing step 1: send local BLE address to controller."""
    addr = bytes(local_addr_bytes)
    # "address minus 1" — decrement the last byte
    addr_m1 = bytearray(addr)
    addr_m1[5] = (addr_m1[5] - 1) & 0xFF
    return bytes([
        CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x01,
        0x00, 0x0E, 0x00, 0x00, 0x00, 0x02,
    ]) + addr + bytes(addr_m1)


# Pairing steps 2-4 use fixed cryptographic values from BlueRetro
PAIR_STEP2 = bytes([
    CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x04,
    0x00, 0x11, 0x00, 0x00, 0x00,
    0xEA, 0xBD, 0x47, 0x13, 0x89, 0x35, 0x42,
    0xC6, 0x79, 0xEE, 0x07, 0xF2, 0x53, 0x2C, 0x6C, 0x31,
])

PAIR_STEP3 = bytes([
    CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x02,
    0x00, 0x11, 0x00, 0x00, 0x00,
    0x40, 0xB0, 0x8A, 0x5F, 0xCD, 0x1F, 0x9B,
    0x41, 0x12, 0x5C, 0xAC, 0xC6, 0x3F, 0x38, 0xA0, 0x73,
])

PAIR_STEP4 = bytes([
    CMD_PAIRING, REQ_TYPE, IFACE_BLE, 0x03,
    0x00, 0x01, 0x00, 0x00, 0x00,
])


def on_input_notification(value: bytes):
    """Handle input report notification from handle 0x000A."""
    global notification_count
    notification_count += 1
    notification_sources[H_INPUT_REPORT] = notification_sources.get(H_INPUT_REPORT, 0) + 1
    elapsed = time.time() - start_time

    if len(value) >= 16:
        buttons = struct.unpack_from("<I", value, 4)[0]
        lx = value[10] | ((value[11] & 0x0F) << 8)
        ly = (value[11] >> 4) | (value[12] << 4)
        rx = value[13] | ((value[14] & 0x0F) << 8)
        ry = (value[14] >> 4) | (value[15] << 4)

        lt = value[0x3C] if len(value) > 0x3C else 0
        rt = value[0x3D] if len(value) > 0x3D else 0

        if notification_count % 60 == 1 or notification_count <= 5:
            print(
                f"[{elapsed:6.1f}s] INPUT #{notification_count:5d} "
                f"({len(value)}B) | "
                f"Btn=0x{buttons:08X} "
                f"L=({lx:4d},{ly:4d}) R=({rx:4d},{ry:4d}) "
                f"Trig=({lt:3d},{rt:3d})"
            )
    else:
        print(
            f"[{elapsed:6.1f}s] INPUT #{notification_count} "
            f"({len(value)}B): {value.hex()}"
        )


def on_cmd_response(value: bytes):
    """Handle command response notification from handle 0x001A."""
    elapsed = time.time() - start_time
    notification_sources[H_CMD_RESPONSE] = notification_sources.get(H_CMD_RESPONSE, 0) + 1
    print(
        f"[{elapsed:6.1f}s] CMD_RESP ({len(value)}B): {value.hex()}"
    )
    cmd_responses.put_nowait(value)


def on_other_notification(handle):
    """Create handler for other notification characteristics."""
    def handler(value: bytes):
        global notification_count
        notification_count += 1
        notification_sources[handle] = notification_sources.get(handle, 0) + 1
        elapsed = time.time() - start_time
        print(
            f"[{elapsed:6.1f}s] NOTIFY 0x{handle:04X} "
            f"({len(value)}B): {value.hex()}"
        )
    return handler


async def wait_cmd_response(timeout=3.0):
    """Wait for a command response notification."""
    try:
        return await asyncio.wait_for(cmd_responses.get(), timeout=timeout)
    except asyncio.TimeoutError:
        return None


async def write_handle(peer, handle, data, with_response=False):
    """Write to a specific ATT handle."""
    try:
        await peer.gatt_client.write_value(
            attribute=handle,
            value=data,
            with_response=with_response,
        )
        return True
    except Exception as e:
        print(f"  Write to 0x{handle:04X} failed: {e}")
        return False


async def scan_for_controller(device, timeout=10.0):
    """Scan for the NSO GC controller."""
    print(f"\nScanning for controller {CONTROLLER_MAC} (timeout {timeout}s)...")
    found = asyncio.Event()

    def on_advertisement(advertisement):
        addr = str(advertisement.address).upper()
        if CONTROLLER_MAC in addr:
            print(f"  Found! RSSI={advertisement.rssi}")
            print(f"  Addr: {advertisement.address}")
            print(f"  Data: {advertisement.data}")
            found.set()

    device.on("advertisement", on_advertisement)
    await device.start_scanning(filter_duplicates=False)

    try:
        await asyncio.wait_for(found.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        print(f"  Not found — press SYNC on controller and retry")
        return False
    finally:
        await device.stop_scanning()


async def main():
    global start_time

    log_level = logging.WARNING
    if "--debug" in sys.argv:
        log_level = logging.DEBUG
    elif "--verbose" in sys.argv:
        log_level = logging.INFO
    logging.basicConfig(level=log_level)

    scan_only = "--scan" in sys.argv
    skip_scan = "--no-scan" in sys.argv
    skip_pair = "--no-pair" in sys.argv
    skip_smp = "--no-smp" in sys.argv
    skip_encrypt = "--no-encrypt" in sys.argv

    print("=== NSO GC Controller BLE Connect (Bumble + SW2 Protocol) ===")
    print(f"Transport: {TRANSPORT}")
    print(f"Target:    {CONTROLLER_MAC}")
    print()

    async with await open_transport(TRANSPORT) as (hci_source, hci_sink):
        device = Device.with_hci(
            "Bumble-GC",
            Address("F0:F1:F2:F3:F4:F5"),
            hci_source,
            hci_sink,
        )

        # Configure for Legacy SMP to match BlueRetro's exact parameters:
        #   io=NO_INPUT_OUTPUT, oob=0, auth_req=BONDING(0x01), max_key=16
        #   init_key_dist=ID_KEY(0x02), resp_key_dist=ENC_KEY(0x01)
        # Bumble's defaults are init=0x03, resp=0x03 which the controller rejects!
        device.pairing_config_factory = lambda connection: PairingConfig(
            sc=False,          # Legacy pairing — SW2 controllers reject SC
            mitm=False,        # Just Works
            bonding=True,
            delegate=PairingDelegate(
                io_capability=PairingDelegate.IoCapability.NO_OUTPUT_NO_INPUT,
                local_initiator_key_distribution=(
                    PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY  # 0x02
                ),
                local_responder_key_distribution=(
                    PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY  # 0x01
                ),
            ),
        )

        await device.power_on()
        print("HCI adapter powered on")

        if not skip_scan:
            if not await scan_for_controller(device):
                return
            if scan_only:
                return

        # --- Connect ---
        print(f"\nConnecting to {CONTROLLER_MAC}...")
        start_time = time.time()

        try:
            connection = await device.connect(
                Address(CONTROLLER_MAC, Address.PUBLIC_DEVICE_ADDRESS),
                connection_parameters_preferences={
                    HCI_LE_1M_PHY: ConnectionParametersPreferences(
                        connection_interval_min=15.0,
                        connection_interval_max=30.0,
                        max_latency=0,
                        supervision_timeout=5000,
                    )
                },
                timeout=15.0,
            )
            print(f"Connected! (handle=0x{connection.handle:04X})")
        except Exception as e:
            print(f"Connection failed: {e}")
            return

        disconnected = asyncio.Event()
        connection.on("disconnection", lambda r: (
            print(f"\n!!! Disconnected: {r} !!!"),
            disconnected.set(),
        ))

        # --- SMP Pairing ---
        # Register event handlers for SMP events (always, so we can see what the
        # controller does during GATT discovery even if we skip our own attempt)
        connection.on("pairing_start",
                      lambda: print("  >> SMP pairing started"))
        connection.on("pairing",
                      lambda k: print(f"  >> SMP pairing SUCCEEDED! encrypted={connection.is_encrypted}"))
        connection.on("pairing_failure",
                      lambda r: print(f"  >> SMP pairing failed: {smp.error_name(r)}"))
        connection.on("connection_encryption_change",
                      lambda: print(f"  >> Encryption changed! encrypted={connection.is_encrypted}"))

        # Handle Security Request from the controller (peripheral-initiated security)
        async def on_security_request(auth_req):
            elapsed = time.time() - start_time
            print(f"\n[{elapsed:6.1f}s] >> Controller sent Security Request! auth_req={auth_req:#x}")
            print(f"         Responding by initiating pairing...")
            try:
                await connection.pair()
                print(f"         Pairing OK! encrypted={connection.is_encrypted}")
            except Exception as e:
                print(f"         Pairing failed: {e}")

        connection.on("security_request",
                      lambda auth_req: asyncio.ensure_future(on_security_request(auth_req)))

        smp_succeeded = False
        if not skip_smp:
            print("\n--- SMP Legacy \"Just Works\" Pairing ---")
            print("  (BlueRetro does this immediately after connect, before GATT)")
            try:
                await connection.pair()
                smp_succeeded = True
                print(f"  SMP pairing OK! Encrypted: {connection.is_encrypted}")
            except Exception as e:
                print(f"  SMP pairing failed: {e}")
                print("  Continuing without encryption (will try proprietary pairing)")
                if disconnected.is_set():
                    return
        else:
            print("\n--- Skipping SMP (--no-smp) ---")
            print("  (Will respond to controller-initiated security requests)")

        if disconnected.is_set():
            return

        # --- MTU Exchange ---
        # BlueRetro does MTU exchange immediately after encryption, before GATT.
        # SW2 input reports are 63 bytes; default MTU 23 means max 20-byte payload.
        # Without a larger MTU, the controller may silently drop notifications.
        print("\n--- MTU Exchange ---")
        peer = Peer(connection)
        try:
            mtu = await peer.request_mtu(512)
            print(f"  MTU negotiated: {mtu}")
        except Exception as e:
            print(f"  MTU exchange failed: {e} (continuing with default)")

        if disconnected.is_set():
            return

        # --- GATT Discovery ---
        print("\nDiscovering GATT services...")
        await peer.discover_services()

        for service in peer.services:
            await service.discover_characteristics()
            print(f"  Service: {service.uuid} "
                  f"(0x{service.handle:04X}-0x{service.end_group_handle:04X})")
            for char in service.characteristics:
                await char.discover_descriptors()

        if disconnected.is_set():
            return

        # =============================================================
        # SW2 BLE INITIALIZATION SEQUENCE
        # (from BlueRetro sw2.c and ndeadly's switch2_input_viewer.py)
        # =============================================================

        print("\n" + "=" * 60)
        print("SW2 BLE Initialization Sequence")
        print("=" * 60)

        # --- Step 1: Enable proprietary service ---
        print("\n[Step 1] Write 0x0100 to handle 0x0005 (enable service)...")
        await write_handle(peer, H_SVC1_ENABLE, bytes([0x01, 0x00]), with_response=True)

        if disconnected.is_set():
            return
        await asyncio.sleep(0.2)

        # --- Step 2: Enable command response notifications ---
        print("[Step 2] Enable cmd response notifications (CCCD 0x001B)...")
        await write_handle(peer, H_CMD_RESP_CCCD, bytes([0x01, 0x00]), with_response=True)

        # Register notification handler for command responses
        # Find the characteristic at handle 0x001A and subscribe
        for service in peer.services:
            for char in service.characteristics:
                if char.handle == H_CMD_RESPONSE:
                    try:
                        await char.subscribe(subscriber=on_cmd_response)
                        print("  Subscribed to cmd responses (0x001A)")
                    except Exception as e:
                        print(f"  Subscribe failed: {e}")

        if disconnected.is_set():
            return
        await asyncio.sleep(0.2)

        # --- Step 3: Read device info ---
        print("[Step 3] Read device info (SPI 0x00013000, 0x40 bytes)...")
        cmd = build_spi_read(SPI_DEVICE_INFO, 0x40)
        print(f"  CMD: {cmd.hex()}")
        await write_handle(peer, H_CMD_WRITE, cmd)
        resp = await wait_cmd_response(timeout=3.0)
        if resp:
            print(f"  Got device info response!")
        else:
            print(f"  No response (timeout)")

        if disconnected.is_set():
            return

        # --- Step 4: Proprietary pairing handshake ---
        if not skip_pair:
            print("\n[Step 4] Proprietary pairing handshake (cmd 0x15)...")

            # Get our local BLE address
            local_addr = device.public_address
            if local_addr:
                addr_bytes = bytes(local_addr)
            else:
                # Use the random address we set
                addr_bytes = bytes([0xF5, 0xF4, 0xF3, 0xF2, 0xF1, 0xF0])
            print(f"  Local address: {addr_bytes.hex()}")

            # Step 4a: Send local BLE address
            print("  [4a] Sending local address...")
            pair1 = build_pair_step1(addr_bytes)
            print(f"       CMD: {pair1.hex()}")
            await write_handle(peer, H_CMD_WRITE, pair1)
            resp = await wait_cmd_response(timeout=3.0)
            if resp:
                print(f"       Response: {resp.hex()}")
            else:
                print(f"       No response (timeout)")

            if disconnected.is_set():
                return

            # Step 4b: Send crypto challenge
            print("  [4b] Sending crypto challenge...")
            print(f"       CMD: {PAIR_STEP2.hex()}")
            await write_handle(peer, H_CMD_WRITE, PAIR_STEP2)
            resp = await wait_cmd_response(timeout=3.0)
            if resp:
                print(f"       Response: {resp.hex()}")
            else:
                print(f"       No response (timeout)")

            if disconnected.is_set():
                return

            # Step 4c: Send second crypto value
            print("  [4c] Sending second crypto value...")
            print(f"       CMD: {PAIR_STEP3.hex()}")
            await write_handle(peer, H_CMD_WRITE, PAIR_STEP3)
            resp = await wait_cmd_response(timeout=3.0)
            if resp:
                print(f"       Response: {resp.hex()}")
            else:
                print(f"       No response (timeout)")

            if disconnected.is_set():
                return

            # Step 4d: Finalize pairing
            print("  [4d] Finalizing pairing...")
            print(f"       CMD: {PAIR_STEP4.hex()}")
            await write_handle(peer, H_CMD_WRITE, PAIR_STEP4)
            resp = await wait_cmd_response(timeout=3.0)
            if resp:
                print(f"       Response: {resp.hex()}")
            else:
                print(f"       No response (timeout)")

            if disconnected.is_set():
                return

            # Step 4e: Read FULL pairing data block (64 bytes at 0x1FA000)
            # Layout (from ndeadly's research):
            #   0x00-0x07: Unknown/flags
            #   0x08-0x0D: Host BT address #1 (6 bytes)
            #   0x0E-0x19: Unknown — may contain EDIV (2B) + Rand (8B) + padding
            #   0x1A-0x29: LTK (16 bytes)
            #   0x2A-0x2F: Unknown
            #   0x30-0x35: Host BT address #2 (6 bytes)
            #   0x36-0x3F: Unknown
            print("  [4e] Reading full pairing data from SPI (0x1FA000, 64B)...")
            cmd = build_spi_read(SPI_PAIRING_DATA, 0x40)
            print(f"       CMD: {cmd.hex()}")
            await write_handle(peer, H_CMD_WRITE, cmd)
            resp = await wait_cmd_response(timeout=3.0)
            ltk_bytes = None
            ediv_value = 0
            rand_bytes = bytes(8)
            if resp:
                print(f"       Full response ({len(resp)}B): {resp.hex()}")
                # Response header: [cmd 1B] [status 3B] [flags 4B] [size 1B] [pad 3B] [addr 4B]
                # = 16 bytes of header, then the actual SPI flash data
                if len(resp) >= 16 + 0x30:
                    spi = resp[16:]  # SPI flash data (skip 16-byte header)
                    print(f"       SPI data ({len(spi)}B): {spi.hex()}")
                    print(f"       Bytes 0x00-0x07 (flags?):    {spi[0x00:0x08].hex()}")
                    host_addr1 = spi[0x08:0x0E]
                    print(f"       Bytes 0x08-0x0D (host addr1): {host_addr1.hex()}"
                          f" ({':'.join(f'{b:02x}' for b in reversed(host_addr1))})")
                    unknown1 = spi[0x0E:0x1A]
                    print(f"       Bytes 0x0E-0x19 (unknown):    {unknown1.hex()}"
                          f" (potential EDIV+Rand?)")
                    ltk_bytes = bytes(spi[0x1A:0x2A])
                    print(f"       Bytes 0x1A-0x29 (LTK):        {ltk_bytes.hex()}")
                    unknown2 = spi[0x2A:0x30]
                    print(f"       Bytes 0x2A-0x2F (unknown):    {unknown2.hex()}")
                    if len(spi) > 0x35:
                        host_addr2 = spi[0x30:0x36]
                        print(f"       Bytes 0x30-0x35 (host addr2): {host_addr2.hex()}"
                              f" ({':'.join(f'{b:02x}' for b in reversed(host_addr2))})")
                    if len(spi) > 0x3F:
                        print(f"       Bytes 0x36-0x3F (unknown):    {spi[0x36:0x40].hex()}")

                    # Try to extract EDIV (2 bytes LE) and Rand (8 bytes) from the unknown region
                    # Hypothesis 1: EDIV at 0x0E, Rand at 0x10
                    ediv_value = struct.unpack_from("<H", unknown1, 0)[0]
                    rand_bytes = bytes(unknown1[2:10])
                    print(f"       Possible EDIV: 0x{ediv_value:04X} ({ediv_value})")
                    print(f"       Possible Rand: {rand_bytes.hex()}")
                elif len(resp) >= 16:
                    # Fallback: just grab last 16 bytes as LTK
                    ltk_bytes = bytes(resp[-16:])
                    print(f"       LTK (fallback): {ltk_bytes.hex()}")
            else:
                print(f"       No response (timeout)")
        else:
            print("\n[Step 4] Skipping pairing (--no-pair)")
            ltk_bytes = None
            ediv_value = 0
            rand_bytes = bytes(8)

        if disconnected.is_set():
            return

        # --- Step 4f: LE Encryption with LTK ---
        # If SMP already established encryption, skip this. Otherwise try the SPI LTK.
        if connection.is_encrypted:
            print("\n[Step 4f] Link already encrypted via SMP — skipping LTK encryption")
        elif ltk_bytes and not skip_encrypt:
            print("\n[Step 4f] Encrypting BLE link with SPI LTK...")
            print(f"  LTK:  {ltk_bytes.hex()}")
            print(f"  EDIV: 0x{ediv_value:04X}")
            print(f"  Rand: {rand_bytes.hex()}")

            # Register encryption change handler
            encryption_done = asyncio.Event()

            def on_enc_change():
                print(f"  >> Encryption changed! encrypted={connection.is_encrypted}")
                encryption_done.set()

            def on_enc_failure(e):
                print(f"  >> Encryption FAILED: {e}")
                encryption_done.set()

            connection.on("connection_encryption_change", on_enc_change)
            connection.on("connection_encryption_failure", on_enc_failure)

            # Try multiple EDIV/Rand/LTK combinations via raw HCI command
            attempts = [
                ("SPI EDIV+Rand", ediv_value, rand_bytes, ltk_bytes),
                ("EDIV=0 Rand=0", 0, bytes(8), ltk_bytes),
                ("Reversed LTK", 0, bytes(8), bytes(reversed(ltk_bytes))),
            ]
            # Only add SPI EDIV+Rand attempt if they're non-zero
            if ediv_value == 0 and rand_bytes == bytes(8):
                attempts = attempts[1:]  # Skip duplicate

            for label, ediv, rand, ltk in attempts:
                if connection.is_encrypted:
                    break
                if disconnected.is_set():
                    break
                print(f"\n  Trying: {label}")
                print(f"    EDIV={ediv:#06x} Rand={rand.hex()} LTK={ltk.hex()}")
                encryption_done.clear()
                try:
                    await device.send_command(
                        HCI_LE_Enable_Encryption_Command(
                            connection_handle=connection.handle,
                            random_number=rand,
                            encrypted_diversifier=ediv,
                            long_term_key=ltk,
                        )
                    )
                    # Wait for encryption result
                    try:
                        await asyncio.wait_for(encryption_done.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        print(f"    Timeout waiting for encryption result")
                except Exception as e:
                    print(f"    HCI command failed: {e}")

                if connection.is_encrypted:
                    print(f"  >>> ENCRYPTION SUCCESS with {label}! <<<")
                    break
                await asyncio.sleep(0.3)

            if not connection.is_encrypted:
                print("\n  All encryption attempts failed. Continuing unencrypted.")

            if disconnected.is_set():
                return
            await asyncio.sleep(0.3)
        elif skip_encrypt:
            print("\n[Step 4f] Skipping encryption (--no-encrypt)")
        elif not ltk_bytes:
            print("\n[Step 4f] No LTK available, skipping encryption")

        if disconnected.is_set():
            return

        # --- Step 5: Set player LED ---
        # (BlueRetro does this after calibration reads, which we skip)
        print("\n[Step 5] Set Player 1 LED...")
        cmd = build_led_cmd(LED_MAP[0])
        print(f"  LED CMD: {cmd.hex()}")
        await write_handle(peer, H_CMD_WRITE, cmd)
        resp = await wait_cmd_response(timeout=2.0)
        if resp:
            print(f"  LED response: {resp.hex()}")

        if disconnected.is_set():
            return
        await asyncio.sleep(0.2)

        # --- Step 6: Enable input + disable cmd response (BlueRetro's EN_REPORT) ---
        # BlueRetro enables input CCCD AND disables cmd response CCCD simultaneously.
        print("[Step 6] Enable input CCCD (0x000B) + disable cmd response CCCD (0x001B)...")

        # Register notification handler for input reports FIRST
        for service in peer.services:
            for char in service.characteristics:
                if char.handle == H_INPUT_REPORT:
                    try:
                        await char.subscribe(subscriber=on_input_notification)
                        print("  Subscribed to input reports (0x000A)")
                    except Exception as e:
                        print(f"  Subscribe failed: {e}")

        # Enable input CCCD
        await write_handle(peer, H_INPUT_CCCD, bytes([0x01, 0x00]), with_response=True)
        print("  Input CCCD enabled (0x000B)")

        # Disable cmd response CCCD (BlueRetro does this!)
        await write_handle(peer, H_CMD_RESP_CCCD, bytes([0x00, 0x00]), with_response=True)
        print("  Cmd response CCCD disabled (0x001B)")

        if disconnected.is_set():
            return

        # Also subscribe to other notify chars for monitoring
        for service in peer.services:
            for char in service.characteristics:
                if (char.properties & Characteristic.Properties.NOTIFY
                        and char.handle not in (H_INPUT_REPORT, H_CMD_RESPONSE)):
                    try:
                        await char.subscribe(subscriber=on_other_notification(char.handle))
                        print(f"  Subscribed: 0x{char.handle:04X}")
                    except Exception as e:
                        print(f"  Failed 0x{char.handle:04X}: {e}")

        # --- Listen ---
        print(f"\n{'=' * 60}")
        print(f"Listening for notifications (Ctrl+C to stop)")
        print(f"  Encrypted: {connection.is_encrypted}")
        print(f"  MTU: {peer.gatt_client.mtu if hasattr(peer, 'gatt_client') else 'unknown'}")
        print(f"{'=' * 60}\n")

        async def status_timer():
            while not disconnected.is_set():
                await asyncio.sleep(5)
                elapsed = time.time() - start_time
                print(
                    f"[{elapsed:6.1f}s] Status: "
                    f"{notification_count} notifications, "
                    f"encrypted={connection.is_encrypted}"
                )
                for h, c in sorted(notification_sources.items()):
                    print(f"         0x{h:04X}: {c}")

        timer = asyncio.ensure_future(status_timer())

        try:
            await disconnected.wait()
        except asyncio.CancelledError:
            pass
        finally:
            timer.cancel()
            try:
                await timer
            except asyncio.CancelledError:
                pass

        elapsed = time.time() - start_time
        print(f"\n=== Session Summary ===")
        print(f"Duration:      {elapsed:.1f}s")
        print(f"Encrypted:     {connection.is_encrypted}")
        print(f"Notifications: {notification_count}")
        for h, c in sorted(notification_sources.items()):
            print(f"  0x{h:04X}: {c}")


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    main_task = loop.create_task(main())

    def signal_handler():
        main_task.cancel()

    loop.add_signal_handler(signal.SIGINT, signal_handler)
    loop.add_signal_handler(signal.SIGTERM, signal_handler)

    try:
        loop.run_until_complete(main_task)
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()
