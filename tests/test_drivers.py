import threading
import time

import numpy as np
import pytest

import hp3458a_studio.drivers as driver_module
from hp3458a_studio.connection_diagnostics import (
    ConnectionIssueCode,
    inspect_visa_environment,
)
from hp3458a_studio.drivers import (
    AcquisitionConfig,
    Fluke8508ADriver,
    InstrumentError,
    Keysight3458ADriver,
    MeasurementFunction,
    ScpiDmmDriver,
    SimulatorDriver,
    choose_gpib_assignments,
    discover_visa_resources,
    gpib_instrument_resources,
    is_gpib_instrument_resource,
    parse_ascii_values,
)
from hp3458a_studio.models import InstrumentModel


def test_parse_3458a_ascii_payload():
    values = parse_ascii_values(b"+1.0000001E+01\r\n+9.9999998E+00\r\n")
    assert np.allclose(values, [10.000001, 9.9999998])


def test_only_gpib_instrument_resources_are_offered_for_3458a():
    resources = [
        "USB0::0x2A8D::0x0201::MY60075067::0::INSTR",
        "GPIB0::22::INSTR",
        "TCPIP0::192.0.2.1::inst0::INSTR",
        "GPIB1::7::0::INSTR",
    ]
    assert gpib_instrument_resources(resources) == [
        "GPIB0::22::INSTR",
        "GPIB1::7::0::INSTR",
    ]
    assert is_gpib_instrument_resource(" gpib0::22::instr ")
    assert not is_gpib_instrument_resource(resources[0])


def test_scan_assignments_replace_stale_addresses():
    assignments = choose_gpib_assignments(
        ["GPIB0::22::INSTR", "GPIB0::23::INSTR"],
        {
            "A": "GPIB0::21::INSTR",
            "B": "GPIB0::22::INSTR",
        },
    )
    assert assignments == {
        "A": "GPIB0::22::INSTR",
        "B": "GPIB0::23::INSTR",
    }


def test_scan_assignments_do_not_move_a_running_channel():
    assignments = choose_gpib_assignments(
        ["GPIB0::22::INSTR", "GPIB0::23::INSTR"],
        {
            "A": "GPIB0::22::INSTR",
            "B": "GPIB0::21::INSTR",
        },
        running_channels={"A"},
    )
    assert assignments == {
        "A": "GPIB0::22::INSTR",
        "B": "GPIB0::23::INSTR",
    }


def test_scan_assignments_keep_reserved_c_unique_when_only_two_are_found():
    assignments = choose_gpib_assignments(
        ["GPIB0::21::INSTR", "GPIB1::22::INSTR"],
        {
            "A": "GPIB0::21::INSTR",
            "B": "GPIB1::22::INSTR",
            "C": "GPIB2::23::INSTR",
        },
    )
    assert assignments == {
        "A": "GPIB0::21::INSTR",
        "B": "GPIB1::22::INSTR",
        "C": "GPIB2::23::INSTR",
    }


def test_3458a_driver_rejects_usb_resource_before_opening_visa(monkeypatch):
    manager_opened = False

    def open_manager(_backend):
        nonlocal manager_opened
        manager_opened = True
        raise AssertionError("VISA manager must not open for a USB resource")

    monkeypatch.setattr(driver_module.pyvisa, "ResourceManager", open_manager)
    driver = Keysight3458ADriver("USB0::0x2A8D::0x0201::MY60075067::0::INSTR")
    try:
        driver.connect()
    except InstrumentError as exc:
        assert "3458A 只支持 GPIB" in str(exc)
        assert "GPIB0::22::INSTR" in str(exc)
    else:
        raise AssertionError("USB resource must be rejected")
    assert not manager_opened


def test_simulator_identity_and_reading():
    config = AcquisitionConfig(
        function=MeasurementFunction.DC_VOLTAGE,
        measurement_range="10",
        nplc=10,
    )
    driver = SimulatorDriver(config)
    identity = driver.connect()
    driver.configure(config)
    reading = driver.read_single(include_temperature=True)
    driver.disconnect()
    assert "3458A" in identity.model
    assert reading.unit == "V"
    assert 9.9 < reading.value < 10.1
    assert 20 < reading.internal_temperature_c < 30


def test_simulator_burst():
    driver = SimulatorDriver()
    driver.connect()
    x, y = driver.acquire_burst(1000, 0.001, 0.0001)
    driver.disconnect()
    assert x.shape == (1000,)
    assert y.shape == (1000,)
    assert np.isclose(x[1] - x[0], 0.001)


