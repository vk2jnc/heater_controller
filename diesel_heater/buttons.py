"""
Physical button support for the diesel heater controller.

Wiring (no resistors needed — uses Pi's internal pull-ups):
    START button:  one leg → GPIO pin (default 23), other leg → GND
    STOP  button:  one leg → GPIO pin (default 24), other leg → GND

The buttons are active-low: pressing = LOW signal.
A short debounce prevents multiple triggers from one press.
"""

import logging
import threading
import time
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    logger.warning("RPi.GPIO not available. Button support disabled (simulation mode).")


DEBOUNCE_MS = 300  # milliseconds


class ButtonController:
    """
    Monitors two GPIO buttons (START and STOP) and triggers callbacks.

    Args:
        start_pin:      BCM GPIO pin for the START button (default 23).
        stop_pin:       BCM GPIO pin for the STOP  button (default 24).
        on_start:       Callable triggered when START is pressed.
        on_stop:        Callable triggered when STOP is pressed.
        led_pin:        Optional BCM GPIO pin for a status LED (default None).
                        LED is ON while a schedule is running.
    """

    def __init__(
        self,
        start_pin: int = 23,
        stop_pin: int = 24,
        on_start: Optional[Callable] = None,
        on_stop: Optional[Callable] = None,
        led_pin: Optional[int] = None,
    ):
        self.start_pin = start_pin
        self.stop_pin = stop_pin
        self.on_start = on_start
        self.on_stop = on_stop
        self.led_pin = led_pin
        self._running = False
        self._last_press: dict = {}

    def _debounce(self, pin: int) -> bool:
        """Return True if enough time has passed since the last press on this pin."""
        now = time.monotonic()
        last = self._last_press.get(pin, 0)
        if (now - last) * 1000 < DEBOUNCE_MS:
            return False
        self._last_press[pin] = now
        return True

    def _handle_start(self, channel):
        if not self._debounce(channel):
            return
        logger.info("START button pressed")
        if self.on_start:
            threading.Thread(target=self.on_start, daemon=True).start()

    def _handle_stop(self, channel):
        if not self._debounce(channel):
            return
        logger.info("STOP button pressed")
        if self.on_stop:
            threading.Thread(target=self.on_stop, daemon=True).start()

    def setup(self):
        """Set up GPIO pins and register interrupt callbacks."""
        if not GPIO_AVAILABLE:
            logger.warning("GPIO not available — buttons will not work.")
            return

        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.start_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.stop_pin,  GPIO.IN, pull_up_down=GPIO.PUD_UP)

        if self.led_pin is not None:
            GPIO.setup(self.led_pin, GPIO.OUT)
            GPIO.output(self.led_pin, GPIO.LOW)

        GPIO.add_event_detect(
            self.start_pin,
            GPIO.FALLING,
            callback=self._handle_start,
            bouncetime=DEBOUNCE_MS,
        )
        GPIO.add_event_detect(
            self.stop_pin,
            GPIO.FALLING,
            callback=self._handle_stop,
            bouncetime=DEBOUNCE_MS,
        )
        logger.info(
            f"Buttons ready — START on GPIO {self.start_pin}, "
            f"STOP on GPIO {self.stop_pin}"
        )
        self._running = True

    def set_led(self, state: bool):
        """Turn the status LED on or off."""
        if GPIO_AVAILABLE and self.led_pin is not None:
            GPIO.output(self.led_pin, GPIO.HIGH if state else GPIO.LOW)

    def cleanup(self):
        self._running = False
        if GPIO_AVAILABLE:
            GPIO.cleanup()

    def wait_forever(self):
        """Block the main thread while button callbacks handle events."""
        try:
            while self._running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass
        finally:
            self.cleanup()

    def __enter__(self):
        self.setup()
        return self

    def __exit__(self, *args):
        self.cleanup()
