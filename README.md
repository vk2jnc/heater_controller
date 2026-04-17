# diesel-heater

Control a Chinese diesel heater via 433MHz RF from a **Raspberry Pi Zero 2**
(or any Pi with GPIO). Based on the RF signal work by
[ChilliChump](https://github.com/ChilliChump/Diesel-Heater-433mhz-Remote-Control).

Designed for use cases like **drying breathing apparatus clothing** after
washing — delayed start + timed auto-shutdown, no sensors required.

---

## Hardware

| Part | Notes |
|---|---|
| Pi Zero 2 W | Any Pi with GPIO works |
| 433MHz TX module | Data pin → GPIO 17 (BCM) by default |
| 433MHz RX module | Data pin → GPIO 27 (BCM), only needed for initial code capture |
| Your heater's remote | Needed once to capture the RF codes |

Wire TX VCC → 3.3V or 5V, GND → GND, DATA → GPIO 17.

---

## Installation

```bash
# On the Pi:
pip install --break-system-packages "diesel-heater[all]"

# Or from source:
git clone <this-repo>
cd diesel_heater_pkg
pip install --break-system-packages ".[all]"
```

---

## Step 1 — Capture your RF codes

Wire the **RX module** data pin to GPIO 27, then run:

```bash
heater capture
```

Point your remote at the receiver and press **ON** and **OFF**.
You'll see output like:

```
Code:     5592405  Protocol: 1  Pulselength: 350  Bit length: 24
Code:     5592404  Protocol: 1  Pulselength: 350  Bit length: 24
```

Note the values — you'll need them for config.

---

## Step 2 — Configure

```bash
mkdir -p ~/.config/diesel_heater
cp config.example.toml ~/.config/diesel_heater/config.toml
nano ~/.config/diesel_heater/config.toml
```

Fill in your captured `code_on`, `code_off`, `protocol`, and `pulselength`.

---

## Usage

```bash
# Turn on immediately
heater on

# Turn off
heater off

# Start now, auto-shutdown after 3 hours
heater schedule --run-for 180

# Start in 1 hour, auto-shutdown 3 hours after that
heater schedule --delay 60 --run-for 180

# Show current config
heater config --show
```

---

## Systemd (run automatically)

```bash
sudo cp diesel-heater.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable diesel-heater   # start on every boot
sudo systemctl start  diesel-heater   # start now
```

Edit the `ExecStart` line in the service file to set your preferred
`--delay` and `--run-for` values.

---

## Python API

```python
from diesel_heater import HeaterController, HeaterScheduler

controller = HeaterController(
    gpio_pin=17,
    protocol=1,
    pulselength=350,
    code_length=24,
    code_on=5592405,
    code_off=5592404,
)

# Simple on/off
with controller:
    controller.turn_on()

# Scheduled: start in 2 hours, run for 3 hours
scheduler = HeaterScheduler(
    controller=controller,
    delay_min=120,
    run_for_min=180,
)
scheduler.start(blocking=True)
```

---

## Safety notes

- There is no sensor to confirm the heater actually ignited. If the RF
  signal is missed, the heater may not start.
- Always ensure the heater is in a safe, ventilated location.
- The `--run-for` timer is software-only; a physical timer relay is a
  good additional safeguard.
- Always run `heater off` before unplugging the Pi.
