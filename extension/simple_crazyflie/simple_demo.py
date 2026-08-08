"""Direct TOC poll + telemetry — bypasses SyncCrazyflie entirely."""
import cflib.crtp
import time

cflib.crtp.init_drivers()
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig

URI = 'radio://0/80/2M/E7E7E7E7E7'
cf = Crazyflie(rw_cache='./cache')
link_ok = False

def on_connected(uri):
    global link_ok
    link_ok = True

cf.connected.add_callback(on_connected)
print('Opening link...')
cf.open_link(URI)

# Wait up to 60s for TOC download to complete.
# Old firmware may have gaps between TOC items, so we:
#  1. Wait for cf.log.toc to become non-None (TOC download started)
#  2. Then track when counts stop growing for 3s → done
deadline = time.monotonic() + 60
last_log_n = 0
last_param_n = 0
stable_count = 0
toc_started = False
while not link_ok and time.monotonic() < deadline:
    time.sleep(0.5)
    toc = cf.log.toc
    ptoc = cf.param.toc
    log_n = len(toc.toc) if toc else 0
    param_n = len(ptoc.toc) if ptoc else 0
    if toc is not None:
        toc_started = True
    if log_n or param_n:
        print(f'  TOC: log={log_n} param={param_n}')
    # Only check stability after TOC object exists and count > 0
    if toc_started and log_n > 0:
        if log_n == last_log_n and param_n == last_param_n:
            stable_count += 1
            if stable_count >= 6:  # 3s of no change → done
                print('  TOC download complete.')
                break
        else:
            stable_count = 0
            last_log_n = log_n
            last_param_n = param_n

toc = cf.log.toc
if link_ok or (toc is not None and len(toc.toc) > 0):
    print(f'\nConnected! Log TOC: {len(toc.toc)} items, Param TOC: {len(cf.param.toc.toc) if cf.param.toc else 0} items')

    # List available stabilizer-related variables
    stabs = [k for k in toc.toc if 'stab' in k.lower() or 'roll' in k.lower() or 'pitch' in k.lower()]
    print(f'Stabilizer vars: {stabs[:10]}')

    # Try subscribing to stabilizer
    if 'stabilizer.roll' in toc.toc:
        print('\nSubscribing to stabilizer roll/pitch/yaw...')
        lg = LogConfig(name='Stab', period_in_ms=100)
        lg.add_variable('stabilizer.roll', 'float')
        lg.add_variable('stabilizer.pitch', 'float')
        lg.add_variable('stabilizer.yaw', 'float')
        count = [0]
        def show(timestamp, data, logconf):
            print(f'[{timestamp}] roll={data["stabilizer.roll"]:7.3f} pitch={data["stabilizer.pitch"]:7.3f} yaw={data["stabilizer.yaw"]:7.3f}')
            count[0] += 1
        lg.data_received_cb.add_callback(show)
        cf.log.add_config(lg)
        lg.start()
        time.sleep(10)
        lg.stop()
        print(f'\n{count[0]} samples received.')
    else:
        print('stabilizer.roll not in TOC')
        # Show what's available
        tocs = sorted(toc.toc.keys())
        print(f'Available log vars ({len(tocs)}):')
        for k in tocs[:50]:
            print(f'  {k}')
else:
    print('FAILED: could not connect / download TOC')

cf.close_link()
print('Done.')
