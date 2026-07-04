"""Custom Token activity calendar heatmap."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ui.activity import (
    ActivityRange,
    TokenActivityDay,
    activity_levels,
    calendar_position,
    compact_tokens,
    normalize_activity,
)
from ui.qt_theme import (
    C_ACCENT_2,
    C_GLASS_BORDER,
    C_HEAT,
    C_LOW_BLUE,
    C_PALE_BLUE,
    C_SUBTEXT,
    C_SURFACE,
    C_TEXT,
    C_TIME,
)


class ActivityTooltip(QFrame):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("activityTooltip")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            f"QFrame#activityTooltip {{ background: {C_SURFACE}; border: 1px solid {C_GLASS_BORDER}; "
            f"border-radius: 9px; }} QLabel {{ color: {C_TEXT}; background: transparent; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(4)
        self._title = QLabel()
        self._title.setStyleSheet("font-weight: 700;")
        self._body = QLabel()
        self._body.setStyleSheet(f"color: {C_SUBTEXT};")
        layout.addWidget(self._title)
        layout.addWidget(self._body)
        self.hide()

    def show_day(self, day: TokenActivityDay, anchor: QPoint) -> None:
        self._title.setText(day.date.isoformat())
        lines = [f"Token 使用量：{compact_tokens(day.token_count)}"]
        if day.amount is not None:
            lines.append(f"使用金额：¥{day.amount:.4f}".rstrip("0").rstrip("."))
        if day.request_count is not None:
            lines.append(f"请求次数：{day.request_count:,}")
        self._body.setText("\n".join(lines))
        self.adjustSize()
        parent_rect = self.parentWidget().rect()
        x = anchor.x() + 12
        y = anchor.y() + 12
        if x + self.width() > parent_rect.right() - 8:
            x = anchor.x() - self.width() - 12
        if y + self.height() > parent_rect.bottom() - 8:
            y = anchor.y() - self.height() - 12
        self.move(max(8, x), max(8, y))
        self.show()
        self.raise_()


class TokenActivityHeatmap(QWidget):
    CELL = 11
    GAP = 4
    MIN_HORIZONTAL_GAP = 2
    LEFT = 28
    TOP = 28
    BOTTOM = 0

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._period, self._days = normalize_activity([])
        self._levels: dict[date, int] = {}
        self._hits: list[tuple[QRectF, TokenActivityDay]] = []
        self._hovered: date | None = None
        width = self.LEFT + self._period.week_count * (self.CELL + self.MIN_HORIZONTAL_GAP) + 12
        height = self.TOP + 7 * (self.CELL + self.GAP) + self.BOTTOM
        # 固定格子与月份区域的垂直尺寸；底部图例移除后不保留占位。
        self.setMinimumWidth(width)
        self.setFixedHeight(height)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self._tooltip = ActivityTooltip(self)

    @property
    def period(self) -> ActivityRange:
        return self._period

    @property
    def days(self) -> list[TokenActivityDay]:
        return self._days

    def set_activity(self, rows: list[dict[str, Any]], today: date | None = None) -> None:
        self._period, self._days = normalize_activity(rows, today)
        self._levels = activity_levels(self._days)
        width = self.LEFT + self._period.week_count * (self.CELL + self.MIN_HORIZONTAL_GAP) + 12
        self.setMinimumWidth(width)
        self.update()

    def mouseMoveEvent(self, event) -> None:
        point = event.position()
        for rect, day in self._hits:
            if rect.contains(point):
                if self._hovered != day.date:
                    self._hovered = day.date
                    self.update()
                self._tooltip.show_day(day, event.position().toPoint())
                return
        self._hovered = None
        self._tooltip.hide()
        self.update()

    def leaveEvent(self, event) -> None:
        self._hovered = None
        self._tooltip.hide()
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self._hits = []
        vertical_step = self.CELL + self.GAP
        # Horizontal spacing expands with the card so the year stays readable
        # without introducing a scrollbar at supported panel widths.
        horizontal_step = max(
            self.CELL + self.MIN_HORIZONTAL_GAP,
            (self.width() - self.LEFT - 12) // self._period.week_count,
        )

        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.setPen(QColor(C_TIME))
        for weekday, label in ((0, "一"), (2, "三"), (4, "五"), (6, "日")):
            y = self.TOP + weekday * vertical_step
            painter.drawText(QRectF(0, y - 1, self.LEFT - 7, self.CELL + 2), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, label)

        last_label_right = -100
        current = self._period.start.replace(day=1)
        if current < self._period.start:
            current = (current + timedelta(days=32)).replace(day=1)
        while current <= self._period.end:
            week, _weekday = calendar_position(current, self._period.grid_start)
            x = self.LEFT + week * horizontal_step
            label = f"{current.month}月"
            width = painter.fontMetrics().horizontalAdvance(label)
            if x > last_label_right + 8:
                painter.drawText(QRectF(x, 0, width + 5, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
                last_label_right = x + width
            current = (current + timedelta(days=32)).replace(day=1)

        for day in self._days:
            week, weekday = calendar_position(day.date, self._period.grid_start)
            rect = QRectF(
                self.LEFT + week * horizontal_step,
                self.TOP + weekday * vertical_step,
                self.CELL,
                self.CELL,
            )
            in_range = self._period.start <= day.date <= self._period.end
            if day.date > self._period.end:
                # Complete-week padding is not data; matching unused cells keeps
                # future dates present without introducing a black visual break.
                color = QColor(C_HEAT[0])
            elif not in_range:
                color = QColor(C_LOW_BLUE)
            else:
                color = QColor(C_HEAT[self._levels.get(day.date, 0)])
            painter.setBrush(color)
            if day.date == self._hovered:
                painter.setPen(QPen(QColor(C_PALE_BLUE), 1.5))
            elif day.date == self._period.end:
                painter.setPen(QPen(QColor(C_ACCENT_2), 1.2))
            else:
                painter.setPen(QPen(color.lighter(112), 0.7))
            painter.drawRoundedRect(rect, 2.5, 2.5)
            if day.date <= self._period.end:
                self._hits.append((rect, day))

        painter.end()
