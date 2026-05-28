from __future__ import annotations

from dataclasses import dataclass
import threading
import time


NO_QR = "NO_QR"


@dataclass(frozen=True)
class BufferSnapshot:
    value: str
    has_qr: bool
    qr_sent: bool


class QRBuffer:
    def __init__(self, ack_timeout_ms: int) -> None:
        self._ack_timeout_s = ack_timeout_ms / 1000.0
        self._lock = threading.Lock()
        self._qr_data = ""
        self._has_qr = False
        self._qr_sent = False
        self._sent_at = 0.0

    def store_scan(self, value: str) -> bool:
        text = value.strip()
        if not text:
            return False

        with self._lock:
            self._qr_data = text
            self._has_qr = True
            self._qr_sent = False
            self._sent_at = 0.0
        return True

    def current_value(self) -> str:
        with self._lock:
            if self._has_qr:
                return self._qr_data
            return NO_QR

    def request_payload(self) -> str:
        with self._lock:
            if self._has_qr:
                self._qr_sent = True
                self._sent_at = time.monotonic()
                return self._qr_data
            return NO_QR

    def acknowledge(self) -> bool:
        with self._lock:
            if not (self._has_qr and self._qr_sent):
                return False

            self._has_qr = False
            self._qr_sent = False
            self._sent_at = 0.0
            return True

    def rearm_if_timed_out(self) -> bool:
        with self._lock:
            if not self._qr_sent:
                return False

            if (time.monotonic() - self._sent_at) <= self._ack_timeout_s:
                return False

            self._qr_sent = False
            self._sent_at = 0.0
            return True

    def snapshot(self) -> BufferSnapshot:
        with self._lock:
            return BufferSnapshot(
                value=self._qr_data if self._has_qr else NO_QR,
                has_qr=self._has_qr,
                qr_sent=self._qr_sent,
            )
