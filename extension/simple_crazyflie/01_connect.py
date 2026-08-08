"""Step 1: connect to the Crazyflie over the Crazyradio PA and read the
battery voltage — the smallest possible end-to-end check of the radio link.

Run:  python 01_connect.py
"""
import logging
import time

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

# URI of the Crazyflie to connect to (radio link via the Crazyradio PA):
#   radio://<dongle>/<channel>/<datarate>/<address>
# Adjust if the drone was provisioned to a different channel/address.
URI = 'radio://0/80/2M'

# Only output errors from the logging framework
logging.basicConfig(level=logging.ERROR)

def read_vbat(cf, timeout=10.0):
    """Read the battery voltage via a one-shot log subscription.

    This drone runs a custom firmware build whose param table does NOT
    expose pm.vbat (only pm.lowVoltage / pm.criticalLowVoltage), but the
    log TOC still provides pm.vbat, so subscribe instead of get_value.
    """
    # The log TOC downloads asynchronously after connect; wait for it
    deadline = time.monotonic() + timeout
    while 'pm' not in cf.log.toc.toc:
        if time.monotonic() > deadline:
            raise TimeoutError('Log TOC never downloaded')
        time.sleep(0.1)

    result = {}
    log_config = LogConfig(name='battery', period_in_ms=100)
    log_config.add_variable('pm.vbat', 'float')

    def _on_data(timestamp, data, logconf):
        result.update(data)
        logconf.stop()

    log_config.data_received_cb.add_callback(_on_data)
    cf.log.add_config(log_config)
    log_config.start()

    while 'pm.vbat' not in result and time.monotonic() < deadline:
        time.sleep(0.05)
    if 'pm.vbat' not in result:
        raise TimeoutError(f'pm.vbat log data never arrived within {timeout:.0f}s')
    return float(result['pm.vbat'])


if __name__ == '__main__':
    # Initialize the low-level drivers (scans for the Crazyradio)
    cflib.crtp.init_drivers()

    with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
        print('Link open:', scf.is_link_open())
        # Battery via log subscription (this firmware has no pm.vbat param)
        vbat = read_vbat(scf.cf)
        print(f'Battery: {vbat:.2f} V  (fly only if >= 3.9 V)')

    print('Disconnected cleanly.')
