"""Identify the ESP32 board among the Mac's USB serial ports by sending
an esptool-style reset pulse and capturing the boot log."""
import time
import serial

for port in ('/dev/cu.usbmodem31201', '/dev/cu.usbmodem31302'):
    print('=' * 25, port)
    try:
        s = serial.Serial(port, 115200, timeout=0.2)
        # esptool-style reset pulse (DTR/RTS chase)
        s.dtr = False
        s.rts = True
        time.sleep(0.1)
        s.dtr = True
        time.sleep(0.1)
        s.dtr = False
        time.sleep(0.05)
        s.reset_input_buffer()
        data = b''
        deadline = time.time() + 3.0
        while time.time() < deadline:
            chunk = s.read(512)
            if chunk:
                data += chunk
        s.close()
        txt = data.decode('utf-8', errors='replace')
        if txt:
            print(txt[:800])
        else:
            print('(无输出)')
    except Exception as e:
        print('ERR:', e)
