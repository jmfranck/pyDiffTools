"""Pre-build migration of legacy and unregistered comment authors."""

import colorsys
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap

import yaml

_FRONT_MATTER_RE = re.compile(
    r"\A(\ufeff?---[ \t]*\r?\n)(.*?)(\r?\n(?:---|\.\.\.)[ \t]*(?:\r?\n|$))",
    re.DOTALL,
)
_LEGACY_TAG_RE = re.compile(
    r"(?P<closing></?)comment(?P<side>-(?:left|right))?>", re.I
)
_LEGACY_CLASS_RE = re.compile(r"(?<=\.)comment-(left|right)(?=[\s}])")
_AUTHOR_TAG_RE = re.compile(
    r"</?([A-Za-z]{2})com(?:-(?:left|right))?>", re.I
)
_AUTHOR_CLASS_RE = re.compile(
    r"\.([A-Za-z]{2})com(?:-(?:left|right))?(?=[\s}])", re.I
)
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
_SEED_COLOR = "#5aa0ff"


def _front_matter(text):
    match = _FRONT_MATTER_RE.match(text)
    if not match:
        if re.match(r"\A\ufeff?---[ \t]*(?:\r?\n|$)", text):
            raise ValueError(
                "YAML front matter starts with '---' but has no closing "
                "delimiter"
            )
        return None, {}, {}
    try:
        metadata = yaml.safe_load(match.group(2)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML front matter: {exc}") from exc
    if not isinstance(metadata, dict):
        raise ValueError("YAML front matter must contain a mapping")
    colors = {}
    for key, value in metadata.items():
        initials = re.fullmatch(r"([A-Z]{2})color", str(key))
        if not initials:
            continue
        if not isinstance(value, str) or not _HEX_RE.fullmatch(value):
            raise ValueError(f"{key} must be a six-digit hex color")
        colors[initials.group(1)] = value.lower()
    return match, metadata, colors


def _most_distant_hue(colors):
    """Return the midpoint of the largest gap between existing hues."""
    def hue(color):
        red, green, blue = (
            int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)
        )
        return colorsys.rgb_to_hsv(red, green, blue)[0] * 360

    if not colors:
        return hue(_SEED_COLOR)
    hues = sorted({hue(color) % 360 for color in colors})
    gaps = [
        (
            (hues[index + 1] if index + 1 < len(hues) else hues[0] + 360)
            - hue,
            hue,
        )
        for index, hue in enumerate(hues)
    ]
    gap_size, start = max(gaps, key=lambda gap: (gap[0], -gap[1]))
    return (start + gap_size / 2) % 360


