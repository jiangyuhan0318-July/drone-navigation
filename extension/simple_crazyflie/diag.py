"""Diagnose the exact failure point."""
import cflib.crtp
import logging
import time

# Full debug output
logging.basicConfig(level=logging.DEBUG)

print('Step 1: init_drivers...')
cflib.crtp.init_drivers()
print('Step 1: done')

from cflib.crazyflie import Crazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

print('Step 2: create Crazyflie...')
cf = Crazyflie(rw_cache='./cache')

def connected_cb(link_uri):
    print(f'*** CONNECTED: {link_uri}')

def disconnected_cb(link_uri):
    print(f'*** DISCONNECTED: {link_uri}')

def failed_cb(link_uri, msg):
    print(f'*** FAILED: {link_uri} - {msg}')

cf.connected.add_callback(connected_cb)
cf.disconnected.add_callback(disconnected_cb)

print('Step 3: open_link...')
try:
    cf.open_link(URI)
    print('Step 3: open_link returned (non-blocking)')
except Exception as e:
    print(f'Step 3: open_link ERROR: {e}')
    import sys; sys.exit(1)

print('Step 4: waiting 8 seconds for callback...')
deadline = time.monotonic() + 8
while time.monotonic() < deadline:
    time.sleep(0.5)

print(f'Step 5: link_established={cf.link_established}')
print('Step 6: close_link...')
cf.close_link()
print('Done.')
