import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMenu

from ui.qt_theme import APP_STYLE, C_SURFACE, C_TEXT


APP = QApplication.instance() or QApplication([])
APP.setStyleSheet(APP_STYLE)


def test_context_menu_has_explicit_readable_colors():
    menu = QMenu()
    menu.addAction("显示/隐藏")
    menu.show()
    APP.processEvents()

    assert menu.palette().color(QPalette.ColorRole.Window) == QColor(C_SURFACE)
    assert menu.palette().color(QPalette.ColorRole.WindowText) == QColor(C_TEXT)
    menu.close()
