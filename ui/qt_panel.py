"""Codex-inspired monitoring panel built from PySide6 widgets."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

import pyqtgraph as pg
from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QStackedWidget,
    QStyle,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

import config_manager
from data.store import TokenData
from ui.activity import compact_tokens
from ui.qt_heatmap import TokenActivityHeatmap
from ui.qt_theme import app_icon, current_theme, fluent_icon, theme_controller


PANEL_MIN_WIDTH = 640
PANEL_MAX_WIDTH = 820
PANEL_HEIGHT = 550
HEADER_HEIGHT = 50
TOP_SECTION_HEIGHT = 154
ACTIVITY_SECTION_HEIGHT = 176
STATISTICS_SECTION_HEIGHT = 92
STATUS_SECTION_HEIGHT = 38
SECTION_SPACING = 8
SECTION_HORIZONTAL_MARGIN = 22


def format_money(value: float | Decimal | None) -> str:
    if value is None:
        return "--"
    amount = float(value)
    decimals = 4 if 0 < abs(amount) < 0.01 else 2
    return f"¥{amount:.{decimals}f}"


def format_token_axis(value: float) -> str:
    return compact_tokens(int(round(value)))


def format_money_axis(value: float) -> str:
    absolute = abs(value)
    if absolute >= 100:
        return f"¥{value:,.0f}"
    decimals = 4 if 0 < absolute < 0.01 else 2
    return f"¥{value:.{decimals}f}"


class MoneyAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [format_money_axis(value * scale) for value in values]


class TokenAxis(pg.AxisItem):
    def tickStrings(self, values, scale, spacing):
        return [format_token_axis(value * scale) for value in values]


class DraggableHeader(QFrame):
    """Header drag surface used to move the entire frameless window."""

    pressed = Signal(QPoint)
    dragged = Signal(QPoint)
    released = Signal(QPoint)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.pressed.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.dragged.emit(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.released.emit(event.globalPosition().toPoint())
            event.accept()


class StatusDot(QWidget):
    """Small semantic status mark that follows live theme changes."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._role = "accent"
        self._explicit_color: QColor | None = None
        self.setFixedSize(12, 12)

    def set_role(self, role: str) -> None:
        self._role = role
        self._explicit_color = None
        self.update()

    def set_color(self, color: str) -> None:
        """Keep the old color API available for callers outside MainPanel."""
        self._explicit_color = QColor(color)
        self.update()

    def refresh_theme(self) -> None:
        self.update()

    def paintEvent(self, _event) -> None:
        tokens = current_theme()
        color = self._explicit_color or QColor(getattr(tokens, self._role, tokens.accent))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(2, 2, 8, 8)
        painter.end()


class MetricCard(QFrame):
    """One logical metric in the flat top summary area."""

    def __init__(self, title: str, icon_name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon_name = icon_name
        self.setObjectName("metricCard")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        self.title_label = QLabel(title)
        self.title_label.setObjectName("metricLabel")
        self.value = QLabel("--")
        self.value.setObjectName("metricValue")
        self.detail = QLabel()
        self.detail.setObjectName("metricDetail")
        self.footer = QLabel()
        self.footer.setObjectName("muted")
        # The third visual direction intentionally keeps the summary sparse.
        # Detail values remain populated for compatibility and accessibility.
        self.detail.hide()
        self.footer.hide()

        layout.addWidget(self.title_label)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)
        layout.addWidget(self.footer)
        layout.addStretch(1)

    def set_variant(self, variant: str) -> None:
        self.value.setObjectName("heroValue" if variant == "hero" else "metricValue")
        self.setProperty("variant", variant)

    def set_values(self, value: str, detail: str = "", footer: str = "") -> None:
        self.value.setText(value)
        self.detail.setText(detail)
        self.footer.setText(footer)
        self.detail.setToolTip(detail)
        self.footer.setToolTip(footer)

    def set_title(self, title: str) -> None:
        self.title_label.setText(title)


