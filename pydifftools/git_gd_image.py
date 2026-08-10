"""In-memory Qt image comparison used by :mod:`pydifftools.git_gd`."""

from __future__ import annotations

import argparse
import json
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
MESSAGE_HEIGHT = 40
ALIGNMENT_MAX_DIMENSION = 192
ALIGNMENT_SKIP_RMS = 0.5
MIN_SCALE = 0.5
MAX_SCALE = 2.0
OPAQUE_WHITE = (255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)
CHECKER_LIGHT = (255, 255, 255)
CHECKER_DARK = (208, 208, 208)
CHECKER_SIZE = 16
ALPHA_MESSAGE = (
    "Change in alpha — blue = increased alpha; red = decreased alpha."
)


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
    size_message: str | None
    alpha_difference: Image.Image | None
    rgb_score: float
    alpha_score: float


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
        if "A" in oriented.getbands() or "transparency" in opened.info:
            return oriented.convert("RGBA")
        return oriented.convert("RGB")


def _has_alpha(image: Image.Image | None) -> bool:
    return image is not None and (
        "A" in image.getbands() or "transparency" in image.info
    )


def _canvas(
    size: tuple[int, int], color: tuple[int, int, int] = OPAQUE_WHITE
) -> Image.Image:
    return Image.new("RGB", size, color)


def _paste_on_canvas(
    image: Image.Image | None, size: tuple[int, int]
) -> Image.Image:
    canvas = _canvas(size)
    if image is not None:
        canvas.paste(image, (0, 0))
    return canvas


