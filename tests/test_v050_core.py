from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from hp3458a_studio import drivers as driver_module
from hp3458a_studio.drivers import (
    SCPI_DMM_PROFILES,
    AcquisitionConfig,
    Fluke8508ADriver,
    Keysight34470ADriver,
    ScpiDmmDriver,
    gpib_instrument_resources,
    visa_instrument_resources,
)
from hp3458a_studio.models import (
    InstrumentModel,
    Measurement,
    MeasurementFunction,
    SessionData,
)
from hp3458a_studio.persistence import (
    DurableSessionWriter,
    list_recovery_files,
)
from hp3458a_studio.trend_logic import assign_unit_axes


def test_mixed_physical_units_receive_independent_axes() -> None:
    channels, units = assign_unit_axes({"A": "V", "B": "Ω", "C": "A"})
    assert channels == {"A": 0, "B": 1, "C": 2}
    assert units == {"V": 0, "Ω": 1, "A": 2}


def test_equal_units_share_an_axis_without_losing_channel_identity() -> None:
    channels, units = assign_unit_axes({"A": "V", "B": "V", "C": "A"})
    assert channels == {"A": 0, "B": 0, "C": 1}
    assert units == {"V": 0, "A": 1}


def test_session_wall_clock_axis_uses_real_timestamps() -> None:
    start = datetime(2026, 7, 24, 1, 2, 3, tzinfo=timezone.utc)
    session = SessionData()
    for index in range(3):
        session.append(
            Measurement(
                elapsed_s=index * 0.25,
                value=float(index),
                unit="V",
                timestamp=start + timedelta(seconds=index * 0.25),
            )
        )
    np.testing.assert_allclose(
        session.wall_clock_x,
        np.asarray([start.timestamp() + index * 0.25 for index in range(3)]),
    )


def test_durable_writer_retains_partial_capture_and_finalizes(
    tmp_path,
) -> None:
    writer = DurableSessionWriter(
        channel="B",
        instrument_model="Keysight 34470A",
        resource="USB0::DMM::INSTR",
        run_id="test-run",
        root=tmp_path,
    )
    reading = Measurement(
        elapsed_s=0.1,
        value=123.456,
        unit="Ω",
        timestamp=datetime.now(timezone.utc),
    )
    writer.append(reading)
    assert writer.partial_path.exists()
    assert list_recovery_files(tmp_path)[0].path == writer.partial_path
    assert "123.456" in writer.partial_path.read_text(encoding="utf-8")

    output = writer.finalize("completed")
    assert output.exists()
    assert not writer.partial_path.exists()
    assert list_recovery_files(tmp_path) == []
    metadata = writer.metadata_path.read_text(encoding="utf-8")
    assert '"samples": 1' in metadata
    assert '"status": "completed"' in metadata


def test_resource_discovery_keeps_usb_lan_for_scpi_but_3458a_stays_gpib() -> None:
    resources = [
        "GPIB0::21::INSTR",
        "USB0::0x2A8D::0x0201::MY123::0::INSTR",
        "TCPIP0::192.0.2.10::inst0::INSTR",
        "ASRL1::INSTR",
    ]
    assert visa_instrument_resources(resources) == resources
    assert gpib_instrument_resources(resources) == ["GPIB0::21::INSTR"]


def test_model_catalog_covers_ten_manufacturers_and_fourteen_models() -> None:
    assert len(InstrumentModel) == 14
    assert len({model.manufacturer for model in InstrumentModel}) == 10
    assert len(SCPI_DMM_PROFILES) == 12
    assert set(SCPI_DMM_PROFILES) == {
        model for model in InstrumentModel if model.uses_scpi_commands
    }
    assert InstrumentModel.FLUKE_8508A.requires_gpib is True
    assert InstrumentModel.FLUKE_8508A.uses_scpi_commands is False
    assert InstrumentModel.FLUKE_8588A.nplc_bounds == (0.0, 600.0)
    assert InstrumentModel.FLUKE_8508A.supports_autozero_control is False
    assert InstrumentModel.FLUKE_8588A.supports_autozero_control is False
    assert InstrumentModel.HIOKI_DM7276.supported_functions == (
        MeasurementFunction.DC_VOLTAGE,
    )
    assert MeasurementFunction.FREQUENCY not in (
        InstrumentModel.FLUKE_8508A.supported_functions
    )


