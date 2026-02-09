"""
Settings Manager

Handles loading and saving calibration settings to a JSON file,
including migration from v1 (single-controller) to v3 (device-based BLE) format.
"""

import json
import os
from typing import List

from .controller_constants import DEFAULT_CALIBRATION, MAX_SLOTS, BLE_DEVICE_CAL_KEYS


# Keys that are global (not per-slot).
_GLOBAL_KEYS = {
    'auto_connect', 'emulation_mode', 'trigger_bump_100_percent',
    'minimize_to_tray', 'known_ble_devices',
}


class SettingsManager:
    """Manages persistent calibration settings for up to 4 controller slots."""

    def __init__(self, slot_calibrations: List[dict], settings_dir: str):
        self._slot_calibrations = slot_calibrations
        self._settings_file = os.path.join(settings_dir, 'gc_controller_settings.json')

    def load(self):
        """Load settings from file. Handles v1, v2, and v3 formats."""
        try:
            if not os.path.exists(self._settings_file):
                return
            with open(self._settings_file, 'r') as f:
                saved = json.load(f)

            version = saved.get('version', 1)
            if version >= 3:
                self._load_v3(saved)
            elif version >= 2:
                self._load_v2(saved)
            else:
                self._load_v1(saved)
        except Exception as e:
            print(f"Failed to load settings: {e}")

    def _load_v1(self, saved: dict):
        """Migrate v1 flat settings into slot 0, defaults for others."""
        # Run key migration for old trigger key names
        key_migration = {
            'left_base': 'trigger_left_base',
            'left_bump': 'trigger_left_bump',
            'left_max': 'trigger_left_max',
            'right_base': 'trigger_right_base',
            'right_bump': 'trigger_right_bump',
            'right_max': 'trigger_right_max',
            'bump_100_percent': 'trigger_bump_100_percent',
        }
        for old_key, new_key in key_migration.items():
            if old_key in saved and new_key not in saved:
                saved[new_key] = saved.pop(old_key)
            elif old_key in saved:
                del saved[old_key]

        # Strip removed keys
        saved.pop('preferred_ble_address', None)
        saved.pop('connection_mode', None)
        saved.pop('known_ble_addresses', None)

        # Apply all v1 data to slot 0
        self._slot_calibrations[0].update(saved)

    def _load_v2(self, saved: dict):
        """Load v2 multi-slot format, migrating to v3 device-based BLE."""
        global_settings = saved.get('global', {})
        slots_data = saved.get('slots', {})

        # Migrate known_ble_addresses → known_ble_devices
        old_known = global_settings.pop('known_ble_addresses', [])
        known_devices = global_settings.get('known_ble_devices', {})

        # Build device entries from per-slot preferred_ble_address + calibration
        for i in range(MAX_SLOTS):
            slot_data = slots_data.get(str(i), {})
            addr = slot_data.pop('preferred_ble_address', '').upper()
            slot_data.pop('connection_mode', None)

            if addr and addr not in known_devices:
                # Migrate per-device calibration keys from the slot
                dev_cal = {}
                for key in BLE_DEVICE_CAL_KEYS:
                    if key in slot_data:
                        dev_cal[key] = slot_data[key]
                known_devices[addr] = dev_cal

        # Also add any addresses from the old known_ble_addresses list
        for addr in old_known:
            addr_upper = addr.upper()
            if addr_upper not in known_devices:
                known_devices[addr_upper] = {}

        global_settings['known_ble_devices'] = known_devices

        for i in range(MAX_SLOTS):
            slot_data = slots_data.get(str(i), {})
            # Strip removed keys
            slot_data.pop('preferred_ble_address', None)
            slot_data.pop('connection_mode', None)
            if i == 0:
                for key in _GLOBAL_KEYS:
                    if key in global_settings:
                        slot_data.setdefault(key, global_settings[key])
            self._slot_calibrations[i].update(slot_data)

        # Ensure global keys are accessible from slot 0
        for key in _GLOBAL_KEYS:
            if key in global_settings:
                self._slot_calibrations[0][key] = global_settings[key]

    def _load_v3(self, saved: dict):
        """Load v3 format with device-based BLE registry."""
        global_settings = saved.get('global', {})
        slots_data = saved.get('slots', {})

        for i in range(MAX_SLOTS):
            slot_data = slots_data.get(str(i), {})
            if i == 0:
                for key in _GLOBAL_KEYS:
                    if key in global_settings:
                        slot_data.setdefault(key, global_settings[key])
            self._slot_calibrations[i].update(slot_data)

        # Ensure global keys are accessible from slot 0
        for key in _GLOBAL_KEYS:
            if key in global_settings:
                self._slot_calibrations[0][key] = global_settings[key]

    def save(self):
        """Write all slot calibrations in v3 format. Raises on failure."""
        global_settings = {}
        slots_data = {}

        for i in range(MAX_SLOTS):
            cal = self._slot_calibrations[i]
            slot_dict = {}
            for key, value in cal.items():
                if key in _GLOBAL_KEYS:
                    # Only read global keys from slot 0
                    if i == 0:
                        global_settings[key] = value
                else:
                    slot_dict[key] = value
            slots_data[str(i)] = slot_dict

        output = {
            'version': 3,
            'global': global_settings,
            'slots': slots_data,
        }

        with open(self._settings_file, 'w') as f:
            json.dump(output, f, indent=2)
