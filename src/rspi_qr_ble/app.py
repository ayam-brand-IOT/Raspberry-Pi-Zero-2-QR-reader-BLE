from __future__ import annotations

import logging

from .ble_gatt_server import BLEServer
from .camera_scanner import CameraScanner
from .config import Settings
from .qr_buffer import QRBuffer


def main() -> None:
    settings = Settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    log = logging.getLogger(__name__)
    log.info("[SYS] Rspi_QR_BLE iniciando...")
    log.info("[SYS] BLE name: %s", settings.ble_device_name)
    log.info("[SYS] Camera backend: %s", settings.camera_backend)

    qr_buffer = QRBuffer(settings.ack_timeout_ms)
    scanner = CameraScanner(settings, qr_buffer.store_scan)

    try:
        scanner.start()
        BLEServer(settings, qr_buffer).run()
    except KeyboardInterrupt:
        log.info("Interrupted by user")
    except Exception as exc:
        log.exception("Fatal error: %s", exc)
        raise
    finally:
        scanner.stop()


if __name__ == "__main__":
    main()