def _migration_dialog(filename, colors, legacy):
    """Ask Qt for all migrations and return decisions without editing files."""
    script = r"""
import colorsys
import json
import re
import sys
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor, QIcon, QLinearGradient, QPainter, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QDialogButtonBox, QLabel,
    QLineEdit, QMessageBox, QVBoxLayout, QWidget,
)

payload = json.loads(sys.argv[1])
with open(sys.argv[2], encoding="utf-8", newline="") as fp:
    text = fp.read()
colors = payload["colors"]
app = QApplication(sys.argv[:1])
result = {"accepted": True, "replacements": {}, "colors": {}}

def color_hue(color):
    rgb = [int(color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    return colorsys.rgb_to_hsv(*rgb)[0] * 360

def most_distant_hue(used_colors):
    if not used_colors:
        return color_hue("#5aa0ff")
    hues = sorted(set(color_hue(color) % 360 for color in used_colors))
    gaps = [
        ((hues[i + 1] if i + 1 < len(hues) else hues[0] + 360) - hue, hue)
        for i, hue in enumerate(hues)
    ]
    gap, start = max(gaps, key=lambda item: (item[0], -item[1]))
    return (start + gap / 2) % 360

class HueBar(QWidget):
    hueChanged = Signal(int)
    def __init__(self, hue):
        super().__init__()
        self.hue = int(round(hue)) % 360
        self.setMinimumWidth(300)
        self.setMinimumHeight(34)
    def paintEvent(self, event):
        painter = QPainter(self)
        gradient = QLinearGradient(0, 0, self.width(), 0)
        for hue in range(0, 361, 30):
            gradient.setColorAt(hue / 360, QColor.fromHsv(hue % 360, 165, 255))
        painter.fillRect(0, 7, self.width(), 20, gradient)
        x = round(self.hue / 359 * (self.width() - 1))
        painter.setPen(QPen(Qt.GlobalColor.black, 2))
        painter.drawLine(x, 2, x, 31)
    def mousePressEvent(self, event):
        self.set_hue(event.position().x() / max(1, self.width() - 1) * 359)
    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.set_hue(event.position().x() / max(1, self.width() - 1) * 359)
    def set_hue(self, hue):
        self.hue = max(0, min(359, int(round(hue))))
        self.update()
        self.hueChanged.emit(self.hue)

def ask_hue(initial):
    dlg = QDialog()
    dlg.setWindowTitle("Create comment user")
    layout = QVBoxLayout(dlg)
    layout.addWidget(QLabel("Choose a hue for this comment user."))
    bar = HueBar(initial)
    layout.addWidget(bar)
    preview = QLabel()
    preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
    preview.setMinimumHeight(48)
    layout.addWidget(preview)
    def update_preview():
        # Match the saturation and opacity of the existing hard-coded blue.
        color = QColor.fromHsv(bar.hue, 165, 255, 255).name()
        preview.setText(color)
        preview.setStyleSheet("background-color: " + color)
        bar.update()
    bar.hueChanged.connect(update_preview)
    update_preview()
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok
        | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dlg.accept)
    buttons.rejected.connect(dlg.reject)
    layout.addWidget(buttons)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return QColor.fromHsv(bar.hue, 165, 255, 255).name()

def ask_legacy_initials():
    while True:
        dlg = QDialog()
        dlg.setWindowTitle("Migrate legacy comments")
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            "Legacy comment tags and blocks were found. Enter the two "
            "initials to use for all of them."
        ))
        field = QLineEdit()
        field.setMaxLength(2)
        field.setPlaceholderText("JF")
        layout.addWidget(field)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        initials = field.text().upper()
        if re.fullmatch(r"[A-Z]{2}", initials):
            return initials
        QMessageBox.warning(None, "Invalid initials", "Enter two letters.")

legacy = payload["legacy"]
if legacy:
    initials = ask_legacy_initials()
    legacy_occurrences = len(re.findall(
        r"</?comment(?:-(?:left|right))?>", text, re.I
    )) + len(re.findall(
        r"\.comment-(?:left|right)(?=[\s}])", text, re.I
    ))
    if initials is None:
        result["accepted"] = False
    elif not QMessageBox.question(
        None, "Replace legacy comments",
        "Replace " + str(legacy_occurrences)
        + " legacy tag or block-class occurrences with "
        + initials + "com markup?",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes:
        result["accepted"] = False
    else:
        result["replacements"]["legacy"] = initials

if result["accepted"]:
    authors = sorted(set(
        initials.upper() for initials in re.findall(
            r"</?([A-Za-z]{2})com(?:-(?:left|right))?>", text, re.I
        )
    ) | set(
        initials.upper() for initials in re.findall(
            r"\.([A-Za-z]{2})com(?:-(?:left|right))?(?=[\s}])",
            text, re.I
        )
    ))
    if result["replacements"].get("legacy"):
        authors.append(result["replacements"]["legacy"])
        authors = sorted(set(authors))
    for author in authors:
        if author in colors:
            continue
        box = QMessageBox()
        box.setWindowTitle("Unknown comment author")
        box.setText(
            author + "com tags or block classes have no matching "
            + author + "color field."
        )
        selector = QComboBox()
        for existing in sorted(colors):
            selector.addItem(existing + "  " + colors[existing], existing)
            swatch = QPixmap(14, 14)
            swatch.fill(QColor(colors[existing]))
            selector.setItemIcon(selector.count() - 1, QIcon(swatch))
        create = "Create " + author + " as a new comment user"
        selector.addItem(create, "__create__")
        selector.setCurrentIndex(selector.count() - 1)
        box.layout().addWidget(selector, 1, 0, 1, box.layout().columnCount())
        box.setStandardButtons(
            QMessageBox.StandardButton.Cancel
            | QMessageBox.StandardButton.Ok
        )
        box.setDefaultButton(QMessageBox.StandardButton.Ok)
        if box.exec() != QMessageBox.StandardButton.Ok:
            result["accepted"] = False
            break
        target = selector.currentData()
        if target == "__create__":
            seed = colors.get(author)
            if seed is None:
                used = [*colors.values(), *result["colors"].values()]
                seed_hue = most_distant_hue(used)
                seed = QColor.fromHsv(round(seed_hue), 165, 255).name()
            color = ask_hue(QColor(seed).hue())
            if color is None:
                result["accepted"] = False
                break
            result["colors"][author] = color
            colors[author] = color
        elif target:
            result["replacements"][author] = target

print(json.dumps(result))
"""
    completed = subprocess.run(
        # the dialog reads the document from its file, since the text of a
        # large document exceeds the operating system's argument limit
        [sys.executable, "-c", textwrap.dedent(script),
         json.dumps({"colors": colors, "legacy": legacy}), filename],
        capture_output=True, text=True,
    )
    if completed.returncode:
        detail = completed.stderr.strip()
        message = "cpb comment migration dialog failed"
        if detail:
            message += f": {detail}"
        else:
            message += "."
        raise RuntimeError(message)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "cpb comment migration dialog returned invalid data"
        ) from exc