def test_simulator_burst_uses_explicit_function_without_reconfiguring_precision():
    driver = SimulatorDriver(AcquisitionConfig(function=MeasurementFunction.DC_CURRENT))
    driver.connect()
    try:
        _, y = driver.acquire_burst(
            count=1000,
            interval_s=0.001,
            aperture_s=0.0001,
            function=MeasurementFunction.DIGITIZE_DC,
            measurement_range="10",
        )
        assert np.isclose(np.mean(y), 1.0, atol=0.001)
        assert driver.config.function is MeasurementFunction.DC_CURRENT
    finally:
        driver.disconnect()


class _FakeVisaInstrument:
    def __init__(self):
        self.timeout = 0
        self.write_termination = None
        self.read_termination = None
        self.commands = []
        self.last_command = ""
        self.closed = False

    def clear(self):
        pass

    def write(self, command):
        self.commands.append(command)
        self.last_command = command

    def read(self):
        responses = {
            "ID?": "HEWLETT-PACKARD,3458A",
            "REV?": "9.2,9.1",
            "OPT?": "1",
            "LINE?": "50",
            "ERR?": "0",
            "TRIG SGL": "+1.00000001E+01",
            "TEMP?": "23.42",
        }
        return responses[self.last_command]

    def close(self):
        self.closed = True


class _FakeVisaManager:
    def __init__(self, instrument):
        self.instrument = instrument
        self.closed = False

    def open_resource(self, _resource_name):
        return self.instrument

    def close(self):
        self.closed = True


def test_real_driver_uses_3458a_language_not_scpi(monkeypatch):
    instrument = _FakeVisaInstrument()
    manager = _FakeVisaManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    config = AcquisitionConfig(
        function=MeasurementFunction.DC_VOLTAGE,
        measurement_range="10",
        nplc=100,
        digits=8,
        autozero="ON",
        sample_interval_s=1.0,
    )
    driver = Keysight3458ADriver("GPIB0::22::INSTR", config)
    identity = driver.connect()
    driver.configure(config)
    reading = driver.read_single(include_temperature=True)
    driver.disconnect()

    all_commands = ";".join(instrument.commands)
    assert identity.model == "HEWLETT-PACKARD,3458A"
    assert "ID?" in instrument.commands
    assert "*IDN?" not in all_commands
    assert "DCV 10" in all_commands
    assert "NPLC 100" in all_commands
    assert "TRIG SGL" in instrument.commands
    assert np.isclose(reading.value, 10.0000001)
    assert np.isclose(reading.internal_temperature_c, 23.42)
    assert instrument.closed


def test_connect_continues_when_visa_clear_is_rejected(monkeypatch):
    instrument = _FakeVisaInstrument()

    def reject_clear():
        raise RuntimeError("VI_ERROR_NLISTENERS (-1073807265): No listeners condition")

    instrument.clear = reject_clear
    manager = _FakeVisaManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )

    driver = Keysight3458ADriver("GPIB0::22::INSTR")
    identity = driver.connect()
    driver.disconnect()

    assert identity.model == "HEWLETT-PACKARD,3458A"
    assert "ID?" in instrument.commands


def test_cancel_pending_io_closes_active_visa_session(monkeypatch):
    instrument = _FakeVisaInstrument()
    manager = _FakeVisaManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    driver = Keysight3458ADriver("GPIB0::22::INSTR")
    driver.connect()

    driver.cancel_pending_io()
    driver.disconnect()

    assert instrument.closed
    assert driver._instrument is None
    assert manager.closed


