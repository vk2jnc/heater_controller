"""
Diesel Heater 433MHz Controller
Transmits OOK_PWM RF signals via GPIO to control Chinese diesel heaters.

Uses pigpio for accurate microsecond-level pulse timing, which is required
for the PWM modulation this remote uses.

Captured signal parameters (from rtl_433 -A, House Code: 47010):
    Modulation:  OOK_PWM
    Short pulse: ~390 µs  (bit = 0)
    Long pulse:  ~1220 µs (bit = 1)
    Gap (short): ~435 µs
    Gap (long):  ~1252 µs
    Period:      ~1652 µs
    Reset/inter-burst: ~12300 µs
    Bit length:  25 bits

IMPORTANT: This heater requires the button to be held for ~2-3 seconds
to register ON or OFF. The controller transmits continuously for a
configurable hold_seconds duration to simulate this.
"""

import time
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

try:
    import pigpio
    PIGPIO_AVAILABLE = True
except ImportError:
    PIGPIO_AVAILABLE = False
    logger.warning("pigpio not available. Running in simulation mode.")

# ── Default pulse parameters from rtl_433 capture ───────────────────────────
DEFAULT_SHORT_US  = 390
DEFAULT_LONG_US   = 1220
DEFAULT_GAP_US    = 435
DEFAULT_LGAP_US   = 1252
DEFAULT_RESET_US  = 12300
DEFAULT_GPIO_PIN  = 17

# How long to hold the button signal in seconds.
# The heater needs ~2-3s of continuous transmission to register ON or OFF.
DEFAULT_HOLD_ON_SECONDS  = 2.5
DEFAULT_HOLD_OFF_SECONDS = 2.5
DEFAULT_HOLD_ADJ_SECONDS = 0.5   # +/- only needs a brief press


def _burst_duration_us(bit_length: int, reset_us: int) -> int:
    """Approximate duration of one full burst in microseconds."""
    return bit_length * 1700 + reset_us


def _build_wave(pi, gpio_pin: int, code: int, bit_length: int,
                short_us: int, long_us: int, gap_us: int,
                lgap_us: int, reset_us: int):
    """Build and register a pigpio waveform. Returns wave ID."""
    pulses = []
    for i in range(bit_length - 1, -1, -1):
        bit = (code >> i) & 1
        if bit:
            pulses.append(pigpio.pulse(1 << gpio_pin, 0, long_us))
            pulses.append(pigpio.pulse(0, 1 << gpio_pin, lgap_us))
        else:
            pulses.append(pigpio.pulse(1 << gpio_pin, 0, short_us))
            pulses.append(pigpio.pulse(0, 1 << gpio_pin, gap_us))
    # Inter-burst silence
    pulses.append(pigpio.pulse(0, 1 << gpio_pin, reset_us))

    pi.wave_clear()
    pi.wave_add_generic(pulses)
    wid = pi.wave_create()
    if wid < 0:
        raise RuntimeError(f"pigpio wave_create failed: {wid}")
    return wid


class _PigpioTX:
    """Transmitter backed by pigpio."""

    def __init__(self, gpio_pin: int):
        self.gpio_pin = gpio_pin
        self._pi = pigpio.pi()
        if not self._pi.connected:
            raise RuntimeError(
                "Cannot connect to pigpio daemon. Run: sudo systemctl start pigpiod"
            )
        self._pi.set_mode(gpio_pin, pigpio.OUTPUT)
        self._pi.write(gpio_pin, 0)

    def send(self, code: int, bit_length: int, short_us: int, long_us: int,
             gap_us: int, lgap_us: int, reset_us: int, hold_seconds: float):
        """
        Transmit code continuously for hold_seconds to simulate button hold.
        """
        wid = _build_wave(
            self._pi, self.gpio_pin, code, bit_length,
            short_us, long_us, gap_us, lgap_us, reset_us,
        )

        burst_us = _burst_duration_us(bit_length, reset_us)
        bursts_needed = max(1, int((hold_seconds * 1_000_000) / burst_us))

        logger.debug(
            f"Transmitting 0x{code:07X} for {hold_seconds:.1f}s "
            f"(~{bursts_needed} bursts @ {burst_us}µs each)"
        )

        # wave_send_repeat transmits continuously; we stop after hold_seconds
        self._pi.wave_send_repeat(wid)
        time.sleep(hold_seconds)
        self._pi.wave_tx_stop()
        self._pi.wave_delete(wid)
        self._pi.write(self.gpio_pin, 0)

    def cleanup(self):
        try:
            self._pi.wave_tx_stop()
            self._pi.write(self.gpio_pin, 0)
            self._pi.stop()
        except Exception:
            pass


