"""Determine why the drone ignores takeoff: read supervisor/blocking
params, then send a direct hover setpoint (the bench-verified path).

Watch the motors during the hover phase — spinning = drone is fine and
the problem is in the bridge's takeoff path; still = drone is locked.
"""
import logging
import time
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

logging.basicConfig(level=logging.ERROR)
warnings.filterwarnings('ignore')

_state = {'sup': 0, 'flying': 0, 'canfly': 0}


def _cb(ts, data, conf):
    _state['sup'] = data.get('supervisor.info', 0)
    _state['flying'] = data.get('sys.isFlying', 0)
    _state['canfly'] = data.get('sys.canfly', 0)


cflib.crtp.init_drivers()
with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    lg = LogConfig(name='Probe', period_in_ms=100)
    lg.add_variable('supervisor.info', 'uint16_t')
    lg.add_variable('sys.isFlying', 'uint8_t')
    lg.add_variable('sys.canfly', 'uint8_t')
    scf.cf.log.add_config(lg)
    lg.data_received_cb.add_callback(_cb)
    lg.start()
    time.sleep(0.5)

    print('=== 封锁参数 ===')
    for name in ('supervisor.info', 'stabilizer.stop',
                 'supervisor.tmblChckEn', 'supervisor.prefltTimeout',
                 'commander.enHighLevel'):
        try:
            print(f'  {name} = {scf.cf.param.get_value(name)}')
        except Exception as e:
            print(f'  {name} = ERR {e}')
    print(f'  sys.isFlying = {_state["flying"]}  sys.canfly = {_state["canfly"]}  LOCKED位 = {bool(_state["sup"] & 0x40)}')

    print()
    print('现在发送悬停指令 z=0.2m (enHighLevel=1) — 看电机')
    try:
        scf.cf.param.set_value('commander.enHighLevel', 1)
    except Exception:
        pass
    deadline = time.monotonic() + 3.5
    while time.monotonic() < deadline:
        scf.cf.commander.send_hover_setpoint(0, 0, 0, 0.2)
        time.sleep(0.05)
    scf.cf.commander.send_stop_setpoint()
    print(f'已停止。isFlying={_state["flying"]} canfly={_state["canfly"]}')
