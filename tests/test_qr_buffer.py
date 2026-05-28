from rspi_qr_ble.qr_buffer import NO_QR, QRBuffer


def test_request_without_qr_returns_no_qr():
    buffer = QRBuffer(ack_timeout_ms=1000)
    assert buffer.request_payload() == NO_QR


def test_ack_clears_only_after_send():
    buffer = QRBuffer(ack_timeout_ms=1000)
    buffer.store_scan("ABC")
    assert buffer.acknowledge() is False
    assert buffer.request_payload() == "ABC"
    assert buffer.acknowledge() is True
    assert buffer.current_value() == NO_QR
