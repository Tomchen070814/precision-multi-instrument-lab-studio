"""Virtual SMU demonstration only. No VISA resource is opened or voltage sourced."""

from __future__ import annotations

import csv
import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .styles import APP_STYLE, COLORS
from .widgets import configure_plot


@dataclass(frozen=True)
class DiodeModel:
    saturation_a: float = 2e-12
    ideality: float = 1.8
    series_ohm: float = 8.0
    temperature_k: float = 298.15

    def current(self, voltage: float, compliance_a: float) -> tuple[float, float, bool]:
        if (
            not math.isfinite(voltage)
            or not math.isfinite(compliance_a)
            or compliance_a <= 0
        ):
            raise ValueError("Voltage must be finite and compliance positive")
        thermal = self.ideality * 8.617333262e-5 * self.temperature_k
        if voltage <= 0:
            return voltage, self.saturation_a * math.expm1(voltage / thermal), False
        maximum_v = (
            thermal * math.log1p(compliance_a / self.saturation_a)
            + compliance_a * self.series_ohm
        )
        if voltage >= maximum_v:
            return maximum_v, compliance_a, True
        lower, upper = 0.0, compliance_a
        for _ in range(60):
            midpoint = (lower + upper) / 2
            diode_v = (
                thermal * math.log1p(midpoint / self.saturation_a)
                + midpoint * self.series_ohm
            )
            if diode_v < voltage:
                lower = midpoint
            else:
                upper = midpoint
        return voltage, (lower + upper) / 2, False


class VirtualSmuDriver:
    """Seeded diode digital twin with Gaussian current measurement noise."""

    def __init__(self, channel: str, *, seed: int = 20261001):
        index = ("A", "B", "C").index(channel)
        self.channel = channel
        self.resource = f"SIM::GPIB0::{21 + index}::SMU"
        self.model = DiodeModel(
            2e-12 * (index + 1), 1.8 + index * 0.12, 8.0 + index * 4
        )
        self.random = np.random.default_rng(seed + index)

    def read(
        self, set_voltage: float, compliance_a: float, noise: bool = True
    ) -> tuple[float, float, bool]:
        voltage, current, limited = self.model.current(set_voltage, compliance_a)
        if noise:
            current += float(self.random.normal(0.0, 1e-9 + abs(current) * 0.002))
        return voltage, current, limited


@dataclass(frozen=True)
class SweepConfig:
    start_v: float = -0.2
    stop_v: float = 1.2
    points: int = 141
    compliance_a: float = 0.01
    dwell_s: float = 0.02
    noise: bool = True

    def validate(self) -> None:
        if not all(
            math.isfinite(value)
            for value in (self.start_v, self.stop_v, self.compliance_a, self.dwell_s)
        ):
            raise ValueError("Sweep parameters must be finite")
        if (
            not 2 <= self.points <= 5000
            or self.stop_v <= self.start_v
            or not 0 < self.compliance_a <= 1
            or not 0 <= self.dwell_s <= 10
        ):
            raise ValueError("Invalid sweep range, points, compliance or dwell")


