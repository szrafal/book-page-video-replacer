from pathlib import Path

import cv2
import numpy as np
import pytest

from src.replacement import (
    ReplacementPipeline,
    ReplacementConfigError,
    auto_replacement_config,
    load_replacement_config,
)


def _image(path: Path, color: tuple[int, int, int] = (40, 120, 220)) -> None:
    image = np.full((120, 180, 3), color, np.uint8)
    cv2.putText(image, "TEST", (24, 72), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    assert cv2.imwrite(str(path), image)


def test_load_pages_yaml_and_null_side(tmp_path: Path) -> None:
    pages = tmp_path / "replacement_pages"
    pages.mkdir()
    _image(pages / "left.png")
    config = pages / "pages.yaml"
    config.write_text(
        "mode: replace\npaper_blend_strength: 0.6\nspreads:\n"
        "  - id: 7\n    left: replacement_pages/left.png\n    right: null\n",
        encoding="utf-8",
    )
    loaded = load_replacement_config(config, pages, tmp_path)
    assert loaded.paper_blend_strength == pytest.approx(0.6)
    assert loaded.spreads[0].id == 7
    assert loaded.spreads[0].left == (pages / "left.png").resolve()
    assert loaded.spreads[0].right is None


def test_missing_image_has_readable_error(tmp_path: Path) -> None:
    pages = tmp_path / "replacement_pages"
    pages.mkdir()
    config = pages / "pages.yaml"
    config.write_text(
        "mode: replace\nspreads:\n  - id: 1\n    left: missing.png\n    right: null\n",
        encoding="utf-8",
    )
    with pytest.raises(ReplacementConfigError, match="Nie znaleziono ilustracji"):
        load_replacement_config(config, pages, tmp_path)


def test_automatic_filename_order(tmp_path: Path) -> None:
    pages = tmp_path / "replacement_pages"
    pages.mkdir()
    _image(pages / "spread_02_right.jpg")
    _image(pages / "spread_01_left.png")
    _image(pages / "spread_02_left.png")
    loaded = auto_replacement_config(pages)
    assert [spread.id for spread in loaded.spreads] == [1, 2]
    assert loaded.spreads[0].left.name == "spread_01_left.png"
    assert loaded.spreads[0].right is None
    assert loaded.spreads[1].right.name == "spread_02_right.jpg"


def test_invalid_blend_strength(tmp_path: Path) -> None:
    pages = tmp_path / "replacement_pages"
    pages.mkdir()
    _image(pages / "left.png")
    config = pages / "pages.yaml"
    config.write_text(
        "mode: replace\npaper_blend_strength: 1.5\nspreads:\n"
        "  - id: 1\n    left: replacement_pages/left.png\n    right: null\n",
        encoding="utf-8",
    )
    with pytest.raises(ReplacementConfigError, match="zakresie 0-1"):
        load_replacement_config(config, pages, tmp_path)


def test_page_fit_keeps_image_aspect_ratio() -> None:
    image = np.full((100, 200, 3), 180, np.uint8)
    quad = np.float32([[0, 0], [500, 0], [500, 900], [0, 900]])
    _, alpha = ReplacementPipeline._fit_image_to_page(image, quad)
    points = cv2.findNonZero(alpha)
    assert points is not None
    _, _, width, height = cv2.boundingRect(points)
    assert width / height == pytest.approx(2.0, rel=0.02)


def test_foreground_hand_like_region_is_kept_at_page_edge() -> None:
    frame = np.full((240, 320, 3), (170, 190, 215), np.uint8)
    cv2.rectangle(frame, (0, 120), (80, 239), (95, 140, 195), -1)
    page = np.full((240, 320), 255, np.uint8)
    foreground = ReplacementPipeline._foreground_occlusion(frame, page)
    assert foreground.shape == page.shape
    assert np.count_nonzero(foreground) > 0


def test_loose_reference_rectangle_is_clipped_inside_page() -> None:
    page = np.float32([[20, 10], [180, 20], [170, 190], [25, 180]])
    loose = np.float32([[-15, -10], [205, 0], [210, 215], [-5, 205]])
    safe = ReplacementPipeline._constrain_region_to_page(loose, page)
    assert safe is not None
    polygon = page.astype(np.float32)
    for point in safe:
        assert cv2.pointPolygonTest(polygon, tuple(float(v) for v in point), False) >= 0
    assert abs(cv2.contourArea(safe)) < abs(cv2.contourArea(page))