class _Fake34470AInstrument:
    def __init__(self):
        self.timeout = 0
        self.write_termination = ""
        self.read_termination = ""
        self.commands: list[str] = []
        self.last_command = ""
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)
        self.last_command = command

    def read(self) -> str:
        return {
            "*IDN?": "KEYSIGHT TECHNOLOGIES,34470A,MY123,A.03.03",
            "SYST:LFREQ?": "60",
            "SYST:ERR?": '+0,"No error"',
            "READ?": "1.23456789",
        }[self.last_command]

    def close(self) -> None:
        self.closed = True


class _Fake34470AManager:
    def __init__(self, instrument):
        self.instrument = instrument

    def open_resource(self, _resource_name):
        return self.instrument

    def close(self) -> None:
        pass


def test_34470a_scpi_adapter_configures_and_reads(monkeypatch) -> None:
    instrument = _Fake34470AInstrument()
    manager = _Fake34470AManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa,
        "ResourceManager",
        lambda _backend: manager,
    )
    config = AcquisitionConfig(
        function=MeasurementFunction.DC_VOLTAGE,
        measurement_range="AUTO",
        nplc=10,
        autozero="ON",
    )
    driver = Keysight34470ADriver("USB0::DMM::INSTR", config)
    identity = driver.connect()
    driver.configure(config)
    reading = driver.read_single()
    driver.disconnect()

    assert "34470A" in identity.model
    assert InstrumentModel.KEYSIGHT_34470A.supports_burst is False
    assert "CONF:VOLT:DC" in instrument.commands
    assert "SENS:VOLT:DC:RANG:AUTO ON" in instrument.commands
    assert "SENS:VOLT:DC:NPLC 10" in instrument.commands
    assert "SENS:VOLT:DC:ZERO:AUTO ON" in instrument.commands
    assert instrument.commands[-1] == "READ?"
    assert reading.value == 1.23456789
    assert reading.unit == "V"


class _FakeScpiInstrument:
    def __init__(self, idn: str):
        self.idn = idn
        self.timeout = 0
        self.write_termination = ""
        self.read_termination = ""
        self.commands: list[str] = []
        self.last_command = ""
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)
        self.last_command = command

    def read(self) -> str:
        if self.last_command == "*IDN?":
            return self.idn
        if self.last_command == "SYST:LFREQ?":
            return "50"
        if self.last_command == "SYST:ERR?":
            return '+0,"No error"'
        if self.last_command == "SYST:ERR:NEXT?":
            return '0,"No error"'
        if self.last_command == "SYST:TEMP?":
            return "24.25,25.00"
        if self.last_command == "READ? TEMP":
            return "9.87654321,23.5"
        if self.last_command == "READ?":
            return "9.87654321"
        raise AssertionError(f"Unexpected query: {self.last_command}")

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("model", "idn"),
    [
        (
            InstrumentModel.KEYSIGHT_34465A,
            "KEYSIGHT TECHNOLOGIES,34465A,MY1,A.03",
        ),
        (
            InstrumentModel.KEYSIGHT_34470A,
            "KEYSIGHT TECHNOLOGIES,34470A,MY1,A.03",
        ),
        (InstrumentModel.FLUKE_8588A, "FLUKE,8588A,1234567890,2.10"),
        (InstrumentModel.FLUKE_8846A, "FLUKE,8846A,123,2.0"),
        (
            InstrumentModel.KEITHLEY_DMM7510,
            "KEITHLEY INSTRUMENTS,DMM7510,123,1.7",
        ),
        (
            InstrumentModel.ROHDE_SCHWARZ_HMC8012,
            "ROHDE&SCHWARZ,HMC8012,123,3.2",
        ),
        (InstrumentModel.RIGOL_DM3068, "RIGOL TECHNOLOGIES,DM3068,123,1.0"),
        (
            InstrumentModel.SIGLENT_SDM3065X,
            "SIGLENT TECHNOLOGIES,SDM3065X,123,1.0",
        ),
        (
            InstrumentModel.GW_INSTEK_GDM9061,
            "GW INSTEK,GDM-9061,123,1.0",
        ),
        (InstrumentModel.HIOKI_DM7276, "HIOKI,DM7276-03,123,V1.00"),
        (InstrumentModel.YOKOGAWA_DM7560, "YOKOGAWA,DM7560,123,1.0"),
        (InstrumentModel.PICOTEST_M3510A, "PICOTEST,M3510A,123,1.0"),
    ],
)
def test_all_scpi_profiles_verify_identity_configure_and_read(
    monkeypatch,
    model: InstrumentModel,
    idn: str,
) -> None:
    instrument = _FakeScpiInstrument(idn)
    manager = _Fake34470AManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa,
        "ResourceManager",
        lambda _backend: manager,
    )
    config = AcquisitionConfig(
        function=MeasurementFunction.DC_VOLTAGE,
        measurement_range="AUTO",
        nplc=10,
        autozero="ON",
    )
    driver = ScpiDmmDriver("USB0::DMM::INSTR", model, config)
    identity = driver.connect()
    driver.configure(config)
    reading = driver.read_single(include_temperature=True)
    driver.disconnect()

    assert model.short_name.upper().replace("-", "") in (
        identity.model.upper().replace("-", "")
    )
    assert instrument.commands[0] == "*IDN?"
    assert any(command.startswith("READ?") for command in instrument.commands)
    assert reading.value == 9.87654321
    assert reading.unit == "V"
    if model is InstrumentModel.HIOKI_DM7276:
        assert reading.internal_temperature_c == 23.5
    if model is InstrumentModel.FLUKE_8588A:
        assert reading.internal_temperature_c == 24.25
        assert "TRIG:COUN 1" in instrument.commands
        assert "SAMP:COUN 1" not in instrument.commands
        assert not any("ZERO:AUTO" in item for item in instrument.commands)


