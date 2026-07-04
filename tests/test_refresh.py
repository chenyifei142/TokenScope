import os
import unittest
from pathlib import Path
from unittest.mock import Mock

os.environ["APPDATA"] = str(Path.cwd() / ".test-appdata")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from data.store import FetchError, TokenData
from PySide6.QtWidgets import QApplication
from ui.qt_panel import MainPanel
from ui.qt_widget import FloatingWidget

APP = QApplication.instance() or QApplication([])


def widget_stub():
    widget = FloatingWidget.__new__(FloatingWidget)
    widget._refresh_lock = __import__("threading").Lock()
    widget._refreshing = False
    widget._pending_refresh = False
    widget._request_id = 0
    widget._closed = False
    widget._data = TokenData()
    widget._apply_update = Mock()
    widget._thread_pool = Mock()
    return widget


class RefreshTests(unittest.TestCase):
    def test_repeated_refresh_runs_once_then_one_pending(self):
        widget = widget_stub()
        widget.refresh()
        widget.refresh()
        widget.refresh()
        self.assertEqual(widget._thread_pool.start.call_count, 1)
        self.assertTrue(widget._pending_refresh)

    def test_older_request_does_not_replace_newer_data(self):
        widget = widget_stub()
        current = TokenData(balance_cny=2)
        widget._data = current
        widget._refreshing = True
        widget._request_id = 2
        widget._finish_refresh(1, TokenData(balance_cny=1))
        self.assertIs(widget._data, current)

    def test_status_summary_distinguishes_configuration_and_request_errors(self):
        cases = (
            ("NOT_CONFIGURED", "尚未配置"),
            ("AUTH_EXPIRED", "认证信息已失效"),
            ("NETWORK_ERROR", "网络连接失败"),
            ("SERVER_ERROR", "API 服务异常"),
        )
        for code, expected in cases:
            data = TokenData(
                status="error", errors=[FetchError(code, "test", "failed")]
            )
            self.assertIn(expected, MainPanel.status_summary(data)[0])

    def test_status_summary_treats_successful_zero_usage_as_normal(self):
        data = TokenData(status="ok", daily_usage=[])
        self.assertIn("暂无 Token 活动", MainPanel.status_summary(data)[0])


if __name__ == "__main__":
    unittest.main()
