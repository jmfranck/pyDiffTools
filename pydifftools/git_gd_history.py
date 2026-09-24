"""Date-ordered Git history with first-parent branch continuity."""

from dataclasses import dataclass, field
import shlex
import subprocess

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QGraphicsEllipseItem, QGraphicsScene, QGraphicsView,
    QGraphicsPathItem, QGraphicsRectItem, QGraphicsTextItem,
    QLabel, QMenu, QMessageBox, QToolButton, QVBoxLayout, QWidget,
)

from .git_gd import build_entries, git_bytes
from .git_gd_qt import DiffWindow


@dataclass
class HistoryCommit:
    oid: str
    parents: list[str]
    date: str
    subject: str
    tags: list[str] = field(default_factory=list)
    branches: list[str] = field(default_factory=list)
    lane: int = 0
    author: str = ""

    @property
    def label(self):
        return next(iter(self.tags or self.branches), self.oid[:6])


def load_history(limit=40):
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    data = git_bytes([
        "log", "--all", *([head] if head else []), "--date-order",
        f"--max-count={limit}",
        "--format=%H%x00%P%x00%cI%x00%an%x00%s",
    ]).decode("utf-8", errors="replace")
    commits = []
    for line in data.splitlines():
        oid, parents, date, author, subject = line.split("\0", 4)
        if date.endswith("Z"):
            date = date[:-1] + "+00:00"
        commits.append(HistoryCommit(
            oid, parents.split(), date, subject, author=author,
        ))
    by_oid = {commit.oid: commit for commit in commits}
    refs = git_bytes([
        "for-each-ref", "--sort=refname",
        "--format=%(objectname)%00%(*objectname)%00%(refname)",
        "refs/tags", "refs/heads", "refs/remotes",
    ]).decode("utf-8", errors="replace")
    for line in refs.splitlines():
        oid, peeled, ref = line.split("\0", 2)
        commit = by_oid.get(peeled or oid)
        if commit is not None:
            if ref.startswith("refs/tags/"):
                commit.tags.append(ref[len("refs/tags/"):])
            else:
                commit.branches.append(ref.split("/", 2)[2])
    # {{{ assign entire first-parent chains before visiting merged branches
    # HEAD's receiving branch owns its ancestry, even when another branch's
    # tip is more recent. Other tips keep their own color until the fork.
    seeds = ([by_oid[head]] if head in by_oid else []) + commits
    assigned = set()
    lane = 0
    for seed in seeds:
        commit = seed
        if commit.oid in assigned:
            continue
        while commit is not None and commit.oid not in assigned:
            assigned.add(commit.oid)
            commit.lane = lane
            commit = by_oid.get(commit.parents[0]) if commit.parents else None
        lane += 1
    # }}}
    return commits


class CommitBubble(QGraphicsEllipseItem):
    def __init__(self, commit, window, x, y, color):
        super().__init__(-6, -6, 12, 12)
        self.commit = commit
        self.window = window
        self.setPos(x, y)
        self.setBrush(color)
        self.setPen(QPen(color.lighter(140), 2))
        self.setZValue(2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"{commit.oid}\n{commit.date}\n{commit.subject}")

        self.setData(0, commit)


class HistoryView(QGraphicsView):
    def commit_at(self, position):
        item = self.itemAt(position)
        while item is not None:
            if isinstance(item.data(0), HistoryCommit):
                return item.data(0)
            item = item.parentItem()
        return None

    def mousePressEvent(self, event):
        commit = self.commit_at(event.position().toPoint())
        if commit is not None and event.button() == Qt.MouseButton.LeftButton:
            self.window().open_commit(commit)
            event.accept()
            return
        super().mousePressEvent(event)

    def contextMenuEvent(self, event):
        commit = self.commit_at(event.pos())
        if commit is None:
            return
        menu = QMenu(self)
        copy = menu.addAction("Copy hash")
        endpoint = menu.addAction("Comparison endpoint")
        menu.addSeparator()
        reset = menu.addAction("Reset endpoint to working directory")
        chosen = menu.exec(event.globalPos())
        if chosen == copy:
            QApplication.clipboard().setText(commit.oid)
        elif chosen == endpoint:
            self.window().set_endpoint(commit)
        elif chosen == reset:
            self.window().set_endpoint(None)
        event.accept()