class TrendCard(QFrame):
    """Seven-day cost chart rendered as seven flat bars."""

    BAR_WIDTH = 0.36

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("trendSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 5, 0, 2)
        layout.setSpacing(2)

        self.title = QLabel("近 7 天使用金额")
        self.title.setObjectName("sectionTitle")
        layout.addWidget(self.title)

        self.plot = pg.PlotWidget(
            axisItems={"left": MoneyAxis(orientation="left")},
        )
        self.plot.setStyleSheet("border: 0;")
        self.plot.setMinimumHeight(100)
        self.plot.setMouseEnabled(x=False, y=False)
        self.plot.hideButtons()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=False, y=True, alpha=0.14)

        axis_font = QFont("Microsoft YaHei UI", 8)
        left_axis = self.plot.getAxis("left")
        bottom_axis = self.plot.getAxis("bottom")
        left_axis.setTickFont(axis_font)
        bottom_axis.setTickFont(axis_font)
        bottom_axis.setStyle(hideOverlappingLabels=False)
        left_axis.setStyle(hideOverlappingLabels=False)
        left_axis.setWidth(44)
        left_axis.enableAutoSIPrefix(False)
        bottom_axis.setHeight(22)
        self.plot.getViewBox().setLimits(xMin=-0.5, xMax=6.5, yMin=0)

        self._dates: list[date] = []
        self._values: list[float] = []
        self._series: pg.BarGraphItem | None = None
        self._hover_index: int | None = None
        self._mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved,
            rateLimit=60,
            slot=self._on_mouse_moved,
        )
        layout.addWidget(self.plot, 1)
        self._connect_theme_changes()
        self.set_rows([])

    def _connect_theme_changes(self) -> None:
        try:
            theme_controller().changed.connect(self._on_theme_changed)
        except RuntimeError:
            # Standalone component tests may construct the chart before an app-level
            # controller exists; production configures the theme before any window.
            pass

    def set_rows(self, rows: list[dict], today: date | None = None) -> None:
        current = today or date.today()
        by_date = {str(row.get("date")): row for row in rows}
        self._dates = [current - timedelta(days=offset) for offset in range(6, -1, -1)]
        self._values = [
            float(by_date.get(day.isoformat(), {}).get("cost_cny", 0) or 0)
            for day in self._dates
        ]
        self.plot.clear()

        tokens = current_theme()
        self._series = pg.BarGraphItem(
            x=list(range(7)),
            height=self._values,
            width=self.BAR_WIDTH,
            pen=pg.mkPen(tokens.accent),
            brush=pg.mkBrush(tokens.accent),
        )
        self.plot.addItem(self._series)

        self.plot.getAxis("bottom").setTicks(
            [[(index, day.strftime("%m/%d")) for index, day in enumerate(self._dates)]]
        )
        # Preserve half a day at each edge so all seven bars stay fully visible.
        self.plot.setXRange(-0.5, 6.5, padding=0)
        maximum = max(self._values, default=0.0)
        tick_max = max(0.01, maximum)
        range_max = tick_max * 1.08 if maximum > 0 else tick_max
        self.plot.setYRange(0, range_max, padding=0)
        self.plot.getAxis("left").setTicks(
            [[
                (tick_max * index / 3, format_money_axis(tick_max * index / 3))
                for index in range(4)
            ]]
        )
        self._hover_index = None
        self.refresh_theme()

    def refresh_theme(self) -> None:
        tokens = current_theme()
        # The selected layout is one continuous surface; the chart must not
        # introduce a nested rectangular card behind the bars.
        self.plot.setBackground(tokens.window)
        left_axis = self.plot.getAxis("left")
        bottom_axis = self.plot.getAxis("bottom")
        left_axis.setTextPen(pg.mkPen(tokens.subtext))
        bottom_axis.setTextPen(pg.mkPen(tokens.subtext))
        axis_color = QColor(tokens.border)
        axis_color.setAlpha(96)
        left_axis.setPen(pg.mkPen(axis_color))
        bottom_axis.setPen(pg.mkPen(axis_color))
        if self._series is not None:
            if self._hover_index is None:
                self._series.setOpts(
                    pens=None,
                    brushes=None,
                    pen=pg.mkPen(tokens.accent),
                    brush=pg.mkBrush(tokens.accent),
                )
            else:
                self._series.setOpts(
                    pens=[
                        pg.mkPen(tokens.accent_hover if index == self._hover_index else tokens.accent)
                        for index in range(len(self._values))
                    ],
                    brushes=[
                        pg.mkBrush(tokens.accent_hover if index == self._hover_index else tokens.accent)
                        for index in range(len(self._values))
                    ],
                )

    def _on_theme_changed(self, _mode: str, _resolved: str) -> None:
        self.refresh_theme()

    def _on_mouse_moved(self, event) -> None:
        scene_pos = event[0]
        if not self.plot.sceneBoundingRect().contains(scene_pos):
            self._hide_hover()
            return
        point = self.plot.getViewBox().mapSceneToView(scene_pos)
        index = int(round(point.x()))
        if not 0 <= index < len(self._values) or abs(point.x() - index) > self.BAR_WIDTH / 2:
            self._hide_hover()
            return

        self._hover_index = index
        self.refresh_theme()
        local = self.plot.mapFromScene(scene_pos)
        QToolTip.showText(
            self.plot.mapToGlobal(local),
            self.tooltip_text(index),
            self.plot,
        )

    def _hide_hover(self) -> None:
        had_hover = self._hover_index is not None
        self._hover_index = None
        if had_hover:
            self.refresh_theme()
        QToolTip.hideText()

    def tooltip_text(self, index: int) -> str:
        return (
            f"{self._dates[index].isoformat()}\n"
            f"使用金额：{format_money(self._values[index])}"
        )


