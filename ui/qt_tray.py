"""Qt system tray integration."""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from ui.qt_theme import app_icon


class SystemTray(QSystemTrayIcon):
    def __init__(self, app):
        super().__init__(app_icon(64), app.widget)
        self.app = app
        self.setToolTip("TokenSpider - LLM 用量监控")
        menu = QMenu()
        visible = QAction("显示/隐藏", menu)
        visible.triggered.connect(app.widget.set_visible_from_tray)
        refresh = QAction("刷新", menu)
        refresh.triggered.connect(app.widget.refresh)
        settings = QAction("设置", menu)
        settings.triggered.connect(app.widget.open_settings)
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addActions((visible, refresh, settings))
        menu.addSeparator()
        menu.addAction(quit_action)
        self.setContextMenu(menu)
        self.activated.connect(self._activated)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.app.widget.set_visible_from_tray()

    def quit_app(self) -> None:
        self.hide()
        self.app.widget.close()

    def run(self) -> None:
        self.show()

    def stop(self) -> None:
        self.hide()
