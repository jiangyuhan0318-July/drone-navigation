"""Read the drone's deck.* params to see which expansion boards are
attached (AI-Deck? flow deck?) — quick radio probe, bridge reconnects."""
import logging
import warnings

import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

URI = 'radio://0/80/2M/E7E7E7E7E7'

logging.basicConfig(level=logging.ERROR)
warnings.filterwarnings('ignore')

cflib.crtp.init_drivers()
with SyncCrazyflie(URI, cf=Crazyflie(rw_cache='./cache')) as scf:
    toc = scf.cf.param.toc.toc
    for g in ('deck', 'deckTest', 'firmware'):
        if g in toc:
            for k in sorted(toc[g].keys()):
                name = f'{g}.{k}'
                try:
                    print(f'{name} = {scf.cf.param.get_value(name)}')
                except Exception as e:
                    print(f'{name} = ERR {e}')
