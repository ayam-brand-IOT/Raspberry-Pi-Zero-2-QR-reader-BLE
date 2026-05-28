from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .config import Settings
from .scan_gate import ScanGate


LOG = logging.getLogger(__name__)


class CameraUnavailableError(RuntimeError):
    pass


class CameraScanner:
    def __init__(self, settings: Settings, on_scan: Callable[[str], None]) -> None:
        self._settings = settings
        self._on_scan = on_scan
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._gate = ScanGate(settings.qr_disappear_reset_ms)

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="camera-scanner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None

    def _run(self) -> None:
        try:
            self._run_camera_loop()
        except Exception:  # pragma: no cover - runtime hardware path
            LOG.exception("Camera scanner stopped unexpectedly")

    def _run_camera_loop(self) -> None:  # pragma: no cover - runtime hardware path
        import cv2

        detector = cv2.QRCodeDetector()
        capture = self._open_capture()
        sleep_s = self._settings.scan_interval_ms / 1000.0

        LOG.info("Camera scanner started")

        try:
            while not self._stop_event.is_set():
                frame = capture.read()
                decoded = self._decode_frame(detector, frame)
                emitted = self._gate.observe(decoded)
                if emitted:
                    LOG.info("QR detected: %s", emitted)
                    self._on_scan(emitted)
                time.sleep(sleep_s)
        finally:
            capture.close()
            LOG.info("Camera scanner stopped")

    def _open_capture(self):  # pragma: no cover - runtime hardware path
        if self._settings.camera_backend == "picamera2":
            return _Picamera2Capture(self._settings)
        return _OpenCVCapture(self._settings)

    @staticmethod
    def _decode_frame(detector, frame) -> Optional[str]:  # pragma: no cover - runtime hardware path
        import cv2

        text = ""
        if hasattr(detector, "detectAndDecodeMulti"):
            ok, decoded_list, _points, _straight = detector.detectAndDecodeMulti(frame)
            if ok:
                for candidate in decoded_list:
                    if candidate:
                        text = candidate
                        break

        if not text:
            text, _points, _straight = detector.detectAndDecode(frame)

        return text.strip() or None


class _Picamera2Capture:
    def __init__(self, settings: Settings) -> None:  # pragma: no cover - runtime hardware path
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CameraUnavailableError(
                "Picamera2 is not installed. Install python3-picamera2 or switch CAMERA_BACKEND=opencv."
            ) from exc

        self._picam = Picamera2()
        config = self._picam.create_video_configuration(
            main={"size": (settings.camera_width, settings.camera_height), "format": "RGB888"}
        )
        self._picam.configure(config)
        self._picam.start()
        time.sleep(0.5)

    def read(self):  # pragma: no cover - runtime hardware path
        import cv2

        frame = self._picam.capture_array()
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def close(self) -> None:  # pragma: no cover - runtime hardware path
        self._picam.stop()


class _OpenCVCapture:
    def __init__(self, settings: Settings) -> None:  # pragma: no cover - runtime hardware path
        import cv2

        self._cap = cv2.VideoCapture(settings.camera_index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)
        if not self._cap.isOpened():
            raise CameraUnavailableError(f"Could not open camera index {settings.camera_index}")

    def read(self):  # pragma: no cover - runtime hardware path
        ok, frame = self._cap.read()
        if not ok:
            raise CameraUnavailableError("Failed to read frame from OpenCV capture")
        return frame

    def close(self) -> None:  # pragma: no cover - runtime hardware path
        self._cap.release()
