"""Separate general and advanced configuration surface."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .localized_dialogs import localize_dialog_buttons


class SettingsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.setModal(True)
        self.resize(520, 360)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._general_tab(), "一般設定")
        self.tabs.addTab(self._advanced_tab(), "進階設定")
        layout.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        localize_dialog_buttons(buttons)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("文件設定")
        form = QFormLayout(group)
        form.addRow("目前輸入檔：", QLabel("將由目前開啟的月份文件同步"))
        form.addRow("覆寫既有結果：", QLabel("後續接入執行流程時提供"))
        layout.addWidget(group)
        notice = QLabel(
            "第一階段只建立設定畫面結構；設定資料將在後續提交接上 config draft。"
        )
        notice.setObjectName("mutedText")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addStretch(1)
        return page

    def _advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("候選與輸出設定")
        form = QFormLayout(group)
        form.addRow("候選搜尋：", QLabel("後續 solver 接入時提供"))
        form.addRow("診斷時間上限：", QLabel("後續 solver 接入時提供"))
        form.addRow("候選輸出份數：", QLabel("後續 solver 接入時提供"))
        form.addRow("輸出格式：", QLabel("後續 solver 接入時提供"))
        layout.addWidget(group)
        notice = QLabel("進階設定不會出現在第一階段的必要輸入流程中。")
        notice.setObjectName("mutedText")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addStretch(1)
        return page
