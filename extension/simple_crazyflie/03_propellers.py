r"""Verify propeller assembly — spin each motor individually and check
its direction BY EYE.

The Crazyflie 2.1 motor layout (X-configuration, top-down view):

             Front
        M4 (CW)    M1 (CCW)
             \    /
              \  /
              /  \
             /    \
        M3 (CCW)   M2 (CW)
             Back

Each motor must spin in the direction shown AND carry the matching
propeller type (CW or CCW).  A wrong prop or wrong motor order makes
the drone flip on takeoff.

Run:  python 03_propellers.py

Why by eye and not by the gyroscope?  A single small propeller on a
grounded quad produces a yaw reaction torque far below the gyro's
vibration-rectification noise floor.  In practice the gyro reading
during a one-motor spin is dominated by vibration artifacts — the
same motor can read +0.16 rad/s in one run and +1.28 rad/s in the
next, with the sign unrelated to the actual spin direction.  Human
eyes (plus a phone in slow-motion mode if needed) are the reliable
sensor for this check.

The script spins each motor one at a time via motorPowerSet so you
can see exactly which motor spins and in which direction.  If the
motorPowerSet params are missing from this firmware, all four motors
are spun together during the hover instead.

After the individual check the script performs a short hover at
~20 cm.  This catches the one fault a spin-direction check cannot:
a propeller mounted upside-down (correct rotation, but no lift).
"""
import logging
import time
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'
POWER = 20000          # ~30 % — clearly visible spin, safe on the ground
SPIN_TIME = 2.5        # seconds per motor — long enough to see direction
PAUSE = 1.5            # between motors

LOCKED_BIT = 0x40      # supervisor.info bit 6 — "must be restarted"

# Live supervisor flags, refreshed by the log callback below.
_state = {'flying': 1, 'sup': 0}


def _state_cb(ts, data, conf):
    _state['flying'] = data.get('sys.isFlying', 1)
    _state['sup'] = data.get('supervisor.info', 0)


def _start_state_log(cf):
    lg = LogConfig(name='PropState', period_in_ms=100)
    lg.add_variable('sys.isFlying', 'uint8_t')
    lg.add_variable('supervisor.info', 'uint16_t')
    cf.log.add_config(lg)
    lg.data_received_cb.add_callback(_state_cb)
    lg.start()
    return lg


def _locked():
    return bool(_state['sup'] & LOCKED_BIT)


def _settle(cf, duration=2.5):
    """Keep feeding z=0 altitude hold after the descent ramp.

    Cutting the motors abruptly the instant the setpoint reaches zero
    (the drone still airborne) latches the LOCKED state, which needs a
    power cycle to clear — see 04_flying.py.  The supervisor's
    sys.isFlying flag never clears on this firmware, so the settle is
    time-based rather than flag-based.
    """
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        cf.commander.send_hover_setpoint(0, 0, 0, 0)
        time.sleep(0.05)

logging.basicConfig(level=logging.ERROR)

# Suppress CRTP-v6 compatibility warnings (same rationale as the other
# scripts — this firmware needs the legacy paths).
warnings.filterwarnings(
    'ignore',
    message=r'Using legacy TYPE_.*_LEGACY',
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'platform\.send_arming_request is deprecated',
    category=DeprecationWarning,
)
warnings.filterwarnings(
    'ignore',
    message=r'The supervisor subsystem requires CRTP protocol version 12 or later',
    category=UserWarning,
)

DIAGRAM = """\
               Front
          M4 (CW)    M1 (CCW)
               \\    /
                \\  /
                /  \\
               /    \\
          M3 (CCW)   M2 (CW)
               Back"""


# ── individual motor check (motorPowerSet required) ─────────────────

