from __future__ import annotations

import subprocess
import sys
from typing import TYPE_CHECKING, Sequence

from PySide6.QtCore import (
    QAbstractTableModel,
    QModelIndex,
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThread,
    QThreadPool,
    QTimer,
    Signal,
)
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

from .git_gd import (
    build_difftool_command,
    build_image_difftool_command,
    diff_entry_sort_key,
    is_raster_image_entry,
    numstat_for_paths,
    run_image_score,
)


def _delta_text(entry: "DiffEntry") -> str:
    if entry.status in ("A", "D"):
        return entry.status
    if is_raster_image_entry(entry):
        if entry.rgb_score is not None and entry.alpha_score is not None:
            return f"rgb {entry.rgb_score:.1f} a {entry.alpha_score:.1f}"
        if entry.image_score_error is not None:
            return "rgb … a …"
        return "rgb … a …"
    if entry.added == -1 and entry.deleted == -1:
        return "…"
    if entry.added is None or entry.deleted is None:
        return "binary"
    return f"-{entry.deleted} / +{entry.added}"


class ScoreSignals(QObject):
    finished = Signal(object, object, object, object)


class ImageScoreWorker(QRunnable):
    def __init__(self, diff_args: Sequence[str], entry: "DiffEntry"):
        super().__init__()
        self.diff_args = list(diff_args)
        self.entry = entry
        self.signals = ScoreSignals()

    def run(self):
        try:
            rgb_score, alpha_score = run_image_score(
                self.diff_args, self.entry
            )
        except Exception as exc:
            self.signals.finished.emit(self.entry, None, None, str(exc))
            return
        self.signals.finished.emit(
            self.entry, rgb_score, alpha_score, None
        )


class TextStatsWorker(QRunnable):
    def __init__(self, diff_args, entries):
        super().__init__()
        self.diff_args = list(diff_args)
        self.entries = list(entries)
        self.signals = ScoreSignals()

    def run(self):
        for entry in self.entries:
            try:
                added, deleted = numstat_for_paths(
                    self.diff_args, entry.diff_paths
                )
                self.signals.finished.emit(
                    (entry, added, deleted, None),
                    None,
                    None,
                    "text update",
                )
            except Exception as exc:
                self.signals.finished.emit(
                    (entry, None, None, str(exc)),
                    None,
                    None,
                    "text update",
                )
        self.signals.finished.emit(None, None, None, "text complete")


class DiffModel(QAbstractTableModel):
    headers = ["Seen", "Δ", "File"]

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
                if entry.is_exact_rename:
                    return "R100%"
                return "✓" if entry.seen else "☐"
            if col == 1:
                return _delta_text(entry)
            if col == 2:
                return entry.display_path

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0:
                vertical_alignment = (
                    Qt.AlignmentFlag.AlignTop
                    if entry.has_multiline_display_path
                    else Qt.AlignmentFlag.AlignVCenter
                )
                return int(Qt.AlignmentFlag.AlignHCenter | vertical_alignment)
            return int(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )

        if role == Qt.ItemDataRole.ToolTipRole and col == 1:
            return entry.image_score_error

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
        if entry.status in ("A", "D"):
            if option.state & QStyle.StateFlag.State_Selected:
                painter.setPen(
                    option.palette.color(
                        option.palette.ColorRole.HighlightedText
                    )
                )
            else:
                painter.setPen(
                    QColor("#228b22")
                    if entry.status == "A"
                    else QColor("#b22222")
                )
            painter.drawText(
                rect,
                int(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                ),
                entry.status,
            )
            painter.restore()
            return

        if is_raster_image_entry(entry):
            painter.setPen(option.palette.color(option.palette.ColorRole.Text))
            painter.drawText(
                rect,
                int(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                ),
                _delta_text(entry),
            )
            painter.restore()
            return

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
        w = fm.horizontalAdvance(_delta_text(entry)) + 16
        h = max(size.height(), fm.height() + 6)
        return QSize(w, h)


class DiffTable(QTableView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTableView.SelectionMode.SingleSelection)
        self.setEditTriggers(QTableView.EditTrigger.NoEditTriggers)
        self.setWordWrap(True)
        self.setShowGrid(False)
        self.setAlternatingRowColors(False)
        self.setSortingEnabled(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Fixed
        )
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            parent = self.parent()
            if parent is not None and hasattr(parent, "open_current_row"):
                parent.open_current_row()
                return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        # Keep the two file kinds visually distinct after either result batch
        # resorts its group.  Drawing on the viewport spans every table column.
        for row, entry in enumerate(self.model().entries):
            if is_raster_image_entry(entry):
                line_y = self.visualRect(self.model().index(row, 0)).top()
                if line_y >= 0:
                    painter = QPainter(self.viewport())
                    painter.setPen(QColor("#808080"))
                    painter.drawLine(0, line_y, self.viewport().width(), line_y)
                    painter.end()
                break


