import os

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from hp3458a_studio.widgets import InteractivePlot


@pytest.fixture(scope="module")
def app():
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield application


@pytest.fixture
def plot(app):
    widget = InteractivePlot()
    widget.resize(1000, 500)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def _populate_mixed(plot, app):
    x = 1_700_000_000.0 + np.arange(1000)
    for channel, unit, magnitude in (
        ("A", "V", 1e6),
        ("B", "Ω", 1e12),
        ("C", "A", 1e-9),
    ):
        plot.set_channel_data(
            channel,
            x,
            magnitude * np.sin(np.arange(x.size) * 0.03),
            unit=unit,
            color="#ff007f",
            label=channel,
        )
    plot.reset_view()
    app.processEvents()
    return x


def test_large_mixed_unit_axes_zoom_independently_and_survive_data_updates(plot, app):
    x = _populate_mixed(plot, app)
    plot._viewboxes[0].setXRange(x[200], x[400], padding=0)
    for view, magnitude in zip(plot._viewboxes, (1e6, 1e12, 1e-9)):
        view.setYRange(-magnitude, magnitude, padding=0)
    before = [np.asarray(view.viewRange()) for view in plot._viewboxes]
    plot.set_box_zoom_enabled(True)
    plot.zoom_y(0.5, unit="Ω")
    plot.zoom_x(0.5)
    app.processEvents()
    after = [np.asarray(view.viewRange()) for view in plot._viewboxes]
    assert np.allclose(after[0][1], before[0][1])
    assert np.allclose(after[1][1], before[1][1] * 0.5)
    np.testing.assert_allclose(after[2][1], before[2][1], atol=0)
    assert np.isclose(np.ptp(after[0][0]), np.ptp(before[0][0]) * 0.5)

    plot.set_channel_data(
        "B", x, np.full(x.size, 1e15), unit="Ω", color="#ff007f", label="B"
    )
    app.processEvents()
    for view, expected in zip(plot._viewboxes, after):
        np.testing.assert_allclose(view.viewRange(), expected, atol=0)


@pytest.mark.parametrize("offset", [1e12, -1e12])
def test_epoch_time_and_large_y_offset_support_repeated_zoom(plot, app, offset):
    x = 1_700_000_000.0 + np.arange(1000) * 0.1
    y = offset + np.linspace(-1e6, 1e6, x.size)
    plot.set_data(x, y)
    plot.reset_view()
    app.processEvents()
    before = np.asarray(plot._viewboxes[0].viewRange())
    plot.zoom_x(0.001)
    plot.zoom_y(0.001)
    app.processEvents()
    after = np.asarray(plot._viewboxes[0].viewRange())
    np.testing.assert_allclose(
        np.ptp(after, axis=1), np.ptp(before, axis=1) * 0.001, rtol=1e-5, atol=0
    )
    np.testing.assert_allclose(np.mean(after, axis=1), np.mean(before, axis=1), atol=0)
    plot.set_data(x, y + 1e8)
    app.processEvents()
    np.testing.assert_allclose(plot._viewboxes[0].viewRange(), after, atol=0)


def test_rectangle_zoom_keeps_selected_y_bounds_on_all_physical_axes(plot, app):
    x = _populate_mixed(plot, app)
    for view, magnitude in zip(plot._viewboxes, (1e6, 1e12, 1e-9)):
        view.setYRange(-magnitude, magnitude, padding=0)
    plot.set_box_zoom_enabled(True)
    plot._viewboxes[0].showAxRect(QtCore.QRectF(x[250], -5e5, 100.0, 1e6), padding=0)
    app.processEvents()
    for view, magnitude in zip(plot._viewboxes, (5e5, 5e11, 5e-10)):
        np.testing.assert_allclose(view.viewRange()[1], [-magnitude, magnitude], atol=0)
    assert plot._manual_x_range


class _WheelEvent:
    def __init__(self, position):
        self.position = position
        self.accepted = False
        self.ignored = False

    def pos(self):
        return self.position

    def scenePos(self):
        return self.position

    def delta(self):
        return 120

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.ignored = True


