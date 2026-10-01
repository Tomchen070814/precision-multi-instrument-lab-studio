import pytest
from PySide6 import QtWidgets

from hp3458a_studio.instrument_panel import InstrumentControlPanel
from hp3458a_studio.models import InstrumentModel, MeasurementFunction


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.mark.parametrize("model", list(InstrumentModel))
def test_model_and_functions_roundtrip_through_qt_item_data(app, model):
    panel = InstrumentControlPanel("A", "GPIB0::21::INSTR")
    panel.model_combo.setCurrentIndex(panel.model_combo.findData(model.value))
    assert panel.instrument_model is model
    for function in model.supported_functions:
        panel.function_combo.setCurrentIndex(
            panel.function_combo.findData(function.value)
        )
        assert panel.current_function() is function
        assert panel.read_config().function is function
    panel.deleteLater()
    app.processEvents()


def test_burst_function_and_range_are_preserved(app):
    panel = InstrumentControlPanel("C", "GPIB2::23::INSTR")
    panel.mode_combo.setCurrentIndex(panel.mode_combo.findData("burst"))
    panel.function_combo.setCurrentIndex(
        panel.function_combo.findData(MeasurementFunction.DIGITIZE_AC.value)
    )
    panel.range_combo.setCurrentIndex(panel.range_combo.findData("10"))
    config = panel.read_config()
    assert config.function is MeasurementFunction.DIGITIZE_AC
    assert config.measurement_range == "10"
    panel.deleteLater()
    app.processEvents()