class MinuteUsageChart(QWidget):
    """当天 Token 差额的估算分时图；原始分钟数据始终保持不变。"""

    SERIES = (
        ("PROMPT_CACHE_HIT_TOKEN", "输入（命中缓存）"),
        ("PROMPT_CACHE_MISS_TOKEN", "输入（未命中缓存）"),
        ("RESPONSE_TOKEN", "输出"),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("minuteUsageChart")
        self._values = {key: [0] * 1440 for key, _label in self.SERIES}
        self._visible = {key: True for key, _label in self.SERIES}
        self._signature: tuple | None = None
        self._updating_region = False
        self._fills: dict[str, pg.FillBetweenItem] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._total_curve: pg.PlotDataItem | None = None
        self._nav_curve: pg.PlotDataItem | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        self.state_label = QLabel("等待首次刷新建立估算基线")
        self.state_label.setObjectName("minuteUsageState")
        self.state_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.state_label, 1)

        self.chart_container = QWidget()
        chart_layout = QVBoxLayout(self.chart_container)
        chart_layout.setContentsMargins(0, 0, 0, 0)
        chart_layout.setSpacing(1)
        self.plot = pg.PlotWidget(axisItems={"left": TokenAxis(orientation="left")})
        self.plot.setStyleSheet("border: 0;")
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.hideButtons()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=False, y=True, alpha=0.14)
        self.plot.setMinimumHeight(82)
        self.plot.getViewBox().setLimits(xMin=0, xMax=1439, yMin=0)
        self.plot.getAxis("left").setWidth(42)
        self.plot.getAxis("left").setTickFont(QFont("Microsoft YaHei UI", 8))
        self.plot.getAxis("bottom").setHeight(18)
        self.plot.getAxis("bottom").setTickFont(QFont("Microsoft YaHei UI", 8))
        self.plot.getAxis("bottom").setTicks(
            [[(minute, f"{minute // 60:02d}:00") for minute in range(0, 1440, 240)]]
        )
        chart_layout.addWidget(self.plot, 1)

        self.navigator = pg.PlotWidget()
        self.navigator.setStyleSheet("border: 0;")
        self.navigator.setFixedHeight(25)
        self.navigator.setMouseEnabled(x=False, y=False)
        self.navigator.hideButtons()
        self.navigator.setMenuEnabled(False)
        self.navigator.getAxis("left").hide()
        self.navigator.getAxis("bottom").setHeight(15)
        self.navigator.getAxis("bottom").setTickFont(QFont("Microsoft YaHei UI", 7))
        self.navigator.getAxis("bottom").setTicks(
            [[(minute, f"{minute // 60:02d}:00") for minute in range(0, 1441, 360)]]
        )
        self.navigator.getViewBox().setLimits(xMin=0, xMax=1439, yMin=0)
        self.region = pg.LinearRegionItem(values=(0, 1439), movable=True)
        self.region.sigRegionChanged.connect(self._on_region_changed)
        self.navigator.addItem(self.region)
        chart_layout.addWidget(self.navigator)
        layout.addWidget(self.chart_container, 1)
        self.chart_container.hide()
        self._mouse_proxy = pg.SignalProxy(
            self.plot.scene().sigMouseMoved, rateLimit=60, slot=self._on_mouse_moved
        )
        self.plot.getViewBox().sigXRangeChanged.connect(self._on_main_range_changed)
        try:
            theme_controller().changed.connect(self._on_theme_changed)
        except RuntimeError:
            pass

    @staticmethod
    def _colors() -> tuple[QColor, QColor, QColor]:
        tokens = current_theme()
        hit = QColor(tokens.accent).lighter(155)
        miss = QColor(tokens.accent)
        output = QColor(tokens.accent).darker(135)
        return hit, miss, output

    def legend_color(self, token_type: str) -> QColor:
        return dict(zip((key for key, _label in self.SERIES), self._colors()))[token_type]

    def set_rows(self, rows: list[dict], status: str, loading: bool = False) -> None:
        values = {key: [0] * 1440 for key, _label in self.SERIES}
        for row in rows:
            try:
                minute = int(row.get("minute", -1))
            except (TypeError, ValueError):
                continue
            token_type = str(row.get("token_type", ""))
            if not 0 <= minute < 1440 or token_type not in values:
                continue
            values[token_type][minute] += max(0, int(row.get("token_amount", 0) or 0))
        signature = (status, tuple(tuple(values[key]) for key, _label in self.SERIES))
        self._values = values
        if loading and not rows:
            self._show_state("正在刷新分时估算数据…")
            return
        if status == "baseline":
            self._show_state("已建立估算基线，下一次刷新后显示分时数据")
            return
        if status == "cross_day":
            self._show_state("已跨日重建估算基线，下一次刷新后显示分时数据")
            return
        if status == "unavailable":
            self._show_state("当前平台未启用估算分时数据")
            return
        if status in {"failed", "storage_error"} and not rows:
            self._show_state("分时数据暂不可用，请刷新后重试")
            return
        if not any(sum(values[key]) for key, _label in self.SERIES):
            self._show_state("今日暂无已收集的 Token 分时数据")
            return
        self.state_label.hide()
        self.chart_container.show()
        if signature != self._signature:
            self._signature = signature
            self._render_series()

    def _show_state(self, message: str) -> None:
        self.state_label.setText(message)
        self.state_label.show()
        self.chart_container.hide()

    def _render_series(self) -> None:
        x = list(range(1440))
        hit = self._values["PROMPT_CACHE_HIT_TOKEN"]
        miss = self._values["PROMPT_CACHE_MISS_TOKEN"]
        output = self._values["RESPONSE_TOKEN"]
        cumulative = [hit[index] + miss[index] for index in x]
        total = [cumulative[index] + output[index] for index in x]
        self.plot.clear()
        self.navigator.clear()
        self._fills = {}
        self._curves = {}
        zero_curve = pg.PlotDataItem(x, [0] * 1440, pen=None)
        hit_curve = pg.PlotDataItem(x, hit)
        miss_curve = pg.PlotDataItem(x, cumulative)
        output_curve = pg.PlotDataItem(x, total)
        curves = (hit_curve, miss_curve, output_curve)
        previous = zero_curve
        for (token_type, _label), curve in zip(self.SERIES, curves):
            fill = pg.FillBetweenItem(previous, curve)
            self.plot.addItem(fill)
            self.plot.addItem(curve)
            self._fills[token_type] = fill
            self._curves[token_type] = curve
            previous = curve
        self._total_curve = pg.PlotDataItem(x, total)
        self.plot.addItem(self._total_curve)
        self._nav_curve = pg.PlotDataItem(x, total)
        self.navigator.addItem(self._nav_curve)
        self.navigator.addItem(self.region)
        maximum = max(total, default=0)
        self.plot.setYRange(0, max(1, maximum * 1.08), padding=0)
        self.navigator.setYRange(0, max(1, maximum * 1.08), padding=0)
        self.plot.setXRange(0, 1439, padding=0)
        self.navigator.setXRange(0, 1439, padding=0)
        self.refresh_theme()
        self._apply_visibility()

    def refresh_theme(self) -> None:
        tokens = current_theme()
        for widget in (self.plot, self.navigator):
            widget.setBackground(tokens.window)
            for axis_name in ("left", "bottom"):
                axis = widget.getAxis(axis_name)
                axis.setTextPen(pg.mkPen(tokens.subtext))
                border = QColor(tokens.border)
                border.setAlpha(96)
                axis.setPen(pg.mkPen(border))
        colors = self._colors()
        for ((token_type, _label), color) in zip(self.SERIES, colors):
            fill = self._fills.get(token_type)
            curve = self._curves.get(token_type)
            if fill is not None:
                brush = QColor(color)
                brush.setAlpha(118)
                fill.setBrush(pg.mkBrush(brush))
            if curve is not None:
                curve.setPen(pg.mkPen(color, width=1.0))
        if self._total_curve is not None:
            self._total_curve.setPen(pg.mkPen(tokens.accent_hover, width=1.5))
        if self._nav_curve is not None:
            self._nav_curve.setPen(pg.mkPen(tokens.accent, width=0.9))
        self.region.setBrush(pg.mkBrush(QColor(tokens.accent_soft)))
        for line in self.region.lines:
            line.setPen(pg.mkPen(tokens.accent, width=1.0))

    def set_series_visible(self, token_type: str, visible: bool) -> None:
        if token_type not in self._visible:
            return
        self._visible[token_type] = visible
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        for token_type, visible in self._visible.items():
            if token_type in self._fills:
                self._fills[token_type].setVisible(visible)
            if token_type in self._curves:
                self._curves[token_type].setVisible(visible)

    def _on_region_changed(self) -> None:
        if self._updating_region:
            return
        low, high = self.region.getRegion()
        self._updating_region = True
        try:
            self.plot.setXRange(low, high, padding=0)
        finally:
            self._updating_region = False

    def _on_main_range_changed(self, _view_box, ranges) -> None:
        if self._updating_region:
            return
        x_range = ranges[0] if isinstance(ranges[0], (tuple, list)) else ranges
        low, high = x_range
        self._updating_region = True
        try:
            self.region.setRegion((max(0, low), min(1439, high)))
        finally:
            self._updating_region = False

    def _on_theme_changed(self, _mode: str, _resolved: str) -> None:
        self.refresh_theme()

    def _on_mouse_moved(self, event) -> None:
        scene_pos = event[0]
        if not self.plot.sceneBoundingRect().contains(scene_pos):
            QToolTip.hideText()
            return
        point = self.plot.getViewBox().mapSceneToView(scene_pos)
        minute = int(round(point.x()))
        if not 0 <= minute < 1440:
            QToolTip.hideText()
            return
        local = self.plot.mapFromScene(scene_pos)
        QToolTip.showText(
            self.plot.mapToGlobal(local), self.tooltip_text(minute), self.plot
        )

    def tooltip_text(self, minute: int) -> str:
        hit = self._values["PROMPT_CACHE_HIT_TOKEN"][minute]
        miss = self._values["PROMPT_CACHE_MISS_TOKEN"][minute]
        output = self._values["RESPONSE_TOKEN"][minute]
        total = hit + miss + output
        rate = "--" if hit + miss == 0 else f"{hit / (hit + miss) * 100:.1f}%"
        return (
            f"{minute // 60:02d}:{minute % 60:02d}　总计 {total:,}\n"
            f"■ 输入（命中缓存）　{hit:,}\n"
            f"■ 输入（未命中缓存）　{miss:,}\n"
            f"■ 输出　{output:,}\n"
            f"缓存命中率　{rate}"
        )

    def summary_text(self) -> str:
        hit = sum(self._values["PROMPT_CACHE_HIT_TOKEN"])
        miss = sum(self._values["PROMPT_CACHE_MISS_TOKEN"])
        output = sum(self._values["RESPONSE_TOKEN"])
        total = hit + miss + output
        if not total:
            return "暂无估算数据"
        peak = max(
            range(1440),
            key=lambda minute: sum(self._values[key][minute] for key, _label in self.SERIES),
        )
        rate = "--" if hit + miss == 0 else f"{hit / (hit + miss) * 100:.1f}%"
        return f"今日 {compact_tokens(total)} · 命中 {rate} · 峰值 {peak // 60:02d}:{peak % 60:02d}"


