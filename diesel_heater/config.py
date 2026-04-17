"""
Configuration loader for diesel_heater.

Reads from /etc/diesel_heater/config.toml (system) or
~/.config/diesel_heater/config.toml (user), with the user file
taking precedence.

Example config.toml:
    [rf]
    gpio_pin    = 17
    protocol    = 1
    pulselength = 350
    code_length = 24
    code_on     = 123456   # <-- Replace with YOUR remote's ON code
    code_off    = 123457   # <-- Replace with YOUR remote's OFF code
    repeat_tx   = 10

    [schedule]
    delay_min   = 0
    run_for_min = 180      # 3 hours
"""

import os
import logging
from pathlib import Path
from typing import Any, Dict

logger = logging.getLogger(__name__)

# Try tomllib (Python 3.11+) then tomli (backport)
try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib  # type: ignore
    except ImportError:
        tomllib = None  # type: ignore

_DEFAULTS: Dict[str, Any] = {
    "rf": {
        "gpio_pin":          17,
        "code_on":           76300408,   # 0x485d478
        "code_off":          76301496,   # 0x485d4b8
        "code_up":           76301544,   # 0x485d4e8
        "code_down":         76301528,   # 0x485d4d8
        "hold_on_seconds":   2.5,
        "hold_off_seconds":  2.5,
        "hold_adj_seconds":  0.5,
        "short_us":          390,
        "long_us":           1220,
        "gap_us":            435,
        "lgap_us":           1252,
        "reset_us":          12300,
        "bit_length":        25,
    },
    "schedule": {
        "delay_min": 0,
        "run_for_min": None,
    },
}

_SEARCH_PATHS = [
    Path("/etc/diesel_heater/config.toml"),
    Path.home() / ".config" / "diesel_heater" / "config.toml",
]


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for key, val in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(val, dict):
            result[key] = _deep_merge(result[key], val)
        else:
            result[key] = val
    return result


def load_config(path: str = None) -> Dict[str, Any]:
    """
    Load configuration. If path is given, only that file is read.
    Otherwise, searches default locations.
    """
    config = _DEFAULTS.copy()
    config["rf"] = dict(_DEFAULTS["rf"])
    config["schedule"] = dict(_DEFAULTS["schedule"])

    if tomllib is None:
        logger.warning(
            "No TOML library found. Install 'tomli' on Python < 3.11: pip install tomli. "
            "Using built-in defaults only."
        )
        return config

    search = [Path(path)] if path else _SEARCH_PATHS
    loaded_any = False
    for p in search:
        if p.exists():
            try:
                with open(p, "rb") as f:
                    file_config = tomllib.load(f)
                config = _deep_merge(config, file_config)
                logger.info(f"Loaded config from {p}")
                loaded_any = True
            except Exception as e:
                logger.warning(f"Failed to read config {p}: {e}")

    if not loaded_any:
        logger.info("No config file found. Using defaults. RF codes are NOT set — update config!")

    return config


def config_to_controller_kwargs(config: Dict[str, Any]) -> Dict[str, Any]:
    rf = config.get("rf", {})
    return {
        "gpio_pin":          rf.get("gpio_pin",          17),
        "code_on":           rf.get("code_on",           76300408),
        "code_off":          rf.get("code_off",          76301496),
        "code_up":           rf.get("code_up",           76301544),
        "code_down":         rf.get("code_down",         76301528),
        "hold_on_seconds":   rf.get("hold_on_seconds",   2.5),
        "hold_off_seconds":  rf.get("hold_off_seconds",  2.5),
        "hold_adj_seconds":  rf.get("hold_adj_seconds",  0.5),
        "short_us":          rf.get("short_us",          390),
        "long_us":           rf.get("long_us",           1220),
        "gap_us":            rf.get("gap_us",            435),
        "lgap_us":           rf.get("lgap_us",           1252),
        "reset_us":          rf.get("reset_us",          12300),
        "bit_length":        rf.get("bit_length",        25),
    }
