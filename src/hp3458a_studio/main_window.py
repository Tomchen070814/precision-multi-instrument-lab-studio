from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from pathlib import Path
from typing import ClassVar

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from . import __version__
from .analysis import (
    allan_deviation,
    descriptive_stats,
    estimate_sample_period,
    linear_fit,
    rolling_mean,
    sigma_mask,
    spectrum,
)
from .channel_groups import resolve_channel_group
from .connection_diagnostics import ConnectionDiagnostic
from .connection_dialog import ConnectionDiagnosticDialog
from .csv_io import (
    read_measurement_csv,
    write_multi_session_csv,
    write_session_csv,
)
from .diagnostics import create_diagnostic_report
from .drivers import (
    AcquisitionConfig,
    Fluke8508ADriver,
    Keysight3458ADriver,
    ScpiDmmDriver,
    SimulatorDriver,
    discover_visa_resources,
    gpib_instrument_resources,
    visa_instrument_resources,
)
from .i18n import tr
from .instrument_panel import InstrumentControlPanel
from .models import InstrumentModel, Measurement, SessionData
from .performance import display_indices, memory_snapshot, windowed_display_indices
from .persistence import (
    DurableSessionWriter,
    default_autosave_root,
    list_recovery_files,
    new_run_id,
)
from .styles import APP_STYLE, COLORS
from .widgets import Card, InteractivePlot, MetricCard, configure_plot
from .workers import (
    BurstAcquisitionWorker,
    ConnectionCheckWorker,
    PrecisionAcquisitionWorker,
    VisaDiscoveryWorker,
)

logger = logging.getLogger(__name__)


def format_number(value: float, unit: str = "", significant: int = 6) -> str:
    if not np.isfinite(value):
        return "—"
    if value == 0:
        return f"0 {unit}".strip()
    prefixes = {
        -12: "p",
        -9: "n",
        -6: "µ",
        -3: "m",
        0: "",
        3: "k",
        6: "M",
        9: "G",
    }
    exponent = int(math.floor(math.log10(abs(value)) / 3) * 3)
    exponent = max(-12, min(9, exponent))
    scaled = value / (10**exponent)
    return f"{scaled:.{significant}g} {prefixes[exponent]}{unit}".strip()


@dataclass
class ChannelRuntime:
    key: str
    session: SessionData = field(default_factory=SessionData)
    worker: PrecisionAcquisitionWorker | BurstAcquisitionWorker | None = None
    identity: object | None = None
    state: str = "待机"
    last_temperature: float = np.nan
    last_refresh_ms: int = 0
    error: str = ""
    target_samples: int | None = None
    durable_writer: DurableSessionWriter | None = None
    last_autosave_path: str = ""
    minimum: float = np.inf
    maximum: float = -np.inf
    last_connection_diagnostic: ConnectionDiagnostic | None = None

    @property
    def running(self) -> bool:
        return self.worker is not None and self.worker.isRunning()


