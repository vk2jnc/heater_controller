"""
Command-line interface for the diesel heater controller.

Usage:
    heater on                                   # Turn on immediately
    heater off                                  # Turn off immediately
    heater schedule --run-for 180               # On now, off after 3 hours
    heater schedule --delay 60 --run-for 180    # On in 1h, off 3h later
    heater daemon                               # Button-press mode
    heater capture                              # Listen for RF codes (setup)
    heater config --show                        # Print active config
"""

import argparse
import logging
import sys
import time

from .config import load_config, config_to_controller_kwargs
from .controller import HeaterController
from .scheduler import HeaterScheduler


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_on(args, controller):
    controller.turn_on()
    print("✓ Heater ON command sent.")


def cmd_off(args, controller):
    controller.turn_off()
    print("✓ Heater OFF command sent.")


def cmd_schedule(args, controller):
    delay = getattr(args, "delay", 0) or 0
    run_for = getattr(args, "run_for", None)

    if delay > 0:
        h, m = divmod(int(delay), 60)
        delay_str = f"{h}h {m}m" if h else f"{m}m"
        print(f"⏰ Heater will start in {delay_str}")
    else:
        print("🔥 Starting heater now...")

    if run_for:
        h, m = divmod(int(run_for), 60)
        run_str = f"{h}h {m}m" if h else f"{m}m"
        print(f"⏱  Will auto-shutdown after {run_str}")
    else:
        print("ℹ  No auto-shutdown. Use 'heater off' or STOP button to stop.")

    scheduler = HeaterScheduler(controller=controller, delay_min=delay, run_for_min=run_for)
    try:
        scheduler.start(blocking=False)
        print("Press Ctrl+C to cancel.\n")
        scheduler.wait()
        print("✓ Schedule complete.")
    except KeyboardInterrupt:
        print("\nCancelling...")
        scheduler.cancel()
        try:
            controller.turn_off()
            print("✓ Heater OFF sent for safety.")
        except Exception:
            pass
        sys.exit(0)


def cmd_daemon(args, controller, config):
    """Button-press daemon: START button starts schedule, STOP button kills it."""
    from .buttons import ButtonController

    sched_cfg = config.get("schedule", {})
    btn_cfg = config.get("buttons", {})

    delay_min   = btn_cfg.get("delay_min",  sched_cfg.get("delay_min", 0))
    run_for_min = btn_cfg.get("run_for_min", sched_cfg.get("run_for_min", None))
    start_pin   = btn_cfg.get("start_pin", 23)
    stop_pin    = btn_cfg.get("stop_pin",  24)
    led_pin     = btn_cfg.get("led_pin",   None)

    active_scheduler = [None]

    def on_start():
        if active_scheduler[0] is not None:
            s = active_scheduler[0]
            if not s._cancel_event.is_set():
                print("Already running — press STOP first.")
                return

        if delay_min > 0:
            h, m = divmod(int(delay_min), 60)
            msg = f"{h}h {m}m" if h else f"{m}m"
            print(f"START pressed — heater starts in {msg}")
        else:
            print("START pressed — starting heater now")

        if run_for_min:
            h, m = divmod(int(run_for_min), 60)
            msg = f"{h}h {m}m" if h else f"{m}m"
            print(f"Auto-shutdown after {msg}")

        buttons.set_led(True)
        s = HeaterScheduler(controller=controller, delay_min=delay_min, run_for_min=run_for_min)
        active_scheduler[0] = s

        import threading
        def _run():
            s.start(blocking=True)
            buttons.set_led(False)
            print("Cycle complete.")
        threading.Thread(target=_run, daemon=True).start()

    def on_stop():
        print("STOP pressed")
        if active_scheduler[0]:
            active_scheduler[0].cancel()
        try:
            controller.turn_off()
            print("✓ Heater OFF sent.")
        except Exception as e:
            print(f"Warning: {e}")
        buttons.set_led(False)

    buttons = ButtonController(
        start_pin=start_pin,
        stop_pin=stop_pin,
        on_start=on_start,
        on_stop=on_stop,
        led_pin=led_pin,
    )

    with buttons:
        print(f"Daemon running.  START=GPIO{start_pin}  STOP=GPIO{stop_pin}", end="")
        if led_pin:
            print(f"  LED=GPIO{led_pin}", end="")
        print("\nPress Ctrl+C to exit.\n")
        buttons.wait_forever()


def cmd_capture(args, _controller):
    try:
        from rpi_rf import RFDevice
    except ImportError:
        print("ERROR: rpi-rf not installed: pip install rpi-rf")
        sys.exit(1)

    gpio = getattr(args, "gpio", 27) or 27
    print(f"Listening on GPIO {gpio} (BCM). Press Ctrl+C to stop.")
    print("Press ON and OFF on your remote.\n")
    rf = RFDevice(gpio)
    rf.enable_rx()
    timestamp = None
    try:
        while True:
            if rf.rx_code_timestamp != timestamp:
                timestamp = rf.rx_code_timestamp
                print(
                    f"  Code: {rf.rx_code:>10}  "
                    f"Protocol: {rf.rx_proto}  "
                    f"Pulselength: {rf.rx_pulselength}  "
                    f"Bit length: {rf.rx_bitlength}"
                )
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        rf.cleanup()
    print("\nDone. Add codes to config.toml.")


def main():
    parser = argparse.ArgumentParser(prog="heater",
        description="Diesel heater 433MHz controller for Pi Zero 2")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-c", "--config", metavar="PATH")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("on")
    sub.add_parser("off")

    p_s = sub.add_parser("schedule")
    p_s.add_argument("--delay",   type=float, metavar="MIN", default=0)
    p_s.add_argument("--run-for", type=float, metavar="MIN", dest="run_for")

    sub.add_parser("daemon")

    p_c = sub.add_parser("capture")
    p_c.add_argument("--gpio", type=int, default=27)

    p_cfg = sub.add_parser("config")
    p_cfg.add_argument("--show", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "config":
        import json
        print(json.dumps(load_config(getattr(args, "config", None)), indent=2, default=str))
        return

    if args.command == "capture":
        cmd_capture(args, None)
        return

    config = load_config(getattr(args, "config", None))
    kwargs = config_to_controller_kwargs(config)

    with HeaterController(**kwargs) as controller:
        if   args.command == "on":       cmd_on(args, controller)
        elif args.command == "off":      cmd_off(args, controller)
        elif args.command == "schedule": cmd_schedule(args, controller)
        elif args.command == "daemon":   cmd_daemon(args, controller, config)


if __name__ == "__main__":
    main()