class StatisticsCard(QFrame):
    """Five equal columns matching the selected third-direction mockup."""

    LABELS = (
        "本月使用金额",
        "历史使用总金额",
        "本月 Token",
        "近 7 天使用金额",
        "近 7 天 Token",
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("statisticsSection")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(SECTION_HORIZONTAL_MARGIN, 0, SECTION_HORIZONTAL_MARGIN, 2)
        layout.setSpacing(3)

        line = QFrame()
        line.setObjectName("divider")
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFixedHeight(1)
        layout.addWidget(line)

        title = QLabel("使用统计")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        columns = QHBoxLayout()
        columns.setContentsMargins(10, 0, 10, 0)
        columns.setSpacing(0)
        self._values: list[QLabel] = []
        self._names: list[QLabel] = []
        for index, label in enumerate(self.LABELS):
            column = QWidget()
            column_layout = QVBoxLayout(column)
            column_layout.setContentsMargins(0, 0, 0, 0)
            column_layout.setSpacing(1)
            name = QLabel(label)
            name.setObjectName("statLabel")
            name.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            if label == "历史使用总金额":
                # The provider has no lifetime total; this value is the local cache scope.
                name.setToolTip("按本机已缓存账单累计，未同步的早期账单不计入")
            value = QLabel("--")
            value.setObjectName("statValue")
            value.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
            column_layout.addWidget(name)
            column_layout.addWidget(value)
            columns.addWidget(column, 1)
            self._names.append(name)
            self._values.append(value)
            if index < len(self.LABELS) - 1:
                separator = QFrame()
                separator.setObjectName("divider")
                separator.setFrameShape(QFrame.Shape.VLine)
                separator.setFixedSize(1, 46)
                columns.addWidget(separator, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(columns, 1)

    def set_data(self, data: TokenData) -> None:
        recent_rows = {str(row.get("date")): row for row in data.daily_usage}
        recent_dates = [date.today() - timedelta(days=offset) for offset in range(6, -1, -1)]
        recent_cost = sum(
            float(recent_rows.get(day.isoformat(), {}).get("cost_cny", 0) or 0)
            for day in recent_dates
        )
        recent_tokens = sum(
            int(recent_rows.get(day.isoformat(), {}).get("tokens", 0) or 0)
            for day in recent_dates
        )
        has_daily_data = data.today_tokens is not None
        values = (
            format_money(data.monthly_cost_cny),
            format_money(data.total_cost_cny),
            compact_tokens(data.monthly_usage_tokens) if data.monthly_usage_tokens is not None else "--",
            format_money(recent_cost) if has_daily_data else "--",
            compact_tokens(recent_tokens) if has_daily_data else "--",
        )
        for label, value in zip(self._values, values):
            label.setText(value)


class MainPanel(QFrame):
    settings_requested = Signal()
    refresh_requested = Signal()
    close_requested = Signal()
    theme_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("panelFrame")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(PANEL_MIN_WIDTH, PANEL_HEIGHT)
        self.setMaximumSize(PANEL_MAX_WIDTH, PANEL_HEIGHT)
        self._theme_mode = "dark"
        self._resolved_theme = current_theme().name
        self._theme_feedback_message = ""
        self._button_specs: list[tuple[QToolButton, str, QStyle.StandardPixmap, str]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(1, 1, 1, 1)
        root.setSpacing(0)

        self.header = DraggableHeader()
        self.header.setObjectName("panelHeader")
        self.header.setFixedHeight(HEADER_HEIGHT)
        header_layout = QHBoxLayout(self.header)
        header_layout.setContentsMargins(14, 7, 12, 7)
        header_layout.setSpacing(8)

        logo = QLabel()
        logo.setPixmap(app_icon(28).pixmap(28, 28))
        logo.setFixedSize(28, 28)
        self._title_label = QLabel("TokenSpider")
        self._title_label.setObjectName("panelTitle")
        provider_id = str(config_manager.get("ACTIVE_PROVIDER", "deepseek"))
        provider_name = {"deepseek": "DeepSeek", "mimo": "小米 MiMo"}.get(
            provider_id, provider_id
        )
        self._provider_label = QLabel(f" · {provider_name}" if provider_name else "")
        self._provider_label.setObjectName("panelSubtitle")
        header_layout.addWidget(logo)
        header_layout.addWidget(self._title_label)
        header_layout.addWidget(self._provider_label)
        header_layout.addStretch(1)

        self.theme_segment = QFrame()
        self.theme_segment.setObjectName("themeSegment")
        self.theme_segment.setFixedHeight(30)
        theme_layout = QHBoxLayout(self.theme_segment)
        theme_layout.setContentsMargins(2, 2, 2, 2)
        theme_layout.setSpacing(0)
        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self.light_theme_button = self._theme_button("sun", "light", "切换到浅色主题")
        self.dark_theme_button = self._theme_button("moon", "dark", "切换到深色主题")
        for button in (self.light_theme_button, self.dark_theme_button):
            self._theme_group.addButton(button)
            theme_layout.addWidget(button)
        header_layout.addWidget(self.theme_segment)

        header_divider = QFrame()
        header_divider.setObjectName("divider")
        header_divider.setFrameShape(QFrame.Shape.VLine)
        header_divider.setFixedSize(1, 22)
        header_layout.addWidget(header_divider)

        self.settings_button = self._tool_button(
            "settings", QStyle.StandardPixmap.SP_FileDialogDetailedView, "设置"
        )
        self.refresh_button = self._tool_button(
            "refresh", QStyle.StandardPixmap.SP_BrowserReload, "刷新"
        )
        self.close_button = self._tool_button(
            "close", QStyle.StandardPixmap.SP_TitleBarCloseButton, "收起", role="close"
        )
        self.settings_button.clicked.connect(self.settings_requested)
        self.refresh_button.clicked.connect(self.refresh_requested)
        self.close_button.clicked.connect(self.close_requested)
        for button in (self.settings_button, self.refresh_button, self.close_button):
            header_layout.addWidget(button)
        root.addWidget(self.header)

        body = QWidget()
        body.setObjectName("panelRoot")
        content = QVBoxLayout(body)
        content.setContentsMargins(0, 7, 0, 7)
        content.setSpacing(SECTION_SPACING)

        self.top_section = QFrame()
        self.top_section.setObjectName("topSection")
        self.top_section.setFixedHeight(TOP_SECTION_HEIGHT)
        top_layout = QHBoxLayout(self.top_section)
        top_layout.setContentsMargins(SECTION_HORIZONTAL_MARGIN, 5, SECTION_HORIZONTAL_MARGIN, 5)
        top_layout.setSpacing(16)

        self.metrics_container = QWidget()
        self.metrics_container.setObjectName("metricsContainer")
        self.metrics_container.setMinimumWidth(205)
        metrics_layout = QVBoxLayout(self.metrics_container)
        metrics_layout.setContentsMargins(0, 0, 0, 0)
        metrics_layout.setSpacing(3)

        self.today_card = MetricCard("今日使用金额", "usage")
        self.today_card.set_variant("hero")
        self.balance_card = MetricCard("账户余额", "balance")
        self.balance_card.set_variant("compact")
        self.month_card = MetricCard("本月累计", "month")
        self.month_card.set_variant("compact")
        metrics_layout.addWidget(self.today_card, 3)

        compact_metrics = QHBoxLayout()
        compact_metrics.setContentsMargins(0, 0, 0, 0)
        compact_metrics.setSpacing(14)
        compact_metrics.addWidget(self.balance_card, 1)
        metric_divider = QFrame()
        metric_divider.setObjectName("divider")
        metric_divider.setFrameShape(QFrame.Shape.VLine)
        metric_divider.setFixedWidth(1)
        compact_metrics.addWidget(metric_divider)
        compact_metrics.addWidget(self.month_card, 1)
        metrics_layout.addLayout(compact_metrics, 2)
        top_layout.addWidget(self.metrics_container, 5)

        main_divider = QFrame()
        main_divider.setObjectName("divider")
        main_divider.setFrameShape(QFrame.Shape.VLine)
        main_divider.setFixedWidth(1)
        top_layout.addWidget(main_divider)

        self.trend = TrendCard()
        self.trend.setMinimumWidth(300)
        top_layout.addWidget(self.trend, 11)
        content.addWidget(self.top_section)

        self.activity_card = QFrame()
        self.activity_card.setObjectName("activitySection")
        self.activity_card.setFixedHeight(ACTIVITY_SECTION_HEIGHT)
        activity_layout = QVBoxLayout(self.activity_card)
        activity_layout.setContentsMargins(SECTION_HORIZONTAL_MARGIN, 0, SECTION_HORIZONTAL_MARGIN, 3)
        activity_layout.setSpacing(4)

        activity_divider = QFrame()
        activity_divider.setObjectName("divider")
        activity_divider.setFrameShape(QFrame.Shape.HLine)
        activity_divider.setFixedHeight(1)
        activity_layout.addWidget(activity_divider)

        activity_header = QHBoxLayout()
        activity_header.setContentsMargins(0, 0, 0, 0)
        activity_header.setSpacing(8)
        activity_title = QLabel("Token 活动")
        activity_title.setObjectName("sectionTitle")
        self.activity_mode_group = QButtonGroup(self)
        self.activity_mode_group.setExclusive(True)
        self.annual_activity_button = self._activity_mode_button("年度活动", True)
        self.minute_activity_button = self._activity_mode_button("今日分时", False)
        self.activity_mode_group.addButton(self.annual_activity_button)
        self.activity_mode_group.addButton(self.minute_activity_button)
        self.annual_activity_button.clicked.connect(lambda: self._set_activity_view("annual"))
        self.minute_activity_button.clicked.connect(lambda: self._set_activity_view("minute"))
        self.minute_previous_button = self._minute_date_button("‹", "前一天（仅缓存当天估算数据）")
        self.minute_date_label = QLabel("今天")
        self.minute_date_label.setObjectName("minuteDateLabel")
        self.minute_next_button = self._minute_date_button("›", "后一天不可选择")
        self.minute_previous_button.setEnabled(False)
        self.minute_next_button.setEnabled(False)
        self.minute_date_label.setToolTip("估算分时仅保存当天数据")
        self.minute_controls: list[QWidget] = [
            self.minute_previous_button,
            self.minute_date_label,
            self.minute_next_button,
        ]
        self.minute_estimate_label = QLabel("估算（按刷新间隔均摊）")
        self.minute_estimate_label.setObjectName("muted")
        self.minute_estimate_label.setToolTip("按两次成功刷新之间的累计 Token 差额均摊，非平台原始分钟明细")
        self.activity_summary = QLabel("暂无 Token 活动")
        self.activity_summary.setObjectName("muted")
        activity_header.addWidget(activity_title)
        activity_header.addWidget(self.annual_activity_button)
        activity_header.addWidget(self.minute_activity_button)
        for control in self.minute_controls:
            activity_header.addWidget(control)
            control.hide()
        activity_header.addWidget(self.minute_estimate_label)
        self.minute_estimate_label.hide()
        activity_header.addStretch(1)
        self.minute_legend_buttons: dict[str, QToolButton] = {}
        legend_text = {
            "PROMPT_CACHE_HIT_TOKEN": "命中缓存",
            "PROMPT_CACHE_MISS_TOKEN": "未命中",
            "RESPONSE_TOKEN": "输出",
        }
        for token_type, label in MinuteUsageChart.SERIES:
            button = QToolButton()
            button.setObjectName("minuteLegendButton")
            button.setText(legend_text[token_type])
            button.setCheckable(True)
            button.setChecked(True)
            button.setToolTip(f"显示/隐藏{label}（不改变原始估算数据）")
            button.clicked.connect(
                lambda checked, value=token_type: self.minute_chart.set_series_visible(value, checked)
            )
            self.minute_legend_buttons[token_type] = button
            activity_header.addWidget(button)
            button.hide()
        activity_header.addWidget(self.activity_summary)
        activity_layout.addLayout(activity_header)

        self.activity_scroll = QScrollArea()
        self.activity_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.activity_scroll.setWidgetResizable(True)
        self.activity_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.activity_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Do not style the viewport locally: Qt cascades such rules into the
        # heatmap tooltip. The application palette supplies the themed surface.
        self.activity = TokenActivityHeatmap()
        self._fit_activity_heatmap()
        self.activity_scroll.setWidget(self.activity)
        self.activity_scroll.setFixedHeight(self.activity.height())
        self.minute_chart = MinuteUsageChart()
        self.minute_chart.setFixedHeight(self.activity_scroll.height())
        self.activity_stack = QStackedWidget()
        self.activity_stack.setObjectName("activityStack")
        self.activity_stack.addWidget(self.activity_scroll)
        self.activity_stack.addWidget(self.minute_chart)
        activity_layout.addWidget(self.activity_stack)
        content.addWidget(self.activity_card)
        self.middle_section = self.activity_card

        self.statistics = StatisticsCard()
        self.statistics.setFixedHeight(STATISTICS_SECTION_HEIGHT)
        content.addWidget(self.statistics)
        self.bottom_section = self.statistics

        footer_widget = QWidget()
        footer_widget.setObjectName("statusBar")
        footer_widget.setFixedHeight(STATUS_SECTION_HEIGHT)
        footer = QHBoxLayout(footer_widget)
        footer.setContentsMargins(SECTION_HORIZONTAL_MARGIN, 0, SECTION_HORIZONTAL_MARGIN, 0)
        footer.setSpacing(8)
        self.status_dot = StatusDot()
        self.status_text = QLabel("等待连接")
        self.status_text.setObjectName("statusText")
        self.updated_text = QLabel()
        self.updated_text.setObjectName("statusText")
        footer.addWidget(self.status_dot)
        footer.addWidget(self.status_text)
        footer.addStretch(1)
        footer.addWidget(self.updated_text)
        content.addWidget(footer_widget)
        root.addWidget(body, 1)

        configured_mode = str(config_manager.get("UI_THEME", "dark"))
        self.set_theme_mode(configured_mode, current_theme().name)
        try:
            theme_controller().changed.connect(self._on_theme_changed)
        except RuntimeError:
            # Preserve standalone construction compatibility for callers that do
            # not own application startup; the desktop app configures this first.
            pass
        self._refresh_icons()
        self._set_activity_view("annual")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "activity"):
            self._fit_activity_heatmap()

    def _fit_activity_heatmap(self) -> None:
        # At the supported 640 px minimum, the full 53-week calendar must stay
        # visible without a scrollbar stealing vertical room from the last row.
        compact = self.width() < 775
        self.activity.CELL = 9 if compact else 11
        self.activity.MIN_HORIZONTAL_GAP = 1 if compact else 2
        required_width = (
            self.activity.LEFT
            + self.activity.period.week_count
            * (self.activity.CELL + self.activity.MIN_HORIZONTAL_GAP)
            + 12
        )
        self.activity.setMinimumWidth(required_width)
        self.activity.update()

    def _activity_mode_button(self, text: str, checked: bool) -> QToolButton:
        button = QToolButton()
        button.setObjectName("activityModeButton")
        button.setText(text)
        button.setCheckable(True)
        button.setChecked(checked)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        return button

    def _minute_date_button(self, text: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("minuteDateButton")
        button.setText(text)
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setFixedSize(20, 22)
        return button

    def _set_activity_view(self, view: str) -> None:
        minute_view = view == "minute"
        self.activity_stack.setCurrentIndex(1 if minute_view else 0)
        self.annual_activity_button.setChecked(not minute_view)
        self.minute_activity_button.setChecked(minute_view)
        self.activity_summary.setVisible(not minute_view)
        for control in self.minute_controls:
            control.setVisible(minute_view)
        self.minute_estimate_label.setVisible(minute_view)
        for button in self.minute_legend_buttons.values():
            button.setVisible(minute_view)
        self._refresh_minute_control_colors()

    def _refresh_minute_control_colors(self) -> None:
        if not hasattr(self, "minute_chart"):
            return
        for token_type, button in self.minute_legend_buttons.items():
            color = self.minute_chart.legend_color(token_type).name()
            button.setStyleSheet(f"color: {color};")

    def _theme_button(self, icon_name: str, mode: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setObjectName("themeButton")
        button.setProperty("themeValue", mode)
        button.setCheckable(True)
        button.setAutoRaise(True)
        button.setFixedSize(24, 24)
        button.setIconSize(QSize(14, 14))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.clicked.connect(lambda _checked=False, value=mode: self._request_theme(value))
        button._theme_icon_name = icon_name
        return button

    def _tool_button(
        self,
        name: str,
        standard: QStyle.StandardPixmap,
        tooltip: str,
        role: str = "",
    ) -> QToolButton:
        button = QToolButton()
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setAccessibleName(tooltip)
        button.setObjectName("panelToolButton")
        if role:
            button.setProperty("role", role)
        button.setFixedSize(32, 32)
        button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._button_specs.append((button, name, standard, role))
        return button

    def _request_theme(self, mode: str) -> None:
        self.set_theme_mode(mode, mode)
        self.theme_requested.emit(mode)

    def set_theme_mode(self, mode: str, resolved: str | None = None) -> None:
        """Synchronize the header selector with the configured and resolved mode."""
        normalized_mode = mode if mode in {"system", "light", "dark"} else "dark"
        normalized_resolved = resolved if resolved in {"light", "dark"} else current_theme().name
        if normalized_resolved not in {"light", "dark"}:
            normalized_resolved = "dark"
        self._theme_mode = normalized_mode
        self._resolved_theme = normalized_resolved
        self._theme_feedback_message = ""

        is_light = normalized_resolved == "light"
        self.light_theme_button.setChecked(is_light)
        self.dark_theme_button.setChecked(not is_light)
        for button, selected in (
            (self.light_theme_button, is_light),
            (self.dark_theme_button, not is_light),
        ):
            button.setProperty("selected", selected)
            button.style().unpolish(button)
            button.style().polish(button)

        if normalized_mode == "system":
            theme_name = "浅色" if is_light else "深色"
            segment_tip = f"跟随系统（当前为{theme_name}主题）"
            self.light_theme_button.setToolTip(f"{segment_tip}；点击固定为浅色主题")
            self.dark_theme_button.setToolTip(f"{segment_tip}；点击固定为深色主题")
        else:
            segment_tip = "浅色主题" if is_light else "深色主题"
            self.light_theme_button.setToolTip("浅色主题（当前）" if is_light else "切换到浅色主题")
            self.dark_theme_button.setToolTip("深色主题（当前）" if not is_light else "切换到深色主题")
        self.theme_segment.setToolTip(segment_tip)
        self.theme_segment.setAccessibleDescription(segment_tip)

    def set_theme_feedback(self, message: str, tone: str = "danger") -> None:
        """Expose persistence feedback without replacing provider connection status."""
        self._theme_feedback_message = message.strip()
        self.theme_segment.setProperty("feedbackTone", tone)
        if self._theme_feedback_message:
            self.theme_segment.setToolTip(self._theme_feedback_message)
            self.light_theme_button.setToolTip(self._theme_feedback_message)
            self.dark_theme_button.setToolTip(self._theme_feedback_message)

    def _on_theme_changed(self, mode: str, resolved: str) -> None:
        self.set_theme_mode(mode, resolved)
        self.status_dot.refresh_theme()
        self.minute_chart.refresh_theme()
        self._refresh_minute_control_colors()
        self._refresh_icons()
        self.update()

    def _refresh_icons(self) -> None:
        tokens = current_theme()
        for button, name, standard, role in self._button_specs:
            active_color = tokens.danger if role == "close" else tokens.accent_hover
            icon = fluent_icon(name, active_color=active_color)
            button.setIcon(icon if not icon.isNull() else self.style().standardIcon(standard))
        for button in (self.light_theme_button, self.dark_theme_button):
            icon = fluent_icon(button._theme_icon_name, size=14, active_color=tokens.text)
            button.setIcon(icon)

    def set_refreshing(self, refreshing: bool) -> None:
        self.refresh_button.setEnabled(not refreshing)
        self.refresh_button.setToolTip("刷新中" if refreshing else "刷新")

    def update_data(self, data: TokenData, loading: bool = False) -> None:
        money = lambda value: "--" if loading else format_money(value)
        tokens = lambda value: "--" if loading or value is None else compact_tokens(int(value))
        if data.per_provider:
            provider_name = data.per_provider[0].provider_name
            self._provider_label.setText(f" · {provider_name}")

        self.today_card.set_title("今日使用金额")
        self.balance_card.set_title("账户余额")
        self.month_card.set_title("本月累计")
        self.today_card.set_values(money(data.today_cost_cny), tokens(data.today_tokens), "")
        self.balance_card.set_values(
            money(data.balance_cny),
            f"约 {tokens(data.balance_tokens)}" if data.balance_tokens else "账户可用余额",
            "",
        )
        self.month_card.set_values(
            money(data.monthly_cost_cny),
            tokens(data.monthly_usage_tokens),
            "",
        )

        self.activity.set_activity(data.daily_usage)
        source_days = [day for day in self.activity.days if day.has_source_data]
        total = sum(day.token_count for day in source_days)
        if not source_days:
            summary = "暂无 Token 活动"
        else:
            first = min(day.date for day in source_days)
            if first > self.activity.period.start:
                summary = f"数据始于 {first.isoformat()} · 共 {compact_tokens(total)}"
            else:
                summary = f"过去 12 个月共使用 {compact_tokens(total)}"
        self.activity_summary.setText(summary)

        minute_date = f"今天 {data.minute_usage_date[5:]}" if len(data.minute_usage_date) == 10 else "今天"
        minute_hint = {
            "failed": "（刷新失败）",
            "storage_error": "（缓存失败）",
            "adjusted": "（平台已校正）",
        }.get(data.minute_usage_status, "")
        self.minute_date_label.setText(f"{minute_date}{minute_hint}")
        self.minute_chart.set_rows(
            data.minute_usage,
            data.minute_usage_status,
            loading=loading,
        )
        for button in self.minute_legend_buttons.values():
            button.setEnabled(data.minute_usage_status != "unavailable")
        self._refresh_minute_control_colors()

        self.trend.set_rows(data.daily_usage)
        self.statistics.set_data(data)
        status, _color = self.status_summary(data, loading)
        self.status_text.setText(status)
        self.status_dot.set_role(self.status_role(data, loading))
        self.updated_text.setText(self.relative_update_time(data))

    @staticmethod
    def status_role(data: TokenData, loading: bool = False) -> str:
        if loading:
            return "accent"
        codes = {error.code for error in data.errors}
        if "NOT_CONFIGURED" in codes or data.status == "not_configured":
            return "warning"
        if codes & {"AUTH_EXPIRED", "NETWORK_TIMEOUT", "NETWORK_ERROR", "SERVER_ERROR"}:
            return "danger"
        if data.status == "partial":
            return "warning"
        if data.status == "error":
            return "danger"
        if data.status == "ok":
            return "success"
        return "accent"

    @staticmethod
    def status_summary(data: TokenData, loading: bool = False) -> tuple[str, str]:
        theme = current_theme()
        if loading:
            return "正在更新", theme.accent
        codes = {error.code for error in data.errors}
        if "NOT_CONFIGURED" in codes:
            return "尚未配置 Token/Cookie，请前往设置", theme.warning
        if "AUTH_EXPIRED" in codes:
            return "认证信息已失效，请重新配置", theme.danger
        if codes & {"NETWORK_TIMEOUT", "NETWORK_ERROR"}:
            return "网络连接失败", theme.danger
        if "SERVER_ERROR" in codes:
            return "API 服务异常", theme.danger
        if data.status == "not_configured":
            return "尚未配置凭据，请前往设置", theme.warning
        if data.status == "ok" and data.today_tokens is None:
            return "连接正常，平台未提供按日明细", theme.success
        if data.status == "ok" and not any(day.get("tokens", 0) for day in data.daily_usage):
            return "连接正常，暂无 Token 活动", theme.success
        return {
            "ok": ("连接正常", theme.success),
            "partial": ("部分数据异常，显示可用数据", theme.warning),
            "error": ("连接异常", theme.danger),
        }.get(data.status, ("等待连接", theme.accent))

    @staticmethod
    def relative_update_time(data: TokenData) -> str:
        if not data.last_success_at:
            return "等待首次更新"
        seconds = max(0, int((datetime.now() - data.last_success_at).total_seconds()))
        if seconds < 60:
            return "数据更新于刚刚"
        minutes = seconds // 60
        if minutes < 60:
            return f"数据更新于 {minutes} 分钟前"
        return f"数据更新于 {minutes // 60} 小时前"
