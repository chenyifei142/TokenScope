"""Qt update controller and dialogs."""

from __future__ import annotations

import random
import threading
from typing import Callable

from PySide6.QtCore import QObject, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import config_manager
from app_identity import APP_VERSION
from app_update import (
    CheckResult,
    DownloadBundle,
    DownloadCancelled,
    GitHubReleaseClient,
    ReleaseInfo,
    format_bytes,
    format_speed,
    is_packaged_windows_executable,
    launch_installer,
    mark_skipped_version,
    release_display_time,
    skipped_version,
    status_summary,
)
from app_identity import MAIN_EXECUTABLE_NAME


class UpdateCheckWorker(QThread):
    finished_with_result = Signal(object, object)

    def __init__(self, channel: str, use_cache: bool):
        super().__init__()
        self._channel = channel
        self._use_cache = use_cache

    def run(self) -> None:
        try:
            result = GitHubReleaseClient().check_for_updates(
                APP_VERSION,
                self._channel,
                use_cache=self._use_cache,
            )
        except Exception as exc:
            self.finished_with_result.emit(None, exc)
            return
        self.finished_with_result.emit(result, None)


class UpdateDownloadWorker(QThread):
    progress_changed = Signal(object)
    finished_with_bundle = Signal(object, object)

    def __init__(self, release: ReleaseInfo):
        super().__init__()
        self._release = release
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            bundle = GitHubReleaseClient().download_bundle(
                self._release,
                progress=self.progress_changed.emit,
                cancel_requested=self._cancel_event.is_set,
            )
        except Exception as exc:
            self.finished_with_bundle.emit(None, exc)
            return
        self.finished_with_bundle.emit(bundle, None)


