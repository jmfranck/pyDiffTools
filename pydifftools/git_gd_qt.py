from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Sequence

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QHeaderView,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QWidget,
)

if TYPE_CHECKING:
    from .git_gd import DiffEntry


class DiffModel(QAbstractTableModel):
    headers = ["Seen", "Δlines", "File"]

    def __init__(self, entries: list["DiffEntry"]):
        super().__init__()
        self.entries = entries

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else 3

    def headerData(
        self, section, orientation, role=Qt.ItemDataRole.DisplayRole
    ):
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation == Qt.Orientation.Horizontal:
            return self.headers[section]
        return section + 1

    def flags(self, index: QModelIndex):
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return "✓" if entry.seen else "☐"
            if col == 1:
                if entry.added is None or entry.deleted is None:
                    return "binary"
                return f"-{entry.deleted} / +{entry.added}"
            if col == 2:
                return entry.path

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0:
                return int(
                    Qt.AlignmentFlag.AlignHCenter
                    | Qt.AlignmentFlag.AlignVCenter
                )
            return int(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

        return None

    def mark_seen(self, row: int):
        if row < 0 or row >= len(self.entries):
            return
        if self.entries[row].seen:
            return
        self.entries[row].seen = True
        idx = self.index(row, 0)
        self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DisplayRole])

    def seen_count(self) -> int:
        return sum(1 for x in self.entries if x.seen)


class DeltaDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.font = QFont("Monospace")
        self.font.setStyleHint(QFont.StyleHint.TypeWriter)

    def paint(self, painter: QPainter, option, index: QModelIndex):
        if index.column() != 1:
            super().paint(painter, option, index)
            return

        entry = index.model().entries[index.row()]
        painter.save()
        painter.setFont(self.font)

        style = (
            option.widget.style()
            if option.widget is not None
            else QApplication.style()
        )
        style.drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem,
            option,
            painter,
            option.widget,
        )

        rect = option.rect.adjusted(6, 0, -6, 0)
        if entry.added is None or entry.deleted is None:
            painter.setPen(option.palette.color(option.palette.ColorRole.Text))
            painter.drawText(
                rect,
                int(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                ),
                "binary",
            )
            painter.restore()
            return

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        if selected:
            minus_color = option.palette.color(
                option.palette.ColorRole.HighlightedText
            )
            slash_color = minus_color
            plus_color = minus_color
        else:
            minus_color = QColor("#b22222")
            slash_color = option.palette.color(option.palette.ColorRole.Text)
            plus_color = QColor("#228b22")

        fm = QFontMetrics(self.font)
        minus_text = f"-{entry.deleted}"
        slash_text = " / "
        plus_text = f"+{entry.added}"

        x = rect.left()
        y = rect.top()
        h = rect.height()

        painter.setPen(minus_color)
        w = fm.horizontalAdvance(minus_text)
        painter.drawText(
            x,
            y,
            w,
            h,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            minus_text,
        )
        x += w

        painter.setPen(slash_color)
        w = fm.horizontalAdvance(slash_text)
        painter.drawText(
            x,
            y,
            w,
            h,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            slash_text,
        )
        x += w

        painter.setPen(plus_color)
        w = fm.horizontalAdvance(plus_text)
        painter.drawText(
            x,
            y,
            w,
            h,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            plus_text,
        )
        painter.restore()

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        entry = index.model().entries[index.row()]
        fm = QFontMetrics(self.font)
        if entry.added is None or entry.deleted is None:
            w = fm.horizontalAdvance("binary") + 16
        else:
            w = fm.horizontalAdvance(f"-{entry.deleted} / +{entry.added}") + 16
        h = max(size.height(), fm.height() + 6)
        return QSize(w, h)


class DiffTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setWordWrap(False)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSortingEnabled(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            parent = self.parent()
            if parent is not None and hasattr(parent, "open_current_row"):
                parent.open_current_row()
                return
        super().keyPressEvent(event)


class DiffWindow(QWidget):
    def __init__(
        self,
        repo_name: str,
        diff_args: Sequence[str],
        entries: list["DiffEntry"],
    ):
        super().__init__()
        self.repo_name = repo_name
        self.diff_args = list(diff_args)
        self.model = DiffModel(entries)

        self.table = DiffTable(self)
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(1, DeltaDelegate(self.table))
        self.table.clicked.connect(self._handle_click)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)

        self.table.resizeColumnsToContents()
        self.table.resizeRowsToContents()
        self.table.verticalHeader().setDefaultSectionSize(
            max(22, self.table.verticalHeader().defaultSectionSize())
        )

        self._adjust_geometry()
        self._update_title()

        if self.model.rowCount() > 0:
            self.table.selectRow(0)

    def _update_title(self):
        self.setWindowTitle(
            f"git gd review — {self.repo_name} — "
            f"{self.model.seen_count()}/{len(self.model.entries)} opened"
        )

    def _adjust_geometry(self):
        frame = 2 * self.table.frameWidth()
        width = frame + self.table.verticalHeader().width()
        width += sum(
            self.table.columnWidth(i) for i in range(self.model.columnCount())
        )
        width += self.table.verticalScrollBar().sizeHint().width()

        height = frame + self.table.horizontalHeader().height()
        height += sum(
            self.table.rowHeight(i) for i in range(self.model.rowCount())
        )
        height += self.table.horizontalScrollBar().sizeHint().height()

        screen = QApplication.primaryScreen().availableGeometry()
        width = min(width + 4, int(screen.width() * 0.9))
        height = min(height + 4, int(screen.height() * 0.9))

        self.table.setGeometry(0, 0, width, height)
        self.setFixedSize(width, height)

    def _handle_click(self, index: QModelIndex):
        if index.isValid():
            self.open_row(index.row())

    def open_current_row(self):
        idx = self.table.currentIndex()
        if idx.isValid():
            self.open_row(idx.row())

    def open_row(self, row: int):
        if row < 0 or row >= len(self.model.entries):
            return
        entry = self.model.entries[row]
        self.model.mark_seen(row)
        self._update_title()

        cmd = [
            "git",
            "difftool",
            "--tool=mygvim",
            "--no-prompt",
            *self.diff_args,
            "--",
            entry.path,
        ]

        try:
            subprocess.Popen(cmd)
        except Exception as exc:
            QMessageBox.critical(
                self, "git gd review", f"Failed to launch difftool:\n{exc}"
            )


def launch_review(
    repo_name: str, diff_args: Sequence[str], entries: list["DiffEntry"]
) -> int:
    app = QApplication(sys.argv)
    if not entries:
        QMessageBox.information(None, "git gd review", "No changed files.")
        return 0

    win = DiffWindow(repo_name, diff_args, entries)
    win.show()
    return app.exec()
