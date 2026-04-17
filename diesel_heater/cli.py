"""
heater — diesel heater 433MHz controller CLI

Commands:
    on                                  Turn heater on (holds signal ~2.5s)
    off                                 Turn heater off (holds signal ~2.5s)
    power-up                            Increase power level (+)
    power-down                          Decrease power level (-)
    schedule --run-for 180              Start now, auto-off after 3h
    schedule --delay 60 --run-for 180   Start in 1h, auto-off 3h later
    daemon                              Button-press mode (runs forever)
    config --show                       Print active configuration
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


def cmd_on(args, controller: HeaterController):
    print(f"Sending ON (holding for {controller.hold_on_seconds:.1f}s)...")
    controller.turn_on()
    print("✓ Heater ON sent.")


def cmd_off(args, controller: HeaterController):
    print(f"Sending OFF (holding for {controller.hold_off_seconds:.1f}s)...")
    controller.turn_off()
    print("✓ Heater OFF sent.")


def cmd_power_up(args, controller: HeaterController):
    print("Sending POWER+ ...")
    controller.power_up()
    print("✓ Power + sent.")


def cmd_power_down(args, controller: HeaterController):
    print("Sending POWER- ...")
    controller.power_down()
    print("✓ Power - sent.")


def cmd_schedule(args, controller: HeaterController):
    delay   = getattr(args, "delay",   0) or 0
    run_for = getattr(args, "run_for", None)

    if delay > 0:
        h, m = divmod(int(delay), 60)
        print(f"⏰ Heater will start in {f'{h}h {m}m' if h else f'{m}m'}")
    else:
        print(f"🔥 Starting heater now (holding ON for {controller.hold_on_seconds:.1f}s)...")

    if run_for:
        h, m = divmod(int(run_for), 60)
        print(f"⏱  Auto-shutdown after {f'{h}h {m}m' if h else f'{m}m'}")
    else:
        print("ℹ  No auto-shutdown. Use 'heater off' or STOP button.")

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


def cmd_daemon(args, controller: HeaterController, config: dict):
    """Button-press daemon: START runs schedule, STOP cancels + sends OFF."""
    from .buttons import ButtonController

    sched_cfg = config.get("schedule", {})
    btn_cfg   = config.get("buttons",  {})

    delay_min   = btn_cfg.get("delay_min",   sched_cfg.get("delay_min",   0))
    run_for_min = btn_cfg.get("run_for_min", sched_cfg.get("run_for_min", None))
    start_pin   = btn_cfg.get("start_pin", 23)
    stop_pin    = btn_cfg.get("stop_pin",  24)
    led_pin     = btn_cfg.get("led_pin",   None)

    active = [None]  # mutable scheduler reference

    def on_start():
        if active[0] is not None and not active[0]._cancel_event.is_set():
            print("Already running — press STOP first.")
            return
        if delay_min > 0:
            h, m = divmod(int(delay_min), 60)
            print(f"START pressed — heater starts in {f'{h}h {m}m' if h else f'{m}m'}")
        else:
            print(f"START pressed — sending ON (holding {controller.hold_on_seconds:.1f}s)")
        if run_for_min:
            h, m = divmod(int(run_for_min), 60)
            print(f"Auto-shutdown after {f'{h}h {m}m' if h else f'{m}m'}")

        buttons.set_led(True)
        s = HeaterScheduler(controller=controller, delay_min=delay_min, run_for_min=run_for_min)
        active[0] = s

        import threading
        def _run():
            s.start(blocking=True)
            buttons.set_led(False)
            print("Cycle complete.")
        threading.Thread(target=_run, daemon=True).start()

    def on_stop():
        print(f"STOP pressed — sending OFF (holding {controller.hold_off_seconds:.1f}s)")
        if active[0]:
            active[0].cancel()
        try:
            controller.turn_off()
            print("✓ Heater OFF sent.")
        except Exception as e:
            print(f"Warning: {e}")
        buttons.set_led(False)

    buttons = ButtonController(
        start_pin=start_pin, stop_pin=stop_pin,
        on_start=on_start, on_stop=on_stop, led_pin=led_pin,
    )
    with buttons:
        print(f"Daemon ready.  START=GPIO{start_pin}  STOP=GPIO{stop_pin}", end="")
        if led_pin:
            print(f"  LED=GPIO{led_pin}", end="")
        print(f"\nON hold={controller.hold_on_seconds:.1f}s  OFF hold={controller.hold_off_seconds:.1f}s")
        print("Press Ctrl+C to exit.\n")
        buttons.wait_forever()


def main():
    parser = argparse.ArgumentParser(prog="heater",
        description="Diesel heater 433MHz controller (Pi Zero 2)")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("-c", "--config", metavar="PATH")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("on",          help="Turn heater on")
    sub.add_parser("off",         help="Turn heater off")
    sub.add_parser("power-up",    help="Increase power level (+)")
    sub.add_parser("power-down",  help="Decrease power level (-)")

    p_s = sub.add_parser("schedule", help="Timed start/stop")
    p_s.add_argument("--delay",   type=float, metavar="MIN", default=0,
                     help="Delay before starting (minutes)")
    p_s.add_argument("--run-for", type=float, metavar="MIN", dest="run_for",
                     help="Auto-shutdown after N minutes")

    sub.add_parser("daemon", help="Button-press mode (runs forever)")

    p_cfg = sub.add_parser("config")
    p_cfg.add_argument("--show", action="store_true")

    args = parser.parse_args()
    setup_logging(args.verbose)

    if args.command == "config":
        import json
        print(json.dumps(load_config(getattr(args, "config", None)), indent=2, default=str))
        return

    config = load_config(getattr(args, "config", None))
    kwargs = config_to_controller_kwargs(config)

    with HeaterController(**kwargs) as controller:
        if   args.command == "on":          cmd_on(args, controller)
        elif args.command == "off":         cmd_off(args, controller)
        elif args.command == "power-up":    cmd_power_up(args, controller)
        elif args.command == "power-down":  cmd_power_down(args, controller)
        elif args.command == "schedule":    cmd_schedule(args, controller)
        elif args.command == "daemon":      cmd_daemon(args, controller, config)


if __name__ == "__main__":
    main()
