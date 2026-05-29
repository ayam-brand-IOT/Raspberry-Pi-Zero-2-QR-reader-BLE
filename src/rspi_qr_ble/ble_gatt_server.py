from __future__ import annotations

import logging
from typing import Iterable, List

from .config import Settings
from .qr_buffer import NO_QR, QRBuffer


LOG = logging.getLogger(__name__)

BLUEZ_SERVICE_NAME = "org.bluez"
DBUS_OM_IFACE = "org.freedesktop.DBus.ObjectManager"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHRC_IFACE = "org.bluez.GattCharacteristic1"
ADAPTER_IFACE = "org.bluez.Adapter1"


def _to_dbus_bytes(text: str):
    import dbus

    return dbus.Array([dbus.Byte(b) for b in text.encode("utf-8")], signature="y")


class InvalidArgsException(Exception):
    pass


class NotSupportedException(Exception):
    pass


class FailedException(Exception):
    pass


class Application:
    def __init__(self, bus, path: str) -> None:
        self.bus = bus
        self.path = path
        self.services: List[Service] = []

    def get_path(self):
        import dbus

        return dbus.ObjectPath(self.path)

    def add_service(self, service: "Service") -> None:
        self.services.append(service)

    def get_managed_objects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            for characteristic in service.characteristics:
                response[characteristic.get_path()] = characteristic.get_properties()
        return response


class Service:
    PATH_BASE = "/org/bluez/rspi_qr_ble/service"

    def __init__(self, bus, index: int, uuid: str, primary: bool = True) -> None:
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics: List[Characteristic] = []

    def get_properties(self):
        import dbus

        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": dbus.Boolean(self.primary),
                "Characteristics": dbus.Array(self.get_characteristic_paths(), signature="o"),
            }
        }

    def get_path(self):
        import dbus

        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic: "Characteristic") -> None:
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self) -> Iterable:
        return [characteristic.get_path() for characteristic in self.characteristics]


