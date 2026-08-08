# simple_crazyflie — Connect, Read Telemetry, Fly

English | [中文](README-zh.md)

The scripts in this folder are modified from the official Bitcraze tutorial
[Step-by-Step: Connecting, logging and parameters](https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/user-guides/sbs_connect_log_param/),
using **cflib directly** — no server, no MediaMTX, no browser. Four
ready-made scripts, run in this order:

1. `01_connect.py` — prove the radio link works
2. `02_telemetry.py` — stream live sensor data from the drone
3. `03_propellers.py` — verify each propeller's direction
4. `04_flying.py` — arm, take off, hover, and land

Once all three behave as described below, graduate to the full website
pipeline in [`../crazyflie_bridge`](../crazyflie_bridge).

To assemble the crazyflie 2.1, please refer to the official guideline 
["Getting started with the Crazyflie 2.0 or Crazyflie 2.1(+)"](https://www.bitcraze.io/documentation/tutorials/getting-started-with-crazyflie-2-x/). 

---

## 0. Prerequisites (do these once)

**Hardware**

- Crazyflie 2.x with a charged battery, switched ON, sitting on a flat and
  open surface
- Crazyradio PA plugged into a USB port of this machine

**Software**

- Activate the conda env: `conda activate drone-navigation`
  (it already has cflib; if not, `pip install cflib`)
- On Linux, install the USB permission rule so no `sudo` is needed — the
  exact command is in `deployment/README.md` §5.1 (also in the platform
  READMEs). Unplug/replug the Crazyradio afterwards.

**Radio URI**

- Each script defines a `URI` constant near the top, set to the factory
  default `radio://0/80/2M/E7E7E7E7E7`.
- If the drone's EEPROM identity was changed with `provision_drone.py`, edit
  the constant in all three scripts to match (`radio://0/<channel>/2M/<address>`).
- To read the current identity over a USB cable:
  `python ../crazyflie_bridge/provision_drone.py --read-only`

---

## 1. Connect — `python 01_connect.py`

The smallest possible end-to-end check: it connects over the radio, reads the
battery voltage, and disconnects.

**Expect to see:**

```
Link open: True
Battery: 3.97 V  (fly only if >= 3.9 V)
Disconnected cleanly.
```

If that prints, the radio, permissions, and URI are all correct — every later
step (and the production bridge) builds on this.

**If it fails:**

| Symptom | Cause / fix |
|---|---|
| `Cannot find a Crazyradio USB dongle` | Radio not plugged in, or the udev rule is missing / not reloaded |
| Connect times out (`Too many packets lost`) | Wrong URI, drone switched off, or radio interference — re-check the EEPROM identity |
| `Battery: 0.00 V` printed once | Parameter refresh raced the connect — just re-run |

---

## 2. Read telemetry — `python 02_telemetry.py`

Connects, announces itself, toggles the `stabilizer.estimator` parameter
(2 → 1) to demonstrate parameter read/write, then streams the stabilizer's
roll / pitch / yaw at 100 Hz for 5 seconds.

**Expect to see:**

```
Yeah, I'm connected! :D
Now I will disconnect :'(
The crazyflie has parameter stabilizer.estimator set at number: 2
The crazyflie has parameter stabilizer.estimator set at number: 1
[1234][Stabilizer]: {'stabilizer.roll': 0.42, 'stabilizer.pitch': -0.15, 'stabilizer.yaw': 3.1}
[1244][Stabilizer]: {'stabilizer.roll': 0.40, ...}
... (100 lines per second, stops by itself after 5 s)
```

**Sanity check while it streams:** pick the drone up and tilt it — roll,
pitch and yaw should react immediately. That proves the whole
drone → radio → Python path is live, in both directions.

Notes:

- Angles are in degrees.
- The script exits on its own after 5 seconds; run it again any time.

---

## 3. Check propellers — `python 03_propellers.py`

**Do this before every first flight** — a wrong propeller or reversed
motor direction makes the drone flip on takeoff.

The script spins each motor individually for ~2.5 s via the
`motorPowerSet` params while you watch each propeller against the
diagram below — eye verification is the reliable method here, because
the yaw reaction torque of one small propeller is far below the
gyro's vibration-noise floor (automated gyro verdicts were tried and
proved unreliable on this firmware).

After the individual spins, the script performs a brief ~20 cm hover.
This catches the one fault a spin check cannot: a propeller mounted
upside-down (spins the right way but produces no lift).

If the firmware does not expose the `motorPowerSet` params, the
script skips the individual spins and goes straight to the hover.

**Motor layout (X-configuration, top-down view):**

```
             Front
        M4 (CW)    M1 (CCW)
             \    /
              \  /
              /  \
             /    \
        M3 (CCW)   M2 (CW)
             Back
```

Also verify that M2 and M4 use clockwise (CW) propellers, and M1 and M3 use counter-clockwise (CCW) propellers — see the reference image below:

