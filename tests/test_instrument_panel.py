import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtGui, QtTest, QtWidgets

from hp3458a_studio.instrument_panel import InstrumentControlPanel
from hp3458a_studio.models import InstrumentModel, MeasurementFunction
from hp3458a_studio.styles import APP_STYLE


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


@pytest.mark.parametrize("focused", [False, True])
def test_wheel_does_not_change_interval_or_other_instrument_settings(app, focused):
    panel = InstrumentControlPanel("A", "GPIB0::21::INSTR")
    panel.show()
    app.processEvents()
    panel.interval_spin.setValue(0.1)
    controls = (
        panel.interval_spin,
        panel.function_combo,
        panel.nplc_combo,
        panel.precision_count,
        panel.burst_interval_us,
    )
    values = (
        panel.interval_spin.value(),
        panel.current_function(),
        panel.nplc_combo.currentText(),
        panel.precision_count.value(),
        panel.burst_interval_us.value(),
    )
    for control in controls:
        if focused:
            control.setFocus()
        else:
            control.clearFocus()
        for _ in range(21):
            event = QtGui.QWheelEvent(
                QtCore.QPointF(5, 5),
                QtCore.QPointF(5, 5),
                QtCore.QPoint(),
                QtCore.QPoint(0, 120),
                QtCore.Qt.MouseButton.NoButton,
                QtCore.Qt.KeyboardModifier.NoModifier,
                QtCore.Qt.ScrollPhase.NoScrollPhase,
                False,
            )
            app.sendEvent(control, event)
    assert (
        panel.interval_spin.value(),
        panel.current_function(),
        panel.nplc_combo.currentText(),
        panel.precision_count.value(),
        panel.burst_interval_us.value(),
    ) == values
    panel.interval_spin.setFocus()
    QtTest.QTest.keyClick(panel.interval_spin, QtCore.Qt.Key.Key_Up)
    assert panel.interval_spin.value() > values[0]
    panel.close()
    panel.deleteLater()
    app.processEvents()


def test_wheel_over_setting_scrolls_panel_without_editing_it(app):
    scroll = QtWidgets.QScrollArea()
    scroll.resize(400, 350)
    panel = InstrumentControlPanel("A", "GPIB0::21::INSTR")
    scroll.setWidget(panel)
    scroll.setWidgetResizable(True)
    scroll.show()
    app.processEvents()
    scroll.ensureWidgetVisible(panel.interval_spin)
    app.processEvents()
    scrollbar = scroll.verticalScrollBar()
    before = scrollbar.value()
    interval = panel.interval_spin.value()
    position = QtCore.QPointF(panel.interval_spin.rect().center())
    event = QtGui.QWheelEvent(
        position,
        QtCore.QPointF(panel.interval_spin.mapToGlobal(position.toPoint())),
        QtCore.QPoint(),
        QtCore.QPoint(0, -120),
        QtCore.Qt.MouseButton.NoButton,
        QtCore.Qt.KeyboardModifier.NoModifier,
        QtCore.Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    app.sendEvent(panel.interval_spin, event)
    app.processEvents()
    assert scrollbar.value() > before
    assert panel.interval_spin.value() == interval
    scroll.close()
    scroll.deleteLater()
    app.processEvents()


@pytest.mark.parametrize("language", ["zh", "en"])
@pytest.mark.parametrize(
    "model", [InstrumentModel.KEYSIGHT_3458A, InstrumentModel.FLUKE_8508A]
)
def test_translated_panel_fits_minimum_sidebar_without_horizontal_focus_pan(
    app, language, model
):
    window = QtWidgets.QWidget()
    window.setStyleSheet(APP_STYLE)
    window.resize(1180, 800)
    layout = QtWidgets.QHBoxLayout(window)
    scroll = QtWidgets.QScrollArea()
    # Main sidebar's 295 px minimum less its 24 px layout margins.
    scroll.setFixedWidth(271)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    panel = InstrumentControlPanel("A", "GPIB0::21::INSTR", language=language)
    panel.model_combo.setCurrentIndex(panel.model_combo.findData(model.value))
    panel.interval_spin.setValue(21.1)
    scroll.setWidget(panel)
    layout.addWidget(scroll)
    layout.addWidget(QtWidgets.QWidget(), 1)
    window.show()
    app.processEvents()
    for control in (
        panel.model_combo,
        panel.function_combo,
        panel.precision_length_combo,
        panel.interval_spin,
        panel.resource_combo,
    ):
        control.setFocus()
        scroll.ensureWidgetVisible(control)
        app.processEvents()
        assert scroll.horizontalScrollBar().maximum() == 0
        assert scroll.horizontalScrollBar().value() == 0
        assert panel.mapTo(scroll.viewport(), QtCore.QPoint()).x() == 0
        assert control.mapTo(scroll.viewport(), QtCore.QPoint()).x() >= 0
        assert control.width() <= scroll.viewport().width()
    assert panel.interval_spin.value() == 21.1
    assert panel.model_combo.toolTip() == panel.model_combo.currentText()
    assert (
        panel.precision_length_combo.toolTip()
        == panel.precision_length_combo.currentText()
    )
    window.close()
    window.deleteLater()
    app.processEvents()
