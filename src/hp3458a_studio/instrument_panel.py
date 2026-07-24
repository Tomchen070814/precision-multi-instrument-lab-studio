from __future__ import annotations

from PySide6 import QtWidgets

from .drivers import RANGES, AcquisitionConfig, MeasurementFunction
from .i18n import function_name, tr
from .models import InstrumentModel


class InstrumentControlPanel(QtWidgets.QWidget):
    """Independent, model-aware controls for one acquisition channel."""

    def __init__(
        self,
        channel: str,
        default_resource: str,
        language: str = "zh",
        parent=None,
    ):
        super().__init__(parent)
        self.channel = channel
        self.default_resource = default_resource
        self.language = language
        self._running = False
        self._stoppable = True
        self._field_labels: list[tuple[QtWidgets.QLabel, str]] = []
        self._build_ui()
        self._connect_signals()
        self._driver_changed()
        self._mode_changed()
        self.set_language(language)

    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(7, 9, 7, 9)
        outer.setSpacing(8)

        self.model_combo = QtWidgets.QComboBox()
        for model in InstrumentModel:
            self.model_combo.addItem(model.display_name, model)
        outer.addWidget(self._field("仪表型号", self.model_combo))

        self.driver_combo = QtWidgets.QComboBox()
        self.driver_combo.addItem("", "sim")
        self.driver_combo.addItem("", "visa")
        outer.addWidget(self._field("数据来源", self.driver_combo))

        resource_row = QtWidgets.QHBoxLayout()
        self.resource_combo = QtWidgets.QComboBox()
        self.resource_combo.setEditable(True)
        self.resource_combo.addItem(self.default_resource)
        self.resource_refresh = QtWidgets.QPushButton()
        self.resource_refresh.setFixedWidth(58)
        self.connection_check = QtWidgets.QPushButton()
        self.connection_check.setFixedWidth(66)
        resource_row.addWidget(self.resource_combo, 1)
        resource_row.addWidget(self.resource_refresh)
        resource_row.addWidget(self.connection_check)
        outer.addLayout(resource_row)

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem("", "precision")
        self.mode_combo.addItem("", "burst")
        outer.addWidget(self._field("采集模式", self.mode_combo))

        self.function_combo = QtWidgets.QComboBox()
        outer.addWidget(self._field("测量功能", self.function_combo))
        self.range_combo = QtWidgets.QComboBox()
        outer.addWidget(self._field("量程", self.range_combo))

        self.precision_controls = QtWidgets.QWidget()
        precision_layout = QtWidgets.QVBoxLayout(self.precision_controls)
        precision_layout.setContentsMargins(0, 0, 0, 0)
        precision_layout.setSpacing(8)
        self.nplc_combo = QtWidgets.QComboBox()
        self.nplc_combo.setEditable(True)
        for value in ("0.0001", "0.001", "0.01", "0.1", "1", "10", "100", "1000"):
            self.nplc_combo.addItem(value)
        self.nplc_combo.setCurrentText("10")
        precision_layout.addWidget(self._field("积分时间 NPLC", self.nplc_combo))
        self.digits_combo = QtWidgets.QComboBox()
        for digits in range(3, 9):
            self.digits_combo.addItem("", digits)
        self.digits_combo.setCurrentIndex(5)
        precision_layout.addWidget(self._field("显示位数", self.digits_combo))
        self.autozero_combo = QtWidgets.QComboBox()
        self.autozero_combo.addItems(["ON", "OFF", "ONCE"])
        precision_layout.addWidget(self._field("Autozero", self.autozero_combo))
        self.interval_spin = QtWidgets.QDoubleSpinBox()
        self.interval_spin.setDecimals(3)
        self.interval_spin.setRange(0.01, 6000.0)
        self.interval_spin.setValue(1.0)
        self.interval_spin.setSuffix(" s")
        precision_layout.addWidget(self._field("采样间隔", self.interval_spin))
        self.precision_length_combo = QtWidgets.QComboBox()
        self.precision_length_combo.addItem("", "continuous")
        self.precision_length_combo.addItem("", "fixed")
        precision_layout.addWidget(self._field("采集长度", self.precision_length_combo))
        self.precision_count = QtWidgets.QSpinBox()
        self.precision_count.setRange(1, 10_000_000)
        self.precision_count.setValue(20_000)
        self.precision_count.setSingleStep(1000)
        self.precision_count.setGroupSeparatorShown(True)
        self.precision_count_field = self._field("目标样本数", self.precision_count)
        precision_layout.addWidget(self.precision_count_field)
        outer.addWidget(self.precision_controls)

        self.burst_controls = QtWidgets.QWidget()
        burst_layout = QtWidgets.QVBoxLayout(self.burst_controls)
        burst_layout.setContentsMargins(0, 0, 0, 0)
        burst_layout.setSpacing(8)
        self.burst_count = QtWidgets.QSpinBox()
        self.burst_count.setRange(16, 148_000)
        self.burst_count.setValue(10_000)
        self.burst_count.setSingleStep(1000)
        burst_layout.addWidget(self._field("样本数", self.burst_count))
        self.burst_interval_us = QtWidgets.QDoubleSpinBox()
        self.burst_interval_us.setDecimals(3)
        self.burst_interval_us.setRange(10.0, 6_000_000_000.0)
        self.burst_interval_us.setValue(100.0)
        self.burst_interval_us.setSuffix(" µs")
        burst_layout.addWidget(self._field("采样间隔", self.burst_interval_us))
        self.burst_aperture_us = QtWidgets.QDoubleSpinBox()
        self.burst_aperture_us.setDecimals(3)
        self.burst_aperture_us.setRange(0.5, 1_000_000.0)
        self.burst_aperture_us.setValue(3.0)
        self.burst_aperture_us.setSuffix(" µs")
        burst_layout.addWidget(self._field("孔径 APER", self.burst_aperture_us))
        outer.addWidget(self.burst_controls)

        self.start_button = QtWidgets.QPushButton()
        self.start_button.setObjectName("primary")
        self.start_button.setMinimumHeight(40)
        outer.addWidget(self.start_button)
        outer.addStretch()

    def _connect_signals(self) -> None:
        self.model_combo.currentIndexChanged.connect(self._model_changed)
        self.driver_combo.currentIndexChanged.connect(self._driver_changed)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.function_combo.currentIndexChanged.connect(self._function_changed)
        self.precision_length_combo.currentIndexChanged.connect(
            self._precision_length_changed
        )

    def _field(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        label = QtWidgets.QLabel(title)
        label.setObjectName("hint")
        self._field_labels.append((label, title))
        layout.addWidget(label)
        layout.addWidget(widget)
        return container

    def _driver_changed(self) -> None:
        is_visa = self.driver_combo.currentData() == "visa"
        self.resource_combo.setEnabled(is_visa)
        self.resource_refresh.setEnabled(is_visa)
        self.connection_check.setEnabled(is_visa)

    def _model_changed(self) -> None:
        """Apply model capabilities without changing the channel identity."""
        supports_burst = self.instrument_model.supports_burst
        burst_index = self.mode_combo.findData("burst")
        model = self.mode_combo.model()
        if hasattr(model, "item") and burst_index >= 0:
            item = model.item(burst_index)
            if item is not None:
                item.setEnabled(supports_burst)
        if not supports_burst and self.acquisition_mode == "burst":
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("precision"))
        self._mode_changed()
        self.set_running(self._running, self._stoppable)
        self._apply_model_control_capabilities()

    def _apply_model_control_capabilities(self) -> None:
        """Disable controls that do not map to a safe remote command."""
        can_edit = not self._running
        supports_autozero = self.instrument_model.supports_autozero_control
        self.autozero_combo.setEnabled(can_edit and supports_autozero)
        for label, key in self._field_labels:
            if key == "积分时间 NPLC":
                label.setText(
                    (
                        "Integration target NPLC → RESL/FAST"
                        if self.language == "en"
                        else "积分目标 NPLC → RESL/FAST"
                    )
                    if self.instrument_model is InstrumentModel.FLUKE_8508A
                    else tr(self.language, key)
                )
            elif key == "Autozero":
                label.setText(
                    (
                        "Autozero · unavailable"
                        if self.language == "en"
                        else "Autozero · 此型号不可用"
                    )
                    if not supports_autozero
                    else tr(self.language, key)
                )
        if self.instrument_model is InstrumentModel.FLUKE_8508A:
            tooltip = (
                "8508A does not accept NPLC directly. The requested NPLC is "
                "mapped to the closest documented RESL/FAST integration mode."
                if self.language == "en"
                else "8508A 不直接接受 NPLC；软件会将该值映射到最接近的 "
                "RESL/FAST 官方积分模式。"
            )
        else:
            tooltip = ""
        self.nplc_combo.setToolTip(tooltip)
        self.autozero_combo.setToolTip(
            ""
            if supports_autozero
            else (
                "This model has no compatible remote Autozero command."
                if self.language == "en"
                else "该型号没有兼容的远程 Autozero 命令。"
            )
        )

    def _mode_changed(self) -> None:
        burst = (
            self.mode_combo.currentData() == "burst"
            and self.instrument_model.supports_burst
        )
        self.precision_controls.setVisible(not burst)
        self.burst_controls.setVisible(burst)
        self._precision_length_changed()
        current = self.current_function()
        self.function_combo.blockSignals(True)
        self.function_combo.clear()
        functions = (
            [MeasurementFunction.DIGITIZE_DC, MeasurementFunction.DIGITIZE_AC]
            if burst
            else list(self.instrument_model.supported_functions)
        )
        for function in functions:
            self.function_combo.addItem(
                function_name(self.language, function), function
            )
        if current in functions:
            self.function_combo.setCurrentIndex(functions.index(current))
        self.function_combo.blockSignals(False)
        self._function_changed()

    def _precision_length_changed(self) -> None:
        fixed = self.precision_length_combo.currentData() == "fixed"
        self.precision_count_field.setVisible(fixed)

    def _function_changed(self) -> None:
        function = self.current_function()
        self.range_combo.clear()
        for label, command in RANGES.get(function, [("自动", "AUTO")]):
            self.range_combo.addItem(tr(self.language, label), command)

    def current_function(self) -> MeasurementFunction:
        data = self.function_combo.currentData()
        return (
            data
            if isinstance(data, MeasurementFunction)
            else MeasurementFunction.DC_VOLTAGE
        )

    def read_config(self) -> AcquisitionConfig:
        try:
            nplc = float(self.nplc_combo.currentText())
        except ValueError as exc:
            message = (
                f"{self.instrument_model.short_name} {self.channel}: "
                "NPLC must be numeric"
                if self.language == "en"
                else f"{self.instrument_model.short_name} "
                f"{self.channel}：NPLC 必须是数字"
            )
            raise ValueError(message) from exc
        minimum_nplc, maximum_nplc = self.instrument_model.nplc_bounds
        if not minimum_nplc <= nplc <= maximum_nplc:
            raise ValueError(
                f"{self.instrument_model.short_name} {self.channel}: "
                f"NPLC must be between {minimum_nplc:g} and "
                f"{maximum_nplc:g}"
                if self.language == "en"
                else f"{self.instrument_model.short_name} "
                f"{self.channel}：NPLC 必须在 {minimum_nplc:g} 到 "
                f"{maximum_nplc:g} 之间"
            )
        max_samples = (
            int(self.precision_count.value())
            if self.acquisition_mode == "precision"
            and self.precision_length_combo.currentData() == "fixed"
            else None
        )
        return AcquisitionConfig(
            function=self.current_function(),
            measurement_range=str(self.range_combo.currentData()),
            nplc=nplc,
            digits=int(self.digits_combo.currentData()),
            autozero=self.autozero_combo.currentText(),
            sample_interval_s=float(self.interval_spin.value()),
            max_samples=max_samples,
        )

    @property
    def source_kind(self) -> str:
        return str(self.driver_combo.currentData())

    @property
    def instrument_model(self) -> InstrumentModel:
        data = self.model_combo.currentData()
        return (
            data
            if isinstance(data, InstrumentModel)
            else InstrumentModel.KEYSIGHT_3458A
        )

    @property
    def instrument_name(self) -> str:
        return self.instrument_model.display_name

    @property
    def resource_name(self) -> str:
        return self.resource_combo.currentText().strip() or self.default_resource

    @property
    def acquisition_mode(self) -> str:
        return str(self.mode_combo.currentData())

    def set_resources(
        self,
        resources: list[str],
        selected_resource: str | None = None,
    ) -> None:
        current = selected_resource or self.resource_name
        self.resource_combo.clear()
        for resource in resources:
            self.resource_combo.addItem(resource)
        if current in resources:
            self.resource_combo.setCurrentText(current)
        elif current:
            self.resource_combo.addItem(current)
            self.resource_combo.setCurrentText(current)

    def set_running(self, running: bool, stoppable: bool = True) -> None:
        self._running = running
        self._stoppable = stoppable
        controls = (
            self.model_combo,
            self.driver_combo,
            self.resource_combo,
            self.resource_refresh,
            self.connection_check,
            self.mode_combo,
            self.function_combo,
            self.range_combo,
            self.nplc_combo,
            self.digits_combo,
            self.autozero_combo,
            self.interval_spin,
            self.precision_length_combo,
            self.precision_count,
            self.burst_count,
            self.burst_interval_us,
            self.burst_aperture_us,
        )
        for control in controls:
            control.setEnabled(not running)
        if not running:
            self._driver_changed()
            self._apply_model_control_capabilities()
        self.start_button.setText(
            ("Stop" if self.language == "en" else "停止")
            + " "
            + self.instrument_model.short_name
            + f" {self.channel}"
            if running
            else (
                ("Start" if self.language == "en" else "启动")
                + " "
                + self.instrument_model.short_name
                + f" {self.channel}"
            )
        )
        self.start_button.setObjectName("danger" if running else "primary")
        self.start_button.setEnabled(not running or stoppable)
        self.start_button.style().unpolish(self.start_button)
        self.start_button.style().polish(self.start_button)

    def set_language(self, language: str) -> None:
        """Retranslate controls without changing their current data values."""
        self.language = "en" if language == "en" else "zh"
        self.driver_combo.setItemText(0, tr(self.language, "演示模式 · 数字孪生"))
        self.driver_combo.setItemText(1, tr(self.language, "真实仪表 · VISA / GPIB"))
        self.resource_refresh.setText(tr(self.language, "扫描"))
        self.connection_check.setText(tr(self.language, "连接自检"))
        self.mode_combo.setItemText(0, tr(self.language, "精密连续采集"))
        self.mode_combo.setItemText(1, tr(self.language, "高速突发采集"))
        for index in range(self.digits_combo.count()):
            digits = int(self.digits_combo.itemData(index))
            self.digits_combo.setItemText(
                index,
                f"{digits}.5 digits" if self.language == "en" else f"{digits}.5 位",
            )
        self.precision_length_combo.setItemText(
            0, tr(self.language, "持续采集，手动停止")
        )
        self.precision_length_combo.setItemText(
            1, tr(self.language, "固定点数，完成后自动停止")
        )
        for label, key in self._field_labels:
            label.setText(tr(self.language, key))
        current_function = self.current_function()
        current_range = self.range_combo.currentData()
        for index in range(self.function_combo.count()):
            function = self.function_combo.itemData(index)
            if isinstance(function, MeasurementFunction):
                self.function_combo.setItemText(
                    index, function_name(self.language, function)
                )
        self._function_changed()
        for index in range(self.range_combo.count()):
            if self.range_combo.itemData(index) == current_range:
                self.range_combo.setCurrentIndex(index)
                break
        if current_function:
            for index in range(self.function_combo.count()):
                if self.function_combo.itemData(index) == current_function:
                    self.function_combo.setCurrentIndex(index)
                    break
        self._model_changed()
        self.set_running(self._running, self._stoppable)