def _spin_each_motor(cf):
    """Spin each motor one at a time; the user verifies direction."""
    print()
    print('Individual motor check — watch each propeller as it spins')
    print('-' * 50)
    print()
    print('  Top view (front of the drone pointing away from you):')
    print()
    print(DIAGRAM)
    print()
    motors = [
        ('M1', 'm1', 'front-right', 'counter-clockwise ↺'),
        ('M2', 'm2', 'rear-right ', 'clockwise ↻'),
        ('M3', 'm3', 'rear-left  ', 'counter-clockwise ↺'),
        ('M4', 'm4', 'front-left ', 'clockwise ↻'),
    ]
    for tag, param, pos, direction in motors:
        print(f'  {tag} ({pos}) — expect {direction}')
        print(f'      spinning for {SPIN_TIME:.0f} s ...', flush=True)
        cf.param.set_value(f'motorPowerSet.{param}', POWER)
        time.sleep(SPIN_TIME)
        cf.param.set_value(f'motorPowerSet.{param}', 0)
        time.sleep(PAUSE)
    print()
    print('  Checklist:')
    print('    [ ] M1 — front-right — counter-clockwise ↺')
    print('    [ ] M2 — rear-right  — clockwise ↻')
    print('    [ ] M3 — rear-left   — counter-clockwise ↺')
    print('    [ ] M4 — front-left  — clockwise ↻')
    print()
    print('  A motor that did not spin at all: check its wiring and')
    print('  connectors — a kinked or pinched wire is a common cause.')
    print()


# ── hover check (all four motors at once) ───────────────────────────
#
# Uses send_hover_setpoint() which goes to COMMANDER_GENERIC with
# TYPE_HOVER_LEGACY on this CRTP v6 firmware.  The motors are driven
# by the flight controller; motorPowerSet.enable must be 0 (otherwise
# the motorPowerSet params override the controller output).
#
# This firmware needs no arming — its param TOC has no system.arm /
# system.armed (verified on the bench), and its hover-mode setpoints
# are gated behind commander.enHighLevel = 1, which the main block
# enables.
#
# The trade-off: the drone must actually hover (~20 cm) for the
# controller to spool up all four motors.  A brief low hover is the
# most reliable integration check available on this firmware.

HOVER_HEIGHT = 0.20      # metres — clear of ground effect (important
                         # on soft surfaces), yet low enough that a
                         # wrong prop causes visible tilt, not a
                         # fly-away
HOVER_TIME = 4.0         # seconds of hover — time to check all four


def _pump_hover(cf, vx, vy, yaw_rate, zdistance, duration):
    """Send hover setpoints at ~20 Hz for *duration* seconds.

    The commander watchdog expires after ~1 s without a fresh setpoint,
    so a single call + sleep() is NOT safe.
    """
    deadline = time.monotonic() + duration
    while time.monotonic() < deadline:
        cf.commander.send_hover_setpoint(vx, vy, yaw_rate, zdistance)
        time.sleep(0.05)  # ~20 Hz


def _hover_check(cf):
    """Brief low hover — verifies the props actually produce lift.

    Catches a propeller mounted upside-down (spins the right way but
    pushes air up) and confirms the flight controller drives all four
    channels.  If any propeller is wrong the drone will tilt or flip
    immediately at this low height, making the error obvious.
    """
    print()
    print('Final check — brief hover at ~20 cm')
    print('-' * 50)
    print()
    print('  ⚠️  The drone will lift off briefly.')
    print('  Keep the area clear and your hands away.')
    print()
    print('  The drone should rise straight up and hold position.')
    print('  Immediate tilt, spin, or failure to lift = something')
    print('  is still wrong (re-check the diagram):')
    print()
    print(DIAGRAM)
    print()
    print(f'  Hovering at ~{HOVER_HEIGHT * 100:.0f} cm for '
          f'{HOVER_TIME:.0f} s ...')
    _pump_hover(cf, 0, 0, 0, HOVER_HEIGHT, HOVER_TIME)
    print('  Touching down gently ...')
    # Ramp the altitude setpoint down over 2 s, then keep feeding z=0
    # while the drone physically settles.  Cutting the motors while the
    # drone is still airborne latches the LOCKED state — see 04_flying.py.
    steps = 40                        # 2.0 s descent at 20 Hz
    for i in range(1, steps + 1):
        cf.commander.send_hover_setpoint(
            0, 0, 0, HOVER_HEIGHT * (1 - i / steps))
        time.sleep(0.05)
    _settle(cf)
    print()
    print('-' * 50)
    print('Tip: if the propellers are too fast to see, film them with')
    print('your phone in slow-motion mode (120/240 fps), or watch the')
    print('blur from the side rather than from above.')


