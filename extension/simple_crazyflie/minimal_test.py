"""Minimal test — connect, read firmware info, disconnect. 5s hard timeout."""
import cflib.crtp
import time
import sys

cflib.crtp.init_drivers()

from cflib.crazyflie import Crazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'
done = False

def cb(uri):
    global done
    print('GOT CONNECTED CALLBACK:', uri)

cf = Crazyflie(rw_cache='./cache')
cf.connected.add_callback(cb)
print('Opening link (5s timeout)...')
cf.open_link(URI)

deadline = time.monotonic() + 5
while not done and time.monotonic() < deadline:
    time.sleep(0.1)

if done:
    print('SUCCESS — radio link works!')
    time.sleep(1)
    cf.close_link()
else:
    print('FAILED — no connection callback within 5s')
    sys.exit(1)
