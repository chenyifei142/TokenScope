"""Qt floating window coordinating the ball, panel, refresh, and settings."""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRunnable,
    QThreadPool,
    QTimer,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QAction, QColor, QGuiApplication, QPalette, QRegion
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMenu, QWidget

import config_manager
from data.store import TokenData
from ui.geometry import (
    clamp_window,
    compact_geometry,
    expanded_panel_geometry,
    monitor_work_area,
)
from ui.qt_ball import FloatingUsageBall
from ui.qt_panel import MainPanel, format_money
from ui.qt_settings import SettingsWindow


DEF_PANEL_W = 820
DEF_PANEL_H = 550
DEF_BALL_SIZE = 96


class FetchSignals(QObject):
    finished = Signal(int, object)


class FetchTask(QRunnable):
    def __init__(self, request_id: int):
        super().__init__()
        self.request_id = request_id
        self.signals = FetchSignals()

    @Slot()
    def run(self) -> None:
        self.signals.finished.emit(self.request_id, TokenData.fetch())


class FloatingWidget(QWidget):
    def __init__(self, tray_icon=None):
        super().__init__()
        self.tray = tray_icon
        self._expanded = False
        self._data = TokenData()
        self._refresh_lock = threading.Lock()
        self._refreshing = False
        self._pending_refresh = False
        self._request_id = 0
        self._closed = False
        self._transitioning = False
        self._expand_horizontal = "right"
        self._expand_vertical = "down"
        self._drag_origin = QPoint()
        self._window_origin = QPoint()
        self._drag_started = False
        self._drag_source = ""
        self._settings_window: SettingsWindow | None = None
        self._thread_pool = QThreadPool.globalInstance()

        self.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setObjectName("floatingRoot")
        # Windows may composite a native rectangular surface around a layered
        # frameless window, so keep both the Qt background and palette transparent.
        self.setAutoFillBackground(False)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        self.setPalette(palette)
        self.setStyleSheet(
            "QWidget#floatingRoot { background: transparent; border: 0; }"
        )

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self.ball = FloatingUsageBall(self._compact_size())
        self.panel = MainPanel()
        self.panel.hide()
        self._layout.addWidget(self.ball, 0, Qt.AlignmentFlag.AlignTop)
        self._connect_ui()

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._periodic_refresh)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._apply_update)
        self._clock_timer.start(30_000)
        self._show_compact_at_saved_position()
        self.refresh()

    def _connect_ui(self) -> None:
        self.ball.pressed.connect(lambda point: self._start_drag(point, "ball"))
        self.ball.dragged.connect(self._move_drag)
        self.ball.released.connect(self._end_drag)
        self.panel.header.pressed.connect(lambda point: self._start_drag(point, "header"))
        self.panel.header.dragged.connect(self._move_drag)
        self.panel.header.released.connect(self._end_drag)
        self.panel.settings_requested.connect(self.open_settings)
        self.panel.refresh_requested.connect(self.refresh)
        self.panel.close_requested.connect(self.collapse_panel)

    @staticmethod
    def _compact_size() -> int:
        configured = int(config_manager.get("WIDGET_COMPACT_SIZE", DEF_BALL_SIZE))
        return DEF_BALL_SIZE if configured < 96 else min(124, configured)

    @staticmethod
    def _expanded_size() -> tuple[int, int]:
        size = config_manager.get("WIDGET_EXPANDED_SIZE", (DEF_PANEL_W, DEF_PANEL_H))
        width = max(640, min(DEF_PANEL_W, int(size[0])))
        return width, DEF_PANEL_H

    def _show_compact_at_saved_position(self) -> None:
        size = self._compact_size()
        saved = config_manager.load_widget_position()
        screen = QGuiApplication.primaryScreen().availableGeometry()
        if saved:
            work = monitor_work_area(saved[0], saved[1], screen.width(), screen.height())
            x, y = clamp_window(saved[0], saved[1], size, size, work)
        else:
            x, y = screen.right() - size - 8, screen.top() + 90
        self.panel.hide()
        self.ball.show()
        self.setFixedSize(size, size)
        # Restrict the native compact window itself to the circle. This prevents
        # platform shadows or non-client backgrounds from exposing square corners.
        self.setMask(QRegion(0, 0, size, size, QRegion.RegionType.Ellipse))
        self.move(x, y)
        self.show()
        self._apply_native_window_shape(compact=True)

    def _apply_native_window_shape(self, compact: bool) -> None:
        if sys.platform != "win32" or QGuiApplication.platformName() != "windows":
            return

        hwnd = wintypes.HWND(int(self.winId()))
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
        user32.SetWindowRgn.restype = ctypes.c_int

        if compact:
            gdi32.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
            gdi32.CreateEllipticRgn.restype = wintypes.HANDLE
            region = gdi32.CreateEllipticRgn(0, 0, self.width() + 1, self.height() + 1)
            if not region:
                return
            # SetWindowRgn owns a successfully assigned region; only failed
            # regions remain ours to release.
            if not user32.SetWindowRgn(hwnd, region, True):
                gdi32.DeleteObject(region)
                return
        else:
            user32.SetWindowRgn(hwnd, None, True)

        # Qt's flags do not consistently suppress the Windows 11 non-client
        # border, so disable it on the native HWND too.
        try:
            dwmapi = ctypes.WinDLL("dwmapi")
            for attribute, value in (
                (2, 1),
                (33, 1),
                (34, 0xFFFFFFFE),
            ):
                native_value = wintypes.DWORD(value)
                dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(native_value),
                    ctypes.sizeof(native_value),
                )
        except OSError:
            # The elliptic region above remains sufficient on older Windows.
            pass

    def _arrange_expanded(self) -> None:
        while self._layout.count():
            self._layout.takeAt(0)
        # 展开态完全由面板替代悬浮球，避免重复入口并缩小窗口占用。
        self.ball.hide()
        self._layout.addWidget(self.panel, 1)

    def toggle(self) -> None:
        if self._transitioning:
            return
        if self._expanded:
            self.collapse_panel()
        else:
            self.expand_panel()

    def expand_panel(self) -> None:
        if self._expanded or self._transitioning:
            return
        self._transitioning = True
        size = self._compact_size()
        try:
            work = self._work_area()
            geometry = expanded_panel_geometry(
                (self.x(), self.y(), size, size), self._expanded_size(), work
            )
            x, y, width, height, horizontal, vertical = geometry
            self._expanded = True
            self._expand_horizontal = horizontal
            self._expand_vertical = vertical
            self.clearMask()
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
            self._arrange_expanded()
            self.panel.show()
            self.setFixedSize(width, height)
            self.move(x, y)
            self.show()
            self._apply_native_window_shape(compact=False)
            self.raise_()
            self.activateWindow()
            self.panel.setFocus(Qt.FocusReason.OtherFocusReason)
            self.panel.update_data(self._data, self._refreshing)
            self.refresh()
        finally:
            self._transitioning = False
        self._reschedule_refresh()

    def collapse_panel(self) -> None:
        if not self._expanded or self._transitioning:
            return
        self._transitioning = True
        try:
            size = self._compact_size()
            work = self._work_area()
            x, y = compact_geometry(
                (self.x(), self.y(), self.width(), self.height()),
                size,
                self._expand_horizontal,
                self._expand_vertical,
                work,
            )
            self._expanded = False
            self.panel.hide()
            self.setFixedSize(size, size)
            while self._layout.count():
                self._layout.takeAt(0)
            self._layout.addWidget(self.ball, 0, Qt.AlignmentFlag.AlignTop)
            self.ball.show()
            self.move(x, y)
            config_manager.save_widget_position(x, y)
            # Compact mode remains clickable but cannot take keyboard focus away
            # from the application the user is currently working in.
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
            self.setMask(QRegion(0, 0, size, size, QRegion.RegionType.Ellipse))
            self.show()
            self._apply_native_window_shape(compact=True)
            self.raise_()
        finally:
            self._transitioning = False
        self._reschedule_refresh()

    def event(self, event) -> bool:
        if (
            event.type() == QEvent.Type.WindowDeactivate
            and self._expanded
            and not self._transitioning
        ):
            # Defer until Qt has finished activating a possible child dialog.
            # This distinguishes a real outside click from opening Settings.
            QTimer.singleShot(0, self._collapse_after_deactivation)
        return super().event(event)

    def _collapse_after_deactivation(self) -> None:
        if (
            self._expanded
            and not self._transitioning
            and not self._drag_started
            and not self._has_settings_child()
            and not self.isActiveWindow()
        ):
            self.collapse_panel()

    def _has_settings_child(self) -> bool:
        return bool(self._settings_window and self._settings_window.isVisible())

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._expanded:
            if self._has_settings_child():
                self._settings_window.reject()
            else:
                self.collapse_panel()
            event.accept()
            return
        super().keyPressEvent(event)

    def _start_drag(self, point: QPoint, source: str) -> None:
        self._drag_origin = point
        self._window_origin = self.pos()
        self._drag_started = False
        self._drag_source = source

    def _move_drag(self, point: QPoint) -> None:
        delta = point - self._drag_origin
        if not self._drag_started and delta.manhattanLength() < 5:
            return
        self._drag_started = True
        self.move(self._window_origin + delta)

    def _end_drag(self, _point: QPoint) -> None:
        if self._drag_started:
            self._clamp_to_work_area()
        elif self._drag_source == "ball":
            self.toggle()
        self._drag_started = False
        self._drag_source = ""

    def _work_area(self):
        center = self.frameGeometry().center()
        screen = QGuiApplication.screenAt(center) or QGuiApplication.primaryScreen()
        available = screen.availableGeometry()
        return monitor_work_area(
            center.x(), center.y(), available.width(), available.height()
        )

    def _clamp_to_work_area(self) -> None:
        work = self._work_area()
        if self._expanded:
            x, y = clamp_window(self.x(), self.y(), self.width(), self.height(), work)
        else:
            size = self._compact_size()
            # 自由拖拽仍需限制在工作区内，避免悬浮球被拖出屏幕后无法找回。
            x, y = clamp_window(self.x(), self.y(), size, size, work)
            config_manager.save_widget_position(x, y)
        self.move(x, y)

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        toggle = QAction("展开/收起", menu)
        toggle.triggered.connect(self.toggle)
        refresh = QAction("刷新", menu)
        refresh.triggered.connect(self.refresh)
        settings = QAction("设置", menu)
        settings.triggered.connect(self.open_settings)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.close)
        menu.addActions((toggle, refresh, settings))
        menu.addSeparator()
        menu.addAction(quit_action)
        menu.exec(event.globalPos())

    def open_settings(self) -> None:
        if self._settings_window and self._settings_window.isVisible():
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        # Reuse the same dialog so repeated opens do not duplicate signal
        # connections or leave hidden child windows behind.
        if self._settings_window is None:
            self._settings_window = SettingsWindow(self, on_saved=self._on_config_saved)
        self._settings_window.show()
        self._settings_window.raise_()
        self._settings_window.activateWindow()

    def _on_config_saved(self) -> None:
        config_manager.load_config()
        self._reschedule_refresh()
        self.refresh()

    def refresh(self) -> None:
        with self._refresh_lock:
            if self._closed:
                return
            if self._refreshing:
                self._pending_refresh = True
                return
            self._refreshing = True
            self._request_id += 1
            request_id = self._request_id
        self._apply_update()
        task = FetchTask(request_id)
        task.signals.finished.connect(self._finish_refresh)
        self._thread_pool.start(task)

    @Slot(int, object)
    def _finish_refresh(self, request_id: int, result: TokenData) -> None:
        with self._refresh_lock:
            if self._closed:
                return
            if request_id == self._request_id:
                self._data = result
            self._refreshing = False
            pending = self._pending_refresh
            self._pending_refresh = False
        self._apply_update()
        if pending:
            QTimer.singleShot(0, self.refresh)

    def _apply_update(self) -> None:
        loading = self._refreshing and self._data.last_success_at is None
        self.ball.set_values(
            "--" if loading else format_money(self._data.today_cost_cny),
            "--" if loading else format_money(self._data.balance_cny),
        )
        self.panel.set_refreshing(self._refreshing)
        if self._expanded:
            self.panel.update_data(self._data, loading)

    def _periodic_refresh(self) -> None:
        self.refresh()
        self._reschedule_refresh()

    def _reschedule_refresh(self) -> None:
        configured = int(config_manager.get("REFRESH_INTERVAL", 60_000))
        interval = configured if self._expanded else max(configured, 300_000)
        self._refresh_timer.start(interval)

    def set_visible_from_tray(self) -> None:
        self.setVisible(not self.isVisible())
        if self.isVisible():
            self.raise_()
            if self._expanded:
                self.activateWindow()

    def closeEvent(self, event) -> None:
        if self._expanded:
            x, y = compact_geometry(
                (self.x(), self.y(), self.width(), self.height()),
                self._compact_size(),
                self._expand_horizontal,
                self._expand_vertical,
                self._work_area(),
            )
        else:
            x, y = self.x(), self.y()
        config_manager.save_widget_position(x, y)
        self._closed = True
        self._refresh_timer.stop()
        self._clock_timer.stop()
        event.accept()
        QApplication.instance().quit()
