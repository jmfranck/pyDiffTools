import numpy as np
from PIL import Image

from pydifftools.git_gd_image import (
    _transform_image,
    find_alignment,
    load_image,
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


def test_load_image_composites_transparency_over_black(tmp_path):
    path = tmp_path / "transparent.png"
    image = Image.new("RGBA", (1, 1), (100, 60, 20, 128))
    image.save(path)

    loaded = load_image(path)

    assert loaded is not None
    assert loaded.mode == "RGB"
    assert loaded.getpixel((0, 0)) == (50, 30, 10)


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
    window.show_previous()
    assert window.current_state == 0
    assert not window.up_button.isEnabled()
    window.show_next()
    window.show_next()
    assert window.current_state == 2
    assert not window.down_button.isEnabled()
    window.close()
    assert app is not None