def prepare_comment_source(filename):
    """Migrate comment tags and author colors before a build, if requested."""
    with open(filename, encoding="utf-8", newline="") as fp:
        original = fp.read()
    has_legacy = bool(
        _LEGACY_TAG_RE.search(original) or _LEGACY_CLASS_RE.search(original)
    )
    if not (has_legacy or _AUTHOR_TAG_RE.search(original)
            or _AUTHOR_CLASS_RE.search(original)):
        return original
    _, _, colors = _front_matter(original)
    authors = {
        initials.upper()
        for initials in _AUTHOR_TAG_RE.findall(original)
    } | {
        initials.upper()
        for initials in _AUTHOR_CLASS_RE.findall(original)
    }
    if not has_legacy and authors.issubset(colors):
        return original
    decisions = _migration_dialog(filename, colors, has_legacy)
    if not decisions.get("accepted"):
        raise RuntimeError("cpb comment migration was canceled")
    updated = original
    for tag_author, target in decisions.get("replacements", {}).items():
        if tag_author == "legacy":
            updated = _LEGACY_TAG_RE.sub(
                lambda found: (
                    found.group("closing") + target + "com"
                    + (found.group("side") or "") + ">"
                ),
                updated,
            )
            updated = _LEGACY_CLASS_RE.sub(
                lambda found: target + "com-" + found.group(1), updated
            )
        else:
            pattern = re.compile(
                r"(?P<closing></?)" + re.escape(tag_author)
                + r"com(?P<side>-(?:left|right))?>",
                re.I,
            )
            updated = pattern.sub(
                lambda found: (
                    found.group("closing") + target + "com"
                    + (found.group("side") or "") + ">"
                ),
                updated,
            )
            class_pattern = re.compile(
                r"\." + re.escape(tag_author)
                + r"com(?P<side>-(?:left|right))?(?=[\s}])", re.I
            )
            updated = class_pattern.sub(
                lambda found: "." + target + "com"
                + (found.group("side") or ""), updated
            )
    additions = decisions.get("colors", {})
    if additions:
        # {{{ add chosen author colors to the YAML front matter
        match, _, _ = _front_matter(updated)
        color_lines = [
            f'{author}color: "{color}"'
            for author, color in sorted(additions.items())
        ]
        if match:
            body = match.group(2)
            newline = "\r\n" if "\r\n" in updated else "\n"
            if body and not body.endswith("\n"):
                body += newline
            body += newline.join(color_lines)
            updated = (
                updated[:match.start(2)] + body + updated[match.end(2):]
            )
        else:
            newline = "\r\n" if "\r\n" in updated else "\n"
            header = (
                "---" + newline + newline.join(color_lines)
                + newline + "---" + newline
            )
            updated = header + updated
        # }}}
    if updated != original:
        directory = os.path.dirname(os.path.abspath(filename))
        fd, temp_path = tempfile.mkstemp(
            prefix=".cpb-comments-", dir=directory
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fp:
                fp.write(updated)
            os.chmod(temp_path, os.stat(filename).st_mode)
            os.replace(temp_path, filename)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)
    return updated
