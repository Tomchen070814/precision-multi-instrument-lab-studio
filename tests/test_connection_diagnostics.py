from hp3458a_studio.connection_diagnostics import (
    OFFICIAL_DRIVER_DOWNLOADS,
    ConnectionIssueCode,
    classify_connection_error,
    inspect_visa_environment,
    relevant_driver_downloads,
)
from hp3458a_studio.models import InstrumentModel


class _FakeVisaLibrary:
    library_path = r"C:\Windows\System32\visa64.dll"


class _FakeManager:
    def __init__(self, instruments=(), all_resources=()):
        self.instruments = tuple(instruments)
        self.all_resources = tuple(all_resources) or self.instruments
        self.visalib = _FakeVisaLibrary()
        self.closed = False

    def list_resources(self, query="?*::INSTR"):
        return self.all_resources if query == "?*" else self.instruments

    def close(self):
        self.closed = True


def test_missing_visa_runtime_is_reported_as_driver_problem():
    def missing_runtime():
        raise OSError("Could not locate a VISA implementation")

    result = inspect_visa_environment(
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
        manager_factory=missing_runtime,
    )
    assert result.code is ConnectionIssueCode.VISA_RUNTIME_MISSING
    assert result.category == "driver"
    assert result.blocking
    assert "驱动问题" in result.title_zh


def test_working_visa_without_gpib_is_reported_as_gpib_problem():
    manager = _FakeManager(
        instruments=("USB0::0x1234::0x5678::SN::INSTR",),
    )
    result = inspect_visa_environment(
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
        manager_factory=lambda: manager,
    )
    assert result.code is ConnectionIssueCode.GPIB_INTERFACE_MISSING
    assert result.category == "gpib"
    assert manager.closed


def test_visible_gpib_bus_with_wrong_address_names_address_problem():
    manager = _FakeManager(
        instruments=("GPIB0::21::INSTR",),
        all_resources=("GPIB0::INTFC", "GPIB0::21::INSTR"),
    )
    result = inspect_visa_environment(
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
        manager_factory=lambda: manager,
    )
    assert result.code is ConnectionIssueCode.GPIB_ADDRESS_MISSING
    assert "GPIB0::21::INSTR" in result.steps_zh[-1]


def test_visible_target_passes_preflight_and_records_backend():
    manager = _FakeManager(
        instruments=("GPIB0::22::INSTR",),
        all_resources=("GPIB0::INTFC", "GPIB0::22::INSTR"),
    )
    result = inspect_visa_environment(
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
        manager_factory=lambda: manager,
    )
    assert result.ok
    assert result.visa_backend.endswith("visa64.dll")
    assert result.discovered_resources[-1] == "GPIB0::22::INSTR"


def test_manual_lan_address_can_continue_when_not_enumerated():
    manager = _FakeManager()
    result = inspect_visa_environment(
        "TCPIP0::192.0.2.10::inst0::INSTR",
        InstrumentModel.KEYSIGHT_34470A,
        manager_factory=lambda: manager,
    )
    assert result.code is ConnectionIssueCode.RESOURCE_NOT_ENUMERATED
    assert not result.blocking


def test_gpib_error_codes_are_classified_without_guessing():
    no_listener = classify_connection_error(
        "VI_ERROR_NLISTENERS (-1073807265)",
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
    )
    not_controller = classify_connection_error(
        "VI_ERROR_NCIC (-1073807264)",
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
    )
    assert no_listener.code is ConnectionIssueCode.GPIB_NO_LISTENER
    assert not_controller.code is ConnectionIssueCode.GPIB_NOT_CONTROLLER
    assert no_listener.category == not_controller.category == "gpib"


def test_model_mismatch_is_not_mislabeled_as_driver_failure():
    result = classify_connection_error(
        "当前通道选择的是 Keysight 34470A，身份应包含 34470A",
        "USB0::0x0957::INSTR",
        InstrumentModel.KEYSIGHT_34470A,
    )
    assert result.code is ConnectionIssueCode.IDENTITY_MISMATCH
    assert result.category == "instrument"


def test_driver_downloads_are_official_https_pages():
    assert {item.name for item in OFFICIAL_DRIVER_DOWNLOADS} >= {
        "NI-VISA",
        "NI-488.2",
        "Keysight IO Libraries Suite",
    }
    assert all(item.url.startswith("https://") for item in OFFICIAL_DRIVER_DOWNLOADS)
    assert all(
        any(
            domain in item.url
            for domain in (
                "ni.com",
                "keysight.com",
                "rohde-schwarz.com",
                "tek.com",
            )
        )
        for item in OFFICIAL_DRIVER_DOWNLOADS
    )
    gpib = classify_connection_error(
        "VI_ERROR_NLISTENERS",
        "GPIB0::22::INSTR",
        InstrumentModel.KEYSIGHT_3458A,
    )
    names = {item.name for item in relevant_driver_downloads(gpib)}
    assert names == {
        "NI-VISA",
        "NI-488.2",
        "Keysight IO Libraries Suite",
    }
