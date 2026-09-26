"""Qt review of a possible duplicate citation, run in a separate process."""

import json
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class DuplicateDialog(QDialog):
    """Choose an entry or merge fields; default to existing values and key."""

    def __init__(self, matches, incoming, source):
        super().__init__()
        self.matches = matches
        self.incoming = incoming
        self.decision = None
        self.setWindowTitle("pydifft cpb — Possible duplicate citation")
        self.resize(1000, 650)
        layout = QVBoxLayout(self)
        explanation = QLabel(
            f"Review the imported citation for {source}.\n"
            "Keeping or merging a duplicate also replaces @UNCHOSEN with "
            "@CHOSEN in this Markdown file. Other documents are not edited.\n"
            "For a merge, choose each field below, including the citation key."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.match_selector = QComboBox()
        for match in matches:
            self.match_selector.addItem(f"{match['key']} — {match['reason']}")
        layout.addWidget(self.match_selector)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(
            ["Field", "Existing bibliography", "Zotero", "Merge uses"]
        )
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.table)
        buttons = QHBoxLayout()
        self.buttons = {}
        for label, action in [
            ("Keep existing", "existing"),
            ("Keep Zotero", "incoming"),
            ("Merge selected fields", "merge"),
            ("Not a duplicate: keep both", "both"),
            ("Skip this import", "skip"),
        ]:
            button = QPushButton(label)
            button.setAutoDefault(False)
            button.clicked.connect(
                lambda _checked=False, choice=action: self.choose(choice)
            )
            self.buttons[action] = button
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.match_selector.currentIndexChanged.connect(self.populate)
        self.populate()

    def populate(self):
        existing = self.matches[self.match_selector.currentIndex()]
        self.left = {
            "citation key": existing["key"],
            "entry type": existing["kind"],
            **existing["fields"],
        }
        self.right = {
            "citation key": self.incoming["key"],
            "entry type": self.incoming["kind"],
            **self.incoming["fields"],
        }
        self.names = list(dict.fromkeys([*self.left, *self.right]))
        self.table.setRowCount(len(self.names))
        self.selectors = {}
        for row, name in enumerate(self.names):
            for column, value in enumerate(
                [name, self.left.get(name, ""), self.right.get(name, "")]
            ):
                cell = QTableWidgetItem(value)
                cell.setFlags(cell.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, cell)
            selector = QComboBox()
            if name in self.left:
                selector.addItem("Existing", self.left[name])
            if name in self.right:
                selector.addItem("Zotero", self.right[name])
            self.table.setCellWidget(row, 3, selector)
            self.selectors[name] = selector
        self.table.resizeRowsToContents()

    def choose(self, action):
        existing = self.matches[self.match_selector.currentIndex()]
        self.decision = {"action": action, "existing_key": existing["key"]}
        if action == "merge":
            values = {
                name: selector.currentData()
                for name, selector in self.selectors.items()
            }
            self.decision.update(
                key=values.pop("citation key"),
                kind=values.pop("entry type"),
                fields=values,
            )
        self.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv[:1])
    dialog = DuplicateDialog(**json.load(sys.stdin))
    dialog.exec()
    print(json.dumps(dialog.decision))
