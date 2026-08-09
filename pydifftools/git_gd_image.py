"""In-memory Qt image comparison used by :mod:`pydifftools.git_gd`."""

from __future__ import annotations

import argparse
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from PIL import Image, ImageOps
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QKeyEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

MAX_VIEW_WIDTH = 1200
MAX_VIEW_HEIGHT = 700
ALIGNMENT_MAX_DIMENSION = 192
MIN_SCALE = 0.5
MAX_SCALE = 2.0


@dataclass(frozen=True)
class Alignment:
    scale: float
    translate_x: float
    translate_y: float
    rms_before: float
    rms_after: float


@dataclass(frozen=True)
class ComparisonImages:
    original: Image.Image
    difference: Image.Image
    new: Image.Image
    alignment: Alignment


def load_image(path: str | os.PathLike[str]) -> Image.Image | None:
    """Load one Git difftool side, treating its empty sentinel as missing."""

    image_path = Path(path)
    if (
        str(image_path) == os.devnull
        or not image_path.is_file()
        or image_path.stat().st_size == 0
    ):
        return None

    with Image.open(image_path) as opened:
        opened.seek(0)
        oriented = ImageOps.exif_transpose(opened)
        rgba = oriented.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")


def _black_canvas(size: tuple[int, int]) -> Image.Image:
    return Image.new("RGB", size, (0, 0, 0))


def _paste_on_canvas(
    image: Image.Image | None, size: tuple[int, int]
) -> Image.Image:
    canvas = _black_canvas(size)
    if image is not None:
        canvas.paste(image, (0, 0))
    return canvas


def _transform_image(
    image: Image.Image,
    size: tuple[int, int],
    scale: float,
    translate_x: float,
    translate_y: float,
) -> Image.Image:
    inverse_scale = 1.0 / scale
    return image.transform(
        size,
        Image.Transform.AFFINE,
        (
            inverse_scale,
            0.0,
            -translate_x * inverse_scale,
            0.0,
            inverse_scale,
            -translate_y * inverse_scale,
        ),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(0, 0, 0),
    )


def rgb_rms(first: Image.Image, second: Image.Image) -> float:
    """Return the root-mean-square component difference of two RGB images."""

    first_data = np.asarray(first, dtype=np.float32)
    second_data = np.asarray(second, dtype=np.float32)
    delta = first_data - second_data
    return float(np.sqrt(np.mean(delta * delta)))


def _alignment_thumbnail(
    image: Image.Image, size: tuple[int, int]
) -> Image.Image:
    if image.size == size:
        return image
    return image.resize(size, Image.Resampling.BICUBIC)


def _candidate_scales(
    original_size: tuple[int, int], new_size: tuple[int, int]
) -> list[float]:
    old_width, old_height = original_size
    new_width, new_height = new_size
    ratios = {
        old_width / new_width,
        old_height / new_height,
        math.sqrt((old_width * old_height) / (new_width * new_height)),
    }
    candidates = {0.75 + 0.05 * idx for idx in range(11)}
    candidates.add(1.0)
    candidates.update(ratios)
    return sorted(
        min(MAX_SCALE, max(MIN_SCALE, value)) for value in candidates
    )


