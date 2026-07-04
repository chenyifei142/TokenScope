"""PySide6 settings dialog backed by the existing configuration store."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

import config_manager
from data.store import TokenData
from ui.qt_theme import C_GREEN, C_RED, C_SUBTEXT


class ConnectionWorker(QThread):
    finished_with_data = Signal(object)

    def run(self) -> None:
        self.finished_with_data.emit(TokenData.fetch())


class SettingsWindow(QDialog):
    def __init__(self, parent=None, on_saved: Callable[[], None] | None = None):
        super().__init__(parent)
        self.setWindowTitle("TokenSpider 设置")
        self.setModal(False)
        self.setMinimumWidth(610)
        self.setMaximumWidth(680)
        self.on_saved = on_saved
        self._worker: ConnectionWorker | None = None
        self._secrets: dict[str, QLineEdit] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 22)
        root.setSpacing(14)
        title = QLabel("运行配置")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        description = QLabel(
            f"普通配置保存在 {config_manager.CONFIG_PATH}\n"
            "API Key、Token 和 Cookie 保存在 Windows 凭据管理器"
        )
        description.setStyleSheet(f"color: {C_SUBTEXT};")
        description.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(description)

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)
        self.api_key = self._secret_field("DEEPSEEK_API_KEY")
        self.auth = self._secret_field("DEEPSEEK_AUTH")
        self.cookie = self._secret_field("DEEPSEEK_COOKIE")
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("https://platform.deepseek.com")
        self.refresh_seconds = QSpinBox()
        self.refresh_seconds.setRange(5, 3600)
        self.refresh_seconds.setSuffix(" 秒")
        form.addRow("官方 API Key（可选）", self._with_reveal(self.api_key))
        form.addRow("Bearer Token", self._with_reveal(self.auth))
        form.addRow("Cookie", self._with_reveal(self.cookie))
        form.addRow("API 地址", self.base_url)
        form.addRow("自动刷新间隔", self.refresh_seconds)
        root.addLayout(form)

        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        root.addWidget(self.feedback)

        actions = QHBoxLayout()
        self.test_button = QPushButton("测试连接")
        self.test_button.clicked.connect(self._test_connection)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        save = QPushButton("保存并生效")
        save.setObjectName("primaryButton")
        save.clicked.connect(self._save)
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        actions.addWidget(cancel)
        actions.addWidget(save)
        root.addLayout(actions)
        self._load_values()

    def _secret_field(self, key: str) -> QLineEdit:
        field = QLineEdit()
        field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setPlaceholderText("未配置")
        self._secrets[key] = field
        return field

    @staticmethod
    def _with_reveal(field: QLineEdit):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        reveal = QPushButton("显示")
        reveal.setFixedWidth(66)

        def toggle() -> None:
            hidden = field.echoMode() == QLineEdit.EchoMode.Password
            field.setEchoMode(QLineEdit.EchoMode.Normal if hidden else QLineEdit.EchoMode.Password)
            reveal.setText("隐藏" if hidden else "显示")

        reveal.clicked.connect(toggle)
        row.addWidget(field, 1)
        row.addWidget(reveal)
        return row

    def _load_values(self) -> None:
        values = config_manager.load_config()
        self.api_key.setText(str(values.get("DEEPSEEK_API_KEY", "")))
        self.auth.setText(str(values.get("DEEPSEEK_AUTH", "")))
        self.cookie.setText(str(values.get("DEEPSEEK_COOKIE", "")))
        self.base_url.setText(str(values.get("DEEPSEEK_BASE", "")))
        self.refresh_seconds.setValue(max(5, int(values.get("REFRESH_INTERVAL", 60_000)) // 1000))

    def _values(self) -> dict:
        return {
            "DEEPSEEK_API_KEY": self.api_key.text().strip(),
            "DEEPSEEK_AUTH": self.auth.text().strip(),
            "DEEPSEEK_COOKIE": self.cookie.text().strip(),
            "DEEPSEEK_BASE": self.base_url.text().strip(),
            "REFRESH_INTERVAL": self.refresh_seconds.value() * 1000,
        }

    def _save(self) -> None:
        values = self._values()
        if not config_manager.is_official_base_url(values["DEEPSEEK_BASE"]):
            result = QMessageBox.question(
                self,
                "非官方 API 地址",
                "Token 和 Cookie 将发送到自定义服务器，确认继续吗？",
            )
            if result != QMessageBox.StandardButton.Yes:
                return
        try:
            config_manager.save_config(values)
        except Exception as exc:
            self.feedback.setStyleSheet(f"color: {C_RED};")
            self.feedback.setText(f"保存失败，配置已回滚：{exc}")
            return
        self.feedback.setStyleSheet(f"color: {C_GREEN};")
        self.feedback.setText("配置已保存并即时生效，正在重新获取数据。")
        if self.on_saved:
            self.on_saved()

    def _test_connection(self) -> None:
        try:
            config_manager.validate_config(self._values())
        except Exception as exc:
            self.feedback.setStyleSheet(f"color: {C_RED};")
            self.feedback.setText(f"请先修正配置：{exc}")
            return
        self.test_button.setEnabled(False)
        self.test_button.setText("测试中…")
        self.feedback.setStyleSheet(f"color: {C_SUBTEXT};")
        self.feedback.setText("正在使用当前已保存的凭据测试连接…")
        self._worker = ConnectionWorker(self)
        self._worker.finished_with_data.connect(self._connection_result)
        self._worker.start()

    def _connection_result(self, data: TokenData) -> None:
        self.test_button.setEnabled(True)
        self.test_button.setText("测试连接")
        if data.status in {"ok", "partial"}:
            self.feedback.setStyleSheet(f"color: {C_GREEN};")
            self.feedback.setText("连接成功。" if data.status == "ok" else "连接成功，但部分数据暂不可用。")
        else:
            message = data.errors[0].message if data.errors else "连接失败"
            self.feedback.setStyleSheet(f"color: {C_RED};")
            self.feedback.setText(message)
        self._worker = None
