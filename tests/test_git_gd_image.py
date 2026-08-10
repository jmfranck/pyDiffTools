import json
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image

from pydifftools.git_gd_image import (
    MESSAGE_HEIGHT,
    _transform_image,
    find_alignment,
    load_image,
    main,
    prepare_comparison,
    rgb_rms,
)


def test_prepare_comparison_uses_absolute_rgb_difference():
    rng = np.random.default_rng(1234)
    original_data = rng.integers(0, 256, (24, 24, 3), dtype=np.uint8)
    new_data = original_data.copy()
    new_data[7, 11] = (10, 80, 210)
    original_data[7, 11] = (40, 20, 200)

    comparison = prepare_comparison(
        Image.fromarray(original_data),
        Image.fromarray(new_data),
    )

    difference = np.asarray(comparison.difference)
    assert comparison.alignment.scale == 1.0
    assert tuple(difference[7, 11]) == (30, 60, 10)
    unchanged = difference.copy()
    unchanged[7, 11] = 0
    assert not np.any(unchanged)


def test_prepare_comparison_black_pads_a_missing_side():
    new = Image.new("RGB", (3, 2), (12, 34, 56))

    comparison = prepare_comparison(None, new)

    assert comparison.original.size == (3, 2)
    assert not np.any(np.asarray(comparison.original))
    assert np.array_equal(
        np.asarray(comparison.difference), np.asarray(comparison.new)
    )


def test_load_image_preserves_transparency(tmp_path):
    path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (1, 1), (100, 60, 20, 128))
    image.save(path)

    loaded = load_image(path)

    assert loaded is not None
    assert loaded.mode == "RGBA"
    assert loaded.getpixel((0, 0)) == (100, 60, 20, 128)


def test_load_image_keeps_an_opaque_source_without_alpha(tmp_path):
    path = tmp_path / "opaque.png"
    Image.new("RGB", (1, 1), (100, 60, 20)).save(path)

    loaded = load_image(path)

    assert loaded is not None
    assert loaded.mode == "RGB"


def test_prepare_comparison_separates_visible_rgb_and_alpha_changes():
    old_data = np.full((16, 64, 4), 255, dtype=np.uint8)
    new_data = old_data.copy()
    old_data[:, :32, 3] = 0
    new_data[:, :32, 3] = 128
    new_data[:, 32:, 3] = 127

    comparison = prepare_comparison(
        Image.fromarray(old_data),
        Image.fromarray(new_data),
    )

    assert not np.any(np.asarray(comparison.difference))
    assert comparison.alpha_difference is not None
    alpha_difference = np.asarray(comparison.alpha_difference)
    assert tuple(alpha_difference[0, 0]) == (127, 127, 255)
    assert tuple(alpha_difference[0, 32]) == (255, 127, 127)
    assert comparison.original.getpixel((0, 0)) == (255, 255, 255)
    assert comparison.original.getpixel((16, 0)) == (208, 208, 208)
    assert comparison.original.getpixel((32, 0)) == (255, 255, 255)
    assert comparison.rgb_score == 0.0
    assert comparison.alpha_score == pytest.approx(100 * 128 / 255)


def test_prepare_comparison_always_checkers_images_with_alpha():
    transparent = Image.new("RGBA", (32, 16), (255, 255, 255, 0))

    comparison = prepare_comparison(transparent, transparent)

    assert comparison.alpha_difference is None
    assert comparison.original.getpixel((0, 0)) == (255, 255, 255)
    assert comparison.original.getpixel((16, 0)) == (208, 208, 208)
    assert np.array_equal(
        np.asarray(comparison.original), np.asarray(comparison.new)
    )


def test_image_scores_are_normalized_rms_values():
    rgb_comparison = prepare_comparison(
        Image.new("RGB", (8, 6), "black"),
        Image.new("RGB", (8, 6), "white"),
        render_display=False,
    )
    alpha_comparison = prepare_comparison(
        Image.new("RGBA", (8, 6), (255, 255, 255, 0)),
        Image.new("RGBA", (8, 6), (255, 255, 255, 255)),
        render_display=False,
    )

    assert rgb_comparison.rgb_score == 100.0
    assert rgb_comparison.alpha_score == 0.0
    assert alpha_comparison.rgb_score == 0.0
    assert alpha_comparison.alpha_score == 100.0


def test_score_cli_prints_machine_readable_scores(tmp_path, capsys):
    original_path = tmp_path / "original.png"
    new_path = tmp_path / "new.png"
    Image.new("RGB", (8, 6), "black").save(original_path)
    Image.new("RGB", (8, 6), "white").save(new_path)

    return_code = main(
        ["--score", str(original_path), str(new_path)]
    )

    assert return_code == 0
    assert json.loads(capsys.readouterr().out) == {
        "rgb": 100.0,
        "alpha": 0.0,
    }


