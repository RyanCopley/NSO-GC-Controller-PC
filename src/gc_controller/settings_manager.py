"""
Settings Manager

Handles loading and saving calibration settings to a JSON file,
including migration of old key names.
"""

import json
import os


class SettingsManager:
    """Manages persistent calibration settings."""

    def __init__(self, calibration: dict, settings_dir: str):
        self._calibration = calibration
        self._settings_file = os.path.join(settings_dir, 'gc_controller_settings.json')

    def load(self):
        """Load calibration settings from file, migrating old keys if needed."""
        try:
            if not os.path.exists(self._settings_file):
                return
            with open(self._settings_file, 'r') as f:
                saved_settings = json.load(f)

            # Migrate old key names to new trigger_ prefixed names
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
                if old_key in saved_settings and new_key not in saved_settings:
                    saved_settings[new_key] = saved_settings.pop(old_key)
                elif old_key in saved_settings:
                    del saved_settings[old_key]

            self._calibration.update(saved_settings)
        except Exception as e:
            print(f"Failed to load settings: {e}")

    def save(self):
        """Write calibration dict to JSON. Raises on failure."""
        with open(self._settings_file, 'w') as f:
            json.dump(self._calibration, f, indent=2)
