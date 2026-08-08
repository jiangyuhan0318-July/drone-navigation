#!/usr/bin/env python3
"""Provision a Crazyflie's radio identity (channel / datarate / address).

The drone stores this triple in its on-board EEPROM config block and loads it
at every boot; the Crazyradio dongle is stateless and just follows the URI it
is given. This script writes the EEPROM over the USB cable (same mechanism as
the Bitcraze CFclient "Connect -> Configure 2.x" dialog), then optionally
verifies the new identity over the radio after you power-cycle the drone.

Course roster (13 groups, one drone per group):
  team N  ->  channel 2N (2..26, >=2 MHz apart, 2M datarate)
              address E7E7E7E7NN (NN = team number in hex)

Usage:
  python provision_drone.py --read-only            # just print the current identity (safe)
  python provision_drone.py --team 7               # write team 7's identity over USB
  python provision_drone.py --channel 14 --address E7E7E7E707 --datarate 2M
  python provision_drone.py --team 7 --verify-only # radio check only (no USB)

Notes:
  * The drone must be plugged in with a DATA cable and powered on; the script
    connects to --uri (default usb://0).
  * USB access needs the Crazyflie udev rule on Linux, or run with sudo:
      SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="5740", MODE="0666"
  * The write is persistent. A typo'd address does not brick the drone: it
    still answers on USB — re-run this script to fix the EEPROM.
  * After writing, POWER-CYCLE the drone; the new identity loads at boot.
"""

import argparse
import sys
import threading

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.mem import MemoryElement
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

DEFAULT_ADDRESS = 0xE7E7E7E7E7
DATARATES = {'250K': 0, '1M': 1, '2M': 2}          # EEPROM byte = combo index (cfclient convention)
DATARATE_NAMES = {v: k for k, v in DATARATES.items()}
COURSE_TEAMS = 13                                   # groups in the classroom


def team_config(team):
    """team N -> (channel 2N, address E7E7E7E7NN)."""
    if not 1 <= team <= COURSE_TEAMS:
        raise argparse.ArgumentTypeError(f'team must be 1..{COURSE_TEAMS}')
    return 2 * team, (DEFAULT_ADDRESS & ~0xFF) | team


def parse_address(text):
    try:
        value = int(text.strip().lower().replace('0x', ''), 16)
    except ValueError:
        raise argparse.ArgumentTypeError(f'not a hex address: {text!r}')
    if not 0 <= value < (1 << 40):
        raise argparse.ArgumentTypeError('address must fit in 40 bits (10 hex digits)')
    return value


def fmt_addr(addr):
    return f'{addr:010X}'


def read_block(scf, timeout=10.0):
    """Fetch the EEPROM config block; returns the I2C memory element."""
    mems = scf.cf.mem.get_mems(MemoryElement.TYPE_I2C)
    if not mems:
        sys.exit('ERROR: no I2C EEPROM memory element found (is this a Crazyflie 2.x?)')
    mem = mems[0]
    done = threading.Event()
    mem.update(lambda m: done.set())
    if not done.wait(timeout):
        sys.exit('ERROR: timed out reading the EEPROM config block')
    if not mem.valid:
        sys.exit('ERROR: EEPROM config block checksum invalid — aborting (nothing written)')
    return mem


def show(title, elements):
    addr = elements.get('radio_address')
    addr_txt = fmt_addr(addr) if addr is not None else f'{fmt_addr(DEFAULT_ADDRESS)} (factory default, not stored)'
    print(f'--- {title} ---')
    print(f"  config block version : {elements.get('version')}")
    print(f"  radio channel        : {elements.get('radio_channel')}")
    print(f"  radio datarate       : {DATARATE_NAMES.get(elements.get('radio_speed'), '?')}")
    print(f"  radio address        : {addr_txt}")
    print(f"  pitch/roll trim      : {elements.get('pitch_trim'):.4f} / {elements.get('roll_trim'):.4f}")


def radio_uri(channel, speed_idx, address):
    return f'radio://0/{channel}/{DATARATE_NAMES[speed_idx]}/{fmt_addr(address)}'


def radio_check(uri, timeout=8.0):
    """Try to connect over the radio; True on success."""
    try:
        with SyncCrazyflie(uri, cf=Crazyflie(rw_cache='./cache')):
            return True
    except Exception as e:
        print(f'  (connect attempt failed: {e})')
        return False


