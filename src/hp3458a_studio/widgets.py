from __future__ import annotations

from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtWidgets

from .styles import COLORS
from .trend_logic import assign_unit_axes


class Card(QtWidgets.QFrame):
    def __init__(self, parent=None, object_name: str = "card"):
        super().__init__(parent)
        self.setObjectName(object_name)


class MetricCard(Card):
    def __init__(
        self,
        title: str,
        accent: str = COLORS["cyan"],
        parent=None,
    ):
        super().__init__(parent, "metricCard")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(3)
        self.title = QtWidgets.QLabel(title)
        self.title.setObjectName("metricTitle")
        self.value = QtWidgets.QLabel("—")
        self.value.setObjectName("metricValue")
        self.value.setStyleSheet(f"color: {accent};")
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set_value(self, value: str) -> None:
        self.value.setText(value)


class InteractivePlot(pg.PlotWidget):
    """Wall-clock, multi-axis trend plot with channel-aware marks and box zoom."""

    marker_added = QtCore.Signal(float, float)
    channel_marker_added = QtCore.Signal(str, float, float, object)
    x_window_changed = QtCore.Signal(float, float)
    CHANNELS = ("A", "B", "C")

    def __init__(self, parent=None, title: str = ""):
        date_axis = pg.DateAxisItem(orientation="bottom")
        super().__init__(
            parent=parent,
            axisItems={"bottom": date_axis},
        )
        self.language = "zh"
        self.setBackground(COLORS["card"])
        self.showGrid(x=True, y=True, alpha=0.22)
        self.setMenuEnabled(True)
        self.getPlotItem().setClipToView(True)
        self.getPlotItem().setDownsampling(auto=True, mode="peak")
        if title:
            self.setTitle(title, color=COLORS["muted"], size="10pt")

        plot_item = self.getPlotItem()
        self._manual_x_range = False
        self._viewboxes = [plot_item.vb, pg.ViewBox(), pg.ViewBox()]
        self._axes = [
            plot_item.getAxis("left"),
            plot_item.getAxis("right"),
            pg.AxisItem("right"),
        ]
        plot_item.showAxis("right")
        plot_item.scene().addItem(self._viewboxes[1])
        plot_item.scene().addItem(self._viewboxes[2])
        plot_item.layout.addItem(self._axes[2], 2, 3)
        self._axes[1].linkToView(self._viewboxes[1])
        self._axes[2].linkToView(self._viewboxes[2])
        for view in self._viewboxes[1:]:
            view.setXLink(self._viewboxes[0])
            view.setMouseEnabled(x=False, y=False)
        self._viewboxes[0].sigResized.connect(self._update_view_geometry)
        self._viewboxes[0].sigXRangeChanged.connect(self._x_range_changed)
        self._viewboxes[0].sigRangeChangedManually.connect(self._range_changed_manually)
        self._update_view_geometry()

        for axis in (*self._axes, plot_item.getAxis("bottom")):
            axis.setPen(pg.mkPen(COLORS["border"]))
            axis.setTextPen(pg.mkPen(COLORS["muted"]))

        self.legend = plot_item.addLegend(offset=(10, 10))
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._legend_labels: dict[str, str] = {}
        self._channel_data: dict[str, tuple[np.ndarray, np.ndarray, str, str, str]] = {}
        self._channel_slots: dict[str, int] = {}
        self._unit_slots: dict[str, int] = {}
        for channel, color in zip(
            self.CHANNELS,
            (COLORS["cyan"], COLORS["purple"], COLORS["green"]),
        ):
            curve = pg.PlotDataItem(
                pen=pg.mkPen(color, width=1.6),
                name=channel,
                autoDownsample=True,
            )
            self._viewboxes[0].addItem(curve)
            self.legend.addItem(curve, channel)
            self._curves[channel] = curve
            self._legend_labels[channel] = channel

        # Compatibility aliases retained for earlier UI automation.
        self.curve = self._curves["A"]
        self.secondary_curve = self._curves["B"]
        self.tertiary_curve = self._curves["C"]

        self.smooth_curve = pg.PlotDataItem(
            pen=pg.mkPen(COLORS["yellow"], width=1.3),
            name="Rolling average",
            autoDownsample=True,
        )
        self._viewboxes[0].addItem(self.smooth_curve)
        self.smooth_curve.setVisible(False)
        self._smooth_channel = "A"

        self.v_line = pg.InfiniteLine(
            angle=90,
            movable=False,
            pen=pg.mkPen("#54718A", width=1),
        )
        self.h_line = pg.InfiniteLine(
            angle=0,
            movable=False,
            pen=pg.mkPen("#54718A", width=1),
        )
        self.v_line.setVisible(False)
        self.h_line.setVisible(False)
        self._viewboxes[0].addItem(self.v_line, ignoreBounds=True)
        self._viewboxes[0].addItem(self.h_line, ignoreBounds=True)
        self._hover_slot = 0
        self.hover_label = pg.TextItem(
            "",
            color=COLORS["text"],
            fill=pg.mkBrush("#171E28EE"),
            border=pg.mkPen(COLORS["border_active"]),
            anchor=(0, 1),
        )
        self.hover_label.setVisible(False)
        self._viewboxes[0].addItem(self.hover_label, ignoreBounds=True)

        self._markers: list[tuple[pg.ViewBox, pg.ScatterPlotItem, pg.TextItem]] = []
        self._box_zoom_enabled = False
        self._y_label = "测量值"
        self._legacy_unit = "V"
        self._mouse_proxy = pg.SignalProxy(
            self.scene().sigMouseMoved,
            rateLimit=40,
            slot=self._mouse_moved,
        )
        self.scene().sigMouseClicked.connect(self._mouse_clicked)
        self.set_box_zoom_enabled(False)

    @property
    def axis_assignments(self) -> dict[str, int]:
        """Expose deterministic channel-to-axis mapping for tests/diagnostics."""
        return dict(self._channel_slots)

    @property
    def available_units(self) -> tuple[str, ...]:
        return tuple(self._unit_slots)

    def _update_view_geometry(self) -> None:
        geometry = self._viewboxes[0].sceneBoundingRect()
        for view in self._viewboxes[1:]:
            view.setGeometry(geometry)
            view.linkedViewChanged(
                self._viewboxes[0],
                view.XAxis,
            )

    def _assign_axes(self) -> None:
        visible_units: list[str] = []
        for channel in self.CHANNELS:
            data = self._channel_data.get(channel)
            if data is None or not data[1].size:
                continue
            unit = data[2]
            if unit not in visible_units:
                visible_units.append(unit)
        channel_units = {
            channel: self._channel_data[channel][2]
            for channel in self.CHANNELS
            if (channel in self._channel_data and self._channel_data[channel][1].size)
        }
        channel_slots, self._unit_slots = assign_unit_axes(channel_units)
        visible_units = list(self._unit_slots)
        for index, axis in enumerate(self._axes):
            axis.setVisible(index < len(visible_units))
            if index >= len(visible_units):
                continue
            unit = visible_units[index]
            channels = [
                channel
                for channel in self.CHANNELS
                if (
                    channel in self._channel_data
                    and self._channel_data[channel][2] == unit
                    and self._channel_data[channel][1].size
                )
            ]
            color = self._channel_data[channels[0]][3]
            axis.setPen(pg.mkPen(color))
            axis.setTextPen(pg.mkPen(color))
            axis.setLabel(
                f"{self._y_label} · {'+'.join(channels)}",
                units=unit or None,
                color=color,
            )

        self._channel_slots.clear()
        for channel, curve in self._curves.items():
            slot = channel_slots.get(channel, 0)
            old_slot = next(
                (
                    index
                    for index, view in enumerate(self._viewboxes)
                    if curve in view.addedItems
                ),
                None,
            )
            if old_slot is not None and old_slot != slot:
                self._viewboxes[old_slot].removeItem(curve)
            if curve not in self._viewboxes[slot].addedItems:
                self._viewboxes[slot].addItem(curve)
            self._channel_slots[channel] = slot
        self._move_smooth_curve(self._smooth_channel)
        self._update_view_geometry()

    def _move_smooth_curve(self, channel: str) -> None:
        slot = self._channel_slots.get(channel, 0)
        for view in self._viewboxes:
            if self.smooth_curve in view.addedItems:
                view.removeItem(self.smooth_curve)
        self._viewboxes[slot].addItem(self.smooth_curve)

    def set_labels(
        self,
        x_label: str,
        y_label: str,
        unit: str = "",
    ) -> None:
        self.setLabel("bottom", x_label)
        self._y_label = y_label
        self._legacy_unit = unit
        self._assign_axes()

    def set_channel_data(
        self,
        channel: str,
        x: np.ndarray,
        y: np.ndarray,
        *,
        unit: str,
        color: str,
        label: str,
        visible: bool = True,
        refresh_axes: bool = True,
    ) -> None:
        if channel not in self._curves:
            raise KeyError(f"Unknown trend channel: {channel}")
        x_array = np.asarray(x, dtype=float)
        y_array = np.asarray(y, dtype=float)
        if x_array.size != y_array.size:
            raise ValueError("Trend X/Y arrays must have equal lengths")
        if not visible:
            x_array = np.asarray([], dtype=float)
            y_array = np.asarray([], dtype=float)
        self._channel_data[channel] = (
            x_array,
            y_array,
            unit,
            color,
            label,
        )
        curve = self._curves[channel]
        curve.setPen(pg.mkPen(color, width=1.6))
        curve.setData(x_array, y_array)
        curve.setVisible(bool(y_array.size))
        old_label = self._legend_labels.get(channel, channel)
        if old_label != label:
            self.legend.removeItem(old_label)
            self.legend.addItem(curve, label)
            self._legend_labels[channel] = label
        if refresh_axes:
            self._assign_axes()

    def finish_channel_update(self) -> None:
        """Apply axis routing once after a batch of channel data updates."""
        self._assign_axes()

    def set_smooth_data(
        self,
        channel: str,
        x: np.ndarray,
        y: np.ndarray | None,
    ) -> None:
        self._smooth_channel = channel
        if y is None:
            self.smooth_curve.setVisible(False)
            return
        x_array = np.asarray(x, dtype=float)
        y_array = np.asarray(y, dtype=float)
        if x_array.size != y_array.size or not y_array.size:
            self.smooth_curve.setVisible(False)
            return
        self._move_smooth_curve(channel)
        self.smooth_curve.setData(x_array, y_array)
        self.smooth_curve.setVisible(True)

    # Legacy single/secondary/tertiary methods used by older integrations.
    def set_data(
        self,
        x: np.ndarray,
        y: np.ndarray,
        smooth: np.ndarray | None = None,
    ) -> None:
        self.set_channel_data(
            "A",
            x,
            y,
            unit=self._legacy_unit,
            color=COLORS["cyan"],
            label="A",
        )
        self.set_smooth_data("A", x, smooth)

    def set_secondary_data(
        self,
        x: np.ndarray,
        y: np.ndarray,
        visible: bool = True,
    ) -> None:
        self.set_channel_data(
            "B",
            x,
            y,
            unit=self._legacy_unit,
            color=COLORS["purple"],
            label="B",
            visible=visible,
        )

    def set_tertiary_data(
        self,
        x: np.ndarray,
        y: np.ndarray,
        visible: bool = True,
    ) -> None:
        self.set_channel_data(
            "C",
            x,
            y,
            unit=self._legacy_unit,
            color=COLORS["green"],
            label="C",
            visible=visible,
        )

    def set_language(self, language: str) -> None:
        self.language = "en" if language == "en" else "zh"

    def set_box_zoom_enabled(self, enabled: bool) -> None:
        self._box_zoom_enabled = bool(enabled)
        mode = pg.ViewBox.RectMode if self._box_zoom_enabled else pg.ViewBox.PanMode
        self._viewboxes[0].setMouseMode(mode)

    def reset_view(self) -> None:
        self._manual_x_range = False
        for view in self._viewboxes:
            view.enableAutoRange(x=True, y=True)
            view.autoRange()

    def zoom_x(self, factor: float) -> None:
        """Scale only the shared wall-clock axis around its current center."""
        if factor <= 0:
            raise ValueError("Zoom factor must be positive")
        view = self._viewboxes[0]
        self._manual_x_range = True
        view.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        view.scaleBy(x=float(factor))

    def zoom_y(self, factor: float, unit: str = "") -> None:
        """Scale all Y axes or one physical-unit axis independently."""
        if factor <= 0:
            raise ValueError("Zoom factor must be positive")
        if unit:
            slots = (self._unit_slots[unit],) if unit in self._unit_slots else ()
        else:
            slots = tuple(range(len(self._unit_slots)))
        for slot in slots:
            view = self._viewboxes[slot]
            view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
            view.scaleBy(y=float(factor))

    def _range_changed_manually(self, *_args) -> None:
        self._manual_x_range = True
        self._emit_manual_x_window()

    def _emit_manual_x_window(self) -> None:
        if not self._manual_x_range:
            return
        x_min, x_max = self._viewboxes[0].viewRange()[0]
        self.x_window_changed.emit(float(x_min), float(x_max))

    def _x_range_changed(self, *_args) -> None:
        self._emit_manual_x_window()
        if not self._box_zoom_enabled:
            return
        x_min, x_max = self._viewboxes[0].viewRange()[0]
        for slot, view in enumerate(self._viewboxes):
            values: list[np.ndarray] = []
            for channel, channel_slot in self._channel_slots.items():
                if channel_slot != slot or channel not in self._channel_data:
                    continue
                x, y, _unit, _color, _label = self._channel_data[channel]
                mask = np.isfinite(x) & np.isfinite(y) & (x >= x_min) & (x <= x_max)
                if np.any(mask):
                    values.append(y[mask])
            if not values:
                continue
            combined = np.concatenate(values)
            minimum = float(np.min(combined))
            maximum = float(np.max(combined))
            padding = max((maximum - minimum) * 0.08, abs(maximum) * 1e-12, 1e-15)
            view.setYRange(minimum - padding, maximum + padding, padding=0)

    def clear_markers(self) -> None:
        for view, point, label in self._markers:
            view.removeItem(point)
            view.removeItem(label)
        self._markers.clear()

    def _nearest(
        self,
        scene_position: QtCore.QPointF,
    ) -> tuple[str, float, float] | None:
        nearest: tuple[str, float, float] | None = None
        nearest_distance = np.inf
        for channel, data in self._channel_data.items():
            x, y, _unit, _color, _label = data
            if not x.size or not self._curves[channel].isVisible():
                continue
            slot = self._channel_slots.get(channel, 0)
            view = self._viewboxes[slot]
            mapped = view.mapSceneToView(scene_position)
            index = int(np.searchsorted(x, mapped.x()))
            index = int(np.clip(index, 0, x.size - 1))
            if index > 0 and abs(x[index - 1] - mapped.x()) < abs(
                x[index] - mapped.x()
            ):
                index -= 1
            if not np.isfinite(y[index]):
                continue
            point = view.mapViewToScene(
                QtCore.QPointF(float(x[index]), float(y[index]))
            )
            distance = (point.x() - scene_position.x()) ** 2 + (
                point.y() - scene_position.y()
            ) ** 2
            if distance < nearest_distance:
                nearest_distance = distance
                nearest = channel, float(x[index]), float(y[index])
        return nearest

    def _move_hover_items(self, slot: int) -> None:
        if slot == self._hover_slot:
            return
        previous = self._viewboxes[self._hover_slot]
        previous.removeItem(self.h_line)
        previous.removeItem(self.hover_label)
        target = self._viewboxes[slot]
        target.addItem(self.h_line, ignoreBounds=True)
        target.addItem(self.hover_label, ignoreBounds=True)
        self._hover_slot = slot

    def _mouse_moved(self, event) -> None:
        position = event[0]
        if not self.sceneBoundingRect().contains(position):
            self.v_line.setVisible(False)
            self.h_line.setVisible(False)
            self.hover_label.setVisible(False)
            return
        nearest = self._nearest(position)
        if nearest is None:
            return
        channel, x_value, y_value = nearest
        slot = self._channel_slots.get(channel, 0)
        self._move_hover_items(slot)
        _x, _y, unit, _color, label = self._channel_data[channel]
        timestamp = datetime.fromtimestamp(x_value).astimezone()
        time_text = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        self.v_line.setPos(x_value)
        self.h_line.setPos(y_value)
        self.v_line.setVisible(True)
        self.h_line.setVisible(True)
        self.hover_label.setText(
            f"{label}\nTime  {time_text}\nValue  {y_value:.10g} {unit}"
            if self.language == "en"
            else f"{label}\n时间  {time_text}\n值  {y_value:.10g} {unit}"
        )
        self.hover_label.setPos(x_value, y_value)
        self.hover_label.setVisible(True)

    def _mouse_clicked(self, event) -> None:
        if event.button() != QtCore.Qt.MouseButton.LeftButton:
            return
        position = event.scenePos()
        if not self.sceneBoundingRect().contains(position):
            return
        nearest = self._nearest(position)
        if nearest is None:
            return
        channel, x_value, y_value = nearest
        slot = self._channel_slots.get(channel, 0)
        view = self._viewboxes[slot]
        _x, _y, unit, color, label_text = self._channel_data[channel]
        timestamp = datetime.fromtimestamp(x_value).astimezone()
        time_text = timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        point = pg.ScatterPlotItem(
            [x_value],
            [y_value],
            symbol="o",
            size=9,
            brush=pg.mkBrush(color),
            pen=pg.mkPen("#FFF1B8", width=1),
        )
        label = pg.TextItem(
            f"{label_text} · {y_value:.10g} {unit}\n{time_text}",
            color=color,
            fill=pg.mkBrush("#1B1A16EE"),
            border=pg.mkPen(color),
            anchor=(0, 1),
        )
        label.setPos(x_value, y_value)
        view.addItem(point)
        view.addItem(label)
        self._markers.append((view, point, label))
        if len(self._markers) > 36:
            old_view, old_point, old_label = self._markers.pop(0)
            old_view.removeItem(old_point)
            old_view.removeItem(old_label)
        self.marker_added.emit(x_value, y_value)
        self.channel_marker_added.emit(
            channel,
            x_value,
            y_value,
            timestamp,
        )


def configure_plot(
    plot: pg.PlotWidget,
    x_label: str,
    y_label: str,
    x_unit: str = "",
    y_unit: str = "",
    log_x: bool = False,
    log_y: bool = False,
) -> None:
    plot.setBackground(COLORS["card"])
    plot.showGrid(x=True, y=True, alpha=0.22)
    plot.setLabel("bottom", x_label, units=x_unit or None)
    plot.setLabel("left", y_label, units=y_unit or None)
    plot.setLogMode(x=log_x, y=log_y)
    for axis_name in ("left", "bottom"):
        axis = plot.getAxis(axis_name)
        axis.setPen(pg.mkPen(COLORS["border"]))
        axis.setTextPen(pg.mkPen(COLORS["muted"]))