class Characteristic:
    def __init__(self, bus, index: int, uuid: str, flags: List[str], service: Service) -> None:
        self.path = service.path + "/char" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.flags = flags
        self.service = service

    def get_properties(self):
        return {
            GATT_CHRC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    def get_path(self):
        import dbus

        return dbus.ObjectPath(self.path)


class QRDataCharacteristic(Characteristic):
    def __init__(self, bus, index: int, uuid: str, service: Service, qr_buffer: QRBuffer) -> None:
        super().__init__(bus, index, uuid, ["read", "notify"], service)
        self._buffer = qr_buffer
        self._notifying = False
        self._value = _to_dbus_bytes(NO_QR)

    def set_value(self, text: str) -> None:
        self._value = _to_dbus_bytes(text)

    def read_value(self):
        value = self._buffer.current_value()
        self.set_value(value)
        return self._value

    def start_notify(self) -> None:
        if self._notifying:
            return
        self._notifying = True
        LOG.info("[BLE] Notifications enabled")

    def stop_notify(self) -> None:
        self._notifying = False
        LOG.info("[BLE] Notifications disabled")

    def notify_value(self, text: str) -> None:
        self.set_value(text)
        if not self._notifying:
            LOG.info("[BLE] Client requested value but notifications are not enabled")
            return
        self.properties_changed({ "Value": self._value }, [])

    def properties_changed(self, changed, invalidated):
        pass


class QRRequestCharacteristic(Characteristic):
    def __init__(
        self,
        bus,
        index: int,
        uuid: str,
        service: Service,
        qr_buffer: QRBuffer,
        data_characteristic: QRDataCharacteristic,
    ) -> None:
        super().__init__(bus, index, uuid, ["write", "write-without-response"], service)
        self._buffer = qr_buffer
        self._data_characteristic = data_characteristic

    def write_value(self, value: bytes) -> None:
        text = value.decode("utf-8", errors="replace")
        LOG.info('[BLE] Write recibido: "%s"', text)

        if text == "ACK":
            if self._buffer.acknowledge():
                LOG.info("[BLE] ACK recibido - QR confirmado y buffer limpiado")
            return

        payload = self._buffer.request_payload()
        if payload == NO_QR:
            LOG.info("[BLE] Buffer vacio - enviado NO_QR")
        else:
            LOG.info("[BLE] QR enviado: %s", payload)
        self._data_characteristic.notify_value(payload)


class QRService(Service):
    def __init__(self, bus, index: int, settings: Settings, qr_buffer: QRBuffer) -> None:
        super().__init__(bus, index, settings.service_uuid, True)
        self.data_characteristic = QRDataCharacteristic(
            bus,
            0,
            settings.qr_data_char_uuid,
            self,
            qr_buffer,
        )
        self.request_characteristic = QRRequestCharacteristic(
            bus,
            1,
            settings.qr_req_char_uuid,
            self,
            qr_buffer,
            self.data_characteristic,
        )
        self.add_characteristic(self.data_characteristic)
        self.add_characteristic(self.request_characteristic)


class Advertisement:
    PATH_BASE = "/org/bluez/rspi_qr_ble/advertisement"

    def __init__(self, bus, index: int, settings: Settings) -> None:
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = "peripheral"
        self.local_name = settings.ble_device_name
        self.service_uuids = [settings.service_uuid]

    def get_properties(self):
        import dbus

        return {
            LE_ADVERTISEMENT_IFACE: {
                "Type": self.ad_type,
                "ServiceUUIDs": dbus.Array(self.service_uuids, signature="s"),
                "LocalName": dbus.String(self.local_name),
            }
        }

    def get_path(self):
        import dbus

        return dbus.ObjectPath(self.path)


def _find_adapter(bus):
    import dbus

    remote_om = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, "/"), DBUS_OM_IFACE)
    objects = remote_om.GetManagedObjects()

    fallback = None
    for path, interfaces in objects.items():
        if GATT_MANAGER_IFACE in interfaces:
            fallback = path
        if GATT_MANAGER_IFACE in interfaces and LE_ADVERTISING_MANAGER_IFACE in interfaces:
            return path
    return fallback


