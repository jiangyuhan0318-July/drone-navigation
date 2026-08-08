import cflib.crtp
import logging
logging.basicConfig(level=logging.DEBUG)
cflib.crtp.init_drivers()
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie import Crazyflie
print('Trying to connect...')
try:
    with SyncCrazyflie('radio://0/80/2M/E7E7E7E7E7', cf=Crazyflie(rw_cache='./cache')) as scf:
        print('Link open:', scf.is_link_open())
    print('Disconnected.')
except Exception as e:
    print(f'Failed: {e}')
