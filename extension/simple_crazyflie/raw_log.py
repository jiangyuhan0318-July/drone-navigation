"""Read stabilizer telemetry via raw cflib API — no SyncCrazyflie."""
import cflib.crtp
import logging
import time

cflib.crtp.init_drivers()

from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig

URI = 'radio://0/80/2M/E7E7E7E7E7'

cf = Crazyflie(rw_cache='./cache')
link_open = False
started = False

def _connected(uri):
    global link_open
    link_open = True
    print(f'Link open: {uri}')

def _disconnected(uri):
    global link_open
    link_open = False
    print(f'Disconnected: {uri}')

def _failed(uri, msg):
    print(f'Connection failed: {uri} - {msg}')

cf.connected.add_callback(_connected)
cf.disconnected.add_callback(_disconnected)
cf.connection_failed.add_callback(_failed)

# Open link
print('Opening link...')
cf.open_link(URI)

# Wait for connection
deadline = time.monotonic() + 15
while not link_open and time.monotonic() < deadline:
    time.sleep(0.1)

if not link_open:
    print('FAILED to connect')
    cf.close_link()
    exit(1)

# Try subscribing to stabilizer log
print('\nSubscribing to stabilizer roll/pitch/yaw...')
lg = LogConfig(name='Stabilizer', period_in_ms=50)
lg.add_variable('stabilizer.roll', 'float')
lg.add_variable('stabilizer.pitch', 'float')
lg.add_variable('stabilizer.yaw', 'float')

count = [0]
def _cb(timestamp, data, logconf):
    print(f'[{timestamp}] roll={data["stabilizer.roll"]:7.3f} pitch={data["stabilizer.pitch"]:7.3f} yaw={data["stabilizer.yaw"]:7.3f}')
    count[0] += 1

lg.data_received_cb.add_callback(_cb)

try:
    cf.log.add_config(lg)
    lg.start()
    print('Streaming for 10 seconds...')
    time.sleep(10)
    lg.stop()
    print(f'\nReceived {count[0]} samples.')
except Exception as e:
    print(f'Log error: {e}')

cf.close_link()
print('Done.')
