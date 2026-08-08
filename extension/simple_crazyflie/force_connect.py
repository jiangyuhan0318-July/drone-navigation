"""Force-connect and read telemetry with a hard timeout."""
import cflib.crtp
import logging
import time
import sys

logging.basicConfig(level=logging.WARNING)
cflib.crtp.init_drivers()

from cflib.crazyflie import Crazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

cf = Crazyflie(rw_cache='./cache')
connected = False

def connected_cb(link_uri):
    global connected
    connected = True
    print(f'Connected: {link_uri}')

def disconnected_cb(link_uri):
    print(f'Disconnected: {link_uri}')

def connection_failed_cb(link_uri, msg):
    print(f'Connection failed: {link_uri} - {msg}')

cf.connected.add_callback(connected_cb)
cf.disconnected.add_callback(disconnected_cb)
cf.connection_failed.add_callback(connection_failed_cb)

print('Opening link...')
cf.open_link(URI)

# Wait up to 10 seconds for connection
deadline = time.monotonic() + 10
while not connected and time.monotonic() < deadline:
    time.sleep(0.1)

if not connected:
    print('FAILED to connect within 10s')
    sys.exit(1)

# Wait a moment for TOC to download
print('Waiting for TOC...')
time.sleep(3)

# List what we got
toc = cf.log.toc.toc
print(f'Log TOC items: {len(toc)}')
for k in sorted(toc.keys())[:30]:
    print(f'  {k}')

params = cf.param.toc.toc
print(f'\nParam TOC items: {len(params)}')
for k in sorted(params.keys())[:30]:
    print(f'  {k}')

cf.close_link()
print('Done.')