def _coordinate_descent(
    original: Image.Image,
    new: Image.Image,
    initial: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    width, height = original.size
    lower_bounds = (MIN_SCALE, -0.5 * width, -0.5 * height)
    upper_bounds = (MAX_SCALE, 0.5 * width, 0.5 * height)

    def objective(parameters: tuple[float, float, float]) -> float:
        transformed = _transform_image(new, original.size, *parameters)
        return rgb_rms(original, transformed)

    best_parameters = initial
    best_rms = objective(best_parameters)
    steps = [0.05, max(1.0, 0.05 * width), max(1.0, 0.05 * height)]

    for _iteration in range(48):
        improved = False
        for axis in range(3):
            for direction in (-1.0, 1.0):
                trial = list(best_parameters)
                trial[axis] = min(
                    upper_bounds[axis],
                    max(
                        lower_bounds[axis],
                        trial[axis] + direction * steps[axis],
                    ),
                )
                trial_parameters = tuple(trial)
                trial_rms = objective(trial_parameters)
                if trial_rms + 1e-9 < best_rms:
                    best_parameters = trial_parameters
                    best_rms = trial_rms
                    improved = True
        if not improved:
            steps = [step / 2.0 for step in steps]
        if steps[0] < 0.0005 and max(steps[1:]) < 0.1:
            break

    return (*best_parameters, best_rms)


def find_alignment(
    original: Image.Image,
    new: Image.Image,
    original_content_size: tuple[int, int],
    new_content_size: tuple[int, int],
) -> Alignment:
    """Approximately minimize RGB RMS over isotropic scale and translation."""

    width, height = original.size
    reduction = min(1.0, ALIGNMENT_MAX_DIMENSION / max(width, height))
    small_size = (
        max(1, round(width * reduction)),
        max(1, round(height * reduction)),
    )
    small_original = _alignment_thumbnail(original, small_size)
    small_new = _alignment_thumbnail(new, small_size)
    rms_before = rgb_rms(small_original, small_new)

    coarse_results: list[tuple[float, float, float, float]] = []
    for scale in _candidate_scales(original_content_size, new_content_size):
        center_x = (
            (original_content_size[0] - scale * new_content_size[0])
            * reduction
            / 2.0
        )
        center_y = (
            (original_content_size[1] - scale * new_content_size[1])
            * reduction
            / 2.0
        )
        offsets_x = (-0.15 * small_size[0], 0.0, 0.15 * small_size[0])
        offsets_y = (-0.15 * small_size[1], 0.0, 0.15 * small_size[1])
        for offset_x in offsets_x:
            for offset_y in offsets_y:
                translate_x = min(
                    0.5 * small_size[0],
                    max(-0.5 * small_size[0], center_x + offset_x),
                )
                translate_y = min(
                    0.5 * small_size[1],
                    max(-0.5 * small_size[1], center_y + offset_y),
                )
                transformed = _transform_image(
                    small_new,
                    small_size,
                    scale,
                    translate_x,
                    translate_y,
                )
                coarse_results.append(
                    (
                        scale,
                        translate_x,
                        translate_y,
                        rgb_rms(small_original, transformed),
                    )
                )

    coarse_results.append((1.0, 0.0, 0.0, rms_before))
    coarse_results.sort(key=lambda result: result[3])
    refined = [
        _coordinate_descent(small_original, small_new, result[:3])
        for result in coarse_results[:3]
    ]
    best_scale, best_x, best_y, best_rms = min(
        refined, key=lambda result: result[3]
    )

    required_improvement = max(0.01, 0.001 * rms_before)
    if rms_before - best_rms < required_improvement:
        return Alignment(1.0, 0.0, 0.0, rms_before, rms_before)
    return Alignment(
        best_scale,
        best_x / reduction,
        best_y / reduction,
        rms_before,
        best_rms,
    )


def prepare_comparison(
    original: Image.Image | None, new: Image.Image | None
) -> ComparisonImages:
    """Build equal-size original, absolute-difference, and aligned images."""

    if original is None and new is None:
        raise ValueError("Neither side contains an image.")

    old_size = original.size if original is not None else (0, 0)
    new_size = new.size if new is not None else (0, 0)
    canvas_size = (
        max(old_size[0], new_size[0]),
        max(old_size[1], new_size[1]),
    )
    original_canvas = _paste_on_canvas(original, canvas_size)
    new_canvas = _paste_on_canvas(new, canvas_size)

    if original is None or new is None:
        rms = rgb_rms(original_canvas, new_canvas)
        alignment = Alignment(1.0, 0.0, 0.0, rms, rms)
        aligned_new = new_canvas
    else:
        alignment = find_alignment(
            original_canvas, new_canvas, original.size, new.size
        )
        aligned_new = _transform_image(
            new_canvas,
            canvas_size,
            alignment.scale,
            alignment.translate_x,
            alignment.translate_y,
        )

    old_data = np.asarray(original_canvas, dtype=np.int16)
    new_data = np.asarray(aligned_new, dtype=np.int16)
    difference = Image.fromarray(np.abs(new_data - old_data).astype(np.uint8))
    return ComparisonImages(
        original_canvas, difference, aligned_new, alignment
    )


def _pil_to_pixmap(image: Image.Image) -> QPixmap:
    rgb = image.convert("RGB")
    raw_data = rgb.tobytes()
    qimage = QImage(
        raw_data,
        rgb.width,
        rgb.height,
        3 * rgb.width,
        QImage.Format.Format_RGB888,
    ).copy()
    return QPixmap.fromImage(qimage)


class ImageDiffWindow(QWidget):
    states = ("Original", "Difference", "New")

    def __init__(self, title: str, comparison: ComparisonImages):
        super().__init__()
        self.file_title = title
        self.current_state = 1

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.up_button = QToolButton(self)
        self.up_button.setArrowType(Qt.ArrowType.UpArrow)
        self.up_button.setToolTip("Show previous image (Up)")
        self.up_button.clicked.connect(self.show_previous)

        self.down_button = QToolButton(self)
        self.down_button.setArrowType(Qt.ArrowType.DownArrow)
        self.down_button.setToolTip("Show next image (Down)")
        self.down_button.clicked.connect(self.show_next)

        controls = QVBoxLayout()
        controls.setContentsMargins(2, 0, 0, 0)
        controls.setSpacing(2)
        controls.addStretch(1)
        controls.addWidget(self.up_button)
        controls.addWidget(self.down_button)
        controls.addStretch(1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.image_label)
        layout.addLayout(controls)

        screen = QApplication.primaryScreen().availableGeometry()
        control_width = self.up_button.sizeHint().width() + 2
        max_image_width = max(
            1, min(MAX_VIEW_WIDTH, screen.width()) - control_width
        )
        max_image_height = max(1, min(MAX_VIEW_HEIGHT, screen.height()))
        source_width, source_height = comparison.original.size
        display_scale = min(
            max_image_width / source_width,
            max_image_height / source_height,
        )
        display_size = (
            max(1, math.floor(source_width * display_scale)),
            max(1, math.floor(source_height * display_scale)),
        )
        images = (
            comparison.original,
            comparison.difference,
            comparison.new,
        )
        self.pixmaps = [
            _pil_to_pixmap(
                image.resize(display_size, Image.Resampling.BICUBIC)
                if image.size != display_size
                else image
            )
            for image in images
        ]
        self.image_label.setFixedSize(*display_size)
        self._show_current()
        self.setFixedSize(self.sizeHint())

    def _show_current(self):
        self.image_label.setPixmap(self.pixmaps[self.current_state])
        self.up_button.setEnabled(self.current_state > 0)
        self.down_button.setEnabled(self.current_state < 2)
        state = self.states[self.current_state]
        self.setWindowTitle(f"git gd image — {state} — {self.file_title}")

    def show_previous(self):
        if self.current_state > 0:
            self.current_state -= 1
            self._show_current()

    def show_next(self):
        if self.current_state < 2:
            self.current_state += 1
            self._show_current()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key.Key_Up:
            self.show_previous()
            return
        if event.key() == Qt.Key.Key_Down:
            self.show_next()
            return
        super().keyPressEvent(event)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="image")
    parser.add_argument("original")
    parser.add_argument("new")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    try:
        comparison = prepare_comparison(
            load_image(arguments.original), load_image(arguments.new)
        )
    except Exception as exc:
        QMessageBox.critical(
            None, "git gd image", f"Failed to compare images:\n{exc}"
        )
        return 1

    window = ImageDiffWindow(arguments.title, comparison)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
