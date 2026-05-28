from __future__ import annotations

from dataclasses import dataclass
import os


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    return int(raw)


@dataclass(frozen=True)
class Settings:
    ble_device_name: str = os.getenv("BLE_DEVICE_NAME", "QR-Reader")
    service_uuid: str = os.getenv("BLE_SERVICE_UUID", "12345678-1234-1234-1234-123456789abc")
    qr_data_char_uuid: str = os.getenv("BLE_QR_DATA_CHAR_UUID", "12345678-1234-1234-1234-123456789abd")
    qr_req_char_uuid: str = os.getenv("BLE_QR_REQ_CHAR_UUID", "12345678-1234-1234-1234-123456789abe")
    ack_timeout_ms: int = _env_int("ACK_TIMEOUT_MS", 15000)
    scan_interval_ms: int = _env_int("SCAN_INTERVAL_MS", 120)
    qr_disappear_reset_ms: int = _env_int("QR_DISAPPEAR_RESET_MS", 1200)
    camera_width: int = _env_int("CAMERA_WIDTH", 1280)
    camera_height: int = _env_int("CAMERA_HEIGHT", 720)
    camera_index: int = _env_int("CAMERA_INDEX", 0)
    camera_backend: str = os.getenv("CAMERA_BACKEND", "picamera2").lower()
    log_level: str = os.getenv("LOG_LEVEL", "INFO").upper()