class BLEServer:
    def __init__(self, settings: Settings, qr_buffer: QRBuffer) -> None:
        self._settings = settings
        self._buffer = qr_buffer

    def run(self) -> None:  # pragma: no cover - runtime BLE path
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib

        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        bus = dbus.SystemBus()

        adapter_path = _find_adapter(bus)
        if not adapter_path:
            raise RuntimeError("No Bluetooth adapter with GATT manager was found")

        adapter_props = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), DBUS_PROP_IFACE)
        adapter_props.Set(ADAPTER_IFACE, "Powered", dbus.Boolean(1))

        app_path = "/org/bluez/rspi_qr_ble"

        class ManagedApplication(Application, dbus.service.Object):
            def __init__(self, bus, path: str):
                Application.__init__(self, bus, path)
                dbus.service.Object.__init__(self, bus, self.path)

            @dbus.service.method(DBUS_OM_IFACE, out_signature="a{oa{sa{sv}}}")
            def GetManagedObjects(self):
                return self.get_managed_objects()

        class ManagedDataCharacteristic(QRDataCharacteristic, dbus.service.Object):
            def __init__(self, bus, index: int, uuid: str, service: Service, qr_buffer: QRBuffer):
                QRDataCharacteristic.__init__(self, bus, index, uuid, service, qr_buffer)
                dbus.service.Object.__init__(self, bus, self.path)

            @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                if interface != GATT_CHRC_IFACE:
                    raise InvalidArgsException()
                return self.get_properties()[GATT_CHRC_IFACE]

            @dbus.service.method(GATT_CHRC_IFACE, in_signature="a{sv}", out_signature="ay")
            def ReadValue(self, _options):
                return self.read_value()

            @dbus.service.method(GATT_CHRC_IFACE)
            def StartNotify(self):
                self.start_notify()

            @dbus.service.method(GATT_CHRC_IFACE)
            def StopNotify(self):
                self.stop_notify()

            @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
            def PropertiesChanged(self, interface, changed, invalidated):
                pass

            def properties_changed(self, changed, invalidated):
                self.PropertiesChanged(GATT_CHRC_IFACE, changed, invalidated)

        class ManagedRequestCharacteristic(QRRequestCharacteristic, dbus.service.Object):
            def __init__(
                self,
                bus,
                index: int,
                uuid: str,
                service: Service,
                qr_buffer: QRBuffer,
                data_characteristic: QRDataCharacteristic,
            ):
                QRRequestCharacteristic.__init__(
                    self,
                    bus,
                    index,
                    uuid,
                    service,
                    qr_buffer,
                    data_characteristic,
                )
                dbus.service.Object.__init__(self, bus, self.path)

            @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                if interface != GATT_CHRC_IFACE:
                    raise InvalidArgsException()
                return self.get_properties()[GATT_CHRC_IFACE]

            @dbus.service.method(GATT_CHRC_IFACE, in_signature="aya{sv}", out_signature="")
            def WriteValue(self, value, _options):
                self.write_value(bytes(value))

        class ManagedService(Service, dbus.service.Object):
            def __init__(self, bus, index: int, settings: Settings, qr_buffer: QRBuffer):
                Service.__init__(self, bus, index, settings.service_uuid, True)
                dbus.service.Object.__init__(self, bus, self.path)
                self.data_characteristic = ManagedDataCharacteristic(
                    bus,
                    0,
                    settings.qr_data_char_uuid,
                    self,
                    qr_buffer,
                )
                self.request_characteristic = ManagedRequestCharacteristic(
                    bus,
                    1,
                    settings.qr_req_char_uuid,
                    self,
                    qr_buffer,
                    self.data_characteristic,
                )
                self.add_characteristic(self.data_characteristic)
                self.add_characteristic(self.request_characteristic)

            @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                if interface != GATT_SERVICE_IFACE:
                    raise InvalidArgsException()
                return self.get_properties()[GATT_SERVICE_IFACE]

        class ManagedAdvertisement(Advertisement, dbus.service.Object):
            def __init__(self, bus, index: int, settings: Settings):
                Advertisement.__init__(self, bus, index, settings)
                dbus.service.Object.__init__(self, bus, self.path)

            @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
            def GetAll(self, interface):
                if interface != LE_ADVERTISEMENT_IFACE:
                    raise InvalidArgsException()
                return self.get_properties()[LE_ADVERTISEMENT_IFACE]

            @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
            def Release(self):
                LOG.info("[BLE] Advertisement released")

        app = ManagedApplication(bus, app_path)
        service = ManagedService(bus, 0, self._settings, self._buffer)
        app.add_service(service)
        ad = ManagedAdvertisement(bus, 0, self._settings)

        gatt_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), GATT_MANAGER_IFACE)
        ad_manager = dbus.Interface(bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), LE_ADVERTISING_MANAGER_IFACE)

        loop = GLib.MainLoop()

        def _tick_ack_timeout():
            if self._buffer.rearm_if_timed_out():
                LOG.info("[BLE] ACK timeout - QR rearmado para proximo request")
            return True

        GLib.timeout_add(500, _tick_ack_timeout)

        def _on_app_registered():
            LOG.info("[BLE] GATT application registered")

        def _on_app_error(error):
            LOG.error("Failed to register GATT application: %s", error)
            loop.quit()

        def _on_ad_registered():
            LOG.info("[BLE] Advertising activo - nombre: %s", self._settings.ble_device_name)

        def _on_ad_error(error):
            LOG.error("Failed to register advertisement: %s", error)
            loop.quit()

        gatt_manager.RegisterApplication(app.get_path(), {}, reply_handler=_on_app_registered, error_handler=_on_app_error)
        ad_manager.RegisterAdvertisement(ad.get_path(), {}, reply_handler=_on_ad_registered, error_handler=_on_ad_error)

        LOG.info("[SYS] Esperando escaneo de QR...")
        loop.run()
