"""
Connection Manager

Handles USB initialization and HID device connection for the GameCube controller.
"""

import sys
from typing import Optional, Callable

import hid
import usb.core
import usb.util

from .controller_constants import VENDOR_ID, PRODUCT_ID, DEFAULT_REPORT_DATA, SET_LED_DATA

IS_MACOS = sys.platform == "darwin"


class ConnectionManager:
    """Manages USB initialization and HID connection."""

    def __init__(self, on_status: Callable[[str], None], on_progress: Callable[[int], None]):
        self._on_status = on_status
        self._on_progress = on_progress
        self.device: Optional[hid.device] = None

    def initialize_via_usb(self) -> bool:
        """Initialize controller via USB."""
        try:
            self._on_status("Looking for device...")
            self._on_progress(10)

            dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if dev is None:
                self._on_status("Device not found")
                return False

            self._on_status("Device found")
            self._on_progress(30)

            if IS_MACOS:
                try:
                    if dev.is_kernel_driver_active(1):
                        dev.detach_kernel_driver(1)
                except (usb.core.USBError, NotImplementedError):
                    pass

            try:
                dev.set_configuration()
            except usb.core.USBError:
                pass  # May already be configured

            try:
                usb.util.claim_interface(dev, 1)
            except usb.core.USBError:
                pass  # May already be claimed

            self._on_progress(50)

            self._on_status("Sending initialization data...")
            dev.write(0x02, DEFAULT_REPORT_DATA, 2000)

            self._on_progress(70)

            self._on_status("Sending LED data...")
            dev.write(0x02, SET_LED_DATA, 2000)

            self._on_progress(90)

            try:
                usb.util.release_interface(dev, 1)
            except usb.core.USBError:
                pass

            self._on_status("USB initialization complete")
            return True

        except Exception as e:
            self._on_status(f"USB initialization failed: {e}")
            return False

    def init_hid_device(self) -> bool:
        """Initialize HID connection."""
        try:
            self._on_status("Connecting via HID...")

            self.device = hid.device()
            self.device.open(VENDOR_ID, PRODUCT_ID)

            if self.device:
                self._on_status("Connected via HID")
                self._on_progress(100)
                return True
            else:
                self._on_status("Failed to connect via HID")
                return False

        except Exception as e:
            self._on_status(f"HID connection failed: {e}")
            return False

    def connect(self) -> bool:
        """Full connection sequence: USB init then HID."""
        if not self.initialize_via_usb():
            return False
        return self.init_hid_device()

    def disconnect(self):
        """Close and release the HID device."""
        if self.device:
            try:
                self.device.close()
            except Exception:
                pass
            self.device = None
