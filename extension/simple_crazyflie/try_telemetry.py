"""Simple telemetry test — skips problematic params, just logs what's available."""
import cflib.crtp
import logging
import time

logging.basicConfig(level=logging.INFO)
cflib.crtp.init_drivers()

from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie import Crazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

print('Connecting (timeout 15s)...')
try:
    with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
        cf = scf.cf
        print(f'Link open: {scf.is_link_open()}')

        # Wait briefly for TOC to settle
        time.sleep(2)

        # Show what log variables are available
        tocs = list(cf.log.toc.toc.keys())
        print(f'\nLog variables found: {len(tocs)}')
        stab_vars = [v for v in tocs if 'stab' in v.lower() or 'roll' in v.lower() or 'pitch' in v.lower() or 'yaw' in v.lower()]
        print(f'Stabilizer-related: {stab_vars}')

        # Show what params are available
        params = list(cf.param.toc.toc.keys())
        print(f'\nParams found: {len(params)}')
        stab_params = [p for p in params if 'stab' in p.lower()]
        print(f'Stabilizer params: {stab_params[:10]}')

        print('\nDone.')
except Exception as e:
    print(f'Error: {e}')
