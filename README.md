# Rspi_QR_BLE

Servidor BLE GATT para Raspberry Pi Zero 2 que lee códigos QR por cámara y los entrega al ESP32 (`tote_inbound` / `tote_outbound`) mediante el protocolo `GET → NOTIFY → ACK`.

Reemplaza al proyecto anterior `QR-Reader-BLE`, manteniendo el mismo contrato BLE para no modificar el firmware del ESP32.

---

## Contrato BLE

| Parámetro | Valor |
|---|---|
| Nombre BLE | `QR-Reader` (configurable) |
| Service UUID | `12345678-1234-1234-1234-123456789abc` |
| Data characteristic | `12345678-1234-1234-1234-123456789abd` — READ + NOTIFY |
| Request characteristic | `12345678-1234-1234-1234-123456789abe` — WRITE |

### Protocolo GET / ACK

```
ESP32 (central)               Pi (peripheral)
     │                              │
     │── write "GET" ─────────────► │
     │                              │ (busca QR en buffer)
     │ ◄──────── notify "TOTE001" ──│   o "NO_QR" si vacío
     │                              │
     │── write "ACK" ─────────────► │  (limpia buffer)
     │                              │
```

- Si el ESP32 no envía `ACK` dentro de `ACK_TIMEOUT_MS` (por defecto 15 s), el QR queda **rearmado** para el siguiente `GET`.
- El ESP32 (`tote_inbound`) realiza un `GET` cada 3 segundos mientras está en estado `WAITING_TOTE_ID`.

---

## Arquitectura

```
Rspi_QR_BLE/
├── src/rspi_qr_ble/
│   ├── app.py              # Punto de entrada: arranca scanner + servidor BLE
│   ├── config.py           # Settings leídas desde variables de entorno
│   ├── camera_scanner.py   # Hilo de captura: Picamera2 o OpenCV
│   ├── scan_gate.py        # Deduplicador: evita re-emitir el mismo QR por frames
│   ├── qr_buffer.py        # Buffer thread-safe con lógica de ACK y timeout
│   ├── ble_gatt_server.py  # Servidor GATT sobre BlueZ D-Bus
│   ├── __main__.py
│   └── __init__.py
├── systemd/
│   └── rspi-qr-ble.service
├── tools/
│   ├── ble_tester.py       # Simula un cliente BLE (ESP32) desde otra máquina
│   └── qr_debug_live.py    # Stream MJPEG o ventana con overlay de detección QR
├── tests/
│   ├── test_qr_buffer.py
│   └── test_scan_gate.py
└── pyproject.toml
```

### Flujo interno

```
CameraScanner (hilo) → ScanGate → QRBuffer.store_scan()
                                        │
BLEServer (GLib MainLoop)               │
  ├─ recibe "GET"  → QRBuffer.request_payload() → notify al central
  └─ recibe "ACK"  → QRBuffer.acknowledge()
                                        │
                        (timeout) → QRBuffer.rearm_if_timed_out()
```

**ScanGate** resuelve el problema de cámara vs. lector UART: la misma etiqueta QR puede estar visible durante cientos de frames. El `ScanGate` solo emite un evento al buffer cuando el código aparece por primera vez, y lo vuelve a habilitar solo después de que desaparece de cámara durante `QR_DISAPPEAR_RESET_MS`.

---

## Variables de entorno

Todas tienen valor por defecto; en producción se configuran en el unit de systemd.

| Variable | Default | Descripción |
|---|---|---|
| `BLE_DEVICE_NAME` | `QR-Reader` | Nombre BLE anunciado. Usar `QR-Reader-OUT` para outbound. |
| `BLE_SERVICE_UUID` | `12345678-...abc` | UUID del servicio GATT |
| `BLE_QR_DATA_CHAR_UUID` | `12345678-...abd` | UUID de la characteristic de datos |
| `BLE_QR_REQ_CHAR_UUID` | `12345678-...abe` | UUID de la characteristic de request |
| `ACK_TIMEOUT_MS` | `15000` | Ms sin ACK antes de rearmar el QR |
| `SCAN_INTERVAL_MS` | `120` | Intervalo entre frames de cámara (ms) |
| `QR_DISAPPEAR_RESET_MS` | `1200` | Ms sin ver el QR para considerarlo nuevo |
| `CAMERA_WIDTH` | `1280` | Resolución horizontal de captura |
| `CAMERA_HEIGHT` | `720` | Resolución vertical de captura |
| `CAMERA_INDEX` | `0` | Índice de cámara OpenCV (solo si `CAMERA_BACKEND=opencv`) |
| `CAMERA_BACKEND` | `picamera2` | `picamera2` (Pi CSI) o `opencv` (USB/webcam) |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

---

## Despliegue en Raspberry Pi Zero 2

Probado en Raspberry Pi OS Bookworm con cámara CSI y Bluetooth integrado.

### 1. Dependencias del sistema

```bash
sudo apt update
sudo apt install -y \
  bluetooth bluez bluez-tools \
  python3-dbus python3-gi python3-opencv python3-picamera2 \
  python3-venv
```

### 2. Verificaciones previas

```bash
# Cámara
rpicam-hello -t 3000

# Bluetooth
bluetoothctl show
```

### 3. Habilitar modo experimental en BlueZ

Necesario para registrar un GATT server y advertisement personalizados.

```bash
sudo systemctl edit bluetooth
```

Añadir:

```ini
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd -E
```

```bash
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

### 4. Instalar el paquete

```bash
cd /home/pi/Tote/Rspi_QR_BLE
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
```

### 5. Probar manualmente

```bash
python -m rspi_qr_ble
```

Para el canal outbound:

```bash
BLE_DEVICE_NAME=QR-Reader-OUT python -m rspi_qr_ble
```

### 6. Instalar como servicio systemd

```bash
sudo cp systemd/rspi-qr-ble.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rspi-qr-ble.service
```

Verificar:

```bash
sudo systemctl status rspi-qr-ble
journalctl -u rspi-qr-ble -f
```

---

## Herramientas de desarrollo

### `tools/ble_tester.py` — Simula el cliente ESP32

Conecta como central BLE, envía `GET` y muestra la respuesta. Útil para validar el servidor sin necesidad del hardware ESP32.

```bash
pip install bleak>=0.22
python tools/ble_tester.py
```

### `tools/qr_debug_live.py` — Stream visual de detección QR

Muestra en tiempo real el overlay de detección (recuadro, texto decodificado, FPS).

Stream MJPEG desde laptop/navegador:

```bash
python tools/qr_debug_live.py --backend picamera2 --mode mjpeg --port 8081
# Abrir en navegador: http://<IP_DE_LA_PI>:8081
```

Ventana local (si hay monitor conectado a la Pi):

```bash
python tools/qr_debug_live.py --backend picamera2 --mode window
# Pulsar 'q' para salir
```

---

## Tests

```bash
pip install pytest
pytest tests/
```

Los tests cubren `QRBuffer` y `ScanGate` (lógica pura, sin hardware).

---

## Notas de campo

- El ajuste más crítico en producción es el enfoque/exposición de la cámara y la iluminación del área de escaneo.
- Si BlueZ rechaza el registro del GATT, revisar que el flag `-E` esté activo (`journalctl -u bluetooth`).
- El usuario que corre el servicio debe pertenecer al grupo `bluetooth` para acceder al D-Bus del sistema.