class _StubTX:
    """Simulation stub."""
    def __init__(self, gpio_pin: int):
        self.gpio_pin = gpio_pin

    def send(self, code, bit_length, short_us, long_us,
             gap_us, lgap_us, reset_us, hold_seconds):
        burst_us = _burst_duration_us(bit_length, reset_us)
        bursts = int((hold_seconds * 1_000_000) / burst_us)
        logger.info(
            f"[STUB] TX 0x{code:07X} ({code}) for {hold_seconds:.1f}s "
            f"(~{bursts} bursts)"
        )
        time.sleep(hold_seconds)  # simulate the hold time realistically

    def cleanup(self):
        pass


class HeaterController:
    """
    Controls a Chinese diesel heater via 433MHz OOK_PWM RF.

    Pre-configured with the RF parameters captured from your remote
    (House Code 47010, OOK_PWM, 25-bit).

    The heater requires a sustained button hold (~2-3s) to register ON/OFF.
    hold_on_seconds and hold_off_seconds control how long the signal is
    transmitted. The +/- buttons only need a brief press.

    Args:
        gpio_pin:         BCM GPIO pin for 433MHz TX data (default 17).
        code_on:          25-bit code for ON  (0x485d478 = 76300408).
        code_off:         25-bit code for OFF (0x485d4b8 = 76301496).
        code_up:          25-bit code for power + (0x485d4e8 = 76301544).
        code_down:        25-bit code for power - (0x485d4d8 = 76301528).
        hold_on_seconds:  How long to hold the ON signal (default 2.5s).
        hold_off_seconds: How long to hold the OFF signal (default 2.5s).
        hold_adj_seconds: How long to hold +/- signal (default 0.5s).
        short_us:         Short pulse µs (default 390).
        long_us:          Long pulse µs (default 1220).
        gap_us:           Gap after short pulse µs (default 435).
        lgap_us:          Gap after long pulse µs (default 1252).
        reset_us:         Inter-burst silence µs (default 12300).
        bit_length:       Bits per burst (default 25).
    """

    def __init__(
        self,
        gpio_pin:         int   = DEFAULT_GPIO_PIN,
        code_on:          int   = 76300408,
        code_off:         int   = 76301496,
        code_up:          int   = 76301544,
        code_down:        int   = 76301528,
        hold_on_seconds:  float = DEFAULT_HOLD_ON_SECONDS,
        hold_off_seconds: float = DEFAULT_HOLD_OFF_SECONDS,
        hold_adj_seconds: float = DEFAULT_HOLD_ADJ_SECONDS,
        short_us:         int   = DEFAULT_SHORT_US,
        long_us:          int   = DEFAULT_LONG_US,
        gap_us:           int   = DEFAULT_GAP_US,
        lgap_us:          int   = DEFAULT_LGAP_US,
        reset_us:         int   = DEFAULT_RESET_US,
        bit_length:       int   = 25,
    ):
        self.gpio_pin         = gpio_pin
        self.code_on          = code_on
        self.code_off         = code_off
        self.code_up          = code_up
        self.code_down        = code_down
        self.hold_on_seconds  = hold_on_seconds
        self.hold_off_seconds = hold_off_seconds
        self.hold_adj_seconds = hold_adj_seconds
        self.short_us         = short_us
        self.long_us          = long_us
        self.gap_us           = gap_us
        self.lgap_us          = lgap_us
        self.reset_us         = reset_us
        self.bit_length       = bit_length
        self._tx: Optional[object] = None

    def _get_tx(self):
        if self._tx is None:
            self._tx = _PigpioTX(self.gpio_pin) if PIGPIO_AVAILABLE else _StubTX(self.gpio_pin)
        return self._tx

    def _send(self, code: int, hold: float, label: str):
        if code == 0:
            raise ValueError(f"RF code for '{label}' is 0 — check config.toml.")
        logger.info(f"Sending {label} (holding for {hold:.1f}s)...")
        self._get_tx().send(
            code=code, bit_length=self.bit_length,
            short_us=self.short_us, long_us=self.long_us,
            gap_us=self.gap_us, lgap_us=self.lgap_us,
            reset_us=self.reset_us, hold_seconds=hold,
        )
        logger.info(f"{label} sent.")

    def turn_on(self):
        """Transmit ON — holds signal for hold_on_seconds."""
        self._send(self.code_on, self.hold_on_seconds, "ON")

    def turn_off(self):
        """Transmit OFF — holds signal for hold_off_seconds."""
        self._send(self.code_off, self.hold_off_seconds, "OFF")

    def power_up(self):
        """Transmit + (increase power level)."""
        self._send(self.code_up, self.hold_adj_seconds, "POWER+")

    def power_down(self):
        """Transmit - (decrease power level)."""
        self._send(self.code_down, self.hold_adj_seconds, "POWER-")

    def cleanup(self):
        if self._tx is not None:
            self._tx.cleanup()
            self._tx = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.cleanup()
