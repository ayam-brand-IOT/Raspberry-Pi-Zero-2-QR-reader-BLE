#!/usr/bin/env python3
"""
BLE tester for QR-Reader compatible peripherals.
"""

import asyncio
import os
from typing import Optional

from bleak import BleakClient, BleakScanner

SERVICE_UUID = os.getenv("BLE_SERVICE_UUID", "12345678-1234-1234-1234-123456789abc")
QR_DATA_CHAR_UUID = os.getenv("BLE_QR_DATA_CHAR_UUID", "12345678-1234-1234-1234-123456789abd")
QR_REQ_CHAR_UUID = os.getenv("BLE_QR_REQ_CHAR_UUID", "12345678-1234-1234-1234-123456789abe")
DEVICE_NAME = os.getenv("BLE_DEVICE_NAME", "QR-Reader")


async def main() -> None:
    last_value: Optional[str] = None

    def on_notification(_sender, data: bytearray) -> None:
        nonlocal last_value
        last_value = data.decode("utf-8", errors="replace")
        print(f"  -> notify: {last_value}")

    print(f"Buscando '{DEVICE_NAME}'...")
    device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15.0)
    if device is None:
        print("No encontrado.")
        return

    print(f"Encontrado: {device.address}")
    async with BleakClient(device, timeout=15.0) as client:
        await client.start_notify(QR_DATA_CHAR_UUID, on_notification)
        print("Conectado. ENTER=GET, ack=ACK, q=salir")

        loop = asyncio.get_event_loop()
        while True:
            cmd = await loop.run_in_executor(None, lambda: input("Accion: ").strip())
            if cmd.lower() == "q":
                break

            if cmd.lower() == "ack":
                await client.write_gatt_char(QR_REQ_CHAR_UUID, b"ACK", response=False)
                print("  [->] ACK enviado")
                continue

            last_value = None
            await client.write_gatt_char(QR_REQ_CHAR_UUID, b"GET", response=False)
            print("  [->] GET enviado")
            await asyncio.sleep(0.4)

        await client.stop_notify(QR_DATA_CHAR_UUID)


if __name__ == "__main__":
    asyncio.run(main())