def test_prepare_comparison_aligns_images_with_different_pixel_sizes():
    data = np.full((90, 120, 3), 255, dtype=np.uint8)
    data[12:72, 18:30] = (230, 40, 20)
    data[48:62, 27:100] = (20, 190, 70)
    data[20:38, 65:108] = (60, 80, 240)
    original = Image.fromarray(data)
    resized = original.resize((180, 135), Image.Resampling.BICUBIC)

    comparison = prepare_comparison(original, resized)

    assert comparison.alignment.rms_after < comparison.alignment.rms_before
    assert abs(comparison.alignment.scale - 2 / 3) < 0.03
    assert comparison.size_message == (
        "Pixel dimensions changed: 120 × 90 px → 180 × 135 px."
    )


def test_prepare_comparison_reports_aspect_ratio_change():
    comparison = prepare_comparison(
        Image.new("RGB", (120, 90), "white"),
        Image.new("RGB", (180, 120), "white"),
    )

    assert comparison.size_message == (
        "Pixel dimensions changed: 120 × 90 px → 180 × 120 px; "
        "aspect ratio changed: 1.333 → 1.500."
    )


def test_find_alignment_reduces_rms_for_scale_and_translation():
    data = np.zeros((96, 112, 3), dtype=np.uint8)
    data[12:74, 18:30] = (230, 40, 20)
    data[48:62, 27:91] = (20, 190, 70)
    data[20:38, 65:98] = (60, 80, 240)
    original = Image.fromarray(data)
    moved = _transform_image(original, original.size, 0.9, 7.0, -5.0)

    alignment = find_alignment(original, moved, original.size, moved.size)
    realigned = _transform_image(
        moved,
        original.size,
        alignment.scale,
        alignment.translate_x,
        alignment.translate_y,
    )

    assert alignment.rms_after < alignment.rms_before
    assert rgb_rms(original, realigned) < rgb_rms(original, moved) * 0.55


def test_prepare_comparison_aligns_alpha_with_visible_rgb():
    data = np.zeros((96, 112, 4), dtype=np.uint8)
    data[12:74, 18:30] = (230, 40, 20, 255)
    data[48:62, 27:91] = (20, 190, 70, 180)
    data[20:38, 65:98] = (60, 80, 240, 220)
    original = Image.fromarray(data)
    moved = _transform_image(
        original,
        original.size,
        0.9,
        7.0,
        -5.0,
        fillcolor=(0, 0, 0, 0),
    )

    comparison = prepare_comparison(original, moved)

    assert comparison.alpha_difference is not None
    unaligned_changed = np.mean(
        np.asarray(original)[..., 3] != np.asarray(moved)[..., 3]
    )
    aligned_changed = np.mean(
        np.any(np.asarray(comparison.alpha_difference) != 255, axis=2)
    )
    assert aligned_changed < unaligned_changed * 0.5


def test_image_window_starts_on_diff_and_navigates(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from pydifftools.git_gd_image import ImageDiffWindow

    app = QApplication.instance() or QApplication([])
    comparison = prepare_comparison(
        Image.new("RGB", (10, 8), "black"),
        Image.new("RGB", (10, 8), "white"),
    )
    window = ImageDiffWindow("plot.png", comparison)

    assert window.current_state == 1
    assert "Difference" in window.windowTitle()
    assert window.message_label.text() == ""
    window.show_previous()
    assert window.current_state == 0
    assert not window.up_button.isEnabled()
    window.show_next()
    window.show_next()
    assert window.current_state == 2
    assert not window.down_button.isEnabled()
    window.close()

    old = Image.new("RGBA", (32, 16), (255, 255, 255, 0))
    new = Image.new("RGBA", (32, 16), (255, 255, 255, 128))
    alpha_comparison = prepare_comparison(old, new)
    alpha_window = ImageDiffWindow("transparent.png", alpha_comparison)

    assert alpha_window.states == (
        "Original",
        "Difference",
        "Change in alpha",
        "New",
    )
    assert alpha_window.current_state == 1
    assert alpha_window.message_label.text() == ""
    assert alpha_window.message_label.height() == MESSAGE_HEIGHT
    initial_size = alpha_window.size()
    initial_up_position = alpha_window.up_button.pos()
    initial_down_position = alpha_window.down_button.pos()
    alpha_window.show_next()
    assert alpha_window.current_state == 2
    assert "Change in alpha" in alpha_window.windowTitle()
    assert alpha_window.message_label.text() == (
        "Change in alpha — blue = increased alpha; red = decreased alpha."
    )
    assert alpha_window.size() == initial_size
    assert alpha_window.up_button.pos() == initial_up_position
    assert alpha_window.down_button.pos() == initial_down_position
    alpha_window.show_next()
    assert alpha_window.current_state == 3
    assert not alpha_window.down_button.isEnabled()
    alpha_window.close()

    combined_window = ImageDiffWindow(
        "resized-transparent.png",
        replace(
            alpha_comparison,
            size_message="Pixel dimensions changed: 32 × 16 px → 64 × 32 px.",
        ),
    )
    combined_window.show_next()
    assert combined_window.message_label.text() == (
        "Pixel dimensions changed: 32 × 16 px → 64 × 32 px.\n"
        "Change in alpha — blue = increased alpha; red = decreased alpha."
    )
    combined_window.close()
    assert app is not None
