"""Flash Crazyflie firmware via CrazyRadio PA dongle.

Usage:
  1. Turn OFF the Crazyflie
  2. HOLD the power button, then turn ON (keep holding ~3s until blue M2 LED blinks fast)
  3. Run: python flash_crazyflie.py crazyflie-XXXX.XX.zip
"""
import sys
import cflib.crtp
from cflib.bootloader import Bootloader

FIRMWARE_URL = 'https://github.com/bitcraze/crazyflie-firmware/releases/latest'

def progress_cb(msg, pct):
    print(f'  [{pct:3d}%] {msg}')

def main():
    if len(sys.argv) < 2:
        print(f'Usage: python flash_crazyflie.py <firmware.zip>')
        print(f'Download firmware from: {FIRMWARE_URL}')
        print('Get the .zip release file (NOT source code zip)')
        sys.exit(1)

    fw_file = sys.argv[1]
    cflib.crtp.init_drivers()

    print('Looking for Crazyflie in bootloader mode...')
    print('(drone OFF → hold power button → turn ON → wait 3s for fast blue blink → release)')

    bl = Bootloader()
    try:
        bl.flash_full(
            filename=fw_file,
            warm=False,              # cold boot: drone already in bootloader mode
            targets=('stm32', 'nrf51'),
            progress_cb=progress_cb,
        )
    except Exception as e:
        print(f'FAILED: {e}')
        print('Make sure:')
        print('  1. CrazyRadio dongle is plugged in')
        print('  2. Drone is in bootloader mode (cold boot with button held)')
        print('  3. Firmware .zip file is valid')
        sys.exit(1)

    print('Flash complete! Drone will restart automatically.')
    print('Wait for solid blue LED → firmware is running.')

if __name__ == '__main__':
    main()
