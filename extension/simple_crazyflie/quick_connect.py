"""Quick connect test — works with any firmware version."""
import cflib.crtp
import logging
logging.basicConfig(level=logging.INFO)
cflib.crtp.init_drivers()

from cflib.crazyflie.syncCrazyflie import SyncCrazyflie
from cflib.crazyflie import Crazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    cf = scf.cf
    print(f'Connected: {scf.is_link_open()}')

    # Read a known-working param
    try:
        val = cf.param.get_value('system.selftestPassed')
        print(f'Self-test passed: {val}')
    except Exception as e:
        print(f'Self-test: N/A ({e})')

    # List available log variables (first 30)
    print('\nAvailable log variables (first 30):')
    tocs = list(cf.log.toc.toc.items())
    for name, info in tocs[:30]:
        print(f'  {name}')
    print(f'  ... ({len(tocs)} total)')

print('Done.')