class MainWindow(QtWidgets.QMainWindow):
    CHANNELS: ClassVar[tuple[str, ...]] = ("A", "B", "C")
    DEFAULT_RESOURCES: ClassVar[dict[str, str]] = {
        "A": "GPIB0::21::INSTR",
        "B": "GPIB1::22::INSTR",
        "C": "GPIB2::23::INSTR",
    }
    CHANNEL_COLORS: ClassVar[dict[str, str]] = {
        "A": COLORS["cyan"],
        "B": COLORS["purple"],
        "C": COLORS["green"],
    }

    @staticmethod
    def _create_settings() -> QtCore.QSettings:
        """Create the persistent application settings store.

        Keeping construction behind a small seam lets automated UI tests use an
        isolated INI file. A build must never depend on, overwrite, or clear the
        language and layout preferences from an existing installation.
        """
        return QtCore.QSettings("Louis Lab", "3458A Lab Studio")

    def __init__(self):
        super().__init__()
        self.settings = self._create_settings()
        self.language = str(self.settings.value("language", "zh"))
        if self.language not in {"zh", "en"}:
            self.language = "zh"
        self._static_text_widgets: list[tuple[QtWidgets.QWidget, str]] = []
        self.setWindowTitle("Precision Multi-Instrument Lab Studio")
        self.resize(1600, 960)
        self.setMinimumSize(1180, 720)
        self.setStyleSheet(APP_STYLE)
        self.channels = {key: ChannelRuntime(key) for key in self.CHANNELS}
        self.panels: dict[str, InstrumentControlPanel] = {}
        self.readouts: dict[str, dict[str, QtWidgets.QLabel]] = {}
        self.readout_cards: dict[str, QtWidgets.QWidget] = {}
        self.analysis_banners: dict[str, dict[str, QtWidgets.QLabel]] = {}
        self._group_gate: threading.Event | None = None
        self._group_pending: set[str] = set()
        self._group_members: set[str] = set()
        self._connection_check_workers: dict[str, ConnectionCheckWorker] = {}
        self._visa_scan_worker: VisaDiscoveryWorker | None = None
        self._live_refresh_pending = False
        self._analysis_refresh_pending = False
        self._trend_x_window: tuple[float, float] | None = None
        self._last_memory_snapshot = None
        self._shutdown_in_progress = False
        self._shutdown_complete = False
        self._shutdown_deadline = 0.0
        self._shutdown_timer = QtCore.QTimer(self)
        self._shutdown_timer.setInterval(100)
        self._shutdown_timer.timeout.connect(self._poll_shutdown)
        self._live_refresh_timer = QtCore.QTimer(self)
        self._live_refresh_timer.setInterval(100)
        self._live_refresh_timer.timeout.connect(self._live_refresh_tick)
        self._analysis_refresh_timer = QtCore.QTimer(self)
        self._analysis_refresh_timer.setInterval(900)
        self._analysis_refresh_timer.timeout.connect(self._analysis_refresh_tick)
        self._memory_timer = QtCore.QTimer(self)
        self._memory_timer.setInterval(1000)
        self._memory_timer.timeout.connect(self._update_memory_monitor)
        self.autosave_root = default_autosave_root()
        self.autosave_root.mkdir(parents=True, exist_ok=True)
        self._build_ui()
        self._capture_static_texts()
        self._connect_signals()
        for key, panel in self.panels.items():
            saved_model = str(
                self.settings.value(
                    f"channel_{key}_instrument_model",
                    InstrumentModel.KEYSIGHT_3458A.value,
                )
            )
            try:
                model = InstrumentModel(saved_model)
            except ValueError:
                model = InstrumentModel.KEYSIGHT_3458A
            model_index = panel.model_combo.findData(model)
            if model_index >= 0:
                panel.model_combo.setCurrentIndex(model_index)
            saved_resource = str(
                self.settings.value(
                    f"channel_{key}_resource",
                    self.DEFAULT_RESOURCES[key],
                )
            )
            panel.set_resources([saved_resource], saved_resource)
        self.channel_c_enabled.setChecked(
            self.settings.value("channel_c_enabled", False, type=bool)
        )
        self.language_combo.setCurrentIndex(self.language_combo.findData(self.language))
        for key in self.CHANNELS:
            self._set_channel_state(
                key, "待机" if key in self.enabled_channels else "未启用"
            )
        self._retranslate_ui()
        geometry = self.settings.value("window_geometry")
        restored = bool(geometry and self.restoreGeometry(geometry))
        if not restored or not self._window_geometry_is_visible():
            self._reset_window_geometry()
        splitter_state = self.settings.value("main_splitter")
        if splitter_state:
            self.main_splitter.restoreState(splitter_state)
        self._refresh_views()
        self._live_refresh_timer.start()
        self._analysis_refresh_timer.start()
        self._memory_timer.start()
        self._update_memory_monitor()
        self._report_recovery_files()
        self._log(
            "Multi-instrument mode ready: A GPIB0::21::INSTR, "
            "B GPIB1::22::INSTR; C is reserved and disabled."
            if self.language == "en"
            else "多仪表模式就绪：A 默认 GPIB0::21::INSTR，"
            "B 默认 GPIB1::22::INSTR；C 已预留且默认关闭"
        )

    def _window_geometry_is_visible(self) -> bool:
        """Return whether a useful part of the saved window is on a screen."""
        frame = self.frameGeometry()
        for screen in QtGui.QGuiApplication.screens():
            visible = frame.intersected(screen.availableGeometry())
            if visible.width() >= 160 and visible.height() >= 120:
                return True
        return False

    def _reset_window_geometry(self) -> None:
        """Recover from stale/corrupt geometry or a removed monitor."""
        self.resize(1600, 960)
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        width = min(self.width(), available.width())
        height = min(self.height(), available.height())
        self.resize(width, height)
        self.move(
            available.x() + max(0, (available.width() - width) // 2),
            available.y() + max(0, (available.height() - height) // 2),
        )

    # ---------- UI construction ----------

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QtWidgets.QVBoxLayout(root)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)
        outer.addLayout(self._build_header())
        self.main_splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self._build_sidebar())
        self.main_splitter.addWidget(self._build_center())
        self.main_splitter.addWidget(self._build_inspector())
        self.main_splitter.setStretchFactor(0, 0)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.setSizes([330, 980, 290])
        outer.addWidget(self.main_splitter, 1)

    def _build_header(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        brand_box = QtWidgets.QVBoxLayout()
        brand_box.setSpacing(0)
        brand = QtWidgets.QLabel("PRECISION MULTI-INSTRUMENT LAB")
        brand.setObjectName("brand")
        self.brand_subtitle = QtWidgets.QLabel(
            "MULTI-INSTRUMENT PRECISION MEASUREMENT  /  WINDOWS EDITION"
        )
        self.brand_subtitle.setObjectName("brandSub")
        brand_box.addWidget(brand)
        brand_box.addWidget(self.brand_subtitle)
        layout.addLayout(brand_box)
        layout.addStretch()
        self.header_source = QtWidgets.QLabel("A —  ·  B —  ·  C OFF")
        self.header_source.setObjectName("hint")
        layout.addWidget(self.header_source)
        self.language_combo = QtWidgets.QComboBox()
        self.language_combo.setObjectName("languageSwitch")
        self.language_combo.addItem("中文", "zh")
        self.language_combo.addItem("English", "en")
        self.language_combo.setFixedWidth(102)
        layout.addWidget(self.language_combo)
        self.memory_label = QtWidgets.QLabel("RAM — · APP —")
        self.memory_label.setObjectName("memoryMonitor")
        self.memory_label.setMinimumWidth(150)
        layout.addWidget(self.memory_label)
        self.status_label = QtWidgets.QLabel("A 待机 · B 待机 · C 未启用")
        self.status_label.setObjectName("statusIdle")
        layout.addWidget(self.status_label)
        return layout

    def _build_sidebar(self) -> QtWidgets.QWidget:
        sidebar = QtWidgets.QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setMinimumWidth(295)
        sidebar.setMaximumWidth(410)
        layout = QtWidgets.QVBoxLayout(sidebar)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self._section("独立仪表控制"))

        self.device_tabs = QtWidgets.QTabWidget()
        self.device_tabs.setDocumentMode(True)
        for key in self.CHANNELS:
            panel = InstrumentControlPanel(
                key, self.DEFAULT_RESOURCES[key], language=self.language
            )
            self.panels[key] = panel
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff
            )
            scroll.setWidget(panel)
            self.device_tabs.addTab(scroll, f"通道 {key}")
        layout.addWidget(self.device_tabs, 1)

        self.channel_c_enabled = QtWidgets.QCheckBox("启用第三仪器通道 C")
        self.channel_c_enabled.setToolTip(
            "通道 C 默认关闭；启用后可独立选择任一支持的仪表型号。"
        )
        layout.addWidget(self.channel_c_enabled)

        layout.addWidget(self._section("多通道操作"))
        self.sync_selector_label = QtWidgets.QLabel("同步启动组合")
        self.sync_selector_label.setObjectName("hint")
        layout.addWidget(self.sync_selector_label)

        sync_selector = QtWidgets.QHBoxLayout()
        sync_selector.setSpacing(8)
        self.sync_channel_checks: dict[str, QtWidgets.QCheckBox] = {}
        for key in self.CHANNELS:
            check = QtWidgets.QCheckBox(key)
            check.setObjectName(f"syncChannel{key}")
            check.setChecked(key in {"A", "B"})
            check.setToolTip(f"通道 {key}")
            self.sync_channel_checks[key] = check
            sync_selector.addWidget(check, 1)
        layout.addLayout(sync_selector)

        group_buttons = QtWidgets.QGridLayout()
        self.start_both_button = QtWidgets.QPushButton("同步启动 A + B")
        self.start_both_button.setObjectName("primary")
        self.stop_all_button = QtWidgets.QPushButton("停止全部")
        self.stop_all_button.setObjectName("danger")
        group_buttons.addWidget(self.start_both_button, 0, 0)
        group_buttons.addWidget(self.stop_all_button, 0, 1)
        layout.addLayout(group_buttons)
        self.sync_hint = QtWidgets.QLabel(
            "仅启动勾选的通道；两台或三台仪表会先分别连接和配置，"
            "全部就绪后再统一释放采集线程。其他通道不受影响。"
            "这是软件级近同时启动；严格同步需要外部触发。"
        )
        self.sync_hint.setObjectName("hint")
        self.sync_hint.setWordWrap(True)
        layout.addWidget(self.sync_hint)
        return sidebar

    def _build_center(self) -> QtWidgets.QWidget:
        center = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(center)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        readout_row = QtWidgets.QHBoxLayout()
        readout_row.setSpacing(9)
        for key in self.CHANNELS:
            readout_row.addWidget(self._build_channel_readout(key), 1)
        layout.addLayout(readout_row)

        self.metric_basis_label = QtWidgets.QLabel(
            "当前指标基准 A · 3458A · DCV · GPIB0::21::INSTR"
        )
        self.metric_basis_label.setObjectName("analysisChannelA")
        self.metric_basis_label.setWordWrap(True)
        layout.addWidget(self.metric_basis_label)

        metrics_layout = QtWidgets.QGridLayout()
        metrics_layout.setHorizontalSpacing(8)
        metrics_layout.setVerticalSpacing(8)
        self.metric_cards = {
            "mean": MetricCard("平均值", COLORS["cyan"]),
            "std": MetricCard("标准差", COLORS["yellow"]),
            "min": MetricCard("最小值", COLORS["green"]),
            "max": MetricCard("最大值", COLORS["purple"]),
            "p2p": MetricCard("峰峰值", COLORS["purple"]),
            "noise": MetricCard("离散系数", COLORS["green"]),
            "drift": MetricCard("线性漂移 / h", COLORS["yellow"]),
            "count": MetricCard("样本数", COLORS["cyan"]),
        }
        for index, card in enumerate(self.metric_cards.values()):
            metrics_layout.addWidget(card, index // 4, index % 4)
        layout.addLayout(metrics_layout)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)
        self.trend_tab_index = self.tabs.addTab(self._build_trend_tab(), "多通道趋势")
        self.spectrum_tab_index = self.tabs.addTab(
            self._build_spectrum_tab(), "FFT / ASD · A+B"
        )
        self.statistics_tab_index = self.tabs.addTab(
            self._build_statistics_tab(), "统计分布 · A+B"
        )
        self.stability_tab_index = self.tabs.addTab(
            self._build_stability_tab(), "稳定性 / 温漂 · A+B"
        )
        layout.addWidget(self.tabs, 1)
        return center

    def _build_channel_readout(self, key: str) -> QtWidgets.QWidget:
        card = Card(object_name="channelReadout")
        self.readout_cards[key] = card
        layout = QtWidgets.QVBoxLayout(card)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(3)
        top = QtWidgets.QHBoxLayout()
        tag = QtWidgets.QLabel(f"通道 {key}")
        tag.setObjectName(f"channelTag{key}")
        source = QtWidgets.QLabel("SIMULATOR")
        source.setObjectName("hint")
        state = QtWidgets.QLabel("待机")
        state.setObjectName("statusIdle")
        top.addWidget(tag)
        top.addWidget(source)
        top.addStretch()
        top.addWidget(state)
        layout.addLayout(top)

        value_row = QtWidgets.QHBoxLayout()
        value = QtWidgets.QLabel("—")
        value.setObjectName("channelReadoutValue")
        unit = QtWidgets.QLabel("V")
        unit.setObjectName("readoutUnit")
        value_row.addWidget(value, 1)
        value_row.addWidget(unit, alignment=QtCore.Qt.AlignmentFlag.AlignBottom)
        layout.addLayout(value_row)

        bottom = QtWidgets.QHBoxLayout()
        mode = QtWidgets.QLabel("DCV · AUTO")
        mode.setObjectName("hint")
        time_label = QtWidgets.QLabel("等待数据")
        time_label.setObjectName("hint")
        temperature = QtWidgets.QLabel("TEMP —")
        temperature.setObjectName("hint")
        bottom.addWidget(mode)
        bottom.addStretch()
        bottom.addWidget(time_label)
        bottom.addWidget(temperature)
        layout.addLayout(bottom)
        extremes = QtWidgets.QLabel("MIN —  ·  MAX —")
        extremes.setObjectName("hint")
        layout.addWidget(extremes)
        self.readouts[key] = {
            "tag": tag,
            "source": source,
            "state": state,
            "value": value,
            "unit": unit,
            "mode": mode,
            "time": time_label,
            "temperature": temperature,
            "extremes": extremes,
        }
        return card

    def _build_trend_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        top = QtWidgets.QHBoxLayout()
        self.comparison_note = QtWidgets.QLabel(
            "A 青色 · B 紫色 · C 绿色；不同物理量使用独立 Y 轴"
        )
        self.comparison_note.setObjectName("hint")
        top.addWidget(self.comparison_note)
        top.addStretch()
        self.trend_axis_combo = QtWidgets.QComboBox()
        self.trend_axis_combo.addItem("全部 Y 轴", "")
        self.trend_axis_combo.setMinimumWidth(98)
        top.addWidget(self.trend_axis_combo)
        self.zoom_x_in_button = QtWidgets.QPushButton("X 放大")
        self.zoom_x_out_button = QtWidgets.QPushButton("X 缩小")
        self.zoom_y_in_button = QtWidgets.QPushButton("Y 放大")
        self.zoom_y_out_button = QtWidgets.QPushButton("Y 缩小")
        for button in (
            self.zoom_x_in_button,
            self.zoom_x_out_button,
            self.zoom_y_in_button,
            self.zoom_y_out_button,
        ):
            button.setMinimumWidth(64)
            top.addWidget(button)
        self.box_zoom_button = QtWidgets.QPushButton("框选放大")
        self.box_zoom_button.setCheckable(True)
        self.box_zoom_button.setToolTip(
            "启用后拖动矩形框选择时间范围，并自动缩放每个单位的 Y 轴。"
        )
        self.reset_zoom_button = QtWidgets.QPushButton("重置视图")
        top.addWidget(self.box_zoom_button)
        top.addWidget(self.reset_zoom_button)
        self.clear_marks_button = QtWidgets.QPushButton("清除标记")
        top.addWidget(self.clear_marks_button)
        layout.addLayout(top)
        self.trend_plot = InteractivePlot()
        self.trend_plot.set_labels("当前时间戳", "测量值", "V")
        layout.addWidget(self.trend_plot, 1)
        return page

    def _build_spectrum_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._build_analysis_banner("spectrum"))
        plots = QtWidgets.QHBoxLayout()
        plots.setSpacing(8)
        self.fft_plot = pg.PlotWidget()
        configure_plot(self.fft_plot, "频率", "幅值", "Hz", "V")
        self.fft_plot.addLegend(offset=(10, 10))
        self.fft_curves = {
            channel: self.fft_plot.plot(
                pen=pg.mkPen(self.CHANNEL_COLORS[channel], width=1.6),
                name=f"Channel {channel}",
            )
            for channel in self.CHANNELS
        }
        self.asd_plot = pg.PlotWidget()
        configure_plot(
            self.asd_plot, "频率", "ASD", "Hz", "V/√Hz", log_x=True, log_y=True
        )
        self.asd_plot.addLegend(offset=(10, 10))
        self.asd_curves = {
            channel: self.asd_plot.plot(
                pen=pg.mkPen(self.CHANNEL_COLORS[channel], width=1.6),
                name=f"Channel {channel}",
            )
            for channel in self.CHANNELS
        }
        plots.addWidget(self.fft_plot, 1)
        plots.addWidget(self.asd_plot, 1)
        layout.addLayout(plots, 1)
        return page

    def _build_statistics_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._build_analysis_banner("statistics"))
        content = QtWidgets.QHBoxLayout()
        content.setSpacing(8)
        self.hist_plot = pg.PlotWidget()
        configure_plot(self.hist_plot, "测量值", "计数")
        hist_legend = self.hist_plot.addLegend(offset=(10, 10))
        self.hist_bars: dict[str, pg.BarGraphItem] = {}
        for channel in self.CHANNELS:
            color = self.CHANNEL_COLORS[channel]
            bar = pg.BarGraphItem(
                x=[],
                height=[],
                width=1.0,
                brush=pg.mkBrush(color + "66"),
                pen=pg.mkPen(color, width=1.0),
            )
            self.hist_plot.addItem(bar)
            hist_legend.addItem(bar, f"Channel {channel}")
            self.hist_bars[channel] = bar
        content.addWidget(self.hist_plot, 2)
        summary_stack = QtWidgets.QWidget()
        summary_stack.setMinimumWidth(230)
        summary_stack.setMaximumWidth(290)
        summary_layout = QtWidgets.QVBoxLayout(summary_stack)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(8)
        self.statistics_summary_cards: dict[str, Card] = {}
        self.statistics_summary_titles: dict[str, QtWidgets.QLabel] = {}
        self.summary_labels: dict[str, dict[str, QtWidgets.QLabel]] = {}
        for channel in self.CHANNELS:
            summary_layout.addWidget(self._build_statistics_summary_card(channel), 1)
        content.addWidget(summary_stack)
        layout.addLayout(content, 1)
        return page

    def _build_statistics_summary_card(self, channel: str) -> Card:
        summary = Card()
        summary_layout = QtWidgets.QVBoxLayout(summary)
        summary_layout.setContentsMargins(13, 10, 13, 10)
        summary_layout.setSpacing(3)
        title = QtWidgets.QLabel(f"通道 {channel} · 统计摘要")
        title.setObjectName(f"analysisCardTitle{channel}")
        summary_layout.addWidget(title)
        summary_form = QtWidgets.QFormLayout()
        summary_form.setContentsMargins(0, 2, 0, 0)
        summary_form.setVerticalSpacing(2)
        labels: dict[str, QtWidgets.QLabel] = {}
        for label_text, key in (
            ("最小值", "min"),
            ("最大值", "max"),
            ("中位数", "median"),
            ("RMS", "rms"),
            ("有效 / 剔除", "count"),
        ):
            value = QtWidgets.QLabel("—")
            value.setObjectName("metricValue")
            value.setStyleSheet("font-size: 12px;")
            labels[key] = value
            summary_form.addRow(label_text, value)
        summary_layout.addLayout(summary_form)
        self.statistics_summary_cards[channel] = summary
        self.statistics_summary_titles[channel] = title
        self.summary_labels[channel] = labels
        return summary

    def _build_stability_tab(self) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._build_analysis_banner("stability"))
        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        self.allan_plot = pg.PlotWidget()
        configure_plot(
            self.allan_plot,
            "平均时间 τ",
            "Allan deviation",
            "s",
            "",
            log_x=True,
            log_y=True,
        )
        self.allan_plot.addLegend(offset=(10, 10))
        self.allan_curves = {
            channel: self.allan_plot.plot(
                pen=pg.mkPen(self.CHANNEL_COLORS[channel], width=1.5),
                symbol="o",
                symbolSize=5,
                symbolBrush=self.CHANNEL_COLORS[channel],
                name=f"Channel {channel}",
            )
            for channel in self.CHANNELS
        }
        self.drift_plot = pg.PlotWidget()
        configure_plot(self.drift_plot, "时间", "测量值", "s", "V")
        self.drift_plot.addLegend(offset=(10, 10))
        self.drift_points = {}
        self.drift_fit_curves = {}
        for channel in self.CHANNELS:
            color = self.CHANNEL_COLORS[channel]
            self.drift_points[channel] = self.drift_plot.plot(
                pen=None,
                symbol="o",
                symbolSize=4,
                symbolBrush=pg.mkBrush(color),
                name=f"Channel {channel} data",
            )
            self.drift_fit_curves[channel] = self.drift_plot.plot(
                pen=pg.mkPen(color, width=2),
                name=f"Channel {channel} fit",
            )
        splitter.addWidget(self.allan_plot)
        splitter.addWidget(self.drift_plot)
        layout.addWidget(splitter, 1)
        self.stability_note = QtWidgets.QLabel("需要至少 4 个有效样本")
        self.stability_note.setObjectName("hint")
        layout.addWidget(self.stability_note)
        return page

    def _build_analysis_banner(self, page_key: str) -> QtWidgets.QWidget:
        """Create a self-contained instrument identity strip for an analysis page."""
        banner = Card(object_name="analysisBanner")
        banner.setMinimumHeight(58)
        layout = QtWidgets.QHBoxLayout(banner)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(12)

        channel = QtWidgets.QLabel("Channel A + B")
        channel.setObjectName("analysisChannelAB")
        resource = QtWidgets.QLabel("A GPIB0::21::INSTR  ·  B GPIB1::22::INSTR")
        resource.setObjectName("analysisResource")
        resource.setTextInteractionFlags(
            QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
        )
        meta = QtWidgets.QLabel("同时分析 · A 0 样本 · B 0 样本 · V")
        meta.setObjectName("analysisMeta")

        layout.addWidget(channel)
        divider = QtWidgets.QFrame()
        divider.setFrameShape(QtWidgets.QFrame.Shape.VLine)
        divider.setObjectName("analysisDivider")
        layout.addWidget(divider)
        layout.addWidget(resource, 1)
        layout.addWidget(meta)
        self.analysis_banners[page_key] = {
            "channel": channel,
            "resource": resource,
            "meta": meta,
        }
        return banner

    def _build_inspector(self) -> QtWidgets.QWidget:
        inspector = QtWidgets.QWidget()
        inspector.setObjectName("inspector")
        inspector.setMinimumWidth(260)
        inspector.setMaximumWidth(360)
        layout = QtWidgets.QVBoxLayout(inspector)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(9)

        layout.addWidget(self._section("分析显示"))
        self.analysis_channel_combo = QtWidgets.QComboBox()
        for channel in self.CHANNELS:
            self.analysis_channel_combo.addItem(f"Channel {channel}", channel)
        layout.addWidget(self.analysis_channel_combo)
        self.multi_analysis_check = QtWidgets.QCheckBox("同时显示所有启用通道")
        self.multi_analysis_check.setChecked(True)
        # Compatibility alias for earlier automation and integrations.
        self.dual_analysis_check = self.multi_analysis_check
        layout.addWidget(self.multi_analysis_check)

        layout.addWidget(self._section("分析设置"))
        self.rolling_spin = QtWidgets.QSpinBox()
        self.rolling_spin.setRange(1, 100_000)
        self.rolling_spin.setValue(10)
        layout.addWidget(self._field("滑动平均点数", self.rolling_spin))
        self.show_rolling = QtWidgets.QCheckBox("显示滑动平均")
        self.show_rolling.setChecked(True)
        layout.addWidget(self.show_rolling)
        self.outlier_check = QtWidgets.QCheckBox("分析时剔除异常值")
        layout.addWidget(self.outlier_check)
        self.sigma_spin = QtWidgets.QDoubleSpinBox()
        self.sigma_spin.setRange(1.0, 20.0)
        self.sigma_spin.setValue(5.0)
        self.sigma_spin.setSingleStep(0.5)
        self.sigma_spin.setSuffix(" σ")
        layout.addWidget(self._field("MAD 阈值", self.sigma_spin))
        self.allan_normalized = QtWidgets.QCheckBox("Allan 归一化为 ppm")
        self.allan_normalized.setChecked(True)
        layout.addWidget(self.allan_normalized)

        layout.addWidget(self._section("所选会话"))
        session_card = Card()
        form = QtWidgets.QFormLayout(session_card)
        form.setContentsMargins(12, 11, 12, 11)
        self.session_count = QtWidgets.QLabel("0")
        self.session_duration = QtWidgets.QLabel("0 s")
        self.session_rate = QtWidgets.QLabel("—")
        self.session_unit = QtWidgets.QLabel("V")
        for label in (
            self.session_count,
            self.session_duration,
            self.session_rate,
            self.session_unit,
        ):
            label.setObjectName("metricValue")
            label.setStyleSheet("font-size: 12px;")
        form.addRow("样本", self.session_count)
        form.addRow("时长", self.session_duration)
        form.addRow("实际速率", self.session_rate)
        form.addRow("单位", self.session_unit)
        layout.addWidget(session_card)

        layout.addWidget(self._section("仪表身份"))
        identity_card = Card()
        identity_form = QtWidgets.QFormLayout(identity_card)
        identity_form.setContentsMargins(12, 11, 12, 11)
        self.identity_model = QtWidgets.QLabel("—")
        self.identity_resource = QtWidgets.QLabel("—")
        self.identity_fw = QtWidgets.QLabel("—")
        self.identity_option = QtWidgets.QLabel("—")
        self.identity_line = QtWidgets.QLabel("—")
        for label in (
            self.identity_model,
            self.identity_resource,
            self.identity_fw,
            self.identity_option,
            self.identity_line,
        ):
            label.setWordWrap(True)
            label.setObjectName("hint")
        identity_form.addRow("Model", self.identity_model)
        identity_form.addRow("Resource", self.identity_resource)
        identity_form.addRow("REV", self.identity_fw)
        identity_form.addRow("OPT", self.identity_option)
        identity_form.addRow("LINE", self.identity_line)
        layout.addWidget(identity_card)

        layout.addWidget(self._section("数据"))
        data_buttons = QtWidgets.QGridLayout()
        self.import_button = QtWidgets.QPushButton("导入至所选")
        self.export_button = QtWidgets.QPushButton("导出所选")
        self.export_both_button = QtWidgets.QPushButton("导出全部")
        self.clear_button = QtWidgets.QPushButton("清空所选")
        self.clear_button.setObjectName("danger")
        data_buttons.addWidget(self.import_button, 0, 0)
        data_buttons.addWidget(self.export_button, 0, 1)
        data_buttons.addWidget(self.export_both_button, 1, 0)
        data_buttons.addWidget(self.clear_button, 1, 1)
        layout.addLayout(data_buttons)

        layout.addWidget(self._section("安全自动保存"))
        autosave_card = Card()
        autosave_layout = QtWidgets.QVBoxLayout(autosave_card)
        autosave_layout.setContentsMargins(12, 10, 12, 10)
        autosave_layout.setSpacing(6)
        self.autosave_status = QtWidgets.QLabel(
            "已开启 · 每个接收样本立即 flush + fsync"
        )
        self.autosave_status.setObjectName("statusGood")
        self.autosave_status.setWordWrap(True)
        self.autosave_path_label = QtWidgets.QLabel(str(self.autosave_root))
        self.autosave_path_label.setObjectName("hint")
        self.autosave_path_label.setWordWrap(True)
        self.open_autosave_button = QtWidgets.QPushButton("打开自动保存目录")
        self.open_autosave_button.setObjectName("subtle")
        autosave_layout.addWidget(self.autosave_status)
        autosave_layout.addWidget(self.autosave_path_label)
        autosave_layout.addWidget(self.open_autosave_button)
        layout.addWidget(autosave_card)

        layout.addWidget(self._section("事件"))
        self.event_log = QtWidgets.QTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumHeight(180)
        layout.addWidget(self.event_log)
        self.export_diagnostic_button = QtWidgets.QPushButton("导出诊断报告")
        self.export_diagnostic_button.setObjectName("subtle")
        self.export_diagnostic_button.setToolTip(
            "导出软件版本、通道状态、事件记录和历史错误日志；不包含测量样本。"
        )
        self.box_zoom_button.setToolTip(
            tr(
                self.language,
                "启用后拖动矩形框选择时间范围，并自动缩放每个单位的 Y 轴。",
            )
        )
        layout.addWidget(self.export_diagnostic_button)
        layout.addStretch()
        return inspector

    def _section(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text.upper())
        label.setObjectName("section")
        return label

    def _field(self, title: str, widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        field_layout = QtWidgets.QVBoxLayout(container)
        field_layout.setContentsMargins(0, 0, 0, 0)
        field_layout.setSpacing(4)
        label = QtWidgets.QLabel(title)
        label.setObjectName("hint")
        field_layout.addWidget(label)
        field_layout.addWidget(widget)
        return container

    def _capture_static_texts(self) -> None:
        """Remember build-time labels so language switching is lossless."""
        excluded_names = {
            "statusIdle",
            "statusGood",
            "statusBad",
            "channelReadoutValue",
            "readoutUnit",
            "analysisResource",
            "analysisMeta",
            "memoryMonitor",
        }
        for widget_type in (
            QtWidgets.QLabel,
            QtWidgets.QPushButton,
            QtWidgets.QCheckBox,
        ):
            for widget in self.findChildren(widget_type):
                parent = widget.parentWidget()
                inside_panel = False
                while parent is not None:
                    if isinstance(parent, InstrumentControlPanel):
                        inside_panel = True
                        break
                    parent = parent.parentWidget()
                text = widget.text()
                if inside_panel or not text or widget.objectName() in excluded_names:
                    continue
                self._static_text_widgets.append((widget, text))

    def _retranslate_ui(self) -> None:
        self.setWindowTitle(
            "Precision Multi-Instrument Lab Studio"
            if self.language == "en"
            else "精密多仪器测量平台"
        )
        self.brand_subtitle.setText(
            "MULTI-INSTRUMENT PRECISION MEASUREMENT  /  WINDOWS EDITION"
            if self.language == "en"
            else "多仪表精密测量与分析  /  WINDOWS EDITION"
        )
        for widget, source_text in self._static_text_widgets:
            widget.setText(tr(self.language, source_text))
        for panel in self.panels.values():
            panel.set_language(self.language)
        self.channel_c_enabled.setText(tr(self.language, "启用第三仪器通道 C"))
        self.channel_c_enabled.setToolTip(
            tr(
                self.language,
                "通道 C 默认关闭；启用后可独立选择任一支持的仪表型号。",
            )
        )
        self.export_diagnostic_button.setToolTip(
            tr(
                self.language,
                "导出软件版本、通道状态、事件记录和历史错误日志；不包含测量样本。",
            )
        )
        self.sync_hint.setText(
            tr(
                self.language,
                "仅启动勾选的通道；两台或三台仪表会先分别连接和配置，"
                "全部就绪后再统一释放采集线程。其他通道不受影响。"
                "这是软件级近同时启动；严格同步需要外部触发。",
            )
        )
        self.stop_all_button.setText(tr(self.language, "停止全部"))
        self.multi_analysis_check.setText(tr(self.language, "同时显示所有启用通道"))
        self.export_both_button.setText(tr(self.language, "导出全部"))
        self.tabs.setTabText(self.trend_tab_index, tr(self.language, "多通道趋势"))
        self.trend_plot.set_labels(
            tr(self.language, "当前时间戳"),
            tr(self.language, "测量值"),
            self.channels[self.selected_channel].session.unit,
        )
        self.trend_plot.set_language(self.language)
        self.trend_axis_combo.setItemText(
            0,
            tr(self.language, "全部 Y 轴"),
        )
        self.zoom_x_in_button.setToolTip(
            "Magnify the wall-clock axis around its center."
            if self.language == "en"
            else "围绕当前中心放大真实时间轴。"
        )
        self.zoom_x_out_button.setToolTip(
            "Show a wider wall-clock range."
            if self.language == "en"
            else "显示更宽的真实时间范围。"
        )
        self.zoom_y_in_button.setToolTip(
            "Magnify only the selected physical-unit Y axis."
            if self.language == "en"
            else "只放大所选物理量的 Y 轴。"
        )
        self.zoom_y_out_button.setToolTip(
            "Show a wider range on the selected physical-unit Y axis."
            if self.language == "en"
            else "只扩大所选物理量 Y 轴的显示范围。"
        )
        self.fft_plot.setLabel("bottom", tr(self.language, "频率"), units="Hz")
        self.asd_plot.setLabel("bottom", tr(self.language, "频率"), units="Hz")
        self.hist_plot.setLabel("left", tr(self.language, "计数"))
        self.allan_plot.setLabel("bottom", tr(self.language, "平均时间 τ"), units="s")
        self.drift_plot.setLabel("bottom", tr(self.language, "时间"), units="s")
        for key in self.CHANNELS:
            self._set_channel_state(key, self.channels[key].state)
            self._retranslate_readout(key)
            self._update_channel_model_ui(key)
        self._update_channel_c_ui()
        self._update_sync_controls()
        self._refresh_views()

    def _retranslate_readout(self, channel: str) -> None:
        runtime = self.channels[channel]
        panel = self.panels[channel]
        readout = self.readouts[channel]
        count = len(runtime.session)
        command = panel.current_function().command
        range_text = panel.range_combo.currentText().upper()
        if runtime.target_samples is None:
            length_text = "CONTINUOUS" if self.language == "en" else "持续"
        else:
            length_text = (
                f"{runtime.target_samples:,} samples"
                if self.language == "en"
                else f"{runtime.target_samples:,}点"
            )
        readout["mode"].setText(f"{command} · {range_text} · {length_text}")
        if not count:
            readout["time"].setText(tr(self.language, "等待数据"))
            readout["extremes"].setText("MIN —  ·  MAX —")
            return
        readout["extremes"].setText(
            f"MIN {format_number(runtime.minimum, runtime.session.unit, 7)}"
            f"  ·  MAX {format_number(runtime.maximum, runtime.session.unit, 7)}"
        )
        timestamp = datetime.fromtimestamp(
            float(runtime.session.timestamps[-1]),
            tz=timezone.utc,
        ).astimezone()
        timestamp_text = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        if runtime.state == "已完成":
            readout["time"].setText(
                (
                    f"Complete · {count:,} / "
                    f"{runtime.target_samples or count:,} samples"
                    if self.language == "en"
                    else f"完成 · {count:,} / {runtime.target_samples or count:,} 点"
                )
                + f" · {timestamp_text}"
            )
        elif runtime.target_samples is None:
            readout["time"].setText(
                f"{count:,} samples · {timestamp_text}"
                if self.language == "en"
                else f"{count:,} 点 · {timestamp_text}"
            )
        else:
            readout["time"].setText(
                f"{count:,} / {runtime.target_samples:,} "
                f"{'samples' if self.language == 'en' else '点'}"
                f" · {timestamp_text}"
            )

    def _update_channel_model_ui(self, channel: str) -> None:
        panel = self.panels[channel]
        model = panel.instrument_model
        self.readouts[channel]["tag"].setText(f"{model.short_name} {channel}")
        index = self.CHANNELS.index(channel)
        self.device_tabs.setTabText(
            index,
            f"{model.short_name} {channel}",
        )
        self.sync_channel_checks[channel].setToolTip(f"{model.display_name} {channel}")

    def _language_changed(self, *_args) -> None:
        selected = self.language_combo.currentData()
        if selected not in {"zh", "en"} or selected == self.language:
            return
        self.language = str(selected)
        self.settings.setValue("language", self.language)
        self._retranslate_ui()
        self._log(
            "Language changed to English."
            if self.language == "en"
            else "界面语言已切换为中文。"
        )

    def _channel_c_toggled(self, enabled: bool) -> None:
        runtime = self.channels["C"]
        if not enabled and runtime.running:
            self.channel_c_enabled.blockSignals(True)
            self.channel_c_enabled.setChecked(True)
            self.channel_c_enabled.blockSignals(False)
            QtWidgets.QMessageBox.information(
                self,
                "Channel C is active" if self.language == "en" else "C 通道正在采集",
                (
                    "Stop instrument channel C before disabling it."
                    if self.language == "en"
                    else "请先停止 C 通道仪表，再关闭第三仪器通道。"
                ),
            )
            return
        self.settings.setValue("channel_c_enabled", enabled)
        if not enabled:
            self.sync_channel_checks["C"].setChecked(False)
        if not enabled and self.analysis_channel_combo.currentData() == "C":
            self.analysis_channel_combo.setCurrentIndex(0)
        self._set_channel_state("C", "待机" if enabled else "未启用")
        self._update_channel_c_ui()
        self._retranslate_ui()
        self._log(
            (
                "Channel C enabled."
                if enabled
                else "Channel C disabled; A/B remain unchanged."
            )
            if self.language == "en"
            else ("C 通道已启用。" if enabled else "C 通道已关闭；A/B 不受影响。")
        )

    def _update_channel_c_ui(self) -> None:
        enabled = self.channel_c_enabled.isChecked()
        c_index = self.CHANNELS.index("C")
        self.device_tabs.setTabEnabled(c_index, enabled)
        self.panels["C"].setEnabled(enabled)
        self.readout_cards["C"].setEnabled(enabled)
        model = self.analysis_channel_combo.model()
        if hasattr(model, "item"):
            item = model.item(c_index)
            if item is not None:
                item.setEnabled(enabled)
        self.sync_channel_checks["C"].setEnabled(enabled)
        self._update_sync_controls()

    # ---------- Signals and acquisition ----------

    def _connect_signals(self) -> None:
        for key, panel in self.panels.items():
            panel.start_button.clicked.connect(
                lambda _checked=False, channel=key: self._toggle_channel(channel)
            )
            panel.resource_refresh.clicked.connect(self._discover_resources)
            panel.connection_check.clicked.connect(
                lambda _checked=False, channel=key: self._run_connection_self_check(
                    channel
                )
            )
            panel.resource_combo.currentTextChanged.connect(self._refresh_views)
            panel.driver_combo.currentIndexChanged.connect(self._refresh_views)
            panel.model_combo.currentIndexChanged.connect(
                lambda _index, channel=key: self._instrument_model_changed(channel)
            )
        self.start_both_button.clicked.connect(self._start_both)
        self.stop_all_button.clicked.connect(self._stop_all)
        for check in self.sync_channel_checks.values():
            check.toggled.connect(self._sync_selection_changed)
        self.channel_c_enabled.toggled.connect(self._channel_c_toggled)
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        self.analysis_channel_combo.currentIndexChanged.connect(self._refresh_views)
        self.dual_analysis_check.toggled.connect(self._refresh_views)
        self.import_button.clicked.connect(self._import_csv)
        self.export_button.clicked.connect(self._export_csv)
        self.export_both_button.clicked.connect(self._export_both_csv)
        self.export_diagnostic_button.clicked.connect(self._export_diagnostic_report)
        self.clear_button.clicked.connect(self._clear_selected_session)
        self.clear_marks_button.clicked.connect(self.trend_plot.clear_markers)
        self.box_zoom_button.toggled.connect(self.trend_plot.set_box_zoom_enabled)
        self.reset_zoom_button.clicked.connect(self._reset_trend_zoom)
        self.zoom_x_in_button.clicked.connect(lambda: self.trend_plot.zoom_x(0.5))
        self.zoom_x_out_button.clicked.connect(lambda: self.trend_plot.zoom_x(2.0))
        self.zoom_y_in_button.clicked.connect(
            lambda: self.trend_plot.zoom_y(
                0.5,
                str(self.trend_axis_combo.currentData() or ""),
            )
        )
        self.zoom_y_out_button.clicked.connect(
            lambda: self.trend_plot.zoom_y(
                2.0,
                str(self.trend_axis_combo.currentData() or ""),
            )
        )
        self.open_autosave_button.clicked.connect(self._open_autosave_directory)
        self.trend_plot.channel_marker_added.connect(self._marker_added)
        self.trend_plot.x_window_changed.connect(self._trend_window_changed)
        for control in (
            self.rolling_spin,
            self.show_rolling,
            self.outlier_check,
            self.sigma_spin,
            self.allan_normalized,
        ):
            if hasattr(control, "valueChanged"):
                control.valueChanged.connect(self._refresh_views)
            if hasattr(control, "toggled"):
                control.toggled.connect(self._refresh_views)
        self.tabs.currentChanged.connect(lambda _: self._refresh_views())

    def _marker_added(
        self,
        channel: str,
        x: float,
        y: float,
        timestamp,
    ) -> None:
        time_text = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        unit = self.channels[channel].session.unit
        self._log(
            f"{channel} marker: time={time_text}, value={y:.10g} {unit}"
            if self.language == "en"
            else f"{channel} 固定标记：时间={time_text}，值={y:.10g} {unit}"
        )

    def _instrument_model_changed(self, channel: str) -> None:
        self._update_channel_model_ui(channel)
        self._refresh_views()

    @property
    def selected_channel(self) -> str:
        channel = self.analysis_channel_combo.currentData()
        return channel if channel in self.enabled_channels else "A"

    @property
    def enabled_channels(self) -> tuple[str, ...]:
        return (
            self.CHANNELS if self.channel_c_enabled.isChecked() else self.CHANNELS[:2]
        )

    @property
    def sync_channels(self) -> tuple[str, ...]:
        """Return the checked, currently available synchronized-start group."""
        return resolve_channel_group(
            self.enabled_channels,
            {key: self.sync_channel_checks[key].isChecked() for key in self.CHANNELS},
        )

    @property
    def analysis_channels(self) -> tuple[str, ...]:
        if self.multi_analysis_check.isChecked():
            return self.enabled_channels
        return (self.selected_channel,)

    def _sync_selection_changed(self, *_args) -> None:
        self._update_sync_controls()

    def _update_sync_controls(self) -> None:
        """Refresh selector availability and the exact start-button action."""
        channel_c_available = self.channel_c_enabled.isChecked()
        startup_pending = self._group_gate is not None
        for key, check in self.sync_channel_checks.items():
            check.setEnabled(
                not startup_pending and (key != "C" or channel_c_available)
            )

        members = self.sync_channels
        group_name = "+".join(members)
        if not members:
            self.start_both_button.setText(tr(self.language, "请选择启动通道"))
        elif len(members) == 1:
            self.start_both_button.setText(
                tr(
                    self.language,
                    "启动 {channels}",
                    channels=group_name,
                )
            )
        else:
            self.start_both_button.setText(
                tr(
                    self.language,
                    "同步启动 {channels}",
                    channels=group_name,
                )
            )

        selected_busy = any(self.channels[key].worker is not None for key in members)
        self.start_both_button.setEnabled(
            bool(members) and not startup_pending and not selected_busy
        )

    def _discover_resources(self) -> None:
        if self._visa_scan_worker is not None and self._visa_scan_worker.isRunning():
            return
        self._set_global_status(tr(self.language, "正在扫描 VISA…"), "idle")
        for panel in self.panels.values():
            panel.resource_refresh.setEnabled(False)
        worker = VisaDiscoveryWorker(discover_visa_resources, self)
        self._visa_scan_worker = worker
        worker.result_ready.connect(self._visa_scan_finished)
        worker.finished.connect(self._visa_scan_cleanup)
        worker.start()

    def _visa_scan_finished(self, all_resources: list[str]) -> None:
        resources = visa_instrument_resources(all_resources)
        if resources:
            assignments = self._assign_discovered_resources(resources)
            self._log(
                f"Found {len(resources)} VISA instrument resources: "
                f"{', '.join(resources)}"
                if self.language == "en"
                else f"发现 {len(resources)} 个 VISA 仪表资源：{', '.join(resources)}"
            )
            self._log(
                ("Current assignments: " if self.language == "en" else "当前地址分配：")
                + (", " if self.language == "en" else "，").join(
                    f"{channel}={assignments[channel]}"
                    for channel in self.enabled_channels
                )
            )
            self._set_global_status(
                (
                    f"Found {len(resources)} VISA resources"
                    if self.language == "en"
                    else f"发现 {len(resources)} 个 VISA 资源"
                ),
                "good",
            )
        else:
            if all_resources:
                self._log(
                    f"VISA found {len(all_resources)} resources, but no "
                    "supported instrument sessions."
                    if self.language == "en"
                    else f"VISA 扫描到 {len(all_resources)} 个资源，但没有"
                    "可用的仪表会话"
                )
                self._set_global_status(tr(self.language, "未发现 GPIB"), "bad")
            else:
                self._log(
                    "No VISA resources found. For NI GPIB-USB-HS, verify "
                    "the interfaces in NI MAX first."
                    if self.language == "en"
                    else "未发现 VISA 资源；NI GPIB-USB-HS 请先在 NI MAX "
                    "中确认 GPIB 接口"
                )
                self._set_global_status(tr(self.language, "未发现 VISA"), "bad")

    def _visa_scan_cleanup(self) -> None:
        worker = self._visa_scan_worker
        self._visa_scan_worker = None
        if worker is not None:
            worker.deleteLater()
        for channel, panel in self.panels.items():
            panel.resource_refresh.setEnabled(
                not self.channels[channel].running and panel.source_kind == "visa"
            )

    def _run_connection_self_check(self, channel: str) -> None:
        panel = self.panels[channel]
        if panel.source_kind != "visa":
            QtWidgets.QMessageBox.information(
                self,
                ("Connection self-check" if self.language == "en" else "连接自检"),
                (
                    "The digital twin does not require VISA or GPIB drivers."
                    if self.language == "en"
                    else "数字孪生模式不需要 VISA 或 GPIB 驱动。"
                ),
            )
            return
        existing = self._connection_check_workers.get(channel)
        if existing is not None and existing.isRunning():
            return
        worker = ConnectionCheckWorker(
            panel.resource_name,
            panel.instrument_model,
            self,
        )
        self._connection_check_workers[channel] = worker
        panel.connection_check.setEnabled(False)
        panel.connection_check.setText(tr(self.language, "自检中…"))
        self._set_channel_state(channel, "连接中")
        self._log(
            f"{channel} connection self-check started · "
            f"{panel.instrument_model.display_name} · {panel.resource_name}"
            if self.language == "en"
            else f"{channel} 开始连接自检 · "
            f"{panel.instrument_model.display_name} · {panel.resource_name}"
        )
        worker.result_ready.connect(
            partial(self._connection_self_check_finished, channel)
        )
        worker.finished.connect(partial(self._connection_self_check_cleanup, channel))
        worker.start()

    def _connection_self_check_finished(
        self,
        channel: str,
        diagnostic: ConnectionDiagnostic,
    ) -> None:
        runtime = self.channels[channel]
        runtime.last_connection_diagnostic = diagnostic
        self._set_channel_state(
            channel,
            "待机" if diagnostic.ok else "采集错误",
        )
        self._set_global_status(
            diagnostic.title(self.language),
            "good" if diagnostic.ok else "bad",
        )
        logger.info(
            "Connection self-check complete | channel=%s | code=%s | "
            "resource=%s | backend=%s",
            channel,
            diagnostic.code.value,
            diagnostic.resource,
            diagnostic.visa_backend,
        )
        self._log(
            f"{channel} self-check: {diagnostic.title('en')} · "
            f"{diagnostic.summary('en')}"
            if self.language == "en"
            else f"{channel} 自检：{diagnostic.title('zh')} · "
            f"{diagnostic.summary('zh')}"
        )
        if self._shutdown_in_progress:
            return
        ConnectionDiagnosticDialog(
            diagnostic,
            self.language,
            self,
        ).exec()

    def _connection_self_check_cleanup(self, channel: str) -> None:
        worker = self._connection_check_workers.pop(channel, None)
        if worker is not None:
            worker.deleteLater()
        panel = self.panels[channel]
        panel.connection_check.setText(tr(self.language, "连接自检"))
        if not self.channels[channel].running:
            panel.connection_check.setEnabled(panel.source_kind == "visa")

    def _assign_discovered_resources(self, resources: list[str]) -> dict[str, str]:
        """Assign model-compatible VISA resources without moving live sessions."""
        unique_resources = list(dict.fromkeys(resources))
        running_channels = {
            channel for channel in self.CHANNELS if self.channels[channel].running
        }
        assignments: dict[str, str] = {}
        occupied: set[str] = set()
        for channel in running_channels:
            current = self.panels[channel].resource_name
            assignments[channel] = current
            occupied.add(current.upper())
        stopped_channels = [
            channel
            for channel in self.CHANNELS
            if (
                channel not in running_channels
                and self.panels[channel].instrument_model.requires_gpib
            )
        ] + [
            channel
            for channel in self.CHANNELS
            if (
                channel not in running_channels
                and not self.panels[channel].instrument_model.requires_gpib
            )
        ]
        for channel in stopped_channels:
            panel = self.panels[channel]
            compatible = (
                gpib_instrument_resources(unique_resources)
                if panel.instrument_model.requires_gpib
                else (
                    [
                        resource
                        for resource in unique_resources
                        if resource not in gpib_instrument_resources(unique_resources)
                    ]
                    + gpib_instrument_resources(unique_resources)
                )
            )
            selected = next(
                (
                    resource
                    for resource in compatible
                    if resource.upper() not in occupied
                ),
                panel.resource_name,
            )
            assignments[channel] = selected
            occupied.add(selected.upper())
        for channel in self.CHANNELS:
            panel = self.panels[channel]
            compatible = (
                gpib_instrument_resources(unique_resources)
                if panel.instrument_model.requires_gpib
                else unique_resources
            )
            panel.set_resources(
                compatible,
                selected_resource=assignments[channel],
            )
        return assignments

    def _make_driver(
        self, channel: str, config: AcquisitionConfig
    ) -> SimulatorDriver | Keysight3458ADriver | Fluke8508ADriver | ScpiDmmDriver:
        panel = self.panels[channel]
        if panel.source_kind == "sim":
            return SimulatorDriver(
                config,
                seed=3458 + self.CHANNELS.index(channel),
                resource_name=(f"SIM::{panel.instrument_model.short_name}::{channel}"),
                instrument_model=panel.instrument_model,
            )
        if panel.instrument_model.uses_hpib_commands:
            return Keysight3458ADriver(panel.resource_name, config)
        if panel.instrument_model is InstrumentModel.FLUKE_8508A:
            return Fluke8508ADriver(panel.resource_name, config)
        return ScpiDmmDriver(
            panel.resource_name,
            panel.instrument_model,
            config,
        )

    def _validate_distinct_resources(self, channels: set[str]) -> None:
        real = [
            self.panels[key].resource_name.strip().upper()
            for key in channels
            if self.panels[key].source_kind == "visa"
        ]
        if len(real) != len(set(real)):
            raise ValueError(
                "Enabled channels cannot share a VISA resource. Assign a "
                "different VISA resource to each physical instrument."
                if self.language == "en"
                else "已启用通道不能连接同一个 VISA 地址。请为每台真实仪表"
                "选择不同的 VISA 仪表资源。"
            )

    def _toggle_channel(self, channel: str) -> None:
        runtime = self.channels[channel]
        if runtime.running:
            self._stop_channel(channel)
            return
        if channel not in self.enabled_channels:
            return
        try:
            active = {channel}
            active.update(
                key for key in self.enabled_channels if self.channels[key].running
            )
            self._validate_distinct_resources(active)
            config = self.panels[channel].read_config()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(
                self, tr(self.language, "参数或地址错误"), str(exc)
            )
            return
        self._start_channel(channel, config)

    def _start_both(self) -> None:
        members = self.sync_channels
        if not members:
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "无法同步启动"),
                (
                    "Select at least one channel to start."
                    if self.language == "en"
                    else "请至少勾选一个需要启动的通道。"
                ),
            )
            return
        if any(self.channels[key].running for key in members):
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "无法同步启动"),
                (
                    "Every selected channel must be stopped. Running channels "
                    "that are not selected will remain unaffected."
                    if self.language == "en"
                    else "所有勾选通道都必须处于停止状态；未勾选且正在采集的通道"
                    "不会受到影响。"
                ),
            )
            return
        try:
            configs = {key: self.panels[key].read_config() for key in members}
            active = set(members)
            active.update(
                key for key in self.enabled_channels if self.channels[key].running
            )
            self._validate_distinct_resources(active)
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(
                self, tr(self.language, "参数或地址错误"), str(exc)
            )
            return
        gate = threading.Event()
        self._group_gate = gate
        self._group_pending = set(members)
        self._group_members = set(members)
        self._update_sync_controls()
        group_name = "+".join(members)
        self._log(
            (
                f"{group_name} synchronized start: connecting and "
                "configuring selected instruments."
            )
            if self.language == "en"
            else f"{group_name} 同步启动：正在分别连接并配置所选仪表"
        )
        for key in members:
            self._start_channel(key, configs[key], start_gate=gate)

    def _start_channel(
        self,
        channel: str,
        config: AcquisitionConfig,
        start_gate: threading.Event | None = None,
    ) -> None:
        runtime = self.channels[channel]
        panel = self.panels[channel]
        runtime.session.clear()
        runtime.session.unit = config.function.unit
        runtime.session.source = (
            f"{panel.instrument_model.short_name} {channel} Simulator"
            if panel.source_kind == "sim"
            else panel.resource_name
        )
        runtime.session.channel = channel
        runtime.session.instrument_model = panel.instrument_model.display_name
        runtime.session.resource = runtime.session.source
        runtime.last_temperature = np.nan
        runtime.minimum = np.inf
        runtime.maximum = -np.inf
        runtime.error = ""
        runtime.identity = None
        runtime.target_samples = (
            config.max_samples
            if panel.acquisition_mode == "precision"
            else int(panel.burst_count.value())
        )
        try:
            runtime.durable_writer = DurableSessionWriter(
                channel=channel,
                instrument_model=panel.instrument_model.display_name,
                resource=runtime.session.source,
                run_id=new_run_id(),
                root=self.autosave_root,
            )
            runtime.last_autosave_path = str(runtime.durable_writer.partial_path)
        except Exception as exc:
            logger.exception(
                "Durable autosave initialization failed | channel=%s",
                channel,
            )
            runtime.durable_writer = None
            runtime.error = str(exc)
            QtWidgets.QMessageBox.critical(
                self,
                (
                    "Safe autosave unavailable"
                    if self.language == "en"
                    else "安全自动保存不可用"
                ),
                (
                    "Acquisition was not started because received samples "
                    "could not be guaranteed to persist.\n\n"
                    if self.language == "en"
                    else "由于无法保证接收数据安全落盘，采集未启动。\n\n"
                )
                + str(exc),
            )
            return
        driver = self._make_driver(channel, config)
        if panel.acquisition_mode == "precision":
            worker: PrecisionAcquisitionWorker | BurstAcquisitionWorker
            worker = PrecisionAcquisitionWorker(
                driver,
                config,
                start_gate=start_gate,
                preflight=panel.source_kind == "visa",
            )
            worker.measurement_ready.connect(
                partial(self._measurement_received, channel)
            )
        else:
            worker = BurstAcquisitionWorker(
                driver=driver,
                count=panel.burst_count.value(),
                interval_s=panel.burst_interval_us.value() * 1e-6,
                aperture_s=panel.burst_aperture_us.value() * 1e-6,
                function=config.function,
                measurement_range=config.measurement_range,
                start_gate=start_gate,
                preflight=panel.source_kind == "visa",
            )
            worker.result_ready.connect(partial(self._burst_received, channel))
        worker.identity_ready.connect(partial(self._identity_received, channel))
        worker.armed.connect(partial(self._channel_armed, channel))
        worker.failed.connect(partial(self._worker_failed, channel))
        worker.connection_issue.connect(partial(self._worker_connection_issue, channel))
        # QThread.finished is emitted only after run() has returned. Using the
        # worker's earlier custom "stopped" signal here could drop the final
        # Python reference while the native thread was still unwinding.
        worker.finished.connect(partial(self._worker_stopped, channel))
        runtime.worker = worker
        panel.set_running(
            True, stoppable=isinstance(worker, PrecisionAcquisitionWorker)
        )
        self._set_channel_state(channel, "连接中")
        readout = self.readouts[channel]
        readout["source"].setText(
            "SIMULATOR" if panel.source_kind == "sim" else panel.resource_name
        )
        readout["mode"].setText(
            f"{config.function.command} · {panel.range_combo.currentText().upper()}"
            + (
                (
                    f" · {runtime.target_samples:,} samples"
                    if self.language == "en"
                    else f" · {runtime.target_samples:,}点"
                )
                if runtime.target_samples is not None
                else (" · CONTINUOUS" if self.language == "en" else " · 持续")
            )
        )
        readout["unit"].setText(config.function.unit)
        readout["value"].setText("—")
        readout["time"].setText(tr(self.language, "等待数据"))
        readout["temperature"].setText("TEMP —")
        if self.language == "en":
            target_text = (
                f"target {runtime.target_samples:,}; auto-stop on completion"
                if runtime.target_samples is not None
                else "continuous acquisition"
            )
            self._log(
                f"{channel} {panel.instrument_model.short_name} start "
                f"{panel.mode_combo.currentText()} · "
                f"{config.function.command} · resource {runtime.session.source} · "
                f"{target_text} · durable autosave enabled"
            )
        else:
            self._log(
                f"{channel} 启动 {panel.instrument_model.short_name} · "
                f"{panel.mode_combo.currentText()} · "
                f"{config.function.command} · 实际地址 {runtime.session.source} · "
                + (
                    f"目标 {runtime.target_samples:,} 点，完成后自动停止"
                    if runtime.target_samples is not None
                    else "持续采集"
                )
                + " · 安全自动保存已开启"
            )
        self._refresh_views()
        worker.start()
        self._update_sync_controls()

    def _channel_armed(self, channel: str) -> None:
        if self._group_gate is None or channel not in self._group_members:
            return
        self._group_pending.discard(channel)
        self._set_channel_state(channel, "已就绪")
        self._log(
            f"{channel} configured and waiting for synchronized release."
            if self.language == "en"
            else f"{channel} 已连接并配置，等待同步释放"
        )
        if not self._group_pending:
            self._group_gate.set()
            group_name = "+".join(sorted(self._group_members))
            self._log(
                f"{group_name} acquisition released (software sync)."
                if self.language == "en"
                else f"{group_name} 已释放采集线程（软件级同步）"
            )
            for member in self._group_members:
                self._set_channel_state(member, "正在采集")
            self._group_gate = None
            self._group_members.clear()
            self._update_sync_controls()

    def _stop_channel(self, channel: str) -> None:
        runtime = self.channels[channel]
        worker = runtime.worker
        if worker is None or not worker.isRunning():
            return
        if isinstance(worker, BurstAcquisitionWorker):
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "突发采集中"),
                (
                    f"Instrument channel {channel} is acquiring into memory. "
                    "This batch will stop automatically when complete."
                    if self.language == "en"
                    else f"仪表通道 {channel} 正在执行内存突发采集。"
                    "为避免破坏 GPIB 会话，当前批次完成后会自动停止。"
                ),
            )
            return
        worker.request_stop()
        self.panels[channel].start_button.setEnabled(False)
        self._set_channel_state(channel, "正在停止")
        self._log(
            f"{channel} stopping." if self.language == "en" else f"{channel} 正在停止"
        )

    def _stop_all(self) -> None:
        requested = False
        if self._group_gate is not None:
            self._group_gate.set()
        for key in self.CHANNELS:
            worker = self.channels[key].worker
            if worker is not None and worker.isRunning():
                worker.request_stop()
                requested = True
                self.panels[key].start_button.setEnabled(False)
                self._set_channel_state(key, "正在停止")
        if requested:
            self._log(
                "Stop requested for all running channels."
                if self.language == "en"
                else "已请求停止全部通道"
            )

    def _identity_received(self, channel: str, identity) -> None:
        runtime = self.channels[channel]
        runtime.identity = identity
        self._set_channel_state(
            channel, "等待同步" if channel in self._group_members else "正在采集"
        )
        self._update_identity_view()
        self._update_header_sources()
        self._log(
            f"{channel} connected: {identity.model} · {identity.resource}"
            if self.language == "en"
            else f"{channel} 已连接：{identity.model} · {identity.resource}"
        )

    def _measurement_received(self, channel: str, measurement) -> None:
        runtime = self.channels[channel]
        if measurement.internal_temperature_c is None and np.isfinite(
            runtime.last_temperature
        ):
            measurement.internal_temperature_c = float(runtime.last_temperature)
        elif measurement.internal_temperature_c is not None:
            runtime.last_temperature = measurement.internal_temperature_c
        try:
            if runtime.durable_writer is None:
                raise RuntimeError("durable autosave writer is not active")
            runtime.durable_writer.append(measurement)
            runtime.last_autosave_path = str(runtime.durable_writer.path)
        except Exception as exc:
            logger.exception(
                "Durable sample commit failed | channel=%s",
                channel,
            )
            runtime.error = f"安全自动保存失败: {exc}"
            if runtime.worker is not None:
                runtime.worker.request_stop()
            self._set_channel_state(channel, "采集错误")
            self._log(
                f"{channel} durable autosave failed; acquisition stopped: {exc}"
                if self.language == "en"
                else f"{channel} 安全自动保存失败，已停止采集：{exc}"
            )
            return
        runtime.session.append(measurement)
        runtime.minimum = min(runtime.minimum, float(measurement.value))
        runtime.maximum = max(runtime.maximum, float(measurement.value))
        readout = self.readouts[channel]
        readout["value"].setText(f"{measurement.value:.11g}")
        readout["unit"].setText(measurement.unit)
        readout["extremes"].setText(
            f"MIN {format_number(runtime.minimum, measurement.unit, 7)}"
            f"  ·  MAX {format_number(runtime.maximum, measurement.unit, 7)}"
        )
        timestamp_text = measurement.timestamp.astimezone().strftime(
            "%Y-%m-%d %H:%M:%S.%f"
        )[:-3]
        if runtime.target_samples is None:
            readout["time"].setText(
                f"{len(runtime.session):,} samples · {timestamp_text}"
                if self.language == "en"
                else f"{len(runtime.session):,} 点 · {timestamp_text}"
            )
        else:
            readout["time"].setText(
                f"{len(runtime.session):,} / {runtime.target_samples:,} "
                f"{'samples' if self.language == 'en' else '点'}"
                f" · {timestamp_text}"
            )
        if measurement.internal_temperature_c is not None:
            readout["temperature"].setText(
                f"TEMP {measurement.internal_temperature_c:.3f}°C"
            )
        self._live_refresh_pending = True
        self._analysis_refresh_pending = True
        if len(runtime.session) < 4:
            self._analysis_refresh_pending = False
            self._live_refresh_pending = False
            self._refresh_views()

    def _burst_received(self, channel: str, x, y) -> None:
        runtime = self.channels[channel]
        x_array = np.asarray(x, dtype=float)
        y_array = np.asarray(y, dtype=float)
        runtime.session.replace(
            x_array,
            y_array,
            unit=runtime.session.unit,
            source=runtime.session.source,
        )
        if y_array.size:
            runtime.minimum = float(np.min(y_array))
            runtime.maximum = float(np.max(y_array))
        measurements = [
            Measurement(
                elapsed_s=float(runtime.session.elapsed_s[index]),
                value=float(runtime.session.values[index]),
                unit=runtime.session.unit,
                timestamp=datetime.fromtimestamp(
                    float(runtime.session.timestamps[index]),
                    tz=timezone.utc,
                ),
            )
            for index in range(len(runtime.session))
        ]
        try:
            if runtime.durable_writer is None:
                raise RuntimeError("durable autosave writer is not active")
            runtime.durable_writer.append_many(measurements)
            runtime.last_autosave_path = str(runtime.durable_writer.path)
        except Exception as exc:
            logger.exception(
                "Durable burst commit failed | channel=%s",
                channel,
            )
            runtime.error = f"安全自动保存失败: {exc}"
            self._set_channel_state(channel, "采集错误")
            self._log(
                f"{channel} burst reached the PC but durable commit failed: {exc}"
                if self.language == "en"
                else f"{channel} 突发数据已传到电脑，但安全落盘失败：{exc}"
            )
        if y_array.size:
            readout = self.readouts[channel]
            readout["value"].setText(f"{y_array[-1]:.11g}")
            readout["unit"].setText(runtime.session.unit)
            timestamp_text = (
                datetime.fromtimestamp(
                    float(runtime.session.timestamps[-1]),
                    tz=timezone.utc,
                )
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            )
            readout["time"].setText(
                f"Burst complete · {y_array.size} samples · {timestamp_text}"
                if self.language == "en"
                else f"突发完成 · {y_array.size}点 · {timestamp_text}"
            )
            readout["extremes"].setText(
                f"MIN {format_number(runtime.minimum, runtime.session.unit, 7)}"
                f"  ·  MAX {format_number(runtime.maximum, runtime.session.unit, 7)}"
            )
        self._refresh_views()
        self._log(
            f"{channel} burst complete: {y_array.size} samples."
            if self.language == "en"
            else f"{channel} 高速突发采集完成：{y_array.size} 点"
        )

    def _worker_connection_issue(
        self,
        channel: str,
        diagnostic: ConnectionDiagnostic,
    ) -> None:
        runtime = self.channels[channel]
        runtime.last_connection_diagnostic = diagnostic
        runtime.error = diagnostic.summary(self.language)
        self._finalize_autosave(
            channel,
            "connection_error",
            runtime.error,
        )
        logger.error(
            "Channel connection failed | channel=%s | code=%s | "
            "resource=%s | raw_error=%s",
            channel,
            diagnostic.code.value,
            diagnostic.resource,
            diagnostic.raw_error,
        )
        self._set_channel_state(channel, "采集错误")
        self._set_global_status(diagnostic.title(self.language), "bad")
        self._log(
            f"{channel} {diagnostic.title('en')}: {diagnostic.summary('en')}"
            if self.language == "en"
            else f"{channel} {diagnostic.title('zh')}：{diagnostic.summary('zh')}"
        )
        if self._group_gate is not None and channel in self._group_members:
            self._group_gate.set()
            for other in self._group_members - {channel}:
                other_worker = self.channels[other].worker
                if other_worker is not None:
                    other_worker.request_stop()
            self._group_gate = None
            self._group_pending.clear()
            self._group_members.clear()
            self._update_sync_controls()
        if self._shutdown_in_progress:
            return
        ConnectionDiagnosticDialog(
            diagnostic,
            self.language,
            self,
        ).exec()

    def _worker_failed(self, channel: str, message: str) -> None:
        runtime = self.channels[channel]
        runtime.error = message
        self._finalize_autosave(channel, "error", message)
        logger.error(
            "Channel acquisition failed | channel=%s | resource=%s | error=%s",
            channel,
            runtime.session.source,
            message,
        )
        self._set_channel_state(channel, "采集错误")
        self._log(
            f"{channel} error: {message}"
            if self.language == "en"
            else f"{channel} 错误：{message}"
        )
        if self._group_gate is not None and channel in self._group_members:
            self._group_gate.set()
            for other in self._group_members - {channel}:
                other_worker = self.channels[other].worker
                if other_worker is not None:
                    other_worker.request_stop()
            self._group_gate = None
            self._group_pending.clear()
            self._group_members.clear()
            self._update_sync_controls()
            message = (
                f"Instrument channel {channel} failed during synchronized startup; "
                f"the other channels were cancelled.\n\n{message}"
                if self.language == "en"
                else f"仪表通道 {channel} 在同步启动阶段失败，其他通道已取消。\n\n"
                f"{message}"
            )
        QtWidgets.QMessageBox.critical(
            self,
            (
                f"Instrument channel {channel} acquisition error"
                if self.language == "en"
                else f"仪表通道 {channel} 采集错误"
            ),
            message,
        )

    def _worker_stopped(self, channel: str) -> None:
        runtime = self.channels[channel]
        worker = runtime.worker
        completed_target = bool(
            isinstance(worker, PrecisionAcquisitionWorker) and worker.completed_target
        )
        runtime.worker = None
        self.panels[channel].set_running(False)
        autosave_status = (
            "error"
            if runtime.error
            else ("completed" if completed_target else "stopped")
        )
        self._finalize_autosave(
            channel,
            autosave_status,
            runtime.error,
        )
        if runtime.error:
            self._set_channel_state(channel, "采集错误")
        elif completed_target:
            self._set_channel_state(channel, "已完成")
            timestamp_text = (
                datetime.fromtimestamp(
                    float(runtime.session.timestamps[-1]),
                    tz=timezone.utc,
                )
                .astimezone()
                .strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                if runtime.session.timestamps
                else "—"
            )
            self.readouts[channel]["time"].setText(
                f"Complete · {len(runtime.session):,} / "
                f"{runtime.target_samples or len(runtime.session):,} samples"
                f" · {timestamp_text}"
                if self.language == "en"
                else f"完成 · {len(runtime.session):,} / "
                f"{runtime.target_samples or len(runtime.session):,} 点"
                f" · {timestamp_text}"
            )
        else:
            self._set_channel_state(channel, "已停止")
        if channel in self._group_members:
            self._group_members.discard(channel)
            self._group_pending.discard(channel)
            if not self._group_members:
                self._group_gate = None
                self._update_sync_controls()
        else:
            self._update_sync_controls()
        self._refresh_views()
        if completed_target:
            self._log(
                f"{channel} fixed-count acquisition complete: "
                f"{len(runtime.session):,} samples; stopped automatically."
                if self.language == "en"
                else f"{channel} 固定点数采集完成：{len(runtime.session):,} 点，"
                "已自动停止"
            )
        else:
            self._log(
                f"{channel} acquisition stopped."
                if self.language == "en"
                else f"{channel} 采集已停止"
            )

    def _finalize_autosave(
        self,
        channel: str,
        status: str,
        error: str = "",
    ) -> None:
        runtime = self.channels[channel]
        writer = runtime.durable_writer
        if writer is None:
            return
        try:
            output = writer.finalize(status, error)
            runtime.last_autosave_path = str(output)
            self._log(
                f"{channel} durable capture finalized: {output.name}"
                if self.language == "en"
                else f"{channel} 安全采集文件已完成：{output.name}"
            )
        except Exception:
            logger.exception(
                "Durable capture finalization failed | channel=%s",
                channel,
            )
        finally:
            runtime.durable_writer = None

    # ---------- Analysis ----------

    def _selected_runtime(self) -> ChannelRuntime:
        return self.channels[self.selected_channel]

    def _analysis_arrays(
        self, session: SessionData
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = session.x
        y = session.y
        temperature = session.temperature
        if self.outlier_check.isChecked() and y.size:
            mask = sigma_mask(y, self.sigma_spin.value())
            return x[mask], y[mask], temperature[mask]
        return x, y, temperature

    def _analysis_resource_text(self, channel: str) -> str:
        runtime = self.channels[channel]
        if runtime.identity is not None:
            return runtime.identity.resource
        session_source = runtime.session.source.strip()
        if session_source and session_source not in {"演示模式", "CSV"}:
            return session_source
        panel = self.panels[channel]
        if panel.source_kind == "visa":
            return panel.resource_name
        return f"SIM::{panel.instrument_model.short_name}::{channel}"

    def _sample_text(self, channel: str) -> str:
        runtime = self.channels[channel]
        noun = "samples" if self.language == "en" else "样本"
        if runtime.target_samples is not None:
            return f"{len(runtime.session):,} / {runtime.target_samples:,} {noun}"
        return f"{len(runtime.session):,} {noun}"

    def _analysis_units_match(self) -> bool:
        units = {
            self.channels[channel].session.unit
            for channel in self.analysis_channels
            if len(self.channels[channel].session)
        }
        return len(units) <= 1

    @staticmethod
    def _set_legend_label(
        plot: pg.PlotWidget,
        item,
        text: str,
    ) -> None:
        legend = getattr(plot.getPlotItem(), "legend", None)
        if legend is None:
            return
        label = legend.getLabel(item)
        if label is not None:
            label.setText(text)

    def _update_analysis_identity(self) -> None:
        """Keep every analysis surface visibly tied to its physical instruments."""
        metric_channel = self.selected_channel
        metric_panel = self.panels[metric_channel]
        metric_resource = self._analysis_resource_text(metric_channel)
        metric_identity = (
            f"{metric_channel} · {metric_panel.instrument_model.short_name} · "
            f"{metric_panel.current_function().command} · "
            f"{metric_resource} · "
            f"{self.channels[metric_channel].session.unit}"
        )
        self.metric_basis_label.setText(
            f"METRIC SOURCE  {metric_identity}"
            if self.language == "en"
            else f"当前指标来源  {metric_identity}"
        )
        metric_object = f"analysisChannel{metric_channel}"
        if self.metric_basis_label.objectName() != metric_object:
            self.metric_basis_label.setObjectName(metric_object)
            self.metric_basis_label.style().unpolish(self.metric_basis_label)
            self.metric_basis_label.style().polish(self.metric_basis_label)
        metric_labels = {
            "mean": "平均值",
            "std": "标准差",
            "min": "最小值",
            "max": "最大值",
            "p2p": "峰峰值",
            "noise": "离散系数",
            "drift": "线性漂移 / h",
            "count": "样本数",
        }
        for key, label in metric_labels.items():
            self.metric_cards[key].title.setText(
                f"{metric_channel} · {tr(self.language, label)}"
            )
            self.metric_cards[key].setToolTip(metric_identity)

        for index, key in enumerate(self.CHANNELS):
            item_resource = self._analysis_resource_text(key)
            model_name = self.panels[key].instrument_model.short_name
            self.analysis_channel_combo.setItemText(
                index, f"{model_name} {key} · {item_resource}"
            )
            self.analysis_channel_combo.setItemData(
                index, item_resource, QtCore.Qt.ItemDataRole.ToolTipRole
            )

        analysis_channels = self.analysis_channels
        multi = len(analysis_channels) > 1
        if multi:
            suffix = "+".join(analysis_channels)
            channel_text = " + ".join(
                f"{self.panels[key].instrument_model.short_name} {key}"
                for key in analysis_channels
            )
            resource = "  ·  ".join(
                f"{key} {self._analysis_resource_text(key)}"
                for key in analysis_channels
            )
            unit_text = (
                self.channels[analysis_channels[0]].session.unit
                if self._analysis_units_match()
                else " / ".join(
                    f"{key} {self.channels[key].session.unit}"
                    for key in analysis_channels
                )
            )
            mismatch_text = (
                ""
                if self._analysis_units_match()
                else (
                    " · mixed units; analysis plots follow selected channel"
                    if self.language == "en"
                    else " · 混合单位；分析曲线跟随当前所选通道"
                )
            )
            sample_text = " · ".join(
                f"{key} {self._sample_text(key)}" for key in analysis_channels
            )
            meta_text = (
                f"{tr(self.language, '多通道分析')} · "
                f"{sample_text} · {unit_text}{mismatch_text}"
            )
            channel_object = "analysisChannelAB"
            tab_suffix = suffix
            title_color = COLORS["text"]
        else:
            channel = self.selected_channel
            runtime = self.channels[channel]
            session = runtime.session
            resource = self._analysis_resource_text(channel)
            source_kind = (
                tr(self.language, "实时采集")
                if runtime.running
                else (
                    tr(self.language, "CSV 会话")
                    if session.source.lower().endswith(".csv")
                    else tr(self.language, "会话数据")
                )
            )
            channel_text = (
                f"{self.panels[channel].instrument_model.short_name} {channel}"
            )
            meta_text = (
                f"{tr(self.language, '单通道分析')} · {source_kind} · "
                f"{self._sample_text(channel)} · {session.unit}"
            )
            channel_object = f"analysisChannel{channel}"
            tab_suffix = channel
            title_color = self.CHANNEL_COLORS[channel]

        for banner in self.analysis_banners.values():
            label = banner["channel"]
            label.setText(channel_text)
            if label.objectName() != channel_object:
                label.setObjectName(channel_object)
                label.style().unpolish(label)
                label.style().polish(label)
            banner["resource"].setText(resource)
            banner["meta"].setText(meta_text)
        for key in self.CHANNELS:
            panel = self.panels[key]
            legend_identity = (
                f"{key} · {panel.instrument_model.short_name} · "
                f"{self._analysis_resource_text(key)}"
            )
            for plot, item in (
                (self.fft_plot, self.fft_curves[key]),
                (self.asd_plot, self.asd_curves[key]),
                (self.hist_plot, self.hist_bars[key]),
                (self.allan_plot, self.allan_curves[key]),
            ):
                self._set_legend_label(plot, item, legend_identity)
            self._set_legend_label(
                self.drift_plot,
                self.drift_points[key],
                f"{legend_identity} · DATA",
            )
            self._set_legend_label(
                self.drift_plot,
                self.drift_fit_curves[key],
                f"{legend_identity} · FIT",
            )
            self.statistics_summary_titles[key].setText(
                f"{self.panels[key].instrument_model.short_name} {key} · "
                f"{tr(self.language, '统计摘要')}"
            )

        self.tabs.setTabText(self.spectrum_tab_index, f"FFT / ASD · {tab_suffix}")
        self.tabs.setTabText(
            self.statistics_tab_index,
            f"{tr(self.language, '统计分布')} · {tab_suffix}",
        )
        self.tabs.setTabText(
            self.stability_tab_index,
            f"{tr(self.language, '稳定性 / 温漂')} · {tab_suffix}",
        )
        self.fft_plot.setTitle(
            (
                f"{channel_text} · FFT amplitude spectrum · {resource}"
                if self.language == "en"
                else f"{channel_text} · FFT 幅度谱 · {resource}"
            ),
            color=title_color,
            size="11pt",
        )
        self.asd_plot.setTitle(
            f"{channel_text} · ASD · {resource}",
            color=title_color,
            size="11pt",
        )
        self.hist_plot.setTitle(
            f"{channel_text} · {tr(self.language, '统计分布')} · {resource}",
            color=title_color,
            size="11pt",
        )
        self.allan_plot.setTitle(
            (
                f"{channel_text} · Stability / Allan deviation · {resource}"
                if self.language == "en"
                else f"{channel_text} · 稳定性 / Allan deviation · {resource}"
            ),
            color=title_color,
            size="11pt",
        )
        self.drift_plot.setTitle(
            (
                f"{channel_text} · Drift / temperature · {resource}"
                if self.language == "en"
                else f"{channel_text} · 漂移 / 温漂 · {resource}"
            ),
            color=title_color,
            size="11pt",
        )

    def _update_memory_monitor(self) -> None:
        try:
            snapshot = memory_snapshot()
        except OSError:
            self.memory_label.setText("RAM — · APP —")
            return
        self._last_memory_snapshot = snapshot
        process_mib = snapshot.process_rss_bytes / (1024**2)
        self.memory_label.setText(
            f"RAM {snapshot.system_percent:.1f}% · APP {process_mib:.0f} MB"
        )
        used_gib = snapshot.system_used_bytes / (1024**3)
        total_gib = snapshot.system_total_bytes / (1024**3)
        self.memory_label.setToolTip(
            f"System RAM {used_gib:.2f} / {total_gib:.2f} GiB · "
            f"Application working set {process_mib:.1f} MiB"
            if self.language == "en"
            else f"电脑内存 {used_gib:.2f} / {total_gib:.2f} GiB · "
            f"本软件工作集 {process_mib:.1f} MiB"
        )

    @staticmethod
    def _session_display_arrays(
        session: SessionData,
        max_points: int = 20_000,
        x_window: tuple[float, float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Build a bounded trend payload without copying the full session."""
        if (
            x_window is not None
            and len(session.timestamps) == len(session)
            and session.timestamps
        ):
            indices = windowed_display_indices(
                session.timestamps,
                x_window[0],
                x_window[1],
                max_points,
            )
        else:
            indices = display_indices(len(session), max_points)
        if not indices.size:
            return np.asarray([], dtype=float), np.asarray([], dtype=float)
        y = np.fromiter(
            (float(session.values[int(index)]) for index in indices),
            dtype=float,
            count=indices.size,
        )
        if len(session.timestamps) == len(session):
            x = np.fromiter(
                (float(session.timestamps[int(index)]) for index in indices),
                dtype=float,
                count=indices.size,
            )
            return x, y
        start = (
            float(session.timestamps[0])
            if session.timestamps
            else QtCore.QDateTime.currentDateTimeUtc().toSecsSinceEpoch()
        )
        first_elapsed = float(session.elapsed_s[0])
        x = np.fromiter(
            (
                start + float(session.elapsed_s[int(index)]) - first_elapsed
                for index in indices
            ),
            dtype=float,
            count=indices.size,
        )
        return x, y

    def _update_trend_axis_selector(self) -> None:
        current = str(self.trend_axis_combo.currentData() or "")
        units = self.trend_plot.available_units
        desired = ("", *units)
        existing = tuple(
            str(self.trend_axis_combo.itemData(index) or "")
            for index in range(self.trend_axis_combo.count())
        )
        if existing == desired:
            return
        self.trend_axis_combo.blockSignals(True)
        self.trend_axis_combo.clear()
        self.trend_axis_combo.addItem(
            tr(self.language, "全部 Y 轴"),
            "",
        )
        for unit in units:
            self.trend_axis_combo.addItem(f"Y · {unit}", unit)
        selected_index = self.trend_axis_combo.findData(current)
        self.trend_axis_combo.setCurrentIndex(max(selected_index, 0))
        self.trend_axis_combo.blockSignals(False)

    @QtCore.Slot(float, float)
    def _trend_window_changed(self, x_min: float, x_max: float) -> None:
        if not np.isfinite(x_min) or not np.isfinite(x_max) or x_max <= x_min:
            return
        self._trend_x_window = (float(x_min), float(x_max))
        self._live_refresh_pending = True

    def _reset_trend_zoom(self) -> None:
        self._trend_x_window = None
        self.trend_plot.reset_view()
        self._live_refresh_pending = True

    def _refresh_trend_view(self) -> None:
        channel = self.selected_channel
        session = self.channels[channel].session
        selected_wall_clock, selected_y = self._session_display_arrays(
            session,
            x_window=self._trend_x_window,
        )
        smooth = (
            rolling_mean(selected_y, self.rolling_spin.value())
            if self.show_rolling.isChecked() and selected_y.size
            else None
        )
        self.trend_plot.set_labels(
            tr(self.language, "当前时间戳"),
            tr(self.language, "测量值"),
            session.unit,
        )
        for trend_channel in self.CHANNELS:
            trend_session = self.channels[trend_channel].session
            panel = self.panels[trend_channel]
            x_display, y_display = self._session_display_arrays(
                trend_session,
                x_window=self._trend_x_window,
            )
            label = (
                f"{trend_channel} · {panel.instrument_model.short_name}"
                f" · {panel.current_function().command}"
                f" · {panel.resource_name} ({trend_session.unit})"
            )
            self.trend_plot.set_channel_data(
                trend_channel,
                x_display,
                y_display,
                unit=trend_session.unit,
                color=self.CHANNEL_COLORS[trend_channel],
                label=label,
                visible=(
                    trend_channel in self.enabled_channels and bool(len(trend_session))
                ),
                refresh_axes=False,
            )
        self.trend_plot.finish_channel_update()
        self._update_trend_axis_selector()
        self.trend_plot.set_smooth_data(
            channel,
            selected_wall_clock,
            smooth,
        )
        axis_count = len(
            {
                self.channels[key].session.unit
                for key in self.enabled_channels
                if len(self.channels[key].session)
            }
        )
        panel = self.panels[channel]
        self.comparison_note.setText(
            f"Metric source {channel} · {panel.instrument_model.short_name} · "
            f"{panel.current_function().command} · {panel.resource_name} · "
            f"{axis_count} physical-unit axis/axes"
            if self.language == "en"
            else f"当前指标 {channel} · {panel.instrument_model.short_name} · "
            f"{panel.current_function().command} · {panel.resource_name}；"
            f"{axis_count} 个物理量 Y 轴"
        )

    def _live_refresh_tick(self) -> None:
        if not self._live_refresh_pending:
            return
        self._live_refresh_pending = False
        self._refresh_trend_view()

    def _analysis_refresh_tick(self) -> None:
        if not self._analysis_refresh_pending:
            return
        self._analysis_refresh_pending = False
        self._live_refresh_pending = False
        self._refresh_views()

    @QtCore.Slot()
    def _refresh_views(self, *_args) -> None:
        channel = self.selected_channel
        runtime = self.channels[channel]
        session = runtime.session
        self._update_analysis_identity()
        self._refresh_trend_view()

        selected_x, selected_y, _selected_temperature = self._analysis_arrays(session)
        stats = descriptive_stats(selected_y, selected_x)
        self._update_metrics(stats, session.unit)
        self._update_session_info(session)

        analysis_data: dict[
            str, tuple[np.ndarray, np.ndarray, np.ndarray, str, int]
        ] = {}
        for analysis_channel in self.analysis_channels:
            analysis_session = self.channels[analysis_channel].session
            analysis_x, analysis_y, analysis_temperature = self._analysis_arrays(
                analysis_session
            )
            analysis_data[analysis_channel] = (
                analysis_x,
                analysis_y,
                analysis_temperature,
                analysis_session.unit,
                len(analysis_session) - analysis_y.size,
            )

        if not self._analysis_units_match():
            selected_data = {channel: analysis_data[channel]}
            self._update_spectra(selected_data)
            self._update_histograms(selected_data)
            self._update_stability(selected_data)
            self._update_statistics_summaries(analysis_data)
            self.stability_note.setText(
                "Mixed physical units use independent trend axes. "
                f"FFT/ASD/Allan currently show selected channel {channel}; "
                "select another channel to analyze it without unit mixing."
                if self.language == "en"
                else "混合物理量已在趋势页使用独立 Y 轴；"
                f"FFT/ASD/Allan 当前显示所选通道 {channel}，"
                "切换通道即可分别分析，避免错误混用单位。"
            )
        else:
            self._update_spectra(analysis_data)
            self._update_histograms(analysis_data)
            self._update_stability(analysis_data)
        self._update_identity_view()

    def _clear_analysis_views(self, reason: str | None = None) -> None:
        for channel in self.CHANNELS:
            self.fft_curves[channel].setData([], [])
            self.asd_curves[channel].setData([], [])
            self.hist_bars[channel].setOpts(x=[], height=[], width=1.0)
            self.allan_curves[channel].setData([], [])
            self.drift_points[channel].setData([], [])
            self.drift_fit_curves[channel].setData([], [])
        self.stability_note.setText(
            reason
            or (
                (
                    "All displayed channels require at least 4 valid samples."
                    if self.language == "en"
                    else "所有显示通道均需要至少 4 个有效样本"
                )
                if len(self.analysis_channels) > 1
                else (
                    f"{self.panels[self.selected_channel].instrument_model.short_name} "
                    f"{self.selected_channel} · "
                    f"{tr(self.language, '需要至少 4 个有效样本')}"
                )
            )
        )
        for channel_labels in self.summary_labels.values():
            for label in channel_labels.values():
                label.setText("—")

    def _update_metrics(self, stats, unit: str) -> None:
        self.metric_cards["mean"].set_value(format_number(stats.mean, unit, 8))
        self.metric_cards["std"].set_value(format_number(stats.std, unit, 6))
        self.metric_cards["min"].set_value(format_number(stats.minimum, unit, 8))
        self.metric_cards["max"].set_value(format_number(stats.maximum, unit, 8))
        self.metric_cards["p2p"].set_value(format_number(stats.peak_to_peak, unit, 6))
        self.metric_cards["noise"].set_value(
            "—" if not np.isfinite(stats.noise_ppm) else f"{stats.noise_ppm:.4g} ppm"
        )
        self.metric_cards["drift"].set_value(
            format_number(stats.drift_per_hour, f"{unit}/h", 5)
        )
        self.metric_cards["count"].set_value(f"{stats.count:,}")

    def _update_session_info(self, session: SessionData) -> None:
        count = len(session)
        duration = float(np.ptp(session.x)) if count > 1 else 0.0
        period = estimate_sample_period(session.x) if count > 1 else np.nan
        self.session_count.setText(f"{count:,}")
        self.session_duration.setText(format_number(duration, "s", 5))
        self.session_rate.setText(
            "—" if not np.isfinite(period) or period <= 0 else f"{1 / period:.5g} Sa/s"
        )
        self.session_unit.setText(session.unit)

    def _update_spectra(
        self,
        analysis_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, str, int]],
    ) -> None:
        for channel in self.CHANNELS:
            self.fft_curves[channel].setData([], [])
            self.asd_curves[channel].setData([], [])
        unit = ""
        for channel, (
            x,
            y,
            _temperature,
            channel_unit,
            _removed,
        ) in analysis_data.items():
            unit = channel_unit
            if y.size < 4:
                continue
            result = spectrum(y, estimate_sample_period(x))
            self.fft_curves[channel].setData(result["frequency"], result["amplitude"])
            asd_frequency = result.get("asd_frequency", result["frequency"])
            positive = (asd_frequency > 0) & (result["asd"] > 0)
            self.asd_curves[channel].setData(
                asd_frequency[positive], result["asd"][positive]
            )
        self.fft_plot.setLabel("left", tr(self.language, "幅值"), units=unit or None)
        self.asd_plot.setLabel("left", "ASD", units=f"{unit}/√Hz" if unit else None)

    def _update_statistics_summaries(
        self,
        analysis_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, str, int]],
    ) -> None:
        visible = set(analysis_data)
        for channel in self.CHANNELS:
            self.statistics_summary_cards[channel].setVisible(channel in visible)
            if channel not in visible:
                continue
            _x, y, _temperature, unit, removed = analysis_data[channel]
            stats = descriptive_stats(y)
            labels = self.summary_labels[channel]
            labels["min"].setText(format_number(stats.minimum, unit, 7))
            labels["max"].setText(format_number(stats.maximum, unit, 7))
            labels["median"].setText(format_number(stats.median, unit, 7))
            labels["rms"].setText(format_number(stats.rms, unit, 7))
            labels["count"].setText(f"{y.size:,} / {removed:,}")

    def _update_histograms(
        self,
        analysis_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, str, int]],
    ) -> None:
        self._update_statistics_summaries(analysis_data)
        for channel in self.CHANNELS:
            self.hist_bars[channel].setOpts(x=[], height=[], width=1.0)
        populated = [
            (channel, values[1])
            for channel, values in analysis_data.items()
            if values[1].size
        ]
        if not populated:
            return
        combined = np.concatenate([values for _channel, values in populated])
        bins = min(100, max(8, int(np.sqrt(combined.size))))
        if np.ptp(combined) == 0:
            span = max(abs(float(combined[0])) * 1e-9, 1e-12)
            edges = np.linspace(
                float(combined[0]) - span,
                float(combined[0]) + span,
                bins + 1,
            )
        else:
            edges = np.histogram_bin_edges(combined, bins=bins)
        centers = (edges[:-1] + edges[1:]) / 2
        width = float(np.mean(np.diff(edges))) if edges.size > 1 else 1.0
        for channel, values in populated:
            counts, _ = np.histogram(values, bins=edges)
            self.hist_bars[channel].setOpts(
                x=centers,
                height=counts,
                width=width * 0.92,
            )
        first_unit = analysis_data[populated[0][0]][3]
        self.hist_plot.setLabel("bottom", tr(self.language, "测量值"), units=first_unit)

    def _update_stability(
        self,
        analysis_data: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, str, int]],
    ) -> None:
        for channel in self.CHANNELS:
            self.allan_curves[channel].setData([], [])
            self.drift_points[channel].setData([], [])
            self.drift_fit_curves[channel].setData([], [])
        normalized = self.allan_normalized.isChecked()
        note_parts: list[str] = []
        unit = ""
        for channel, (
            x,
            y,
            temperature,
            channel_unit,
            _removed,
        ) in analysis_data.items():
            unit = channel_unit
            if y.size < 4:
                note_parts.append(
                    f"{self.panels[channel].instrument_model.short_name} "
                    f"{channel} · "
                    f"{tr(self.language, '需要至少 4 个有效样本')}"
                )
                continue
            period = estimate_sample_period(x)
            tau, deviation = allan_deviation(y, period, normalize=normalized)
            if normalized:
                deviation = deviation * 1e6
            valid_allan = (tau > 0) & (deviation > 0)
            self.allan_curves[channel].setData(tau[valid_allan], deviation[valid_allan])
            fitted, drift_per_hour, r_squared = linear_fit(x, y)
            self.drift_points[channel].setData(x, y)
            self.drift_fit_curves[channel].setData(x, fitted)
            temperature_mask = np.isfinite(temperature) & np.isfinite(y)
            temperature_text = tr(self.language, "温度数据不足")
            if (
                np.count_nonzero(temperature_mask) >= 3
                and np.ptp(temperature[temperature_mask]) > 0
            ):
                coefficient, _ = np.polyfit(
                    temperature[temperature_mask], y[temperature_mask], 1
                )
                mean = float(np.mean(y[temperature_mask]))
                coefficient_ppm = coefficient / abs(mean) * 1e6 if mean else np.nan
                temperature_text = (
                    f"temperature coefficient {coefficient_ppm:.5g} ppm/°C"
                    if self.language == "en"
                    else f"温度系数 {coefficient_ppm:.5g} ppm/°C"
                )
            note_parts.append(
                f"{self.panels[channel].instrument_model.short_name} "
                f"{channel} · "
                f"{'linear drift' if self.language == 'en' else '线性漂移'} "
                f"{format_number(drift_per_hour, channel_unit + '/h', 6)}"
                f" · R² {r_squared:.5f} · {temperature_text}"
            )
        self.allan_plot.setLabel(
            "left",
            "Allan deviation",
            units="ppm" if normalized else (unit or None),
        )
        self.drift_plot.setLabel("left", "测量值", units=unit or None)
        self.stability_note.setText(
            "\n".join(note_parts)
            if note_parts
            else (
                "All displayed channels require at least 4 valid samples."
                if self.language == "en"
                else "所有显示通道均需要至少 4 个有效样本"
            )
        )

    # ---------- Files and state ----------

    def _import_csv(self) -> None:
        channel = self.selected_channel
        runtime = self.channels[channel]
        if runtime.running:
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "正在采集"),
                (
                    f"Stop instrument channel {channel} before importing data."
                    if self.language == "en"
                    else f"请先停止仪表通道 {channel} 再导入数据。"
                ),
            )
            return
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            (
                f"Import to channel {channel}"
                if self.language == "en"
                else f"导入至通道 {channel}"
            ),
            "",
            (
                "CSV / TSV (*.csv *.tsv *.txt);;All files (*)"
                if self.language == "en"
                else "CSV / TSV (*.csv *.tsv *.txt);;所有文件 (*)"
            ),
        )
        if not path:
            return
        try:
            imported = read_measurement_csv(path)
            runtime.session.replace(
                imported.elapsed_s,
                imported.values,
                unit=imported.unit,
                source=Path(path).name,
            )
            runtime.session.channel = channel
            runtime.session.instrument_model = self.panels[
                channel
            ].instrument_model.display_name
            runtime.session.resource = f"CSV::{Path(path).name}"
            runtime.minimum = float(np.min(imported.values))
            runtime.maximum = float(np.max(imported.values))
            runtime.target_samples = None
            readout = self.readouts[channel]
            readout["source"].setText(Path(path).name)
            readout["value"].setText(f"{imported.values[-1]:.11g}")
            readout["unit"].setText(imported.unit)
            readout["extremes"].setText(
                f"MIN {format_number(runtime.minimum, imported.unit, 7)}"
                f"  ·  MAX {format_number(runtime.maximum, imported.unit, 7)}"
            )
            readout["time"].setText(
                f"Imported {imported.values.size:,} samples"
                if self.language == "en"
                else f"已导入 {imported.values.size:,}点"
            )
            self._refresh_views()
            self._set_channel_state(channel, "CSV 已载入")
            self._log(
                f"{channel} imported {Path(path).name}: "
                f"X={imported.x_column}, Y={imported.y_column}, "
                f"{imported.values.size} samples"
                if self.language == "en"
                else f"{channel} 导入 {Path(path).name}：X={imported.x_column}, "
                f"Y={imported.y_column}, {imported.values.size} 点"
            )
        except Exception as exc:
            logger.exception(
                "CSV import failed | channel=%s | file=%s",
                channel,
                Path(path).name,
            )
            QtWidgets.QMessageBox.critical(
                self, tr(self.language, "导入失败"), str(exc)
            )
            self._log(
                f"{channel} CSV import failed: {exc}"
                if self.language == "en"
                else f"{channel} CSV 导入失败：{exc}"
            )

    def _export_csv(self) -> None:
        channel = self.selected_channel
        session = self.channels[channel].session
        if not len(session):
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "没有数据"),
                (
                    f"Instrument channel {channel} has no samples to export."
                    if self.language == "en"
                    else f"仪表通道 {channel} 没有可导出的样本。"
                ),
            )
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            (
                f"Export channel {channel}"
                if self.language == "en"
                else f"导出通道 {channel}"
            ),
            f"instrument_{channel}_measurement.csv",
            tr(self.language, "CSV 文件 (*.csv)"),
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            write_session_csv(path, session)
            self._log(
                f"{channel} exported {len(session):,} samples to {Path(path).name}"
                if self.language == "en"
                else f"{channel} 已导出 {len(session):,} 点到 {Path(path).name}"
            )
        except Exception as exc:
            logger.exception(
                "CSV export failed | channel=%s | file=%s",
                channel,
                Path(path).name,
            )
            QtWidgets.QMessageBox.critical(
                self, tr(self.language, "导出失败"), str(exc)
            )

    def _export_both_csv(self) -> None:
        sessions = {key: self.channels[key].session for key in self.enabled_channels}
        if not any(len(session) for session in sessions.values()):
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "没有数据"),
                (
                    "No enabled channel has samples to export."
                    if self.language == "en"
                    else "所有启用通道均没有可导出的样本。"
                ),
            )
            return
        suffix = "_".join(sessions)
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export all enabled channels"
            if self.language == "en"
            else "导出所有启用通道",
            f"multi_instrument_{suffix}_measurement.csv",
            tr(self.language, "CSV 文件 (*.csv)"),
        )
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            write_multi_session_csv(path, sessions)
            counts = ", ".join(
                f"{key} {len(session):,}" for key, session in sessions.items()
            )
            self._log(
                f"Exported enabled channels: {counts} samples."
                if self.language == "en"
                else f"已导出启用通道：{counts} 点"
            )
        except Exception as exc:
            logger.exception(
                "Multi-channel CSV export failed | file=%s",
                Path(path).name,
            )
            QtWidgets.QMessageBox.critical(
                self, tr(self.language, "导出失败"), str(exc)
            )

    def _open_autosave_directory(self) -> None:
        self.autosave_root.mkdir(parents=True, exist_ok=True)
        opened = QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(self.autosave_root))
        )
        if not opened:
            QtWidgets.QMessageBox.information(
                self,
                ("Autosave directory" if self.language == "en" else "自动保存目录"),
                str(self.autosave_root),
            )

    def _report_recovery_files(self) -> None:
        recovery_files = list_recovery_files(self.autosave_root)
        if not recovery_files:
            return
        total_bytes = sum(item.size_bytes for item in recovery_files)
        self.autosave_status.setText(
            f"Durable autosave active · {len(recovery_files)} interrupted "
            f"capture(s) retained ({total_bytes / 1024:.1f} KiB)"
            if self.language == "en"
            else f"安全自动保存已开启 · 检测到 {len(recovery_files)} 个"
            f"中断采集文件（{total_bytes / 1024:.1f} KiB），数据已保留"
        )
        self._log(
            f"Recovered {len(recovery_files)} interrupted durable capture "
            f"file(s); open the autosave directory to inspect them."
            if self.language == "en"
            else f"检测到 {len(recovery_files)} 个异常中断的安全采集文件；"
            "可打开自动保存目录直接恢复数据"
        )

    def _diagnostic_channel_snapshot(self, channel: str) -> dict[str, object]:
        runtime = self.channels[channel]
        panel = self.panels[channel]
        identity = runtime.identity
        elapsed = (
            float(runtime.session.elapsed_s[-1]) if runtime.session.elapsed_s else 0.0
        )
        return {
            "enabled": channel in self.enabled_channels,
            "selected_for_group_start": channel in self.sync_channels,
            "state": runtime.state,
            "running": runtime.worker is not None,
            "source_type": panel.source_kind,
            "instrument_model": panel.instrument_model.display_name,
            "resource": panel.resource_name,
            "acquisition_mode": panel.acquisition_mode,
            "measurement_function": panel.current_function().command,
            "measurement_unit": panel.current_function().unit,
            "range": str(panel.range_combo.currentData()),
            "nplc": panel.nplc_combo.currentText(),
            "digits": panel.digits_combo.currentData(),
            "autozero": panel.autozero_combo.currentText(),
            "sample_interval_s": panel.interval_spin.value(),
            "target_samples": runtime.target_samples,
            "samples_acquired": len(runtime.session),
            "elapsed_s": elapsed,
            "last_error": runtime.error,
            "last_connection_diagnostic": (
                runtime.last_connection_diagnostic.to_dict()
                if runtime.last_connection_diagnostic is not None
                else None
            ),
            "durable_autosave_path": runtime.last_autosave_path,
            "identity": (
                {
                    "model": identity.model,
                    "resource": identity.resource,
                    "firmware": identity.firmware,
                    "options": identity.options,
                    "line_frequency_hz": identity.line_frequency_hz,
                }
                if identity is not None
                else None
            ),
        }

    def _export_diagnostic_report(self) -> None:
        timestamp = QtCore.QDateTime.currentDateTime().toString("yyyyMMdd_HHmmss")
        documents = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.DocumentsLocation
        )
        suggested = str(
            Path(documents or ".")
            / f"Multi_Instrument_Diagnostic_Report_{timestamp}.zip"
        )
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            tr(self.language, "导出诊断报告"),
            suggested,
            tr(self.language, "诊断报告 (*.zip)"),
        )
        if not path:
            return
        try:
            output = create_diagnostic_report(
                path,
                app_version=__version__,
                language=self.language,
                event_log=self.event_log.toPlainText(),
                channels={
                    key: self._diagnostic_channel_snapshot(key) for key in self.CHANNELS
                },
                application={
                    "active_sync_selection": list(self.sync_channels),
                    "analysis_channels": list(self.analysis_channels),
                    "multi_channel_analysis": (self.multi_analysis_check.isChecked()),
                    "channel_c_enabled": (self.channel_c_enabled.isChecked()),
                    "autosave_directory": str(self.autosave_root),
                    "interrupted_autosave_files": len(
                        list_recovery_files(self.autosave_root)
                    ),
                    "memory": (
                        {
                            "system_percent": (
                                self._last_memory_snapshot.system_percent
                            ),
                            "system_used_bytes": (
                                self._last_memory_snapshot.system_used_bytes
                            ),
                            "system_total_bytes": (
                                self._last_memory_snapshot.system_total_bytes
                            ),
                            "process_rss_bytes": (
                                self._last_memory_snapshot.process_rss_bytes
                            ),
                        }
                        if self._last_memory_snapshot is not None
                        else None
                    ),
                },
            )
            self._log(
                f"Diagnostic report exported: {output.name}"
                if self.language == "en"
                else f"诊断报告已导出：{output.name}"
            )
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "诊断报告已导出"),
                (
                    f"Saved to:\n{output}"
                    if self.language == "en"
                    else f"已保存至：\n{output}"
                ),
            )
        except Exception as exc:
            logger.exception("Diagnostic report export failed")
            QtWidgets.QMessageBox.critical(
                self,
                tr(self.language, "诊断报告导出失败"),
                str(exc),
            )

    def _clear_selected_session(self) -> None:
        channel = self.selected_channel
        runtime = self.channels[channel]
        if runtime.running:
            QtWidgets.QMessageBox.information(
                self,
                tr(self.language, "正在采集"),
                (
                    f"Stop instrument channel {channel} before clearing its data."
                    if self.language == "en"
                    else f"请先停止仪表通道 {channel} 再清空数据。"
                ),
            )
            return
        runtime.session.clear()
        runtime.identity = None
        runtime.last_temperature = np.nan
        runtime.target_samples = None
        runtime.minimum = np.inf
        runtime.maximum = -np.inf
        readout = self.readouts[channel]
        readout["value"].setText("—")
        readout["time"].setText(tr(self.language, "等待数据"))
        readout["temperature"].setText("TEMP —")
        readout["extremes"].setText("MIN —  ·  MAX —")
        self.trend_plot.clear_markers()
        self._set_channel_state(channel, "待机")
        self._refresh_views()
        self._log(
            f"{channel} session cleared."
            if self.language == "en"
            else f"{channel} 会话数据已清空"
        )

    def _update_identity_view(self) -> None:
        identity = self._selected_runtime().identity
        if identity is None:
            for label in (
                self.identity_model,
                self.identity_resource,
                self.identity_fw,
                self.identity_option,
                self.identity_line,
            ):
                label.setText("—")
            return
        self.identity_model.setText(identity.model)
        self.identity_resource.setText(identity.resource)
        self.identity_fw.setText(identity.firmware or "—")
        self.identity_option.setText(identity.options or "0")
        self.identity_line.setText(f"{identity.line_frequency_hz:g} Hz")

    def _set_channel_state(self, channel: str, state: str) -> None:
        runtime = self.channels[channel]
        runtime.state = state
        label = self.readouts[channel]["state"]
        label.setText(tr(self.language, state))
        bad = "错误" in state
        good = state in {
            "正在采集",
            "已就绪",
            "等待同步",
            "CSV 已载入",
            "已完成",
        }
        label.setObjectName(
            "statusBad" if bad else ("statusGood" if good else "statusIdle")
        )
        label.style().unpolish(label)
        label.style().polish(label)
        self._update_global_status()

    def _update_global_status(self) -> None:
        text = " · ".join(
            f"{key} {tr(self.language, self.channels[key].state)}"
            for key in self.CHANNELS
        )
        if any("错误" in self.channels[key].state for key in self.CHANNELS):
            kind = "bad"
        elif any(
            self.channels[key].state in {"正在采集", "已就绪", "等待同步"}
            for key in self.CHANNELS
        ):
            kind = "good"
        else:
            kind = "idle"
        self._set_global_status(text, kind)

    def _set_global_status(self, text: str, kind: str) -> None:
        self.status_label.setText(text)
        self.status_label.setObjectName(
            {"good": "statusGood", "bad": "statusBad"}.get(kind, "statusIdle")
        )
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _update_header_sources(self) -> None:
        values = []
        for key in self.CHANNELS:
            if key not in self.enabled_channels:
                values.append(f"{key} OFF")
                continue
            identity = self.channels[key].identity
            values.append(f"{key} {identity.resource if identity else '—'}")
        self.header_source.setText("  ·  ".join(values))

    def _log(self, text: str) -> None:
        timestamp = QtCore.QTime.currentTime().toString("HH:mm:ss")
        self.event_log.append(f"{timestamp}  {text}")
        logging.getLogger("hp3458a_studio.event").info(text)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self._shutdown_complete:
            event.accept()
            return
        if self._shutdown_in_progress:
            event.ignore()
            return
        self.settings.setValue("window_geometry", self.saveGeometry())
        self.settings.setValue("main_splitter", self.main_splitter.saveState())
        self.settings.setValue("language", self.language)
        self.settings.setValue("channel_c_enabled", self.channel_c_enabled.isChecked())
        for key, panel in self.panels.items():
            self.settings.setValue(
                f"channel_{key}_instrument_model",
                panel.instrument_model.value,
            )
            self.settings.setValue(
                f"channel_{key}_resource",
                panel.resource_name,
            )
        self.settings.sync()
        running = [
            runtime
            for runtime in self.channels.values()
            if runtime.worker is not None and runtime.worker.isRunning()
        ]
        background_running = bool(
            self._visa_scan_worker is not None and self._visa_scan_worker.isRunning()
        ) or any(
            worker.isRunning() for worker in self._connection_check_workers.values()
        )
        if not running and not background_running:
            self._shutdown_complete = True
            logger.info("Main window closed")
            event.accept()
            return

        event.ignore()
        self._shutdown_in_progress = True
        self._shutdown_deadline = time.monotonic() + 20.0
        self.setEnabled(False)
        self._set_global_status(
            "Stopping instruments before exit…"
            if self.language == "en"
            else "正在停止仪表并安全退出…",
            "idle",
        )
        logger.info(
            "Application shutdown requested | active_channels=%s | "
            "background_checks=%s",
            ",".join(runtime.key for runtime in running),
            background_running,
        )
        if self._group_gate is not None:
            self._group_gate.set()
        for runtime in running:
            runtime.worker.request_stop()
        self._shutdown_timer.start()
        self._poll_shutdown()

    def _poll_shutdown(self) -> None:
        active = [
            runtime.key
            for runtime in self.channels.values()
            if runtime.worker is not None and runtime.worker.isRunning()
        ]
        if self._visa_scan_worker is not None and self._visa_scan_worker.isRunning():
            active.append("VISA_SCAN")
        active.extend(
            f"CHECK_{channel}"
            for channel, worker in self._connection_check_workers.items()
            if worker.isRunning()
        )
        if not active:
            self._shutdown_timer.stop()
            self._shutdown_complete = True
            logger.info("All acquisition workers stopped; closing application")
            self.close()
            return
        if time.monotonic() < self._shutdown_deadline:
            return

        # A vendor VISA call can become uninterruptible inside a native driver.
        # A process that keeps running after its window closes prevents a clean
        # relaunch and may retain GPIB sessions. After a generous cancellation
        # window, record the condition and let Windows release those handles by
        # ending the process.
        self._shutdown_timer.stop()
        logger.critical(
            "Forced process exit after shutdown timeout | active_channels=%s",
            ",".join(active),
        )
        for channel in active:
            if channel in self.CHANNELS:
                self._finalize_autosave(
                    channel,
                    "forced_shutdown",
                    ("Instrument worker did not stop before the shutdown deadline."),
                )
        logging.shutdown()
        os._exit(2)
