from rspi_qr_ble.scan_gate import ScanGate


def test_same_code_emits_once_until_absent():
    gate = ScanGate(disappear_reset_ms=1000)
    now = 10.0

    assert gate.observe("HELLO", now=now) == "HELLO"
    assert gate.observe("HELLO", now=now + 0.1) is None
    assert gate.observe(None, now=now + 0.5) is None
    assert gate.observe(None, now=now + 1.2) is None
    assert gate.observe("HELLO", now=now + 1.3) == "HELLO"


def test_different_code_emits_immediately():
    gate = ScanGate(disappear_reset_ms=1000)
    now = 20.0

    assert gate.observe("A", now=now) == "A"
    assert gate.observe("B", now=now + 0.1) == "B"