def test_secondary_y_axis_wheel_zooms_only_its_unit_and_plot_overlay_ignores_wheel(
    plot, app
):
    _populate_mixed(plot, app)
    before = [np.asarray(view.viewRange()) for view in plot._viewboxes]
    # AxisItem forwards its wheel event with axis=YAxis to the linked view.
    event = _WheelEvent(plot._axes[1].mapRectToScene(plot._axes[1].rect()).center())
    plot._axes[1].wheelEvent(event)
    app.processEvents()
    after = [np.asarray(view.viewRange()) for view in plot._viewboxes]
    assert event.accepted
    assert np.ptp(after[1][1]) < np.ptp(before[1][1])
    np.testing.assert_allclose(after[0], before[0], atol=0)
    np.testing.assert_allclose(after[2], before[2], atol=0)

    surface_event = _WheelEvent(plot._viewboxes[0].sceneBoundingRect().center())
    plot._viewboxes[1].wheelEvent(surface_event)
    assert surface_event.ignored
    np.testing.assert_allclose(plot._viewboxes[1].viewRange(), after[1], atol=0)


def test_y_only_gesture_does_not_mark_time_axis_as_manually_zoomed(plot, app):
    _populate_mixed(plot, app)
    windows = []
    plot.x_window_changed.connect(lambda low, high: windows.append((low, high)))
    plot._range_changed_manually([False, True])
    assert not plot._manual_x_range
    assert windows == []


def test_manual_unit_range_follows_unit_when_other_channel_is_hidden(plot, app):
    x = _populate_mixed(plot, app)
    plot._viewboxes[1].setYRange(2e11, 3e11, padding=0)
    plot.set_channel_data(
        "A", x, np.ones(x.size), unit="V", color="#ff007f", label="A", visible=False
    )
    app.processEvents()
    assert plot.axis_assignments["B"] == 0
    np.testing.assert_allclose(plot._viewboxes[0].viewRange()[1], [2e11, 3e11], atol=0)
    assert not plot._viewboxes[0].autoRangeEnabled()[1]
    assert not plot._viewboxes[2].isVisible()


def test_smoothing_can_move_between_clipped_unit_views_and_refresh_repeatedly(
    plot, app
):
    x = _populate_mixed(plot, app)
    for channel in ("A", "B", "C", "B", "A"):
        y = plot._channel_data[channel][1]
        plot.set_smooth_data(channel, x, y)
        plot.finish_channel_update()
        plot.finish_channel_update()
        app.processEvents()
        view = plot._viewboxes[plot.axis_assignments[channel]]
        assert plot.smooth_curve.getViewBox() is view
        assert plot.smooth_curve.opts["clipToView"]


def test_display_clips_to_zoomed_time_window_and_limits_large_offscreen_values(
    plot, app
):
    x = 1_700_000_000.0 + np.arange(10_000)
    y = np.where(np.arange(x.size) % 2, 1e15, -1e15)
    plot.set_channel_data("A", x, y, unit="V", color="#ff007f", label="A")
    plot._viewboxes[0].setXRange(x[4000], x[4100], padding=0)
    plot._viewboxes[0].setYRange(-1, 1, padding=0)
    app.processEvents()
    displayed_x, displayed_y = plot.curve.getData()
    assert displayed_x.size <= 104
    assert np.max(np.abs(displayed_y)) <= 2000
    original_x, original_y = plot.curve.getOriginalDataset()
    np.testing.assert_array_equal(original_x, x)
    np.testing.assert_array_equal(original_y, y)