# ── main ────────────────────────────────────────────────────────────

if __name__ == '__main__':
    cflib.crtp.init_drivers()
    with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
        time.sleep(2)

        _start_state_log(scf.cf)
        time.sleep(0.5)

        toc = scf.cf.param.toc.toc
        use_motor_power = ('motorPowerSet' in toc
                           and 'm1' in toc['motorPowerSet'])

        # Arming is firmware-dependent.  Modern stock firmware exposes
        # system.arm (uint8), mid-generation firmware system.armed
        # (bool); THIS firmware exposes neither (verified on the bench)
        # — there the flight controller drives the motors directly from
        # setpoints, no arming step exists.  The CRTP arming packet
        # (platform.send_arming_request()) is silently ignored here, so
        # it is never used.  Resolve the arming switch from the live TOC:
        system_params = toc.get('system', {})
        if 'arm' in system_params:
            ARM_ON, ARM_OFF, ARMED_STR = 1, 0, '1'
            ARM_PARAM = 'system.arm'
        elif 'armed' in system_params:
            ARM_ON, ARM_OFF, ARMED_STR = True, False, 'True'
            ARM_PARAM = 'system.armed'
        else:
            ARM_PARAM = None

        # This firmware gates hover-mode setpoints behind the
        # high-level commander toggle (verified: with it enabled, the
        # hover setpoint spools all four motors).
        if 'enHighLevel' in toc.get('commander', {}):
            scf.cf.param.set_value('commander.enHighLevel', 1)

        if _locked():
            print('NOTE: the drone is in the LOCKED supervisor state —')
            print('a previous flight ended with the motors cut while it')
            print('was airborne.  The individual spins still work, but')
            print('the hover is skipped.  Power-cycle the drone to clear.')
            armed = False
        elif ARM_PARAM is None:
            print('NOTE: this firmware has no arming parameter — the')
            print('flight controller drives the motors straight from')
            print('setpoints (verified on the bench).')
            armed = True
        else:
            scf.cf.param.set_value(ARM_PARAM, ARM_ON)
            time.sleep(0.3)
            armed = str(scf.cf.param.get_value(ARM_PARAM)) == ARMED_STR
            if not armed:
                print('WARNING: the drone did not accept arming — the')
                print('individual spins still work, but the hover will not.')

        if use_motor_power:
            # Individual motor control is gated behind the enable flag:
            # enable=1 overrides the motors with motorPowerSet.m1..m4.
            try:
                scf.cf.param.set_value('motorPowerSet.enable', 1)
            except Exception:
                pass

        try:
            if use_motor_power:
                _spin_each_motor(scf.cf)
                # Hand the motors back to the flight controller so the
                # hover setpoints below can drive them.
                scf.cf.param.set_value('motorPowerSet.enable', 0)
                time.sleep(0.2)
            else:
                print('NOTE: motorPowerSet params not found — all four')
                print('motors will spin together during the hover check.')

            if armed:
                _hover_check(scf.cf)
            else:
                print('Skipping the hover check (drone not armed).')
        except KeyboardInterrupt:
            print('\n[Ctrl+C] — aborting the check.')
        finally:
            # Always hand motor control back to the flight controller,
            # cut the motors and disarm, so leftover state (enable=1,
            # armed) can never block a later flight.
            if use_motor_power:
                try:
                    scf.cf.param.set_value('motorPowerSet.enable', 0)
                except Exception:
                    pass
            scf.cf.commander.send_stop_setpoint()
            scf.cf.commander.send_notify_setpoint_stop()
            time.sleep(0.1)
            if ARM_PARAM is not None:
                try:
                    scf.cf.param.set_value(ARM_PARAM, ARM_OFF)
                except Exception:
                    pass
            time.sleep(0.3)
            if _locked():
                print('NOTE: the drone latched into the LOCKED state.')
                print('Power-cycle it before the next flight.')

    print('\nDone.')
    print('Remember: correct propeller TYPES (CW/CCW) are just as '
          'important as direction.')