def main():
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = p.add_mutually_exclusive_group()
    target.add_argument('--team', type=int,
                        help=f'course team number 1..{COURSE_TEAMS} -> channel 2N, address E7E7E7E7NN')
    target.add_argument('--channel', type=int,
                        help='explicit radio channel 0..125 (needs --address too)')
    p.add_argument('--address', type=parse_address,
                   help='explicit 40-bit radio address, e.g. E7E7E7E707')
    p.add_argument('--datarate', choices=DATARATES.keys(), default='2M')
    p.add_argument('--uri', default='usb://0',
                   help='link used for provisioning (default: usb://0)')
    p.add_argument('--read-only', action='store_true',
                   help='print the current identity and exit (no write)')
    p.add_argument('--verify-only', action='store_true',
                   help='skip USB entirely; only run the post-power-cycle radio check')
    p.add_argument('--yes', action='store_true',
                   help='do not ask for confirmation before writing')
    p.add_argument('--skip-radio-verify', action='store_true',
                   help='do not wait for a power-cycle / radio re-check after writing')
    args = p.parse_args()

    # Resolve the target identity
    if args.team is not None:
        channel, address = team_config(args.team)
    elif args.channel is not None:
        if not 0 <= args.channel <= 125:
            p.error('--channel must be 0..125')
        if args.channel > 80:
            print('WARNING: channels >80 are outside the ISM band in many countries — check local regulations')
        if args.address is None:
            p.error('--channel needs --address')
        address = args.address
    else:
        channel, address = None, None
    speed_idx = DATARATES[args.datarate]

    if args.verify_only:
        if channel is None:
            p.error('--verify-only needs --team or --channel/--address')
        uri = radio_uri(channel, speed_idx, address)
        print(f'Checking {uri} ...')
        ok = radio_check(uri)
        print('PASS — drone answers on its new identity' if ok else
              'FAIL — no answer (power-cycled? right channel/address? dongle attached?)')
        sys.exit(0 if ok else 1)

    cflib.crtp.init_drivers()
    print(f'Connecting to {args.uri} ...')
    try:
        scf_ctx = SyncCrazyflie(args.uri, cf=Crazyflie(rw_cache='./cache'))
        scf = scf_ctx.__enter__()
    except Exception as e:
        sys.exit(f'ERROR: cannot connect on {args.uri}: {e}\n'
                 'Drone on a DATA cable and powered on? USB permissions (udev rule / sudo)?')

    with scf_ctx:
        mem = read_block(scf)
        show('CURRENT identity (from EEPROM)', mem.elements)

        if args.read_only:
            return

        if channel is None:
            p.error('nothing to do: give --team, or --channel/--address (or use --read-only)')

        # v0 blocks predate the address field — upgrading to v1 stores it (trims preserved)
        if 'radio_address' not in mem.elements:
            print('NOTE: upgrading config block v0 -> v1 to store the address (trim values preserved)')
            mem.elements['version'] = 1
            mem.elements['radio_address'] = DEFAULT_ADDRESS

        print(f'\nAbout to WRITE:  channel {channel}  datarate {args.datarate}  address {fmt_addr(address)}')
        if not args.yes:
            if input('Type "yes" to write this to the drone EEPROM: ').strip() != 'yes':
                sys.exit('Aborted — nothing written.')

        mem.elements['radio_channel'] = channel
        mem.elements['radio_speed'] = speed_idx
        mem.elements['radio_address'] = address

        written = threading.Event()
        mem.write_data(lambda m, a: written.set())
        if not written.wait(10.0):
            sys.exit('ERROR: timed out writing the EEPROM config block')

        # Read-back verification while still on USB
        mem2 = read_block(scf)
        ok = (mem2.elements.get('radio_channel') == channel and
              mem2.elements.get('radio_speed') == speed_idx and
              mem2.elements.get('radio_address') == address)
        if not ok:
            show('READ-BACK MISMATCH', mem2.elements)
            sys.exit('ERROR: read-back does not match what was written — re-run the script')
        print('EEPROM write verified (read-back matches).')

    uri = radio_uri(channel, speed_idx, address)
    print(f'\nStudents connect with:  ./start_bridge.sh --cf-uri {uri}')

    if args.skip_radio_verify:
        print('Power-cycle the drone to activate the new identity.')
        return

    input('\nNow POWER-CYCLE the drone (off + on), then press Enter to verify over the radio...')
    print(f'Checking {uri} ...')
    ok = radio_check(uri)
    print('PASS — drone answers on its new identity' if ok else
          'FAIL — no answer (power-cycled? right channel/address? dongle attached?)')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
