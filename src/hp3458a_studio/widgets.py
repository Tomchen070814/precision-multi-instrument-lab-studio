from __future__ import annotations

from datetime import datetime

import numpy as np
import pyqtgraph as pg
from PySide6 import QtCore, QtGui, QtWidgets

from .styles import COLORS
from .trend_logic import assign_unit_axes


class _TrendDataItem(pg.PlotDataItem):
    def viewRangeChanged(self, vb=None, ranges=None, changed=None):
        if changed is None or changed[1]:
            # Pyqtgraph's Y-limit hysteresis can otherwise reuse an unclipped
            # dataset with stale clipping bounds after auto-fit then deep zoom.
            self._datasetDisplay = None
        super().viewRangeChanged(vb, ranges, changed)

    def dataBounds(self, ax, frac=1.0, orthoRange=None):
        # Clipping/downsampling changes the display dataset. Auto-ranging must
        # use the original values, otherwise X zoom unexpectedly changes Y and
        # large off-screen values expand the Y scale over several paint cycles.
        x, y = self.getOriginalDataset()
        if x is None or y is None:
            return None, None
        values, other = (x, y) if ax == 0 else (y, x)
        mask = np.isfinite(values)
        if orthoRange is not None:
            mask &= (other >= orthoRange[0]) & (other <= orthoRange[1])
        finite = values[mask]
        if not finite.size:
            return None, None
        if frac < 1.0:
            lower, upper = np.percentile(finite, [50 * (1 - frac), 50 * (1 + frac)])
        else:
            lower, upper = np.min(finite), np.max(finite)
        return float(lower), float(upper)


class _TrendViewBox(pg.ViewBox):
    rectangle_selected = QtCore.Signal(float, float)

    def shape(self) -> QtGui.QPainterPath:
        # ViewBox's default bounding shape includes half a border pixel.
        # Clip curves and annotations to the actual data rectangle instead.
        path = QtGui.QPainterPath()
        path.addRect(self.rect())
        return path

    def showAxRect(self, ax, **kwargs) -> None:
        previous_min, previous_max = self.viewRange()[1]
        selected = ax.normalized()
        span = previous_max - previous_min
        super().showAxRect(selected, **kwargs)
        if span > 0:
            self.rectangle_selected.emit(
                (selected.top() - previous_min) / span,
                (selected.bottom() - previous_min) / span,
            )


