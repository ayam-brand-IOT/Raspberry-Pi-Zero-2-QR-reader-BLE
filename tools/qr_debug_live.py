#!/usr/bin/env python3
from __future__ import annotations

import argparse
import logging
import threading
import time
from http import server
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np


LOG = logging.getLogger("qr_debug_live")


class CameraUnavailableError(RuntimeError):
    pass


class _Picamera2Capture:
    def __init__(self, width: int, height: int) -> None:
        try:
            from picamera2 import Picamera2
        except ImportError as exc:
            raise CameraUnavailableError(
                "Picamera2 no esta instalado. Instala python3-picamera2 o usa --backend opencv."
            ) from exc

        self._picam = Picamera2()
        config = self._picam.create_video_configuration(main={"size": (width, height), "format": "RGB888"})
        self._picam.configure(config)
        self._picam.start()
        time.sleep(0.5)

    def read(self):
        frame = self._picam.capture_array()
        return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)

    def close(self) -> None:
        self._picam.stop()
        self._picam.close()


class _OpenCVCapture:
    def __init__(self, width: int, height: int, index: int) -> None:
        self._cap = cv2.VideoCapture(index)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        if not self._cap.isOpened():
            raise CameraUnavailableError(f"No se pudo abrir camera index {index}.")

    def read(self):
        ok, frame = self._cap.read()
        if not ok:
            raise CameraUnavailableError("Fallo leyendo frame de OpenCV capture.")
        return frame

    def close(self) -> None:
        self._cap.release()


class FrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._jpeg: Optional[bytes] = None
        self._sequence = 0

    def update(self, jpeg: bytes) -> None:
        with self._condition:
            self._jpeg = jpeg
            self._sequence += 1
            self._condition.notify_all()

    def wait_next(self, last_sequence: int, timeout_s: float = 2.0) -> Tuple[Optional[bytes], int]:
        with self._condition:
            if self._sequence == last_sequence:
                self._condition.wait(timeout=timeout_s)
            return self._jpeg, self._sequence


def _decode_qrs(detector, frame) -> List[Tuple[str, Sequence[Sequence[float]]]]:
    found: List[Tuple[str, Sequence[Sequence[float]]]] = []
    if hasattr(detector, "detectAndDecodeMulti"):
        ok, decoded_list, points, _straight = detector.detectAndDecodeMulti(frame)
        if ok and points is not None:
            for idx, payload in enumerate(decoded_list):
                text = (payload or "").strip()
                if text:
                    found.append((text, points[idx]))
    if found:
        return found

    text, points, _straight = detector.detectAndDecode(frame)
    text = (text or "").strip()
    if text and points is not None:
        found.append((text, points))
    return found


def _draw_overlay(frame, detections: List[Tuple[str, Sequence[Sequence[float]]]], fps: float) -> None:
    for idx, (payload, points) in enumerate(detections, start=1):
        pts = np.asarray(points, dtype=np.float32).reshape(-1, 2)
        if pts.shape[0] >= 4:
            poly = np.rint(pts).astype(np.int32)
            cv2.polylines(frame, [poly], True, (0, 255, 0), 2)
        label = f"QR{idx}: {payload}"
        y = 30 + (idx * 28)
        cv2.putText(frame, label, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.putText(
        frame,
        f"FPS: {fps:.1f} | Detections: {len(detections)}",
        (10, 24),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (0, 200, 255),
        2,
        cv2.LINE_AA,
    )


class MjpegHandler(server.BaseHTTPRequestHandler):
    frame_store: FrameStore

    def do_GET(self) -> None:  # pragma: no cover - runtime path
        if self.path in ("/", "/index.html"):
            body = (
                "<html><body style='background:#111;color:#ddd;font-family:monospace;'>"
                "<h3>QR Debug Live</h3>"
                "<img src='/stream.mjpg' style='max-width:100%;height:auto;'/>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path != "/stream.mjpg":
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()

        last_sequence = -1
        try:
            while True:
                frame, sequence = self.frame_store.wait_next(last_sequence)
                if frame is None or sequence == last_sequence:
                    continue
                last_sequence = sequence
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode("ascii"))
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError):
            return

    def log_message(self, fmt, *args) -> None:  # pragma: no cover - avoid noisy HTTP logs
        LOG.debug("HTTP: " + fmt, *args)


def _run_http_server(host: str, port: int, frame_store: FrameStore):  # pragma: no cover - runtime path
    class _Handler(MjpegHandler):
        pass

    _Handler.frame_store = frame_store
    httpd = server.ThreadingHTTPServer((host, port), _Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    LOG.info("Preview web: http://%s:%d", host, port)
    return httpd


def _open_capture(backend: str, width: int, height: int, index: int):
    if backend == "picamera2":
        return _Picamera2Capture(width, height)
    return _OpenCVCapture(width, height, index)


def main() -> None:  # pragma: no cover - runtime path
    parser = argparse.ArgumentParser(description="Herramienta de debug en vivo para deteccion QR.")
    parser.add_argument("--backend", choices=["picamera2", "opencv"], default="picamera2")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=720)
    parser.add_argument("--camera-index", type=int, default=0)
    parser.add_argument("--fps-limit", type=float, default=12.0)
    parser.add_argument("--mode", choices=["window", "mjpeg"], default="mjpeg")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, str(args.log_level).upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    capture = _open_capture(args.backend, args.width, args.height, args.camera_index)
    detector = cv2.QRCodeDetector()
    frame_store = FrameStore()
    httpd = None

    if args.mode == "mjpeg":
        httpd = _run_http_server(args.host, args.port, frame_store)

    LOG.info("Iniciando debug QR en vivo (%s)", args.mode)
    LOG.info("Backend: %s", args.backend)

    last_printed = set()
    min_delta_s = 1.0 / max(args.fps_limit, 1.0)
    last_frame_at = 0.0
    fps = 0.0
    fps_alpha = 0.25

    try:
        while True:
            now = time.monotonic()
            wait_s = min_delta_s - (now - last_frame_at)
            if wait_s > 0:
                time.sleep(wait_s)
            current = time.monotonic()
            dt = current - last_frame_at if last_frame_at else min_delta_s
            last_frame_at = current
            instant_fps = 1.0 / max(dt, 1e-6)
            fps = instant_fps if fps == 0.0 else ((1.0 - fps_alpha) * fps + fps_alpha * instant_fps)

            frame = capture.read()
            detections = _decode_qrs(detector, frame)
            current_payloads = {payload for payload, _points in detections}

            for payload in sorted(current_payloads):
                if payload not in last_printed:
                    LOG.info("QR detectado: %s", payload)
            last_printed = current_payloads

            _draw_overlay(frame, detections, fps)
            ok, jpeg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if ok:
                frame_store.update(jpeg.tobytes())

            if args.mode == "window":
                cv2.imshow("QR Debug Live", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
    except KeyboardInterrupt:
        LOG.info("Detenido por usuario.")
    finally:
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        capture.close()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