def test_two_connections_on_one_gpib_bus_are_serialized(monkeypatch):
    state_lock = threading.Lock()
    state = {"active": 0, "maximum": 0}

    class SlowInstrument(_FakeVisaInstrument):
        def _enter_transfer(self):
            with state_lock:
                state["active"] += 1
                state["maximum"] = max(state["maximum"], state["active"])
            time.sleep(0.002)

        def _leave_transfer(self):
            with state_lock:
                state["active"] -= 1

        def clear(self):
            self._enter_transfer()
            try:
                return super().clear()
            finally:
                self._leave_transfer()

        def write(self, command):
            self._enter_transfer()
            try:
                return super().write(command)
            finally:
                self._leave_transfer()

        def read(self):
            self._enter_transfer()
            try:
                return super().read()
            finally:
                self._leave_transfer()

    instruments = {
        "GPIB0::22::INSTR": SlowInstrument(),
        "GPIB0::23::INSTR": SlowInstrument(),
    }

    class SharedManager:
        def open_resource(self, resource_name):
            return instruments[resource_name]

        def close(self):
            pass

    manager = SharedManager()
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    drivers = [
        Keysight3458ADriver("GPIB0::22::INSTR"),
        Keysight3458ADriver("GPIB0::23::INSTR"),
    ]

    threads = [threading.Thread(target=driver.connect) for driver in drivers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    for driver in drivers:
        driver.disconnect()

    assert state["maximum"] == 1


class _MixedVisaInstrument(_FakeVisaInstrument):
    def __init__(self, idn):
        super().__init__()
        self.idn = idn

    def write(self, command):
        if self.closed:
            raise InstrumentError("VISA session closed")
        super().write(command)

    def read(self):
        if self.closed:
            raise InstrumentError("VISA session closed")
        return {
            "*IDN?": self.idn,
            "SYST:LFREQ?": "50",
            "READ?": "10.000001",
            "X?": "5.000001",
        }.get(self.last_command) or super().read()


class _SharedVisaManager:
    """Model PyVISA: one cached manager closes all its resource sessions."""

    def __init__(self):
        self.instruments = {
            "GPIB0::22::INSTR": _MixedVisaInstrument("HEWLETT-PACKARD,3458A"),
            "GPIB0::23::INSTR": _MixedVisaInstrument("KEYSIGHT,34470A,SN,1.0"),
            "GPIB0::24::INSTR": _MixedVisaInstrument("FLUKE,8508A,SN,1.0"),
        }
        self.close_calls = 0
        self.fail_discovery = False

    def open_resource(self, resource):
        if resource not in self.instruments:
            raise InstrumentError("No listener")
        return self.instruments[resource]

    def list_resources(self, query="?*::INSTR"):
        if self.fail_discovery:
            raise RuntimeError("VISA enumeration failed")
        if query == "?*":
            return ("GPIB0::INTFC", *self.instruments)
        return tuple(self.instruments)

    def close(self):
        self.close_calls += 1
        for instrument in self.instruments.values():
            instrument.close()


def test_three_mixed_drivers_survive_peer_stop_scan_and_connection_check(monkeypatch):
    manager = _SharedVisaManager()
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    drivers = [
        Keysight3458ADriver("GPIB0::22::INSTR"),
        ScpiDmmDriver(
            "GPIB0::23::INSTR", InstrumentModel.KEYSIGHT_34470A, visa_backend="@alias"
        ),
        Fluke8508ADriver("GPIB0::24::INSTR"),
    ]
    try:
        for driver in drivers:
            driver.connect()
        drivers[0].disconnect()
        assert manager.close_calls == 0
        assert discover_visa_resources() == list(manager.instruments)
        diagnostic = inspect_visa_environment(
            "GPIB0::24::INSTR", InstrumentModel.FLUKE_8508A
        )
        assert diagnostic.ok
        assert manager.close_calls == 0
        assert np.isclose(drivers[1].read_single().value, 10.000001)
        assert np.isclose(drivers[2].read_single().value, 5.000001)
        drivers[1].disconnect()
        assert manager.close_calls == 0
        assert np.isclose(drivers[2].read_single().value, 5.000001)
    finally:
        for driver in drivers:
            driver.disconnect()
    assert manager.close_calls == 1


def test_failed_connection_releases_lease_without_closing_running_peer(monkeypatch):
    manager = _SharedVisaManager()
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    running = Keysight3458ADriver("GPIB0::22::INSTR")
    failing = Fluke8508ADriver("GPIB0::25::INSTR")
    running.connect()
    try:
        with pytest.raises(InstrumentError):
            failing.connect()
        assert manager.close_calls == 0
        assert np.isclose(running.read_single().value, 10.0000001)
    finally:
        failing.disconnect()
        running.disconnect()
    assert manager.close_calls == 1


def test_failed_scan_and_injected_preflight_keep_running_session_open(monkeypatch):
    manager = _SharedVisaManager()
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    running = Keysight3458ADriver("GPIB0::22::INSTR")
    running.connect()
    try:
        manager.fail_discovery = True
        assert discover_visa_resources() == []
        diagnostic = inspect_visa_environment(
            "GPIB0::22::INSTR",
            InstrumentModel.KEYSIGHT_3458A,
            manager_factory=lambda: manager,
        )
        assert diagnostic.code is ConnectionIssueCode.VISA_DISCOVERY_FAILED
        assert manager.close_calls == 0
        assert np.isclose(running.read_single().value, 10.0000001)
    finally:
        running.disconnect()
    assert manager.close_calls == 1


def test_failed_discovery_without_drivers_still_closes_manager(monkeypatch):
    manager = _SharedVisaManager()
    manager.fail_discovery = True
    monkeypatch.setattr(
        driver_module.pyvisa, "ResourceManager", lambda _backend: manager
    )
    assert discover_visa_resources() == []
    assert manager.close_calls == 1
