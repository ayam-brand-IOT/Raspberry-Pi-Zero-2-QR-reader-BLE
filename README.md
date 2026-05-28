# Rspi_QR_BLE

Reemplazo compatible del proyecto `QR-Reader-BLE` para Raspberry Pi Zero 2 + camara.

Este proyecto expone el mismo contrato BLE que el ESP32:

- Nombre BLE por defecto: `QR-Reader`
- Service UUID: `12345678-1234-1234-1234-123456789abc`
- QR data characteristic: `12345678-1234-1234-1234-123456789abd`
- Request characteristic: `12345678-1234-1234-1234-123456789abe`

Semantica compatible:

- El cliente escribe `GET` en la characteristic de request.
- El servidor responde por `NOTIFY` en la characteristic de data.
- Si hay QR en buffer, envia el texto del QR.
- Si no hay QR en buffer, envia `NO_QR`.
- El cliente escribe `ACK` para confirmar que ya proceso el QR y limpiar el buffer.
- Si no llega `ACK` en `ACK_TIMEOUT_MS`, el QR queda rearmado para el siguiente `GET`.

## Arquitectura elegida

Para Raspberry Pi Zero 2 use una implementacion Linux-native:

- **BLE peripheral/GATT server**: `bluez` sobre D-Bus (`python3-dbus` + `python3-gi`)
- **Camara**: `Picamera2` en Raspberry Pi OS Bookworm/Bullseye
- **QR detection**: `OpenCV QRCodeDetector`

Razones:

- Mantiene compatibilidad BLE real con el cliente ESP32 actual.
- Evita depender de librerias BLE de Python menos estables para modo peripheral.
- `Picamera2` es la ruta oficial moderna en Raspberry Pi OS.
- `QRCodeDetector` evita depender de `zbar`/`pyzbar`.

## Estructura

```text
Rspi_QR_BLE/
├── pyproject.toml
├── requirements-dev.txt
├── README.md
├── tools/
│   ├── ble_tester.py
│   └── qr_debug_live.py
├── systemd/
│   └── rspi-qr-ble.service
└── src/
    └── rspi_qr_ble/
        ├── __init__.py
        ├── __main__.py
        ├── app.py
        ├── ble_gatt_server.py
        ├── camera_scanner.py
        ├── config.py
        ├── qr_buffer.py
        └── scan_gate.py
```

## Compatibilidad con el ESP actual

Este proyecto fue hecho para ser reemplazable frente a los clientes BLE del repo (`tote_inbound` y `tote_outbound`):

- mismo nombre BLE por defecto
- mismos UUIDs
- mismo `GET` / `ACK`
- misma respuesta `NO_QR`
- mismo patron de "buffer de ultimo QR"

Tambien soporta cambiar el nombre BLE por variable de entorno para el caso outbound:

```bash
BLE_DEVICE_NAME=QR-Reader-OUT
```

## Comportamiento importante frente a una camara

Con UART, el lector GM69Pro entrega un evento por escaneo.

Con camara, el mismo QR puede aparecer durante muchos frames seguidos. Para que se comporte como el ESP:

- el proyecto **no vuelve a bufferizar el mismo QR en cada frame**
- el mismo QR solo vuelve a emitirse si desaparece de camara durante un tiempo configurable

Eso evita que:

- el buffer se sobrescriba miles de veces
- el `ACK` quede inutil
- un QR quieto enfrente de la camara se reprograme continuamente

## Configuracion por entorno

Variables principales:

```bash
BLE_DEVICE_NAME=QR-Reader
BLE_SERVICE_UUID=12345678-1234-1234-1234-123456789abc
BLE_QR_DATA_CHAR_UUID=12345678-1234-1234-1234-123456789abd
BLE_QR_REQ_CHAR_UUID=12345678-1234-1234-1234-123456789abe

ACK_TIMEOUT_MS=15000
SCAN_INTERVAL_MS=120
QR_DISAPPEAR_RESET_MS=1200

CAMERA_WIDTH=1280
CAMERA_HEIGHT=720
CAMERA_INDEX=0
CAMERA_BACKEND=picamera2

LOG_LEVEL=INFO
```

## Desarrollo local

Si quieres probar el comportamiento BLE desde otra maquina Linux:

```bash
python tools/ble_tester.py
```

## Herramienta de debug visual en vivo

Para depurar como detecta y decodifica QR en tiempo real, usa:

```bash
python tools/qr_debug_live.py --backend picamera2 --mode mjpeg --port 8081
```

Abre desde tu laptop:

```text
http://IP_DE_LA_PI:8081
```

La vista muestra:

- recuadro del QR detectado
- texto decodificado sobre la imagen
- FPS y numero de detecciones
- logs en consola cuando aparece un QR nuevo

Si tienes monitor conectado a la Pi, tambien puedes usar ventana local:

```bash
python tools/qr_debug_live.py --backend picamera2 --mode window
```

Pulsa `q` para salir.

## Pasos para correrlo en tu Raspberry Pi Zero 2

Asumo Raspberry Pi OS Bookworm o Bullseye, Bluetooth integrado funcional y una camara CSI soportada por `Picamera2`.

1. Instala paquetes del sistema:

```bash
sudo apt update
sudo apt install -y \
  bluetooth bluez bluez-tools \
  python3-dbus python3-gi python3-opencv python3-picamera2 \
  python3-venv
```

2. Verifica que la camara funcione:

```bash
rpicam-hello -t 3000
```

3. Verifica que Bluetooth este activo:

```bash
bluetoothctl show
```

4. Si BlueZ no te deja registrar advertising/GATT custom, habilita modo experimental en `bluetoothd`.
   En Raspberry Pi OS normalmente esto se hace creando un override del servicio:

```bash
sudo systemctl edit bluetooth
```

Y agrega:

```ini
[Service]
ExecStart=
ExecStart=/usr/libexec/bluetooth/bluetoothd -E
```

Si tu sistema usa otra ruta de `bluetoothd`, ajustala. Luego:

```bash
sudo systemctl daemon-reload
sudo systemctl restart bluetooth
```

5. Entra al proyecto:

```bash
cd /ruta/a/Tote/Rspi_QR_BLE
```

6. Crea un entorno virtual que vea los paquetes `apt` del sistema:

```bash
python3 -m venv --system-site-packages .venv
source .venv/bin/activate
pip install -e .
```

Si tambien quieres usar el tester BLE de este proyecto desde la misma Pi o desde otra maquina Python:

```bash
pip install -r requirements-dev.txt
```

7. Ejecuta el servidor:

```bash
python -m rspi_qr_ble
```

8. Si quieres usarlo como reemplazo del lector outbound:

```bash
BLE_DEVICE_NAME=QR-Reader-OUT python -m rspi_qr_ble
```

9. Prueba desde el tester BLE o desde `tote_inbound` / `tote_outbound`.

10. Si quieres dejarlo como servicio:

```bash
sudo cp systemd/rspi-qr-ble.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rspi-qr-ble.service
```

## Notas

- No pude probar hardware real de camara/BLE desde este workspace.
- El contrato BLE si quedo alineado con `QR-Reader-BLE`.
- La parte mas sensible en campo probablemente sera:
  - enfoque/exposicion de la camara
  - iluminacion
  - permisos/flags de BlueZ para advertising/GATT