def test_overlay_geometry_and_rendered_curves_stay_inside_plot_rect(plot, app):
    _populate_mixed(plot, app)
    for view in plot._viewboxes:
        view.setYRange(-1, 1, padding=0)
    app.processEvents()
    primary = plot._viewboxes[0]
    rect = primary.mapRectToScene(primary.rect())
    for view in plot._viewboxes[1:]:
        assert view.geometry() == rect
        assert view.shape().boundingRect() == view.rect()

    pixmap = plot.grab()
    image = pixmap.toImage()
    ratio = pixmap.devicePixelRatio()
    x_low = int((rect.left() + 20) * ratio)
    x_high = int((rect.right() - 20) * ratio)
    outside_rows = [
        *range(max(0, int(rect.top() * ratio))),
        *range(int(np.ceil(rect.bottom() * ratio)) + 1, image.height()),
    ]
    for row in outside_rows:
        for column in range(x_low, x_high):
            color = image.pixelColor(column, row)
            assert not (color.red() > 220 and color.green() < 40 and color.blue() > 80)


def test_axis_clicks_do_not_create_annotations_or_change_range(plot, app):
    _populate_mixed(plot, app)
    ranges = [np.asarray(view.viewRange()) for view in plot._viewboxes]

    class ClickEvent:
        def button(self):
            return QtCore.Qt.MouseButton.LeftButton

        def scenePos(self):
            return plot._axes[0].mapRectToScene(plot._axes[0].rect()).center()

    plot._mouse_clicked(ClickEvent())
    plot._mouse_moved((ClickEvent().scenePos(),))
    app.processEvents()
    assert plot._markers == []
    assert not plot.hover_label.isVisible()
    for view, expected in zip(plot._viewboxes, ranges):
        np.testing.assert_allclose(view.viewRange(), expected, atol=0)


def test_markers_and_hover_clear_on_channel_axis_changes_but_survive_refresh(plot, app):
    x = _populate_mixed(plot, app)
    # Use a distinct B range so its curve does not overlap the other channels.
    plot._viewboxes[1].setYRange(-2e12, 2e12, padding=0)
    app.processEvents()
    y = plot._channel_data["B"][1]
    position = plot._viewboxes[1].mapViewToScene(QtCore.QPointF(x[100], y[100]))

    class ClickEvent:
        def button(self):
            return QtCore.Qt.MouseButton.LeftButton

        def scenePos(self):
            return position

    plot._mouse_clicked(ClickEvent())
    plot._mouse_moved((position,))
    assert len(plot._markers) == 1
    old_view, point, label = plot._markers[0]
    assert old_view is plot._viewboxes[1]
    assert plot.hover_label.isVisible()

    plot.set_channel_data("B", x, y + 1e3, unit="Ω", color="#ff007f", label="B")
    plot.finish_channel_update()
    app.processEvents()
    assert len(plot._markers) == 1
    assert plot.hover_label.isVisible()

    plot.set_channel_data(
        "A", x, np.ones(x.size), unit="V", color="#ff007f", label="A", visible=False
    )
    app.processEvents()
    assert plot.axis_assignments["B"] == 0
    assert plot._markers == []
    assert point.parentItem() is None
    assert label.parentItem() is None
    assert not plot.v_line.isVisible()
    assert not plot.h_line.isVisible()
    assert not plot.hover_label.isVisible()


def test_first_sample_is_visible_as_a_point_before_a_line_can_be_drawn(plot, app):
    x = np.asarray([1_700_000_000.0])
    y = np.asarray([10_000.0])
    plot.set_channel_data("A", x, y, unit="Ω", color="#ff007f", label="A")
    app.processEvents()
    assert plot.curve.isVisible()
    assert plot.curve.scatter.isVisible()
    assert len(plot.curve.scatter.points()) == 1
    point = plot._viewboxes[0].mapViewToScene(QtCore.QPointF(x[0], y[0]))
    assert plot._viewboxes[0].mapRectToScene(plot._viewboxes[0].rect()).contains(point)

    plot.set_channel_data(
        "A", np.r_[x, x + 21.1], np.r_[y, y + 1], unit="Ω", color="#ff007f", label="A"
    )
    app.processEvents()
    assert not plot.curve.scatter.isVisible()
    assert plot.curve.curve.isVisible()


