from __future__ import annotations

import time
from typing import Optional


class ScanGate:
    """
    Emit a QR value only on a new sighting edge.

    A camera can decode the same QR for many consecutive frames. This helper
    makes that behave more like the ESP UART reader: one buffered event per
    sighting, then the same QR becomes eligible again only after it disappears
    from view long enough.
    """

    def __init__(self, disappear_reset_ms: int) -> None:
        self._disappear_reset_s = disappear_reset_ms / 1000.0
        self._visible_code: Optional[str] = None
        self._last_visible_at = 0.0
        self._last_emitted_code: Optional[str] = None

    def observe(self, value: Optional[str], now: Optional[float] = None) -> Optional[str]:
        now = time.monotonic() if now is None else now
        text = (value or "").strip()

        if text:
            if text != self._visible_code:
                self._visible_code = text
            self._last_visible_at = now

            if text != self._last_emitted_code:
                self._last_emitted_code = text
                return text
            return None

        if self._visible_code is not None and (now - self._last_visible_at) >= self._disappear_reset_s:
            if self._visible_code == self._last_emitted_code:
                self._last_emitted_code = None
            self._visible_code = None

        return None