class UpdatePromptDialog(QDialog):
    ACTION_LATER = "later"
    ACTION_SKIP = "skip"
    ACTION_DOWNLOAD = "download"

    def __init__(self, release: ReleaseInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self._action = self.ACTION_LATER
        self.setWindowTitle("软件更新")
        self.setModal(True)
        self.resize(620, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        title = QLabel(f"发现新版本 v{release.version}")
        title.setStyleSheet("font-size: 18px; font-weight: 700;")
        root.addWidget(title)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        form.addRow("发布时间", QLabel(release_display_time(release.published_at)))
        form.addRow("文件大小", QLabel(format_bytes(release.setup_asset.size)))
        form.addRow("更新通道", QLabel("预发布版" if release.is_prerelease else "正式版"))
        root.addLayout(form)

        notes_label = QLabel("更新说明")
        notes_label.setStyleSheet("font-weight: 600;")
        root.addWidget(notes_label)

        notes = QPlainTextEdit()
        notes.setReadOnly(True)
        notes.setPlainText(release.body or "该版本未提供更新说明。")
        root.addWidget(notes, 1)

        buttons = QDialogButtonBox()
        later_button = buttons.addButton("稍后提醒", QDialogButtonBox.ButtonRole.RejectRole)
        skip_button = buttons.addButton("跳过此版本", QDialogButtonBox.ButtonRole.DestructiveRole)
        download_button = buttons.addButton("下载并更新", QDialogButtonBox.ButtonRole.AcceptRole)
        later_button.clicked.connect(self._choose_later)
        skip_button.clicked.connect(self._choose_skip)
        download_button.clicked.connect(self._choose_download)
        root.addWidget(buttons)

    @property
    def action(self) -> str:
        return self._action

    def _choose_later(self) -> None:
        self._action = self.ACTION_LATER
        self.reject()

    def _choose_skip(self) -> None:
        self._action = self.ACTION_SKIP
        self.accept()

    def _choose_download(self) -> None:
        self._action = self.ACTION_DOWNLOAD
        self.accept()


class DownloadProgressDialog(QDialog):
    cancelled = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("下载更新")
        self.setModal(True)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        self.status_label = QLabel("正在准备下载…")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)

        self.detail_label = QLabel("0 / 0")
        self.detail_label.setProperty("tone", "muted")
        root.addWidget(self.detail_label)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        actions.addWidget(self.cancel_button)
        root.addLayout(actions)

    def update_progress(self, payload: dict[str, object]) -> None:
        total = int(payload.get("total") or 0)
        downloaded = int(payload.get("downloaded") or 0)
        current = int(payload.get("current") or 0)
        current_total = int(payload.get("current_total") or 0)
        speed = float(payload.get("speed") or 0.0)
        stage = str(payload.get("stage") or "")
        reused = bool(payload.get("reused"))
        percentage = 0 if total <= 0 else min(100, round(downloaded * 100 / total))
        self.progress_bar.setValue(percentage)
        if reused:
            self.status_label.setText(f"已复用缓存文件：{stage}")
        else:
            self.status_label.setText(f"正在下载：{stage}")
        self.detail_label.setText(
            f"{format_bytes(downloaded)} / {format_bytes(total)}"
            f"  当前文件：{format_bytes(current)} / {format_bytes(current_total)}"
            f"  速度：{format_speed(speed)}"
        )


class AppUpdateController(QObject):
    status_changed = Signal(str)
    latest_release_changed = Signal(object)

    def __init__(self, owner: QWidget):
        super().__init__(owner)
        self._owner = owner
        self._check_worker: UpdateCheckWorker | None = None
        self._download_worker: UpdateDownloadWorker | None = None
        self._progress_dialog: DownloadProgressDialog | None = None
        self._latest_release: ReleaseInfo | None = None
        # 自动检查只在本次运行内去重；跨重启仍应再次提醒，避免用户只能手动点检查更新。
        self._prompted_versions_in_session: set[str] = set()
        self.status_changed.emit(self.status_text())
        self.reload_cached_release()

    def version_text(self) -> str:
        return f"v{APP_VERSION}"

    def status_text(self) -> str:
        if not is_packaged_windows_executable():
            return f"当前版本 v{APP_VERSION}，开发运行模式下不提供自更新"
        return status_summary(APP_VERSION)

    def latest_release(self) -> ReleaseInfo | None:
        return self._latest_release

    def reload_cached_release(self) -> None:
        state = config_manager.load_update_state()
        version = str(state.get("latest_version") or "").strip()
        self._latest_release = None
        if version:
            from app_update import _release_from_state  # local import to avoid a cycle during init

            self._latest_release = _release_from_state(state)
        self.latest_release_changed.emit(self._latest_release)
        self.status_changed.emit(self.status_text())

    def schedule_startup_check(self) -> None:
        if not is_packaged_windows_executable():
            return
        if not bool(config_manager.get("UPDATE_AUTO_CHECK_ENABLED", True)):
            return
        delay_ms = random.randint(5_000, 10_000)
        QTimer.singleShot(delay_ms, lambda: self.check_for_updates(manual=False))

    def skip_available_version(self, parent: QWidget | None = None) -> None:
        if not self._latest_release:
            QMessageBox.information(parent or self._owner, "软件更新", "当前没有可跳过的已知版本。")
            return
        mark_skipped_version(self._latest_release.version)
        self.status_changed.emit(self.status_text())
        QMessageBox.information(
            parent or self._owner,
            "软件更新",
            f"已跳过 v{self._latest_release.version}，后续自动检查不再重复提示。",
        )

    def check_for_updates(self, *, manual: bool, parent: QWidget | None = None) -> None:
        if self._check_worker and self._check_worker.isRunning():
            if manual:
                QMessageBox.information(parent or self._owner, "软件更新", "正在检查更新，请稍候。")
            return
        if not is_packaged_windows_executable():
            if manual:
                QMessageBox.information(
                    parent or self._owner,
                    "软件更新",
                    f"开发运行模式下不支持自更新，请使用打包后的 {MAIN_EXECUTABLE_NAME} 验证更新流程。",
                )
            return
        channel = str(config_manager.get("UPDATE_CHANNEL", "stable"))
        self.status_changed.emit("正在检查更新…")
        self._check_worker = UpdateCheckWorker(channel=channel, use_cache=not manual)
        self._check_worker.finished_with_result.connect(
            lambda result, error: self._finish_check(result, error, manual=manual, parent=parent)
        )
        self._check_worker.start()

    def _finish_check(
        self,
        result: CheckResult | None,
        error: Exception | None,
        *,
        manual: bool,
        parent: QWidget | None,
    ) -> None:
        self._check_worker = None
        if error is not None:
            self.reload_cached_release()
            if manual:
                QMessageBox.warning(parent or self._owner, "软件更新", str(error))
            return

        assert result is not None
        self._latest_release = result.latest_release
        self.latest_release_changed.emit(self._latest_release)
        self.status_changed.emit(self.status_text())
        if not result.update_available or not result.latest_release:
            if manual:
                QMessageBox.information(parent or self._owner, "软件更新", result.message)
            return
        if manual:
            self._prompt_for_release(result.latest_release, parent or self._owner)
            return

        version = result.latest_release.version
        if version == skipped_version() or version in self._prompted_versions_in_session:
            return
        self._prompted_versions_in_session.add(version)
        self._prompt_for_release(result.latest_release, parent or self._owner)

    def _prompt_for_release(self, release: ReleaseInfo, parent: QWidget) -> None:
        dialog = UpdatePromptDialog(release, parent)
        dialog.exec()
        if dialog.action == UpdatePromptDialog.ACTION_SKIP:
            mark_skipped_version(release.version)
            self.status_changed.emit(self.status_text())
            return
        if dialog.action == UpdatePromptDialog.ACTION_DOWNLOAD:
            self.download_release(release, parent)

    def download_release(self, release: ReleaseInfo, parent: QWidget | None = None) -> None:
        if self._download_worker and self._download_worker.isRunning():
            QMessageBox.information(parent or self._owner, "软件更新", "当前已有下载任务正在进行。")
            return
        self._progress_dialog = DownloadProgressDialog(parent or self._owner)
        self._download_worker = UpdateDownloadWorker(release)
        self._download_worker.progress_changed.connect(self._progress_dialog.update_progress)
        self._download_worker.finished_with_bundle.connect(
            lambda bundle, error: self._finish_download(bundle, error, parent or self._owner)
        )
        self._progress_dialog.cancelled.connect(self._download_worker.cancel)
        self._progress_dialog.show()
        self._download_worker.start()

    def _finish_download(
        self,
        bundle: DownloadBundle | None,
        error: Exception | None,
        parent: QWidget,
    ) -> None:
        if self._progress_dialog is not None:
            self._progress_dialog.close()
            self._progress_dialog.deleteLater()
            self._progress_dialog = None
        self._download_worker = None
        if error is not None:
            if isinstance(error, DownloadCancelled):
                self.status_changed.emit("已取消更新下载")
                return
            QMessageBox.warning(parent, "软件更新", str(error))
            self.status_changed.emit(self.status_text())
            return

        assert bundle is not None
        try:
            launch_installer(bundle)
        except Exception as exc:
            QMessageBox.warning(parent, "软件更新", str(exc))
            self.status_changed.emit(self.status_text())
            return
        self.status_changed.emit("更新器已启动，正在关闭当前程序…")
        self._owner.close()