class _Fake8508AInstrument:
    def __init__(self, idn: str = "FLUKE,8508A,1234567,1.20"):
        self.idn = idn
        self.timeout = 0
        self.write_termination = ""
        self.read_termination = ""
        self.commands: list[str] = []
        self.last_command = ""
        self.closed = False

    def write(self, command: str) -> None:
        self.commands.append(command)
        self.last_command = command

    def read(self) -> str:
        return {
            "*IDN?": self.idn,
            "*ESR?": "0",
            "X?": "1.234567890E+01",
        }[self.last_command]

    def close(self) -> None:
        self.closed = True


def test_8508a_native_ieee488_driver_uses_documented_commands(
    monkeypatch,
) -> None:
    instrument = _Fake8508AInstrument()
    manager = _Fake34470AManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa,
        "ResourceManager",
        lambda _backend: manager,
    )
    config = AcquisitionConfig(
        function=MeasurementFunction.DC_VOLTAGE,
        measurement_range="AUTO",
        nplc=1000,
        digits=8,
        autozero="ON",
    )
    driver = Fluke8508ADriver("GPIB0::7::INSTR", config)
    identity = driver.connect()
    driver.configure(config)
    reading = driver.read_single(include_temperature=True)
    driver.disconnect()

    assert "8508A" in identity.model
    assert "DCV AUTO,FILT_OFF,RESL8,FAST_OFF,TWO_WR" in instrument.commands
    assert "TRG_SRCE EXT" in instrument.commands
    assert instrument.commands[-1] == "X?"
    assert not any(command.startswith("CONF:") for command in instrument.commands)
    assert not any(command == "READ?" for command in instrument.commands)
    assert reading.value == 12.3456789
    assert reading.unit == "V"


@pytest.mark.parametrize(
    ("function", "expected"),
    [
        (
            MeasurementFunction.RESISTANCE_4W,
            "OHMS 100,FILT_OFF,RESL7,FAST_ON,FOUR_WR,LOI_OFF",
        ),
        (
            MeasurementFunction.AC_CURRENT,
            "ACI AUTO,FILT40HZ,ACCP,RESL6",
        ),
    ],
)
def test_8508a_function_capabilities_and_command_mapping(
    monkeypatch,
    function: MeasurementFunction,
    expected: str,
) -> None:
    instrument = _Fake8508AInstrument()
    manager = _Fake34470AManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa,
        "ResourceManager",
        lambda _backend: manager,
    )
    config = AcquisitionConfig(
        function=function,
        measurement_range=(
            "100" if function is MeasurementFunction.RESISTANCE_4W else "AUTO"
        ),
        nplc=64,
        digits=7,
    )
    driver = Fluke8508ADriver("GPIB0::7::INSTR", config)
    driver.connect()
    driver.configure(config)
    driver.disconnect()
    assert expected in instrument.commands


def test_8508a_rejects_non_gpib_resource() -> None:
    driver = Fluke8508ADriver("USB0::DMM::INSTR")
    with pytest.raises(Exception, match="GPIB"):
        driver.connect()


def test_scpi_profile_rejects_wrong_selected_model(monkeypatch) -> None:
    instrument = _FakeScpiInstrument("FLUKE,8846A,123,2.0")
    manager = _Fake34470AManager(instrument)
    monkeypatch.setattr(
        driver_module.pyvisa,
        "ResourceManager",
        lambda _backend: manager,
    )
    driver = ScpiDmmDriver(
        "USB0::DMM::INSTR",
        InstrumentModel.KEYSIGHT_34470A,
    )
    with pytest.raises(Exception, match="34470A"):
        driver.connect()