class DiffWindow(QWidget):
    def __init__(
        self,
        repo_name: str,
        diff_args: Sequence[str],
        entries: list["DiffEntry"],
        *,
        start_image_scores: bool = True,
    ):
        super().__init__()
        self.repo_name = repo_name
        self.diff_args = list(diff_args)
        self.model = DiffModel(entries)
        self.score_pool = QThreadPool(self)
        self.score_pool.setMaxThreadCount(
            min(4, max(1, QThread.idealThreadCount()))
        )
        self.remaining_image_scores = 0
        # Retain Python ownership while Qt's thread pool runs the QRunnables.
        # Some PySide versions otherwise collect workers before their signals.
        self.workers = []

        self.table = DiffTable(self)
        self.table.setModel(self.model)
        self.table.setItemDelegateForColumn(1, DeltaDelegate(self.table))
        self.table.clicked.connect(self._handle_click)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)

        # {{{ establish the initial table size without Qt measuring every cell
        normal_font = QFontMetrics(self.table.font())
        delta_font = QFontMetrics(self.table.itemDelegateForColumn(1).font)
        self.table.setColumnWidth(
            0, normal_font.horizontalAdvance(self.model.headers[0]) + 18
        )
        self.table.setColumnWidth(
            1, delta_font.horizontalAdvance("rgb 100.0 a 100.0") + 16
        )
        path_width = normal_font.horizontalAdvance(self.model.headers[2]) + 18
        for row, entry in enumerate(self.model.entries):
            for line in entry.display_path.splitlines():
                path_width = max(
                    path_width, normal_font.horizontalAdvance(line) + 18
                )
            if entry.has_multiline_display_path:
                self.table.setRowHeight(row, 2 * normal_font.height() + 8)
        self.table.setColumnWidth(2, path_width)
        # }}}
        self.table.verticalHeader().setDefaultSectionSize(
            max(22, self.table.verticalHeader().defaultSectionSize())
        )

        self._adjust_geometry()
        self._update_title()

        if self.model.rowCount() > 0:
            self.table.selectRow(0)
        if start_image_scores:
            QTimer.singleShot(0, self.start_score_workers)

    def start_score_workers(self):
        # Let the initial window paint before Git and image subprocesses begin.
        text_entries = [
            entry
            for entry in self.model.entries
            if entry.added == -1 and entry.deleted == -1
        ]
        if text_entries:
            worker = TextStatsWorker(self.diff_args, text_entries)
            worker.signals.finished.connect(self.results_finished)
            self.workers.append(worker)
            self.score_pool.start(worker)

        image_entries = [
            entry
            for entry in self.model.entries
            if is_raster_image_entry(entry)
            and entry.status not in ("A", "D")
        ]
        self.remaining_image_scores = len(image_entries)
        for entry in image_entries:
            worker = ImageScoreWorker(self.diff_args, entry)
            worker.signals.finished.connect(self.results_finished)
            self.workers.append(worker)
            self.score_pool.start(worker)

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

    def results_finished(self, result, second, third, category):
        current_index = self.table.currentIndex()
        selected_entry = (
            self.model.entries[current_index.row()]
            if current_index.isValid()
            else None
        )

        vertical_scroll = self.table.verticalScrollBar().value()
        horizontal_scroll = self.table.horizontalScrollBar().value()

        # Both worker types report through this callback so result application,
        # stable sorting, selection, and viewport preservation stay consistent.
        if category == "text update":
            entry, added, deleted, error = result
            entry.added = added
            entry.deleted = deleted
            entry.image_score_error = error
            for row, candidate in enumerate(self.model.entries):
                if candidate is entry:
                    index = self.model.index(row, 1)
                    self.model.dataChanged.emit(
                        index,
                        index,
                        [
                            Qt.ItemDataRole.DisplayRole,
                            Qt.ItemDataRole.ToolTipRole,
                        ],
                    )
                    break
            return
        if category == "text complete":
            should_sort = True
        else:
            result.rgb_score = second
            result.alpha_score = third
            result.image_score_error = category
            self.remaining_image_scores -= 1
            should_sort = self.remaining_image_scores == 0

        if not should_sort:
            for row, candidate in enumerate(self.model.entries):
                if candidate is result:
                    index = self.model.index(row, 1)
                    self.model.dataChanged.emit(
                        index,
                        index,
                        [
                            Qt.ItemDataRole.DisplayRole,
                            Qt.ItemDataRole.ToolTipRole,
                        ],
                    )
                    break
            return

        self.model.layoutAboutToBeChanged.emit()
        self.model.entries.sort(key=diff_entry_sort_key)
        self.model.layoutChanged.emit()

        if selected_entry is not None:
            for row, candidate in enumerate(self.model.entries):
                if candidate is selected_entry:
                    self.table.selectRow(row)
                    break
        self.table.resizeColumnToContents(1)
        self.table.verticalScrollBar().setValue(vertical_scroll)
        self.table.horizontalScrollBar().setValue(horizontal_scroll)
        QTimer.singleShot(
            0,
            lambda: (
                self.table.verticalScrollBar().setValue(vertical_scroll),
                self.table.horizontalScrollBar().setValue(horizontal_scroll),
            ),
        )

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

        if is_raster_image_entry(entry):
            cmd = build_image_difftool_command(self.diff_args, entry)
        else:
            cmd = build_difftool_command(self.diff_args, entry)

        try:
            subprocess.Popen(cmd)
        except Exception as exc:
            QMessageBox.critical(
                self, "git gd review", f"Failed to launch difftool:\n{exc}"
            )


def launch_review(repo_name, diff_args, entries):
    app = QApplication(sys.argv)
    if not entries:
        QMessageBox.information(None, "git gd review", "No changed files.")
        return 0

    win = DiffWindow(repo_name, diff_args, entries)
    win.show()
    return app.exec()
