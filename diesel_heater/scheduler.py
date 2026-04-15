"""
Scheduler for the diesel heater.

Handles:
  - Delayed start (e.g. start in N minutes)
  - Timed run with automatic shutdown (e.g. run for N minutes)
  - Combined: start in X, run for Y, then shut down
"""

import logging
import time
import threading
from typing import Optional

from .controller import HeaterController

logger = logging.getLogger(__name__)


def _fmt_minutes(minutes: float) -> str:
    if minutes < 1:
        return f"{int(minutes * 60)}s"
    h, m = divmod(int(minutes), 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


class HeaterScheduler:
    """
    Schedules the heater to start after a delay and/or run for a fixed duration.

    Args:
        controller:   A configured HeaterController instance.
        delay_min:    Minutes to wait before starting. 0 = start immediately.
        run_for_min:  Minutes to run before auto-shutdown. None = no auto-shutdown.
    """

    def __init__(
        self,
        controller: HeaterController,
        delay_min: float = 0,
        run_for_min: Optional[float] = None,
    ):
        self.controller = controller
        self.delay_min = delay_min
        self.run_for_min = run_for_min
        self._thread: Optional[threading.Thread] = None
        self._cancel_event = threading.Event()

    def _run(self):
        # --- Delay phase ---
        if self.delay_min > 0:
            logger.info(f"Heater start delayed by {_fmt_minutes(self.delay_min)}")
            delay_sec = self.delay_min * 60
            cancelled = self._cancel_event.wait(timeout=delay_sec)
            if cancelled:
                logger.info("Schedule cancelled during delay phase.")
                return

        # --- Start heater ---
        logger.info("Starting heater...")
        try:
            self.controller.turn_on()
        except Exception as e:
            logger.error(f"Failed to start heater: {e}")
            return

        # --- Run-for phase ---
        if self.run_for_min is not None:
            logger.info(f"Heater will auto-shutdown in {_fmt_minutes(self.run_for_min)}")
            run_sec = self.run_for_min * 60
            cancelled = self._cancel_event.wait(timeout=run_sec)
            if cancelled:
                logger.info("Schedule cancelled during run phase.")
            logger.info("Auto-shutdown: stopping heater...")
            try:
                self.controller.turn_off()
            except Exception as e:
                logger.error(f"Failed to stop heater during auto-shutdown: {e}")
        else:
            logger.info("No auto-shutdown configured. Heater will run until manually stopped.")

    def start(self, blocking: bool = False):
        """
        Start the schedule.

        Args:
            blocking: If True, block until the schedule completes.
                      If False (default), run in a background thread.
        """
        self._cancel_event.clear()
        if blocking:
            self._run()
        else:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()
            logger.info("Scheduler running in background thread.")

    def cancel(self):
        """Cancel a running schedule (will also trigger shutdown if heater is running)."""
        logger.info("Cancelling schedule...")
        self._cancel_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def wait(self):
        """Block until the schedule completes."""
        if self._thread:
            self._thread.join()


def run_schedule(
    controller: HeaterController,
    delay_min: float = 0,
    run_for_min: Optional[float] = None,
    blocking: bool = True,
):
    """
    Convenience function: create and run a schedule.

    Args:
        controller:  Configured HeaterController.
        delay_min:   Minutes to wait before starting (0 = immediately).
        run_for_min: Minutes to run before auto-shutdown (None = no limit).
        blocking:    Whether to block until done.
    """
    scheduler = HeaterScheduler(
        controller=controller,
        delay_min=delay_min,
        run_for_min=run_for_min,
    )
    scheduler.start(blocking=blocking)
    return scheduler