def test_shared_time_range_includes_independent_channels_and_empty_axes_do_not_reset_it(
    plot, app
):
    start = 1_700_000_000.0
    for channel, unit, offset in (("A", "V", 10), ("B", "Ω", -100), ("C", "A", 1000)):
        plot.set_channel_data(
            channel,
            start + offset + np.arange(10),
            np.arange(10),
            unit=unit,
            color="#ff007f",
            label=channel,
        )
    app.processEvents()
    for view in plot._viewboxes:
        lower, upper = view.viewRange()[0]
        assert lower <= start - 100
        assert upper >= start + 1009
    plot.reset_view()
    app.processEvents()
    assert plot._viewboxes[0].viewRange()[0][0] <= start - 100
    assert plot._viewboxes[0].viewRange()[0][1] >= start + 1009

    for channel in ("B", "C"):
        plot.set_channel_data(
            channel,
            np.asarray([]),
            np.asarray([]),
            unit="V",
            color="#ff007f",
            label=channel,
        )
    plot.reset_view()
    app.processEvents()
    lower, upper = plot._viewboxes[0].viewRange()[0]
    assert start < lower <= start + 10
    assert start + 19 <= upper < start + 100


def test_live_time_union_preserves_manual_zoom_until_explicit_reset(plot, app):
    x = _populate_mixed(plot, app)
    plot.zoom_x(0.5)
    manual_range = plot._viewboxes[0].viewRange()[0][:]
    plot.set_channel_data(
        "B", x + 5000, np.ones(x.size), unit="Ω", color="#ff007f", label="B"
    )
    app.processEvents()
    np.testing.assert_allclose(plot._viewboxes[0].viewRange()[0], manual_range, atol=0)
    plot.reset_view()
    app.processEvents()
    assert plot._viewboxes[0].viewRange()[0][1] >= x[-1] + 5000


class _LegendClick:
    def button(self):
        return QtCore.Qt.MouseButton.LeftButton

    def accept(self):
        pass


def test_legend_hiding_survives_refresh_and_can_be_restored_explicitly(plot, app):
    x = _populate_mixed(plot, app)
    sample = next(
        sample for sample, _label in plot.legend.items if sample.item is plot.curve
    )
    sample.mouseClickEvent(_LegendClick())
    assert not plot.curve.isVisible()
    assert "V" not in plot.available_units
    plot.set_channel_data(
        "A", x, np.ones(x.size), unit="V", color="#ff007f", label="A new run"
    )
    app.processEvents()
    assert not plot.curve.isVisible()
    plot.restore_channel_visibility("A")
    app.processEvents()
    assert plot.curve.isVisible()
    assert "V" in plot.available_units
    sample = next(
        sample for sample, _label in plot.legend.items if sample.item is plot.curve
    )
    sample.mouseClickEvent(_LegendClick())
    assert not plot.curve.isVisible()


def test_empty_legend_click_does_not_hide_future_samples(plot, app):
    sample = next(
        sample for sample, _label in plot.legend.items if sample.item is plot.curve
    )
    sample.mouseClickEvent(_LegendClick())
    plot.set_data(np.asarray([1_700_000_000.0]), np.asarray([10.0]))
    app.processEvents()
    assert plot.curve.isVisible()
    assert plot.curve.scatter.isVisible()


def test_hidden_channel_average_does_not_pollute_other_unit_axis_after_refresh(
    plot, app
):
    x = _populate_mixed(plot, app)
    y = plot._channel_data["A"][1]
    plot.set_smooth_data("A", x, y)
    assert plot.smooth_curve.isVisible()
    sample = next(
        sample for sample, _label in plot.legend.items if sample.item is plot.curve
    )
    sample.mouseClickEvent(_LegendClick())
    assert not plot.smooth_curve.isVisible()
    assert plot.axis_assignments["B"] == 0
    plot.set_smooth_data("A", x, y)
    app.processEvents()
    assert not plot.smooth_curve.isVisible()
    lower, upper = plot._viewboxes[0].viewRange()[1]
    assert lower < -9e11
    assert upper > 9e11
    plot.restore_channel_visibility("A")
    app.processEvents()
    assert plot.smooth_curve.isVisible()
    assert plot.smooth_curve.getViewBox() is plot._viewboxes[plot.axis_assignments["A"]]