class VirtualSweepWorker(QtCore.QThread):
    sample = QtCore.Signal(str, float, float, float, bool)
    transcript = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, config: SweepConfig, parent=None):
        super().__init__(parent)
        config.validate()
        self.config = config
        self._cancel = threading.Event()

    def stop(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            drivers = [VirtualSmuDriver(channel) for channel in ("A", "B", "C")]
            self.transcript.emit(
                "SIMULATION ONLY / 仅模拟 · no physical GPIB connection"
            )
            for driver in drivers:
                self.transcript.emit(
                    f"{driver.resource} > :SOUR:FUNC VOLT; :SENS:CURR:PROT {self.config.compliance_a:g}; :OUTP ON [SIM]"
                )
            for set_voltage in np.linspace(
                self.config.start_v, self.config.stop_v, self.config.points
            ):
                if self._cancel.is_set():
                    break
                for driver in drivers:
                    voltage, current, limited = driver.read(
                        float(set_voltage), self.config.compliance_a, self.config.noise
                    )
                    self.sample.emit(
                        driver.channel, float(set_voltage), voltage, current, limited
                    )
                    self.transcript.emit(
                        f"{driver.channel} > :SOUR:VOLT {set_voltage:.5g}; :READ? -> {voltage:.7g} V, {current:.9g} A{' [COMPLIANCE]' if limited else ''}"
                    )
                if self._cancel.wait(self.config.dwell_s):
                    break
        except Exception as exc:
            logging.getLogger(__name__).exception("Virtual SMU sweep failed")
            self.failed.emit(str(exc))
        finally:
            self.transcript.emit("A/B/C > :OUTP OFF [SIM] · virtual sweep ended")


class SmuDemoDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setWindowTitle("Virtual SMU · Diode I-V / 二极管 I-V 模拟")
        self.setStyleSheet(APP_STYLE)
        self.resize(1100, 760)
        self.worker: VirtualSweepWorker | None = None
        self.rows: dict[str, list[tuple[float, float, float, bool]]] = {
            key: [] for key in ("A", "B", "C")
        }
        self._closing = False
        self._closing_result = QtWidgets.QDialog.DialogCode.Rejected
        self._error = ""
        layout = QtWidgets.QVBoxLayout(self)
        warning = QtWidgets.QLabel(
            "SIMULATION ONLY · 虚拟 SMU / 模拟 GPIB 指令 · 未连接真实硬件\n三种二极管模型 + 高斯噪声 + 电流限值；I-V 使用模拟实际电压。"
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)
        controls = QtWidgets.QHBoxLayout()
        self.start_v = QtWidgets.QDoubleSpinBox()
        self.stop_v = QtWidgets.QDoubleSpinBox()
        for spin, value in ((self.start_v, -0.2), (self.stop_v, 1.2)):
            spin.setRange(-5, 5)
            spin.setDecimals(3)
            spin.setValue(value)
            spin.setSuffix(" V")
        self.points = QtWidgets.QSpinBox()
        self.points.setRange(2, 5000)
        self.points.setValue(141)
        self.compliance = QtWidgets.QDoubleSpinBox()
        self.compliance.setRange(0.001, 1000)
        self.compliance.setDecimals(3)
        self.compliance.setValue(10)
        self.compliance.setSuffix(" mA")
        self.noise = QtWidgets.QCheckBox("Gaussian noise / 高斯噪声")
        self.noise.setChecked(True)
        for title, widget in (
            ("Start / 起点", self.start_v),
            ("Stop / 终点", self.stop_v),
            ("Points / 点数", self.points),
            ("Limit / 限值", self.compliance),
        ):
            field = QtWidgets.QVBoxLayout()
            field.addWidget(QtWidgets.QLabel(title))
            field.addWidget(widget)
            controls.addLayout(field)
        controls.addWidget(self.noise)
        layout.addLayout(controls)
        self.plot = pg.PlotWidget()
        configure_plot(self.plot, "Voltage / 电压", "Current / 电流", "V", "A")
        self.plot.addLegend()
        self.curves = {
            key: self.plot.plot(name=f"Virtual SMU {key}", pen=pg.mkPen(color, width=2))
            for key, color in zip(
                ("A", "B", "C"),
                (COLORS["cyan"], COLORS["purple"], COLORS["green"]),
                strict=True,
            )
        }
        layout.addWidget(self.plot, 1)
        row = QtWidgets.QHBoxLayout()
        self.channel = QtWidgets.QComboBox()
        self.channel.addItems(["A+B+C", "A", "B", "C"])
        self.start_button = QtWidgets.QPushButton("Run A+B+C / 开始模拟")
        self.stop_button = QtWidgets.QPushButton("Stop / 停止")
        self.export_button = QtWidgets.QPushButton("Export CSV / 导出")
        self.reset_button = QtWidgets.QPushButton("Reset view / 重置视图")
        self.status = QtWidgets.QLabel("Ready / 就绪")
        for widget in (
            self.channel,
            self.start_button,
            self.stop_button,
            self.export_button,
            self.reset_button,
            self.status,
        ):
            row.addWidget(widget)
        layout.addLayout(row)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(800)
        self.log.setMaximumHeight(170)
        layout.addWidget(self.log)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._draw)
        self._timer.start()
        self.channel.currentTextChanged.connect(self._draw)
        self.start_button.clicked.connect(self.start_sweep)
        self.stop_button.clicked.connect(self._stop)
        self.reset_button.clicked.connect(lambda: self.plot.enableAutoRange())
        self.export_button.clicked.connect(self._export)
        self.stop_button.setEnabled(False)

    def start_sweep(self) -> None:
        if self.worker is not None:
            return
        config = SweepConfig(
            self.start_v.value(),
            self.stop_v.value(),
            self.points.value(),
            self.compliance.value() / 1000,
            noise=self.noise.isChecked(),
        )
        try:
            worker = VirtualSweepWorker(config, self)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self.rows = {key: [] for key in self.rows}
        self._error = ""
        self.worker = worker
        worker.sample.connect(self._sample)
        worker.transcript.connect(self.log.appendPlainText)
        worker.failed.connect(self._failed)
        worker.finished.connect(self._finished)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.export_button.setEnabled(False)
        self.plot.enableAutoRange()
        worker.start()

    @QtCore.Slot(str, float, float, float, bool)
    def _sample(self, key, set_voltage, voltage, current, limited) -> None:
        self.rows[key].append((set_voltage, voltage, current, limited))

    def _draw(self, *_args) -> None:
        selected = self.channel.currentText()
        for key, curve in self.curves.items():
            curve.setVisible(selected == "A+B+C" or selected == key)
            rows = self.rows[key]
            curve.setData([row[1] for row in rows], [row[2] for row in rows])
        self.status.setText(
            self._error
            or " · ".join(f"{key}: {len(rows)}" for key, rows in self.rows.items())
        )

    def _failed(self, message: str) -> None:
        self._error = message
        self.status.setText(message)

    def _stop(self) -> None:
        if self.worker is not None:
            self.worker.stop()

    def _finished(self) -> None:
        worker, self.worker = self.worker, None
        if worker is not None:
            worker.deleteLater()
        self._draw()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.export_button.setEnabled(True)
        if self._closing:
            self.done(self._closing_result)

    def write_csv(self, path: str | Path) -> None:
        if self.worker is not None:
            raise RuntimeError("Stop the sweep before exporting")
        with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                (
                    "channel",
                    "source",
                    "set_voltage_V",
                    "measured_voltage_V",
                    "current_A",
                    "compliance_active",
                )
            )
            for key, rows in self.rows.items():
                for set_v, measured_v, current, limited in rows:
                    writer.writerow(
                        (
                            key,
                            f"SIM::GPIB0::{21 + ('A', 'B', 'C').index(key)}::SMU",
                            f"{set_v:.17g}",
                            f"{measured_v:.17g}",
                            f"{current:.17g}",
                            int(limited),
                        )
                    )

    def _export(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Export virtual sweep", "virtual-diode-iv.csv", "CSV (*.csv)"
        )
        if path:
            try:
                self.write_csv(path)
            except OSError as exc:
                QtWidgets.QMessageBox.warning(self, "Export error / 导出失败", str(exc))

    def closeEvent(self, event) -> None:
        if self.worker is not None:
            self._closing = True
            self._stop()
            event.ignore()
        else:
            self._timer.stop()
            super().closeEvent(event)

    def reject(self) -> None:
        # Escape invokes reject directly, bypassing closeEvent.
        self.done(QtWidgets.QDialog.DialogCode.Rejected)

    def done(self, result: int) -> None:
        if self.worker is not None:
            self._closing = True
            self._closing_result = result
            self._stop()
            return
        self._timer.stop()
        super().done(result)