class _UnitViewBox(_TrendViewBox):
    """Receive Y-axis gestures without intercepting the shared plot surface."""

    def wheelEvent(self, event, axis=None) -> None:
        if axis != self.YAxis:
            event.ignore()
            return
        super().wheelEvent(event, axis=axis)

    def mouseDragEvent(self, event, axis=None) -> None:
        if axis != self.YAxis:
            event.ignore()
            return
        super().mouseDragEvent(event, axis=axis)

    def mouseClickEvent(self, event) -> None:
        event.ignore()


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
            viewBox=_TrendViewBox(),
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
        self._viewboxes = [plot_item.vb, _UnitViewBox(), _UnitViewBox()]
        for view in self._viewboxes:
            # One shared time range is fitted to all visible channels below;
            # individual Y views must not replace it with their own X bounds.
            view.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
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
            view.setMouseEnabled(x=False, y=True)
        self._viewboxes[0].sigResized.connect(self._update_view_geometry)
        self._viewboxes[0].sigXRangeChanged.connect(self._x_range_changed)
        self._viewboxes[0].sigRangeChangedManually.connect(self._range_changed_manually)
        self._viewboxes[0].rectangle_selected.connect(self._rectangle_selected)
        self._update_view_geometry()

        for axis in (*self._axes, plot_item.getAxis("bottom")):
            axis.setPen(pg.mkPen(COLORS["border"]))
            axis.setTextPen(pg.mkPen(COLORS["muted"]))

        self.legend = plot_item.addLegend(offset=(10, 10))
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._legend_labels: dict[str, str] = {}
        self._legend_hidden: set[str] = set()
        self._channel_data: dict[str, tuple[np.ndarray, np.ndarray, str, str, str]] = {}
        self._channel_slots: dict[str, int] = {}
        self._unit_slots: dict[str, int] = {}
        self._routing_signature: tuple[tuple[str, str, int], ...] = ()
        for channel, color in zip(
            self.CHANNELS,
            (COLORS["cyan"], COLORS["purple"], COLORS["green"]),
        ):
            curve = _TrendDataItem(
                pen=pg.mkPen(color, width=1.6),
                name=channel,
                autoDownsample=True,
                clipToView=True,
                downsampleMethod="peak",
                dynamicRangeLimit=1e3,
            )
            self._viewboxes[0].addItem(curve)
            self._curves[channel] = curve
            self._add_legend_item(channel, channel)
            self._legend_labels[channel] = channel

        # Compatibility aliases retained for earlier UI automation.
        self.curve = self._curves["A"]
        self.secondary_curve = self._curves["B"]
        self.tertiary_curve = self._curves["C"]

        self.smooth_curve = _TrendDataItem(
            pen=pg.mkPen(COLORS["yellow"], width=1.3),
            name="Rolling average",
            autoDownsample=True,
            clipToView=True,
            downsampleMethod="peak",
            dynamicRangeLimit=1e3,
        )
        self._viewboxes[0].addItem(self.smooth_curve)
        self.smooth_curve.setVisible(False)
        self._smooth_channel = "A"
        self._smooth_enabled = False

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
        geometry = self._viewboxes[0].mapRectToScene(self._viewboxes[0].rect())
        for view in self._viewboxes[1:]:
            view.setGeometry(geometry)
            view.linkedViewChanged(
                self._viewboxes[0],
                view.XAxis,
            )

    def _assign_axes(self) -> None:
        previous_unit_slots = dict(self._unit_slots)
        previous_ranges = {
            unit: (
                self._viewboxes[slot].viewRange()[1][:],
                self._viewboxes[slot].autoRangeEnabled()[1],
            )
            for unit, slot in previous_unit_slots.items()
        }
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
            if (
                channel in self._channel_data
                and self._channel_data[channel][1].size
                and channel not in self._legend_hidden
            )
        }
        channel_slots, self._unit_slots = assign_unit_axes(channel_units)
        routing_signature = tuple(
            (channel, channel_units[channel], channel_slots[channel])
            for channel in self.CHANNELS
            if channel in channel_units
        )
        if routing_signature != self._routing_signature:
            self.clear_markers()
            self.v_line.setVisible(False)
            self.h_line.setVisible(False)
            self.hover_label.setVisible(False)
            self._routing_signature = routing_signature
        visible_units = list(self._unit_slots)
        for index, axis in enumerate(self._axes):
            axis.setVisible(index < len(visible_units))
            if index > 0:
                self._viewboxes[index].setVisible(index < len(visible_units))
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
                    and channel not in self._legend_hidden
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
                # Qt emits parent-change callbacks between removal and
                # insertion, when the curve temporarily has no ViewBox.
                curve.setClipToView(False)
                self._viewboxes[old_slot].removeItem(curve)
            if curve not in self._viewboxes[slot].addedItems:
                self._viewboxes[slot].addItem(curve)
                curve.setClipToView(True)
            self._channel_slots[channel] = slot
        self._move_smooth_curve(self._smooth_channel)
        for unit, slot in self._unit_slots.items():
            if previous_unit_slots.get(unit) == slot:
                continue
            view = self._viewboxes[slot]
            previous = previous_ranges.get(unit)
            if previous is None:
                view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            else:
                (y_min, y_max), automatic = previous
                view.setYRange(y_min, y_max, padding=0)
                view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=automatic)
        self._update_view_geometry()
        self._fit_shared_x()

    def _add_legend_item(self, channel: str, label: str) -> None:
        curve = self._curves[channel]
        self.legend.addItem(curve, label)
        for sample, _label in self.legend.items:
            if sample.item is curve:
                sample.sigClicked.connect(
                    lambda item, key=channel: self._legend_visibility_changed(key, item)
                )
                break

    def _legend_visibility_changed(self, channel: str, curve: pg.PlotDataItem) -> None:
        data = self._channel_data.get(channel)
        if data is None or not data[1].size:
            curve.setVisible(False)
            return
        if curve.isVisible():
            self._legend_hidden.discard(channel)
        else:
            self._legend_hidden.add(channel)
        self._assign_axes()

    def restore_channel_visibility(self, channel: str) -> None:
        """Show a channel explicitly selected or started by the user."""
        curve = self._curves[channel]
        self._legend_hidden.discard(channel)
        data = self._channel_data.get(channel)
        curve.setVisible(data is not None and bool(data[1].size))
        self._assign_axes()

    def _fit_shared_x(self) -> None:
        if self._manual_x_range:
            return
        bounds = []
        for channel, (x, y, _unit, _color, _label) in self._channel_data.items():
            if not y.size or channel in self._legend_hidden:
                continue
            finite_x = x[np.isfinite(x)]
            if finite_x.size:
                bounds.append((float(np.min(finite_x)), float(np.max(finite_x))))
        if not bounds:
            return
        lower = min(bound[0] for bound in bounds)
        upper = max(bound[1] for bound in bounds)
        if lower == upper:
            lower -= 0.5
            upper += 0.5
        self._viewboxes[0].setXRange(lower, upper, padding=0.02)

    def _move_smooth_curve(self, channel: str) -> None:
        data = self._channel_data.get(channel)
        self.smooth_curve.setVisible(
            self._smooth_enabled
            and data is not None
            and bool(data[1].size)
            and channel not in self._legend_hidden
        )
        slot = self._channel_slots.get(channel, 0)
        if self.smooth_curve in self._viewboxes[slot].addedItems:
            return
        self.smooth_curve.setClipToView(False)
        for view in self._viewboxes:
            if self.smooth_curve in view.addedItems:
                view.removeItem(self.smooth_curve)
        self._viewboxes[slot].addItem(self.smooth_curve)
        self.smooth_curve.setClipToView(True)

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
        curve.setData(
            x_array,
            y_array,
            symbol="o" if y_array.size == 1 else None,
            symbolSize=7,
            symbolPen=None,
            symbolBrush=pg.mkBrush(color),
        )
        curve.setVisible(bool(y_array.size) and channel not in self._legend_hidden)
        old_label = self._legend_labels.get(channel, channel)
        if old_label != label:
            self.legend.removeItem(old_label)
            self._add_legend_item(channel, label)
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
            self._smooth_enabled = False
            self.smooth_curve.setVisible(False)
            return
        x_array = np.asarray(x, dtype=float)
        y_array = np.asarray(y, dtype=float)
        if x_array.size != y_array.size or not y_array.size:
            self._smooth_enabled = False
            self.smooth_curve.setVisible(False)
            return
        self._smooth_enabled = True
        self._move_smooth_curve(channel)
        self.smooth_curve.setData(x_array, y_array)

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
            view.enableAutoRange(x=False, y=True)
            view.updateAutoRange()
        self._fit_shared_x()

    def zoom_x(self, factor: float) -> None:
        """Scale only the shared wall-clock axis around its current center."""
        if not np.isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be finite and positive")
        view = self._viewboxes[0]
        self._manual_x_range = True
        view.enableAutoRange(axis=pg.ViewBox.XAxis, enable=False)
        view.scaleBy(x=float(factor))

    def zoom_y(self, factor: float, unit: str = "") -> None:
        """Scale all Y axes or one physical-unit axis independently."""
        if not np.isfinite(factor) or factor <= 0:
            raise ValueError("Zoom factor must be finite and positive")
        if unit:
            slots = (self._unit_slots[unit],) if unit in self._unit_slots else ()
        else:
            slots = tuple(range(len(self._unit_slots)))
        for slot in slots:
            view = self._viewboxes[slot]
            view.enableAutoRange(axis=pg.ViewBox.YAxis, enable=False)
            view.scaleBy(y=float(factor))

    def _range_changed_manually(self, changed) -> None:
        if not changed[0]:
            return
        self._manual_x_range = True
        self._emit_manual_x_window()

    def _emit_manual_x_window(self) -> None:
        if not self._manual_x_range:
            return
        x_min, x_max = self._viewboxes[0].viewRange()[0]
        self.x_window_changed.emit(float(x_min), float(x_max))

    def _x_range_changed(self, *_args) -> None:
        self._emit_manual_x_window()

    def _rectangle_selected(self, lower_fraction: float, upper_fraction: float) -> None:
        for slot in range(1, len(self._unit_slots)):
            view = self._viewboxes[slot]
            y_min, y_max = view.viewRange()[1]
            span = y_max - y_min
            view.setYRange(
                y_min + lower_fraction * span,
                y_min + upper_fraction * span,
                padding=0,
            )

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
            if (
                not self._viewboxes[0]
                .mapRectToScene(self._viewboxes[0].rect())
                .contains(point)
            ):
                continue
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
        nearest = None
        if (
            self._viewboxes[0]
            .mapRectToScene(self._viewboxes[0].rect())
            .contains(position)
        ):
            nearest = self._nearest(position)
        if nearest is None:
            self.v_line.setVisible(False)
            self.h_line.setVisible(False)
            self.hover_label.setVisible(False)
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
        if (
            not self._viewboxes[0]
            .mapRectToScene(self._viewboxes[0].rect())
            .contains(position)
        ):
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
        view.addItem(point, ignoreBounds=True)
        view.addItem(label, ignoreBounds=True)
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
