"""Probe the connected drone's actual param/log TOC for arming-related
names — ground truth for fixing 03_propellers.py / 04_flying.py."""
import logging
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

logging.basicConfig(level=logging.ERROR)
warnings.filterwarnings('ignore')

cflib.crtp.init_drivers()
with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    print('connection OK')
    p = scf.cf.param.toc.toc
    for g in ('platform', 'firmware', 'system', 'sys', 'supervisor',
              'commander', 'motorPowerSet', 'stabilizer'):
        if g in p:
            print(f'PARAM {g:14s} ->', sorted(p[g].keys()))
        else:
            print(f'PARAM {g:14s} -> ABSENT')
    l = scf.cf.log.toc.toc
    for g in ('sys', 'supervisor', 'stabilizer'):
        if g in l:
            print(f'LOG   {g:14s} ->', sorted(l[g].keys()))
        else:
            print(f'LOG   {g:14s} -> ABSENT')
