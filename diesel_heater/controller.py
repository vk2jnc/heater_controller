"""
Diesel Heater 433MHz Controller
Transmits RF codes via GPIO to control Chinese diesel heaters.
Compatible with Pi Zero 2 using rpi-rf.
"""

import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Attempt to import rpi-rf; fall back to a stub for development/testing
try:
    from rpi_rf import RFDevice
    RF_AVAILABLE = True
except ImportError:
    RF_AVAILABLE = False
    logger.warning("rpi-rf not available. Running in simulation mode.")


class RFStub:
    """Stub for testing without hardware."""
    def __init__(self, gpio_pin: int):
        self.gpio_pin = gpio_pin

    def enable_tx(self):
        logger.info(f"[STUB] TX enabled on GPIO {self.gpio_pin}")

    def tx_code(self, code: int, protocol: int, pulselength: int, length: int):
        logger.info(f"[STUB] TX code={code} proto={protocol} pulse={pulselength} len={length}")
        return True

    def cleanup(self):
        logger.info("[STUB] Cleanup")


class HeaterController:
    """
    Controls a Chinese diesel heater via 433MHz RF.

    You must configure this with the RF codes captured from your own remote.
    See README for how to capture your codes using the receiver.

    Args:
        gpio_pin:    BCM GPIO pin connected to the 433MHz TX data pin. Default 17.
        protocol:    rc-switch protocol number (usually 1). Check your capture.
        pulselength: Pulse length in microseconds (commonly 300-500).
        code_length: Bit length of the code (commonly 24).
        code_on:     RF code integer to turn the heater ON.
        code_off:    RF code integer to turn the heater OFF.
        repeat_tx:   How many times to repeat each transmission (default 10).
    """

    def __init__(
        self,
        gpio_pin: int = 17,
        protocol: int = 1,
        pulselength: int = 350,
        code_length: int = 24,
        code_on: int = 0,
        code_off: int = 0,
        repeat_tx: int = 10,
    ):
        self.gpio_pin = gpio_pin
        self.protocol = protocol
        self.pulselength = pulselength
        self.code_length = code_length
        self.code_on = code_on
        self.code_off = code_off
        self.repeat_tx = repeat_tx
        self._rf: Optional[object] = None

    def _get_rf(self):
        if self._rf is None:
            if RF_AVAILABLE:
                self._rf = RFDevice(self.gpio_pin)
            else:
                self._rf = RFStub(self.gpio_pin)
            self._rf.enable_tx()
        return self._rf

    def _send(self, code: int):
        if code == 0:
            raise ValueError(
                "RF code is 0. You must configure code_on / code_off with your remote's codes. "
                "See the README for capture instructions."
            )
        rf = self._get_rf()
        for _ in range(self.repeat_tx):
            rf.tx_code(code, self.protocol, self.pulselength, self.code_length)
            time.sleep(0.02)
        logger.info(f"Sent code {code} ({self.repeat_tx}x)")

    def turn_on(self):
        """Send the ON command."""
        logger.info("Sending heater ON")
        self._send(self.code_on)

    def turn_off(self):
        """Send the OFF command."""
        logger.info("Sending heater OFF")
        self._send(self.code_off)

    def cleanup(self):
        if self._rf is not None:
            self._rf.cleanup()
            self._rf = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