def _composite_over_white(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (*OPAQUE_WHITE, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _rgba_canvas(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    canvas = Image.new("RGBA", size, TRANSPARENT)
    canvas.alpha_composite(image.convert("RGBA"))
    return canvas


def _checkerboard(size: tuple[int, int]) -> Image.Image:
    width, height = size
    x_dark = (np.arange(width) // CHECKER_SIZE) % 2
    y_dark = (np.arange(height) // CHECKER_SIZE) % 2
    dark_squares = x_dark[np.newaxis, :] != y_dark[:, np.newaxis]
    checker_data = np.full((height, width, 3), CHECKER_LIGHT, dtype=np.uint8)
    checker_data[dark_squares] = CHECKER_DARK
    return Image.fromarray(checker_data).convert("RGBA")


def _composite_over_checkerboard(
    image: Image.Image, checkerboard: Image.Image
) -> Image.Image:
    checkerboard = checkerboard.copy()
    checkerboard.alpha_composite(image.convert("RGBA"))
    return checkerboard.convert("RGB")


def _transform_image(
    image: Image.Image,
    size: tuple[int, int],
    scale: float,
    translate_x: float,
    translate_y: float,
    fillcolor: tuple[int, ...] = OPAQUE_WHITE,
    resample: Image.Resampling = Image.Resampling.BICUBIC,
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
        resample=resample,
        fillcolor=fillcolor,
    )


def _size_message(
    original_size: tuple[int, int], new_size: tuple[int, int]
) -> str | None:
    if original_size == new_size:
        return None

    old_width, old_height = original_size
    new_width, new_height = new_size
    message = (
        "Pixel dimensions changed: "
        f"{old_width} × {old_height} px → {new_width} × {new_height} px"
    )
    if old_width * new_height != new_width * old_height:
        old_aspect = old_width / old_height
        new_aspect = new_width / new_height
        message += (
            "; aspect ratio changed: "
            f"{old_aspect:.3f} → {new_aspect:.3f}"
        )
    return message + "."


def rgb_rms(first: Image.Image, second: Image.Image) -> float:
    """Return the root-mean-square component difference of two RGB images."""

    first_data = np.asarray(first, dtype=np.float32)
    return _rgb_rms_against(first_data, second)


def _rgb_rms_against(
    first_data: np.ndarray, second: Image.Image
) -> float:
    second_data = np.asarray(second, dtype=np.float32)
    second_data -= first_data
    np.square(second_data, out=second_data)
    return float(np.sqrt(np.mean(second_data)))


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
    candidates = {0.75 + 0.1 * idx for idx in range(6)}
    candidates.add(1.0)
    candidates.update(ratios)
    return sorted(
        min(MAX_SCALE, max(MIN_SCALE, value)) for value in candidates
    )


def _coordinate_descent(
    original: Image.Image,
    original_data: np.ndarray,
    new: Image.Image,
    initial: tuple[float, float, float],
) -> tuple[float, float, float, float]:
    width, height = original.size
    lower_bounds = (MIN_SCALE, -0.5 * width, -0.5 * height)
    upper_bounds = (MAX_SCALE, 0.5 * width, 0.5 * height)

    def objective(parameters: tuple[float, float, float]) -> float:
        transformed = _transform_image(
            new,
            original.size,
            *parameters,
            resample=Image.Resampling.BILINEAR,
        )
        return _rgb_rms_against(original_data, transformed)

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
    small_original_data = np.asarray(small_original, dtype=np.float32)
    rms_before = _rgb_rms_against(small_original_data, small_new)
    if rms_before < ALIGNMENT_SKIP_RMS:
        return Alignment(1.0, 0.0, 0.0, rms_before, rms_before)

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
                    resample=Image.Resampling.BILINEAR,
                )
                coarse_results.append(
                    (
                        scale,
                        translate_x,
                        translate_y,
                        _rgb_rms_against(
                            small_original_data, transformed
                        ),
                    )
                )

    coarse_results.append((1.0, 0.0, 0.0, rms_before))
    coarse_results.sort(key=lambda result: result[3])
    best_scale, best_x, best_y, best_rms = _coordinate_descent(
        small_original,
        small_original_data,
        small_new,
        coarse_results[0][:3],
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


def _is_identity_alignment(alignment: Alignment) -> bool:
    return (
        alignment.scale == 1.0
        and alignment.translate_x == 0.0
        and alignment.translate_y == 0.0
    )


def _normalized_rms(delta: np.ndarray) -> float:
    flattened = delta.ravel()
    squared_sum = np.einsum(
        "i,i->", flattened, flattened, dtype=np.float64
    )
    return 100.0 * math.sqrt(squared_sum / flattened.size) / 255.0


def prepare_comparison(
    original: Image.Image | None,
    new: Image.Image | None,
    *,
    render_display: bool = True,
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
    original_visible = (
        _composite_over_white(original) if original is not None else None
    )
    new_visible = _composite_over_white(new) if new is not None else None
    original_canvas = _paste_on_canvas(original_visible, canvas_size)
    new_canvas = _paste_on_canvas(new_visible, canvas_size)
    alpha_difference = None
    display_on_checkerboard = _has_alpha(original) or _has_alpha(new)

    if original is None or new is None:
        if original is None:
            original_canvas = _canvas(canvas_size, (0, 0, 0))
        else:
            new_canvas = _canvas(canvas_size, (0, 0, 0))
        rms = rgb_rms(original_canvas, new_canvas)
        alignment = Alignment(1.0, 0.0, 0.0, rms, rms)
        aligned_new = new_canvas
        size_message = None
    else:
        alignment = find_alignment(
            original_canvas, new_canvas, original.size, new.size
        )
        if _is_identity_alignment(alignment):
            aligned_new = new_canvas
        else:
            candidate_new = _transform_image(
                new_canvas,
                canvas_size,
                alignment.scale,
                alignment.translate_x,
                alignment.translate_y,
            )
            full_rms_before = rgb_rms(original_canvas, new_canvas)
            full_rms_after = rgb_rms(original_canvas, candidate_new)
            if full_rms_after < full_rms_before:
                aligned_new = candidate_new
            else:
                alignment = Alignment(
                    1.0,
                    0.0,
                    0.0,
                    full_rms_before,
                    full_rms_before,
                )
                aligned_new = new_canvas
        size_message = _size_message(original.size, new.size)

    # {{{ calculate normalized RGB and alpha RMS scores
    old_data = np.asarray(original_canvas, dtype=np.float32)
    new_data = np.asarray(aligned_new, dtype=np.float32)
    rgb_delta = new_data - old_data
    rgb_score = _normalized_rms(rgb_delta)
    difference = Image.fromarray(np.abs(rgb_delta).astype(np.uint8))

    original_rgba = (
        _rgba_canvas(original, canvas_size)
        if original is not None
        else Image.new("RGBA", canvas_size, TRANSPARENT)
    )
    new_rgba = (
        _rgba_canvas(new, canvas_size)
        if new is not None
        else Image.new("RGBA", canvas_size, TRANSPARENT)
    )
    if (
        original is not None
        and new is not None
        and not _is_identity_alignment(alignment)
    ):
        aligned_new_rgba = _transform_image(
            new_rgba,
            canvas_size,
            alignment.scale,
            alignment.translate_x,
            alignment.translate_y,
            fillcolor=TRANSPARENT,
        )
    else:
        aligned_new_rgba = new_rgba
    old_alpha = np.asarray(original_rgba, dtype=np.float32)[..., 3]
    new_alpha = np.asarray(aligned_new_rgba, dtype=np.float32)[..., 3]
    alpha_delta = new_alpha - old_alpha
    alpha_score = _normalized_rms(alpha_delta)
    # }}}

    if render_display:
        if (
            original is not None
            and new is not None
            and display_on_checkerboard
            and np.any(alpha_delta)
        ):
            alpha_data = np.full(
                (*reversed(canvas_size), 3), 255, dtype=np.uint8
            )
            increased = np.clip(alpha_delta, 0, 255).astype(np.uint8)
            decreased = np.clip(-alpha_delta, 0, 255).astype(np.uint8)
            alpha_data[..., 0] -= increased
            alpha_data[..., 1] -= np.maximum(increased, decreased)
            alpha_data[..., 2] -= decreased
            alpha_difference = Image.fromarray(alpha_data)

        if display_on_checkerboard:
            checkerboard = _checkerboard(canvas_size)
            if original is not None:
                original_canvas = _composite_over_checkerboard(
                    original_rgba, checkerboard
                )
            if new is not None:
                aligned_new = _composite_over_checkerboard(
                    aligned_new_rgba, checkerboard
                )

    return ComparisonImages(
        original_canvas,
        difference,
        aligned_new,
        alignment,
        size_message,
        alpha_difference,
        rgb_score,
        alpha_score,
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
    def __init__(self, title: str, comparison: ComparisonImages):
        super().__init__()
        self.file_title = title
        self.current_state = 1
        if comparison.alpha_difference is None:
            self.states = ("Original", "Difference", "New")
            images = (
                comparison.original,
                comparison.difference,
                comparison.new,
            )
            self.alpha_state = None
        else:
            self.states = (
                "Original",
                "Difference",
                "Change in alpha",
                "New",
            )
            images = (
                comparison.original,
                comparison.difference,
                comparison.alpha_difference,
                comparison.new,
            )
            self.alpha_state = 2
        self.size_message = comparison.size_message

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

        image_layout = QHBoxLayout()
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(0)
        image_layout.addWidget(self.image_label)
        image_layout.addLayout(controls)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.message_label = QLabel(self)
        self.message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.message_label.setMargin(6)
        self.message_label.setFixedHeight(MESSAGE_HEIGHT)
        layout.addWidget(self.message_label)
        layout.addLayout(image_layout)

        screen = QApplication.primaryScreen().availableGeometry()
        control_width = self.up_button.sizeHint().width() + 2
        max_image_width = max(
            1, min(MAX_VIEW_WIDTH, screen.width()) - control_width
        )
        max_image_height = max(
            1, min(MAX_VIEW_HEIGHT, screen.height()) - MESSAGE_HEIGHT
        )
        source_width, source_height = comparison.original.size
        display_scale = min(
            max_image_width / source_width,
            max_image_height / source_height,
        )
        display_size = (
            max(1, math.floor(source_width * display_scale)),
            max(1, math.floor(source_height * display_scale)),
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
        self.down_button.setEnabled(self.current_state < len(self.states) - 1)
        state = self.states[self.current_state]
        messages = []
        if self.size_message is not None:
            messages.append(self.size_message)
        if self.current_state == self.alpha_state:
            messages.append(ALPHA_MESSAGE)
        self.message_label.setText("\n".join(messages))
        self.setWindowTitle(f"git gd image — {state} — {self.file_title}")

    def show_previous(self):
        if self.current_state > 0:
            self.current_state -= 1
            self._show_current()

    def show_next(self):
        if self.current_state < len(self.states) - 1:
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
    parser.add_argument("--score", action="store_true")
    parser.add_argument("original")
    parser.add_argument("new")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    app = (
        None
        if arguments.score
        else QApplication.instance() or QApplication(sys.argv[:1])
    )
    try:
        comparison = prepare_comparison(
            load_image(arguments.original),
            load_image(arguments.new),
            render_display=not arguments.score,
        )
    except Exception as exc:
        if arguments.score:
            print(f"Failed to compare images: {exc}", file=sys.stderr)
        else:
            QMessageBox.critical(
                None, "git gd image", f"Failed to compare images:\n{exc}"
            )
        return 1

    if arguments.score:
        print(
            json.dumps(
                {
                    "rgb": comparison.rgb_score,
                    "alpha": comparison.alpha_score,
                }
            )
        )
        return 0

    assert app is not None
    window = ImageDiffWindow(arguments.title, comparison)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
