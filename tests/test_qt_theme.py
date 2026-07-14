import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMenu

from ui.qt_theme import (
    DARK_THEME,
    LIGHT_THEME,
    ThemeController,
    build_app_style,
    configure_theme,
    current_theme,
)


APP = QApplication.instance() or QApplication([])


def _relative_luminance(color: str) -> float:
    value = QColor(color)
    channels = (value.redF(), value.greenF(), value.blueF())

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_theme_tokens_meet_readability_and_focus_contrast():
    for tokens in (LIGHT_THEME, DARK_THEME):
        assert _contrast(tokens.text, tokens.surface) >= 4.5
        assert _contrast(tokens.subtext, tokens.surface) >= 4.5
        assert _contrast(tokens.muted, tokens.window) >= 4.5
        assert _contrast(tokens.accent, tokens.surface) >= 3.0
        assert _contrast(tokens.border, tokens.surface) >= 3.0
        assert _contrast(tokens.border_hover, tokens.surface) >= 3.0
        assert len(tokens.heat) == 6


def test_minute_tooltip_cost_uses_each_theme_accent():
    for tokens in (LIGHT_THEME, DARK_THEME):
        style = build_app_style(tokens)
        cost_rule = style.split("QLabel#minuteTooltipCost", 1)[1].split("}", 1)[0]
        assert f"color: {tokens.accent};" in cost_rule


def test_activity_selected_mode_uses_the_specified_blue_and_white_text():
    style = build_app_style(LIGHT_THEME)
    checked_rule = style.split("QToolButton#activityModeButton:checked", 1)[1].split("}", 1)[0]

    assert "color: #FFFFFF;" in checked_rule
    assert "background: #2076FA;" in checked_rule


def test_context_menu_palette_tracks_light_and_dark_theme():
    menu = QMenu()
    menu.addAction("显示/隐藏")
    try:
        for mode, tokens in (("light", LIGHT_THEME), ("dark", DARK_THEME)):
            configure_theme(APP, mode)
            menu.show()
            APP.processEvents()
            palette = menu.palette()
            assert palette.color(QPalette.ColorRole.Window) == QColor(tokens.surface)
            assert palette.color(QPalette.ColorRole.WindowText) == QColor(tokens.text)
            assert tokens.surface in APP.styleSheet()
    finally:
        menu.close()
        configure_theme(APP, "dark")


def test_existing_menu_switches_theme_without_reconstruction():
    controller = configure_theme(APP, "dark")
    menu = QMenu()
    menu.addAction("刷新")
    original_identity = id(menu)
    dark_color = menu.palette().color(QPalette.ColorRole.Window)

    controller.set_mode("light")
    APP.processEvents()

    assert id(menu) == original_identity
    assert current_theme() == LIGHT_THEME
    assert menu.palette().color(QPalette.ColorRole.Window) != dark_color
    assert LIGHT_THEME.window in build_app_style()
    menu.close()
    controller.set_mode("dark")


class _FakeSignal:
    def __init__(self) -> None:
        self.callback = None

    def connect(self, callback) -> None:
        self.callback = callback


class _FakeStyleHints:
    def __init__(self, scheme: Qt.ColorScheme) -> None:
        self.scheme = scheme
        self.colorSchemeChanged = _FakeSignal()
        self.forced_scheme = None

    def colorScheme(self) -> Qt.ColorScheme:
        return self.scheme

    def setColorScheme(self, scheme: Qt.ColorScheme) -> None:
        self.forced_scheme = scheme

    def unsetColorScheme(self) -> None:
        self.forced_scheme = None


class _FakeApplication:
    def __init__(self, scheme: Qt.ColorScheme) -> None:
        self.hints = _FakeStyleHints(scheme)
        self.palette = None
        self.style_sheet = ""

    def styleHints(self) -> _FakeStyleHints:
        return self.hints

    def setPalette(self, palette: QPalette) -> None:
        self.palette = palette

    def setStyleSheet(self, style_sheet: str) -> None:
        self.style_sheet = style_sheet


def test_system_mode_unknown_rules_and_live_switching():
    app = _FakeApplication(Qt.ColorScheme.Unknown)
    controller = ThemeController(app, "system")
    changes = []
    controller.changed.connect(lambda mode, resolved: changes.append((mode, resolved)))

    assert controller.mode == "system"
    assert controller.resolved == "dark"
    controller._system_scheme_changed(Qt.ColorScheme.Light)
    assert controller.resolved == "light"
    controller._system_scheme_changed(Qt.ColorScheme.Unknown)
    assert controller.resolved == "light"
    assert changes == [("system", "light")]


def test_explicit_mode_ignores_system_change_notifications():
    app = _FakeApplication(Qt.ColorScheme.Dark)
    controller = ThemeController(app, "dark")
    controller._system_scheme_changed(Qt.ColorScheme.Light)

    assert controller.mode == "dark"
    assert controller.resolved == "dark"