![Crazyflie propeller types](../assets/crazyflie_propellers.png)
![Crazyflie structure diagram](../assets/crazyflie_diagram.png)



**Expect to see:** each motor spins one at a time (the console prints
which motor is next and which direction to expect), followed by a
brief low hover.

If a motor spins the wrong way, power off the drone and swap that
propeller (or check the propeller type — CW and CCW blades are
different). If a motor does not spin at all, check its wiring — a
kinked or pinched wire is a common cause. Re-run until all four are
correct.

---

## 4. Fly — `python 04_flying.py`

**Safety checklist first:**

- Battery ≥ 3.9 V (step 1 tells you)
- At least 2 m of clear space in every direction, no people or pets
- Fly **on battery** — unplug any USB cable (a tether yanks the drone down)
- Keep your fingers near `Ctrl+C` and know where the drone's power switch is

**What the script does:** arms the drone, takes off to 0.3 m (a 3 s
ramp), hovers for 5 s, then lands and disarms. It sends hover setpoints
at 20 Hz through the full flight-controller pipeline — the same
mechanism the propeller check's hover uses.

> **Note:** this demo does not fly laterally. The hover setpoints command
> zero lateral velocity but provide no position feedback, so the drone may
> drift slowly sideways — keep the area clear. Altitude hold itself works
> well: the flow deck's distance sensor (`range.zrange`) is healthy and
> drives the height controller.

**Expect to see:**

- Console: `Arming ...`, `Taking off ...`, `Hovering ...`, `Landing ...`.
- Drone: a smooth ramp up to ~30 cm, a steady 5-second hover, then a
  gentle descent.

**Stopping:** press `Ctrl+C` at any time — the script cuts the motors
immediately and disarms.

**Emergency stop — motors off immediately, even mid-air:**

1. **Unplug the Crazyradio** from the computer. The firmware's commander
   watchdog detects the link loss and cuts the motors within about a second.
   This is the fastest kill switch — but the drone drops like a stone, so
   keep the flight area over something soft and clear.
2. **`Ctrl+C`** — slower (a controlled landing takes a couple of seconds)
   but much gentler on the hardware. Prefer this when you still have control.
3. **Flip the drone's power switch** — only once it is down or tangled;
   never reach into spinning propellers.

In your own scripts, the software equivalent of pulling the radio is
`scf.cf.commander.send_stop_setpoint()` — it zeroes thrust on the spot.
After any emergency stop, power-cycle the drone (and replug the radio)
before flying again.

**Full power-off over the radio:** cflib's `PowerSwitch` utility can shut
the whole drone down — `PowerSwitch(URI).platform_power_down()` powers off
*both* MCUs, exactly like pressing the power button (the command is handled
by the radio MCU, so it works even if the flight firmware is hung).
Triggered mid-air, the drone simply falls to the ground. And once it is
off, there is no way back over the radio: it can only be turned on again
by walking to the drone and pressing its power button — recovery always
requires physical access. For a
*recoverable* kill, use `stm_power_down()` instead (flight MCU and decks
off, radio MCU stays alive), then bring it back with `stm_power_up()` or
`stm_power_cycle()` — no physical access needed. Note: the Crazyradio can
only serve one program at a time, so **stop `04_flying.py` (or the bridge)
first** — `Ctrl+C` releases the radio — and only then run the power-off
command from a free terminal. 

If the drone is airborne and you cannot afford that sequence, 
**unplug the radio**: 
the watchdog cuts the motors in about a second and the script exits on its own.

Rule of thumb: on an airborne drone, always reach for the *recoverable*
options first — unplugging the radio, `send_stop_setpoint()`, or
`stm_power_down()` all keep a path back (reconnect, re-arm, fly again).
`platform_power_down()` is the point of no return: only use it on a drone
you can walk to.

**If it says the drone is in the LOCKED supervisor state:** a previous
flight ended badly — the motors were cut while the drone was still
airborne, or it crashed or tumbled. The firmware then latches a safety
lock (`supervisor.info` bit 6) that nothing over the radio can clear:
power-cycle the drone, then run the script again. The flight scripts
descend on a long ramp and keep feeding a z=0 altitude-hold setpoint
before stopping precisely to avoid latching this lock. After any crash,
inspect the propellers (seating, cracks, bent blades) before flying
again — a damaged prop makes the drone flip on takeoff.

---

## 5. Next steps

- **Full website pipeline** — [`../crazyflie_bridge`](../crazyflie_bridge):
  `./start_bridge.sh` streams this same telemetry to the Livestream Host HUD,
  bridges the AI-Deck video to MediaMTX, and accepts flight commands from the
  browser. Production guide: `deployment/README.md` §5.
- **Deeper cflib tutorial** — Bitcraze's
  [step-by-step guide](https://www.bitcraze.io/documentation/repository/crazyflie-lib-python/master/user-guides/sbs_connect_log_param/)
  covers the same connect → log → fly path in more detail.
