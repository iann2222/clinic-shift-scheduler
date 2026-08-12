"""Human-readable combo editor for availability matrix cells."""

from __future__ import annotations

from PySide6.QtCore import QAbstractItemModel, QModelIndex
from PySide6.QtWidgets import QComboBox, QStyledItemDelegate, QWidget

from ..models.availability_table_model import AVAILABILITY_LABELS


class AvailabilityDelegate(QStyledItemDelegate):
    def createEditor(
        self,
        parent: QWidget,
        _option: object,
        index: QModelIndex,
    ) -> QWidget | None:
        if index.column() < 3:
            return None
        combo = QComboBox(parent)
        for value, label in AVAILABILITY_LABELS.items():
            combo.addItem(label, value)
        return combo

    def setEditorData(self, editor: QWidget, index: QModelIndex) -> None:
        if isinstance(editor, QComboBox):
            value = index.data(2)
            item_index = editor.findData(value)
            if item_index >= 0:
                editor.setCurrentIndex(item_index)

    def setModelData(
        self,
        editor: QWidget,
        model: QAbstractItemModel,
        index: QModelIndex,
    ) -> None:
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentData())
