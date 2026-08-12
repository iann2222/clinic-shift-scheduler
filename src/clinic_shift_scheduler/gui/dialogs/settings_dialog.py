"""Editable general and advanced scheduler configuration dialog."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..drafts import ConfigDraft
from ..widgets import TrimmedDoubleSpinBox, UnitInput, VisibleCheckBox

from .localized_dialogs import localize_dialog_buttons, show_warning


class SettingsDialog(QDialog):
    """Edit one isolated config draft; persistence remains in MainWindow."""

    defaults_restored = Signal()

    def __init__(
        self,
        draft: ConfigDraft,
        *,
        config_path: str | Path,
        input_directory: str | Path,
        current_document_path: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.draft = draft
        self.config_path = Path(config_path)
        self.input_directory = Path(input_directory)
        self.current_document_path = (
            None if current_document_path is None else Path(current_document_path)
        )
        self.setWindowTitle("設定")
        self.setModal(True)
        self.resize(620, 500)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("settingsTabs")
        self.tabs.addTab(self._general_tab(), "一般設定")
        self.tabs.addTab(self._advanced_tab(), "候選班表設定")
        layout.addWidget(self.tabs, 1)

        lower = QHBoxLayout()
        self.restore_button = QPushButton("還原參考預設值")
        self.restore_button.setToolTip("使用 config.json 的『預設設定』覆蓋目前畫面值")
        lower.addWidget(self.restore_button)
        lower.addStretch(1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        localize_dialog_buttons(self.buttons)
        self.buttons.button(QDialogButtonBox.StandardButton.Save).setText("儲存設定")
        lower.addWidget(self.buttons)
        layout.addLayout(lower)

        self.restore_button.clicked.connect(self.defaults_restored.emit)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.candidate_enabled.toggled.connect(self._update_candidate_fields)
        self.search_limit.valueChanged.connect(self._search_limit_changed)
        self.time_mode.currentIndexChanged.connect(self._update_time_fields)
        self._load_widgets()

    def _general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("執行與文件設定")
        form = QFormLayout(group)
        config_label = QLabel(str(self.config_path))
        config_label.setWordWrap(True)
        form.addRow("設定檔：", config_label)

        input_row = QHBoxLayout()
        self.input_file = QLineEdit()
        self.input_file.setPlaceholderText("例如：排班輸入_2026-08.json")
        input_row.addWidget(self.input_file, 1)
        browse = QPushButton("選擇")
        browse.clicked.connect(self._browse_input)
        input_row.addWidget(browse)
        self.current_document_button = QPushButton("使用目前月份")
        self.current_document_button.clicked.connect(self._use_current_document)
        input_row.addWidget(self.current_document_button)
        form.addRow("排班輸入檔：", input_row)

        self.overwrite = VisibleCheckBox("允許正式排班覆寫同名結果檔")
        form.addRow("輸出行為：", self.overwrite)
        self.progress_seconds = TrimmedDoubleSpinBox()
        self.progress_seconds.setRange(0.1, 3600.0)
        self.progress_seconds.setDecimals(1)
        self.progress_seconds.setSingleStep(1.0)
        self.progress_seconds_field = UnitInput(self.progress_seconds, "秒")
        form.addRow("進度更新間隔：", self.progress_seconds_field)
        layout.addWidget(group)
        notice = QLabel(
            "這裡只設定正式排班程式下次執行時使用的參數；"
            "儲存設定不會立即開始排班。"
        )
        notice.setObjectName("mutedText")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addStretch(1)
        return page

    def _advanced_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        group = QGroupBox("同品質候選班表")
        group_layout = QVBoxLayout(group)
        self.candidate_enabled = VisibleCheckBox(
            "正式班表完成後搜尋同品質候選"
        )
        group_layout.addWidget(self.candidate_enabled)
        self.candidate_options = QFrame()
        self.candidate_options.setObjectName("candidateOptions")
        self.candidate_form = QFormLayout(self.candidate_options)
        self.search_limit = QSpinBox()
        self.search_limit.setRange(1, 100000)
        self.search_limit_field = UnitInput(self.search_limit, "份")
        self.candidate_form.addRow("搜尋數量上限：", self.search_limit_field)
        self.time_mode = QComboBox()
        self.time_mode.addItem("依排班時間比例", "比例")
        self.time_mode.addItem("固定秒數", "定值")
        self.candidate_form.addRow("診斷時間模式：", self.time_mode)
        self.time_ratio = TrimmedDoubleSpinBox()
        self.time_ratio.setRange(0.01, 100.0)
        self.time_ratio.setDecimals(2)
        self.time_ratio.setSingleStep(0.05)
        self.time_ratio.setToolTip("0.2 表示正式最佳化時間的五分之一")
        self.candidate_form.addRow("排班時間比例：", self.time_ratio)
        self.fixed_seconds = TrimmedDoubleSpinBox()
        self.fixed_seconds.setRange(0.1, 86400.0)
        self.fixed_seconds.setDecimals(1)
        self.fixed_seconds_field = UnitInput(self.fixed_seconds, "秒")
        self.candidate_form.addRow("固定時間上限：", self.fixed_seconds_field)
        self.export_count = QSpinBox()
        self.export_count.setRange(0, 100000)
        self.export_count_field = UnitInput(self.export_count, "份")
        self.candidate_form.addRow(
            "額外輸出份數上限：", self.export_count_field
        )
        formats = QHBoxLayout()
        self.format_json = VisibleCheckBox("JSON")
        self.format_excel = VisibleCheckBox("Excel")
        self.format_pdf = VisibleCheckBox("PDF")
        formats.addWidget(self.format_json)
        formats.addWidget(self.format_excel)
        formats.addWidget(self.format_pdf)
        formats.addStretch(1)
        self.candidate_form.addRow("候選輸出格式：", formats)
        group_layout.addWidget(self.candidate_options)
        layout.addWidget(group)
        notice = QLabel(
            "候選處理在正式 JSON、Excel、PDF 已輸出後才開始；"
            "停用時不會影響正式班表。"
        )
        notice.setObjectName("mutedText")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        layout.addStretch(1)
        return page

    def _load_widgets(self) -> None:
        draft = self.draft
        self.input_file.setText(draft.input_file)
        self.overwrite.setChecked(draft.overwrite)
        self.progress_seconds.setValue(draft.progress_update_seconds)
        self.candidate_enabled.setChecked(draft.candidate_enabled)
        self.search_limit.setValue(draft.candidate_search_limit)
        self.time_mode.setCurrentIndex(max(self.time_mode.findData(draft.diagnostic_time_mode), 0))
        self.fixed_seconds.setValue(draft.diagnostic_fixed_seconds)
        self.time_ratio.setValue(draft.diagnostic_time_ratio)
        self.export_count.setMaximum(draft.candidate_search_limit)
        self.export_count.setValue(draft.candidate_export_count)
        selected = set(draft.candidate_export_formats)
        self.format_json.setChecked("json" in selected)
        self.format_excel.setChecked("excel" in selected)
        self.format_pdf.setChecked("pdf" in selected)
        self.current_document_button.setEnabled(
            self._current_document_filename() is not None
        )
        self._update_candidate_fields()
        self._update_time_fields()

    def reload_from_draft(self) -> None:
        self._load_widgets()

    def accept(self) -> None:
        self._update_draft()
        try:
            self.draft.to_config()
        except (TypeError, ValueError) as error:
            show_warning(self, "設定內容有誤", str(error))
            return
        super().accept()

    def _update_draft(self) -> None:
        draft = self.draft
        draft.input_file = self.input_file.text().strip()
        draft.overwrite = self.overwrite.isChecked()
        draft.progress_update_seconds = self.progress_seconds.value()
        draft.candidate_enabled = self.candidate_enabled.isChecked()
        draft.candidate_search_limit = self.search_limit.value()
        draft.diagnostic_time_mode = self.time_mode.currentData()
        draft.diagnostic_fixed_seconds = self.fixed_seconds.value()
        draft.diagnostic_time_ratio = self.time_ratio.value()
        draft.candidate_export_count = self.export_count.value()
        draft.candidate_export_formats = [
            value
            for value, checkbox in (
                ("json", self.format_json),
                ("excel", self.format_excel),
                ("pdf", self.format_pdf),
            )
            if checkbox.isChecked()
        ]

    def _browse_input(self) -> None:
        self.input_directory.mkdir(parents=True, exist_ok=True)
        path, _ = QFileDialog.getOpenFileName(
            self,
            "選擇排班輸入",
            str(self.input_directory),
            "JSON files (*.json)",
        )
        if not path:
            return
        selected = Path(path)
        try:
            selected.resolve().relative_to(self.input_directory.resolve())
        except ValueError:
            show_warning(
                self,
                "輸入檔位置不正確",
                "排班輸入檔必須位於程式的 input 資料夾內。",
            )
            return
        self.input_file.setText(selected.name)

    def _use_current_document(self) -> None:
        filename = self._current_document_filename()
        if filename is not None:
            self.input_file.setText(filename)

    def _current_document_filename(self) -> str | None:
        if self.current_document_path is None:
            return None
        try:
            self.current_document_path.resolve().relative_to(
                self.input_directory.resolve()
            )
        except ValueError:
            return None
        return self.current_document_path.name

    def _search_limit_changed(self, value: int) -> None:
        self.export_count.setMaximum(value)

    def _update_candidate_fields(self) -> None:
        enabled = self.candidate_enabled.isChecked()
        self.candidate_options.setEnabled(enabled)
        self._update_time_fields()

    def _update_time_fields(self) -> None:
        enabled = self.candidate_enabled.isChecked()
        proportional = self.time_mode.currentData() == "比例"
        self.candidate_form.setRowVisible(self.time_ratio, proportional)
        self.candidate_form.setRowVisible(
            self.fixed_seconds_field, not proportional
        )
        self.time_ratio.setEnabled(enabled)
        self.fixed_seconds.setEnabled(enabled)
