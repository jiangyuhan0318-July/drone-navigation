"""Bench probe: determine how THIS firmware drives the motors.

Phase A — direct thrust setpoint with NO arming:
  motors spin        -> pre-arming-era firmware, no arming needed
  motors stay still  -> firmware needs some arming step

Phase B — commander.enHighLevel=1 + hover setpoint z=0.2:
  old firmware's high-level commander toggle; confirms the hover
  path used by 03_propellers.py / 04_flying.py.
"""
import logging
import time
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'
THRUST = 20000          # ~30 % — visible spin, safe on the ground

logging.basicConfig(level=logging.ERROR)
warnings.filterwarnings('ignore')

_state = {'sup': 0, 'flying': 0}


def _cb(ts, data, conf):
    _state['sup'] = data.get('supervisor.info', 0)
    _state['flying'] = data.get('sys.isFlying', 0)


cflib.crtp.init_drivers()
with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    lg = LogConfig(name='Probe', period_in_ms=100)
    lg.add_variable('supervisor.info', 'uint16_t')
    lg.add_variable('sys.isFlying', 'uint8_t')
    scf.cf.log.add_config(lg)
    lg.data_received_cb.add_callback(_cb)
    lg.start()
    time.sleep(0.5)
    print('supervisor.info = 0x%04x   sys.isFlying = %d'
          % (_state['sup'], _state['flying']))

    print()
    print('Phase A: direct thrust setpoint, NO arming — watch the motors')
    print('  motors spinning  -> no arming needed on this firmware')
    print('  motors still     -> an arming step is required')
    scf.cf.commander.send_setpoint(0, 0, 0, THRUST)
    time.sleep(2.5)
    scf.cf.commander.send_stop_setpoint()
    print('  (stopped — motors should wind down)  isFlying=%d'
          % _state['flying'])
    time.sleep(2)

    toc = scf.cf.param.toc.toc
    if 'enHighLevel' in toc.get('commander', {}):
        print()
        print('Phase B: commander.enHighLevel=1 + hover setpoint z=0.2m')
        print('  watch the motors again')
        scf.cf.param.set_value('commander.enHighLevel', 1)
        time.sleep(0.3)
        scf.cf.commander.send_hover_setpoint(0, 0, 0, 0.2)
        time.sleep(2.5)
        scf.cf.commander.send_stop_setpoint()
        print('  (stopped)  isFlying=%d' % _state['flying'])
    else:
        print()
        print('Phase B skipped: no commander.enHighLevel param')
    time.sleep(1)
    print()
    print('Probe done — report what you saw.')