class HistoryWindow(QWidget):
    def __init__(self, repo_name, commits):
        super().__init__()
        self.repo_name = repo_name
        self.endpoint = None
        self.diff_windows = []
        self.text_items = []
        self.commits = commits
        self.setWindowTitle(f"tree — {repo_name} — history")
        self.resize(1100, 700)
        self.setStyleSheet(
            "HistoryWindow { background: #f5f7fb; }"
            "QLabel { color: #526078; }"
            "QGraphicsView { background: #ffffff; border: 1px solid #dce2ec;"
            " border-radius: 8px; }"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(10)
        title = QLabel(f"{repo_name} / History")
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setStyleSheet(
            "font-size: 20px; font-weight: 600; color: #202c40;"
        )
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "All branches · Date order · 40 commits at a time\n"
            "Click any commit to open its diff. Right-click for endpoints."
        ))
        self.endpoint_label = QLabel()
        self.endpoint_label.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.endpoint_label)
        self.set_endpoint(None)
        self.scene = QGraphicsScene(self)
        self.view = HistoryView(self.scene, self)
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        layout.addWidget(self.view)
        self.more_button = QToolButton()
        self.more_button.setArrowType(Qt.ArrowType.DownArrow)
        self.more_button.setToolTip("Load the next 40 commits")
        self.more_button.setAccessibleName("Load the next 40 commits")
        self.more_button.clicked.connect(self.load_more)
        self.more_button.setEnabled(len(commits) == 40)
        layout.addWidget(
            self.more_button, alignment=Qt.AlignmentFlag.AlignHCenter
        )
        self.draw_history()

    def load_more(self):
        limit = len(self.commits) + 40
        try:
            commits = load_history(limit)
        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, "tree", str(exc))
            return
        scroll = self.view.verticalScrollBar().value()
        self.commits = commits
        self.draw_history()
        self.view.verticalScrollBar().setValue(scroll)
        self.more_button.setEnabled(len(commits) == limit)
        if len(commits) < limit:
            self.more_button.setToolTip("No more commits")

    def draw_history(self):
        self.text_items.clear()
        self.scene.clear()
        commits = self.commits
        if not commits:
            self.scene.addText("No commits.")
            return
        # {{{ draw ancestry edges, then interactive bubbles and commit labels
        colors = [QColor(value) for value in (
            "#397dcc", "#d47824", "#339969", "#a960c0", "#d14c70",
            "#239ca8", "#8b8940",
        )]
        metadata = []
        for commit in commits:
            date = QGraphicsTextItem("\n".join((
                commit.date[:10], commit.date[11:19], commit.author,
            )))
            date.setFont(QFont(self.font().family(), 9))
            date.document().setDocumentMargin(0)
            date.setDefaultTextColor(QColor("#748198"))
            metadata.append(date)
        row_height = max(
            48, max(item.boundingRect().height() for item in metadata) + 4,
        )
        metadata_width = max(item.boundingRect().width() for item in metadata)
        positions = {
            commit.oid: (24 + commit.lane * 26, row_height * (row + 0.5))
            for row, commit in enumerate(commits)
        }
        by_oid = {commit.oid: commit for commit in commits}
        text_x = 52 + max(commit.lane for commit in commits) * 26
        for commit, date in zip(commits, metadata):
            x, y = positions[commit.oid]
            top = y - row_height / 2
            color = colors[commit.lane % len(colors)]
            for number, parent in enumerate(commit.parents):
                if parent not in positions:
                    # A short tail marks ancestry beyond the loaded commits.
                    self.scene.addLine(x, y, x, y + 14, QPen(color, 2))
                    continue
                px, py = positions[parent]
                edge_color = color if number == 0 else colors[
                    by_oid[parent].lane % len(colors)
                ]
                path = QPainterPath()
                path.moveTo(x, y)
                if x == px:
                    path.lineTo(px, py)
                elif number == 0:
                    path.lineTo(x, py - 16)
                    path.cubicTo(x, py, px, py - 16, px, py)
                else:
                    path.cubicTo(x, y + 16, px, y, px, y + 16)
                    path.lineTo(px, py)
                self.scene.addPath(path, QPen(edge_color, 2))
            self.scene.addItem(CommitBubble(commit, self, x, y, color))
            # Each row, including its labels and artwork, is one click target.
            row = QGraphicsRectItem(0, top, 1000, row_height - 1)
            row.setData(0, commit)
            row.setPen(QPen(Qt.PenStyle.NoPen))
            row.setBrush(QColor("#ffffff"))
            row.setZValue(-1)
            row.setCursor(Qt.CursorShape.PointingHandCursor)
            row.setToolTip(f"{commit.oid}\n{commit.date}\n{commit.subject}")
            self.scene.addItem(row)
            date.setParentItem(row)
            date.setPos(text_x, top + 2)
            subject = QGraphicsTextItem(commit.subject, row)
            subject.setFont(QFont(self.font().family(), 11))
            subject.setDefaultTextColor(QColor("#202c40"))
            subject.setPos(text_x + metadata_width + 16, top)
            self.text_items.extend([date, subject])
            badge_x = subject.x()
            for kind, names in (("tag", commit.tags),
                                ("branch", commit.branches)):
                for name in names:
                    badge_color = QColor("#956414") if kind == "tag" else color
                    label = QGraphicsTextItem(name, row)
                    self.text_items.append(label)
                    label.setFont(QFont(self.font().family(), 9))
                    label.setDefaultTextColor(badge_color)
                    label.setPos(badge_x + 23, top + 23)
                    width = label.boundingRect().width() + 30
                    badge_path = QPainterPath()
                    badge_path.addRoundedRect(
                        QRectF(badge_x, top + 24, width, 23), 5, 5
                    )
                    badge = QGraphicsPathItem(badge_path, row)
                    badge.setBrush(QColor(
                        "#fff4da" if kind == "tag" else "#edf3fc"
                    ))
                    badge.setPen(QPen(Qt.PenStyle.NoPen))
                    badge.setZValue(-0.5)
                    # Vector tag silhouette and branch fork, independent of
                    # emoji fonts and crisp at any display scale.
                    icon = QPainterPath()
                    if kind == "tag":
                        icon.moveTo(1, 2)
                        icon.lineTo(8, 2)
                        icon.lineTo(15, 9)
                        icon.lineTo(8, 16)
                        icon.lineTo(1, 9)
                        icon.closeSubpath()
                        icon.addEllipse(QRectF(4, 5, 2.5, 2.5))
                    else:
                        icon.moveTo(4, 4)
                        icon.lineTo(4, 13)
                        icon.moveTo(4, 10)
                        icon.cubicTo(4, 6, 12, 10, 12, 4)
                        for cx, cy in ((4, 2), (4, 15), (12, 2)):
                            icon.addEllipse(QRectF(cx - 2, cy - 2, 4, 4))
                    art = QGraphicsPathItem(icon, row)
                    art.setPos(badge_x + 5, top + 27)
                    art.setPen(QPen(badge_color, 1.4))
                    badge_x += width + 7
            row.setRect(0, top, max(
                1000, badge_x + 20,
                subject.x() + subject.boundingRect().width() + 20,
            ), row_height - 1)
        # }}}

    def set_endpoint(self, commit):
        self.endpoint = commit
        self.endpoint_label.setText(
            "Comparison endpoint: "
            + (commit.label if commit else "working directory")
        )

    def open_commit(self, commit):
        args = [commit.oid]
        labels = [commit.label]
        if self.endpoint is not None:
            args.append(self.endpoint.oid)
            labels.append(self.endpoint.label)
        try:
            diff_args, entries = build_entries(args)
        except subprocess.CalledProcessError as exc:
            QMessageBox.critical(self, "gd", str(exc))
            return
        window = DiffWindow(
            self.repo_name, diff_args, entries, command_args=labels
        )
        window.setWindowTitle(shlex.join(["gd", *labels]))
        self.diff_windows.append(window)
        window.show()
