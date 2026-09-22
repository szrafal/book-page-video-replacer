from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from .pipeline import BookCleanerPipeline, CleanerState
from .selective import DetectedRegion, SelectiveIllustrationPipeline


SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg"}


class ReplacementConfigError(ValueError):
    """A user-facing configuration error."""


@dataclass(frozen=True)
class SpreadAssignment:
    id: int
    left: Path | None
    right: Path | None


@dataclass(frozen=True)
class ReplacementConfig:
    spreads: tuple[SpreadAssignment, ...]
    paper_blend_strength: float = 0.35


def _resolve_image_path(value: Any, config_dir: Path, project_dir: Path) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ReplacementConfigError("Ścieżka ilustracji musi być tekstem albo wartością null.")
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [project_dir / raw, config_dir / raw]
    path = next((candidate.resolve() for candidate in candidates if candidate.is_file()), candidates[0].resolve())
    if path.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
        raise ReplacementConfigError(f"Nieobsługiwany format ilustracji: {value}. Użyj PNG albo JPG.")
    if not path.is_file():
        raise ReplacementConfigError(f"Nie znaleziono ilustracji: {value}")
    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ReplacementConfigError(f"Nie można odczytać ilustracji: {value}")
    return path


def load_replacement_config(
    pages_path: Path | None,
    replacement_dir: Path = Path("replacement_pages"),
    project_dir: Path = Path("."),
) -> ReplacementConfig:
    project_dir = project_dir.resolve()
    replacement_dir = (project_dir / replacement_dir).resolve() if not replacement_dir.is_absolute() else replacement_dir.resolve()
    default_yaml = replacement_dir / "pages.yaml"
    config_path = pages_path
    if config_path is not None and not config_path.is_absolute():
        config_path = (project_dir / config_path).resolve()
    if config_path is None and default_yaml.is_file():
        config_path = default_yaml

    if config_path is None:
        return auto_replacement_config(replacement_dir)
    if not config_path.is_file():
        raise ReplacementConfigError(f"Nie znaleziono pliku konfiguracji: {config_path}")
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ReplacementConfigError(f"Nie można odczytać YAML {config_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReplacementConfigError("Plik pages.yaml musi zawierać mapę z kluczem 'spreads'.")
    if payload.get("mode", "replace") != "replace":
        raise ReplacementConfigError("W pages.yaml ustaw 'mode: replace'.")
    raw_spreads = payload.get("spreads")
    if not isinstance(raw_spreads, list) or not raw_spreads:
        raise ReplacementConfigError("W pages.yaml brakuje niepustej listy 'spreads'.")
    spreads: list[SpreadAssignment] = []
    ids: set[int] = set()
    for position, item in enumerate(raw_spreads, start=1):
        if not isinstance(item, dict):
            raise ReplacementConfigError(f"Rozkładówka nr {position} ma niepoprawny zapis.")
        try:
            spread_id = int(item.get("id", position))
        except (TypeError, ValueError) as exc:
            raise ReplacementConfigError(f"Niepoprawne id rozkładówki nr {position}.") from exc
        if spread_id in ids:
            raise ReplacementConfigError(f"Powtórzone id rozkładówki: {spread_id}")
        ids.add(spread_id)
        spreads.append(SpreadAssignment(
            spread_id,
            _resolve_image_path(item.get("left"), config_path.parent, project_dir),
            _resolve_image_path(item.get("right"), config_path.parent, project_dir),
        ))
    strength = payload.get("paper_blend_strength", 0.35)
    try:
        strength = float(strength)
    except (TypeError, ValueError) as exc:
        raise ReplacementConfigError("paper_blend_strength musi być liczbą od 0 do 1.") from exc
    if not 0.0 <= strength <= 1.0:
        raise ReplacementConfigError("paper_blend_strength musi mieścić się w zakresie 0-1.")
    return ReplacementConfig(tuple(spreads), strength)


def auto_replacement_config(replacement_dir: Path) -> ReplacementConfig:
    if not replacement_dir.is_dir():
        raise ReplacementConfigError(f"Nie znaleziono katalogu z ilustracjami: {replacement_dir}")
    pattern = re.compile(r"^spread_(\d+)_(left|right)\.(png|jpe?g)$", re.IGNORECASE)
    grouped: dict[int, dict[str, Path]] = {}
    for path in sorted(replacement_dir.iterdir()):
        match = pattern.match(path.name)
        if match:
            grouped.setdefault(int(match.group(1)), {})[match.group(2).lower()] = path.resolve()
    if not grouped:
        raise ReplacementConfigError(
            "Nie znaleziono pages.yaml ani plików nazwanych np. spread_01_left.png i spread_01_right.png."
        )
    spreads: list[SpreadAssignment] = []
    for spread_id in sorted(grouped):
        sides = grouped[spread_id]
        left = _resolve_image_path(str(sides.get("left")), replacement_dir, Path(".")) if sides.get("left") else None
        right = _resolve_image_path(str(sides.get("right")), replacement_dir, Path(".")) if sides.get("right") else None
        spreads.append(SpreadAssignment(spread_id, left, right))
    return ReplacementConfig(tuple(spreads))


@dataclass
class ReplacementPipeline(SelectiveIllustrationPipeline):
    pages_path: Path | None = None
    replacement_dir: Path = Path("replacement_pages")
    paper_blend_strength: float | None = None
    create_preview: bool = True
    _config: ReplacementConfig | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        SelectiveIllustrationPipeline.__post_init__(self)
        self._images: dict[Path, np.ndarray] = {}
        self._replacement_frame_index = 0
        self._page_previous_gray: np.ndarray | None = None
        self._previous_page_quads: dict[str, np.ndarray] = {}
        self._region_previous_gray: np.ndarray | None = None
        self._tracked_regions: dict[str, np.ndarray] = {}
        self._region_ages: dict[str, int] = {}
        self._spread_position = 0
        self._spread_signature: np.ndarray | None = None
        self._change_votes = 0
        self._cooldown = 0
        self._turn_seen = False
        self._had_full_spread = False
        self._first_active_frame: int | None = None
        self._preview_written: set[int] = set()
        self._uncertain_transitions: list[int] = []

    @property
    def backend_name(self) -> str:
        return "selective_reference_inpainting_with_tracked_homography_replacement"

    def run(self) -> None:
        self._config = load_replacement_config(self.pages_path, self.replacement_dir)
        if self.paper_blend_strength is not None:
            if not 0.0 <= self.paper_blend_strength <= 1.0:
                raise ReplacementConfigError("--paper-blend-strength musi mieścić się w zakresie 0-1.")
            self._config = ReplacementConfig(self._config.spreads, self.paper_blend_strength)
        for spread in self._config.spreads:
            for path in (spread.left, spread.right):
                if path is not None and path not in self._images:
                    image = cv2.imread(str(path), cv2.IMREAD_COLOR)
                    if image is None:
                        raise ReplacementConfigError(f"Nie można odczytać ilustracji: {path}")
                    self._images[path] = image
        self._load_references()
        (self.output_path.parent / "replacement_preview").mkdir(parents=True, exist_ok=True)
        BookCleanerPipeline.run(self)
        self._augment_report()
        if self.create_preview and self._first_active_frame is not None:
            self._create_preview_video()

    def _clean_frame(
        self, frame: np.ndarray, state: CleanerState, noise: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, float, bool]:
        cleaned, base_overlay, confidence, active = SelectiveIllustrationPipeline._clean_frame(self, frame, state, noise)
        index = self._replacement_frame_index
        self._replacement_frame_index += 1
        tracking_width = 480
        tracking_height = max(2, int(round(frame.shape[0] * tracking_width / frame.shape[1])))
        small = cv2.resize(frame, (tracking_width, tracking_height), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        regions = self._track_reference_regions(gray)
        if not active:
            self._page_previous_gray = gray
            self._previous_page_quads = {}
            self._spread_signature = None
            self._change_votes = 0
            self._turn_seen = False
            self._had_full_spread = False
            return cleaned, base_overlay, confidence, False

        detected = self._detect_page_quads(small)
        quads, motion = self._track_and_stabilize(gray, detected)
        self._page_previous_gray = gray
        self._previous_page_quads = {side: quad.copy() for side, quad in quads.items()}
        if not quads or not regions:
            return cleaned, base_overlay, min(confidence, 0.35), True
        if self._first_active_frame is None:
            self._first_active_frame = index
        self._update_spread(gray, quads, motion, index)
        target_quads = self._regions_by_side(regions, tracking_width)
        composite = self._compose(frame, cleaned, target_quads)
        overlay = composite.copy()
        scale_x = frame.shape[1] / tracking_width
        scale_y = frame.shape[0] / tracking_height
        for side, quad in target_quads.items():
            full_quad = quad * np.array([scale_x, scale_y], np.float32)
            cv2.polylines(overlay, [full_quad.astype(np.int32)], True, (255, 180, 40), 3, cv2.LINE_AA)
            cv2.putText(overlay, side, tuple(full_quad[0].astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 180, 40), 2)
        spread = self._current_spread()
        label = f"REPLACE spread={spread.id if spread else '-'} motion={motion:.1f}"
        cv2.putText(overlay, label, (24, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        if spread is not None and spread.id not in self._preview_written and motion < 4.0:
            preview_path = self.output_path.parent / "replacement_preview" / f"spread_{spread.id:02d}.jpg"
            cv2.imwrite(str(preview_path), composite, [cv2.IMWRITE_JPEG_QUALITY, 92])
            self._preview_written.add(spread.id)
        return composite, overlay, confidence, True

    def _detect_mask(self, frame: np.ndarray, tracking_size: tuple[int, int]) -> tuple[np.ndarray, int]:
        # Reuse strict SIFT/homography matching from the selective cleaner, but
        # rebuild its mask from page-clipped quads. User crops are guidance: they
        # may be slightly loose and must never erase outside the physical sheet.
        _, matched = SelectiveIllustrationPipeline._detect_mask(self, frame, tracking_size)
        if not self._last_detected_regions:
            return np.zeros(tracking_size[::-1], np.uint8), matched
        small = cv2.resize(frame, tracking_size, interpolation=cv2.INTER_AREA)
        pages = self._detect_page_quads(small)
        safe_regions: dict[str, DetectedRegion] = {}
        mask = np.zeros(tracking_size[::-1], np.uint8)
        for name, region in self._last_detected_regions.items():
            side = "left" if float(region.quad[:, 0].mean()) < tracking_size[0] / 2 else "right"
            safe_quad = self._constrain_region_to_page(region.quad, pages.get(side))
            if safe_quad is None:
                continue
            safe_regions[name] = DetectedRegion(name, safe_quad, region.inliers)
            cv2.fillConvexPoly(mask, safe_quad.astype(np.int32), 255, cv2.LINE_AA)
        self._last_detected_regions = safe_regions
        return mask, len(safe_regions)

    @staticmethod
    def _constrain_region_to_page(region: np.ndarray, page: np.ndarray | None) -> np.ndarray | None:
        region = region.astype(np.float32)
        # A small inset protects text and ornamentation that may touch an
        # imprecisely cropped reference rectangle.
        center = region.mean(axis=0)
        region = center + (region - center) * 0.95
        if page is not None:
            normalized = np.float32([[0, 0], [1000, 0], [1000, 1000], [0, 1000]])
            to_page = cv2.getPerspectiveTransform(page.astype(np.float32), normalized)
            from_page = cv2.getPerspectiveTransform(normalized, page.astype(np.float32))
            local = cv2.perspectiveTransform(region.reshape(1, -1, 2), to_page)[0]
            # Keep a 2% safety band inside the detected sheet boundary.
            local[:, 0] = np.clip(local[:, 0], 20.0, 980.0)
            local[:, 1] = np.clip(local[:, 1], 20.0, 980.0)
            region = cv2.perspectiveTransform(local.reshape(1, -1, 2), from_page)[0]
        if not cv2.isContourConvex(region.astype(np.int32)) or abs(cv2.contourArea(region)) < 120.0:
            return None
        return region.astype(np.float32)

    def _track_reference_regions(self, gray: np.ndarray) -> dict[str, np.ndarray]:
        updated: dict[str, np.ndarray] = {}
        detections = self._last_detected_regions if self._detection_updated else {}
        names = set(self._tracked_regions) | set(detections)
        for name in names:
            detected = detections.get(name)
            previous = self._tracked_regions.get(name)
            tracked: np.ndarray | None = None
            if previous is not None and self._region_previous_gray is not None:
                points, status, _ = cv2.calcOpticalFlowPyrLK(
                    self._region_previous_gray, gray, previous.reshape(-1, 1, 2), None,
                    winSize=(31, 31), maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
                )
                if points is not None and status is not None and int(status.sum()) == 4:
                    tracked = points.reshape(4, 2)
            if detected is not None and tracked is not None:
                quad = tracked * 0.74 + detected.quad * 0.26
                self._region_ages[name] = 0
            elif detected is not None:
                quad = detected.quad.copy()
                self._region_ages[name] = 0
            elif tracked is not None and self._region_ages.get(name, 0) < 10:
                quad = tracked
                self._region_ages[name] = self._region_ages.get(name, 0) + 1
            else:
                continue
            if cv2.isContourConvex(quad.astype(np.int32)) and abs(cv2.contourArea(quad)) > gray.size * 0.004:
                updated[name] = quad.astype(np.float32)
        self._tracked_regions = updated
        self._region_previous_gray = gray
        return updated

    @staticmethod
    def _regions_by_side(regions: dict[str, np.ndarray], tracking_width: int) -> dict[str, np.ndarray]:
        result: dict[str, np.ndarray] = {}
        for quad in regions.values():
            side = "left" if float(quad[:, 0].mean()) < tracking_width / 2 else "right"
            if side not in result or abs(cv2.contourArea(quad)) > abs(cv2.contourArea(result[side])):
                result[side] = quad
        return result

    @staticmethod
    def _sort_quad(points: np.ndarray) -> np.ndarray:
        points = points.astype(np.float32)
        result = np.zeros((4, 2), np.float32)
        sums = points.sum(axis=1)
        differences = np.diff(points, axis=1).ravel()
        result[0] = points[np.argmin(sums)]
        result[2] = points[np.argmax(sums)]
        result[1] = points[np.argmin(differences)]
        result[3] = points[np.argmax(differences)]
        return result

    def _detect_page_quads(self, frame: np.ndarray) -> dict[str, np.ndarray]:
        height, width = frame.shape[:2]
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        warm = (h >= 3) & (h <= 43) & (s >= 8) & (s <= 155) & (v >= 68)
        neutral = (s < 48) & (v >= 92) & (frame[:, :, 2] >= frame[:, :, 0] - 5)
        mask = ((warm | neutral).astype(np.uint8) * 255)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        result: dict[str, np.ndarray] = {}
        for side, x0, x1 in (("left", 0, width // 2 + 8), ("right", width // 2 - 8, width)):
            half = np.zeros_like(mask)
            half[:, x0:x1] = mask[:, x0:x1]
            contours, _ = cv2.findContours(half, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if not contours:
                continue
            contour = max(contours, key=cv2.contourArea)
            if cv2.contourArea(contour) < height * width * 0.08:
                continue
            rect = cv2.minAreaRect(cv2.convexHull(contour))
            quad = self._sort_quad(cv2.boxPoints(rect))
            if abs(cv2.contourArea(quad)) < height * width * 0.07:
                continue
            result[side] = quad
        return result

    def _track_and_stabilize(
        self, gray: np.ndarray, detected: dict[str, np.ndarray]
    ) -> tuple[dict[str, np.ndarray], float]:
        result: dict[str, np.ndarray] = {}
        motions: list[float] = []
        for side in ("left", "right"):
            previous = self._previous_page_quads.get(side)
            tracked: np.ndarray | None = None
            if previous is not None and self._page_previous_gray is not None:
                next_points, status, error = cv2.calcOpticalFlowPyrLK(
                    self._page_previous_gray, gray, previous.reshape(-1, 1, 2), None,
                    winSize=(31, 31), maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
                )
                if next_points is not None and status is not None and int(status.sum()) == 4:
                    tracked = next_points.reshape(4, 2)
                    motions.append(float(np.mean(np.linalg.norm(tracked - previous, axis=1))))
            current = detected.get(side)
            if current is not None and tracked is not None:
                quad = tracked * 0.72 + current * 0.28
            elif current is not None:
                quad = current
            elif tracked is not None:
                quad = tracked
            else:
                continue
            if cv2.isContourConvex(quad.astype(np.int32)) and abs(cv2.contourArea(quad)) > gray.size * 0.06:
                result[side] = quad.astype(np.float32)
        return result, float(np.mean(motions)) if motions else 0.0

    @staticmethod
    def _page_signature(gray: np.ndarray, quads: dict[str, np.ndarray]) -> np.ndarray | None:
        signatures: list[np.ndarray] = []
        destination = np.float32([[0, 0], [63, 0], [63, 63], [0, 63]])
        for side in ("left", "right"):
            quad = quads.get(side)
            if quad is None:
                continue
            matrix = cv2.getPerspectiveTransform(quad.astype(np.float32), destination)
            page = cv2.warpPerspective(gray, matrix, (64, 64))
            page = cv2.GaussianBlur(page, (0, 0), 1.5)
            signatures.append(cv2.resize(page, (16, 16), interpolation=cv2.INTER_AREA).astype(np.float32).ravel())
        return np.concatenate(signatures) if signatures else None

    def _update_spread(self, gray: np.ndarray, quads: dict[str, np.ndarray], motion: float, index: int) -> None:
        signature = self._page_signature(gray, quads)
        if signature is None:
            return
        if self._spread_signature is None or self._spread_signature.shape != signature.shape:
            self._spread_signature = signature
            if len(quads) == 2:
                self._had_full_spread = True
            return
        if self._had_full_spread and (motion > 7.0 or len(quads) < 2):
            self._turn_seen = True
        if len(quads) == 2:
            self._had_full_spread = True
        if self._cooldown > 0:
            self._cooldown -= 1
            self._spread_signature = 0.97 * self._spread_signature + 0.03 * signature
            return
        difference = float(np.mean(np.abs(signature - self._spread_signature)))
        if self._turn_seen and len(quads) == 2 and difference > 18.0 and motion < 4.0:
            self._change_votes += 1
        else:
            self._change_votes = max(0, self._change_votes - 1)
        if self._change_votes >= 6:
            self._spread_position += 1
            self._spread_signature = signature
            self._change_votes = 0
            self._cooldown = 18
            self._turn_seen = False
        elif difference > 32.0 and motion > 8.0:
            if not self._uncertain_transitions or index - self._uncertain_transitions[-1] > 20:
                self._uncertain_transitions.append(index)

    def _current_spread(self) -> SpreadAssignment | None:
        assert self._config is not None
        if self._spread_position >= len(self._config.spreads):
            return None
        return self._config.spreads[self._spread_position]

    @staticmethod
    def _inset_quad(quad: np.ndarray, amount: float = 0.01) -> np.ndarray:
        center = quad.mean(axis=0)
        return center + (quad - center) * (1.0 - 2.0 * amount)

    @staticmethod
    def _fit_image_to_page(image: np.ndarray, quad: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        top = float(np.linalg.norm(quad[1] - quad[0]))
        bottom = float(np.linalg.norm(quad[2] - quad[3]))
        left = float(np.linalg.norm(quad[3] - quad[0]))
        right = float(np.linalg.norm(quad[2] - quad[1]))
        aspect = np.clip((top + bottom) / max(1.0, left + right), 0.45, 1.6)
        canvas_h = 1000
        canvas_w = max(450, int(round(canvas_h * aspect)))
        canvas = np.zeros((canvas_h, canvas_w, 3), np.uint8)
        alpha = np.zeros((canvas_h, canvas_w), np.uint8)
        safe_w, safe_h = int(canvas_w * 0.94), int(canvas_h * 0.94)
        scale = min(safe_w / image.shape[1], safe_h / image.shape[0])
        resized_w = max(1, int(round(image.shape[1] * scale)))
        resized_h = max(1, int(round(image.shape[0] * scale)))
        resized = cv2.resize(image, (resized_w, resized_h), interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
        x0 = (canvas_w - resized_w) // 2
        y0 = (canvas_h - resized_h) // 2
        canvas[y0:y0 + resized_h, x0:x0 + resized_w] = resized
        alpha[y0:y0 + resized_h, x0:x0 + resized_w] = 255
        return canvas, alpha

    def _compose(self, original: np.ndarray, cleaned: np.ndarray, quads: dict[str, np.ndarray]) -> np.ndarray:
        spread = self._current_spread()
        if spread is None:
            return cleaned
        height, width = original.shape[:2]
        tracking_height, tracking_width = self._region_previous_gray.shape if self._region_previous_gray is not None else (height, width)
        scale = np.array([width / tracking_width, height / tracking_height], np.float32)
        result = cleaned.astype(np.float32)
        page_union = np.zeros((height, width), np.uint8)
        strength = self._config.paper_blend_strength if self._config is not None else 0.35
        analysis_width = 480
        analysis_height = max(2, int(round(height * analysis_width / width)))
        small_cleaned = cv2.resize(cleaned, (analysis_width, analysis_height), interpolation=cv2.INTER_AREA)
        small_gray = cv2.cvtColor(small_cleaned, cv2.COLOR_BGR2GRAY).astype(np.float32)
        illumination_small = cv2.GaussianBlur(small_gray, (0, 0), 8.5)
        texture_small = np.clip(small_gray - cv2.GaussianBlur(small_gray, (0, 0), 1.4), -16.0, 16.0)
        illumination_base = cv2.resize(illumination_small, (width, height), interpolation=cv2.INTER_CUBIC)
        texture = cv2.resize(texture_small, (width, height), interpolation=cv2.INTER_CUBIC)[:, :, None]
        for side, path in (("left", spread.left), ("right", spread.right)):
            if path is None or side not in quads:
                continue
            quad = self._inset_quad(quads[side]) * scale
            image, alpha_source = self._fit_image_to_page(self._images[path], quad)
            source = np.float32([[0, 0], [image.shape[1] - 1, 0],
                                 [image.shape[1] - 1, image.shape[0] - 1], [0, image.shape[0] - 1]])
            matrix = cv2.getPerspectiveTransform(source, quad.astype(np.float32))
            warped = cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_CUBIC,
                                         borderMode=cv2.BORDER_REFLECT_101).astype(np.float32)
            alpha = cv2.warpPerspective(alpha_source, matrix, (width, height), flags=cv2.INTER_LINEAR)
            alpha = cv2.GaussianBlur(alpha, (0, 0), 1.6)
            page_union = cv2.max(page_union, alpha)
            values = illumination_base[alpha > 20]
            median = float(np.median(values)) if values.size else 170.0
            illumination = np.clip(illumination_base / max(40.0, median), 0.68, 1.28)[:, :, None]
            printed = warped * (1.0 - 0.32 * strength) + warped * illumination * (0.32 * strength)
            printed += texture * (0.72 * strength)
            if strength > 0.72:
                printed = cv2.GaussianBlur(printed, (3, 3), 0.45)
            a = (alpha.astype(np.float32) / 255.0)[:, :, None]
            result = result * (1.0 - a) + np.clip(printed, 0, 255) * a
        foreground = self._foreground_occlusion(original, page_union)
        if np.any(foreground):
            foreground_alpha = cv2.GaussianBlur(foreground, (0, 0), 1.3).astype(np.float32)[:, :, None] / 255.0
            result = result * (1.0 - foreground_alpha) + original.astype(np.float32) * foreground_alpha
        return np.clip(result, 0, 255).astype(np.uint8)

    @staticmethod
    def _foreground_occlusion(frame: np.ndarray, page_union: np.ndarray) -> np.ndarray:
        if not np.any(page_union):
            return np.zeros(frame.shape[:2], np.uint8)
        height, width = frame.shape[:2]
        analysis_width = 480
        analysis_height = max(2, int(round(height * analysis_width / width)))
        small = cv2.resize(frame, (analysis_width, analysis_height), interpolation=cv2.INTER_AREA)
        small_union = cv2.resize(page_union, (analysis_width, analysis_height), interpolation=cv2.INTER_AREA)
        ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
        y, cr, cb = cv2.split(ycrcb)
        skin = ((cr >= 133) & (cr <= 180) & (cb >= 74) & (cb <= 138) & (y >= 45)).astype(np.uint8) * 255
        skin[small_union < 10] = 0
        skin = cv2.morphologyEx(skin, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
        skin = cv2.morphologyEx(skin, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
        count, labels, stats, _ = cv2.connectedComponentsWithStats(skin)
        keep = np.zeros_like(skin)
        mask_height, mask_width = skin.shape
        for label in range(1, count):
            x, y0, w, h, area = stats[label]
            touches_edge = x < mask_width * 0.07 or x + w > mask_width * 0.93 or y0 + h > mask_height * 0.91
            if area >= skin.size * 0.0025 and (touches_edge or area >= skin.size * 0.018):
                keep[labels == label] = 255
        keep = cv2.dilate(keep, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        return cv2.resize(keep, (width, height), interpolation=cv2.INTER_LINEAR)

    def _augment_report(self) -> None:
        report_path = self.output_path.parent / f"{self.output_path.stem}_report.txt"
        if not report_path.is_file() or self._config is None:
            return
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["replacement"] = {
            "configured_spreads": len(self._config.spreads),
            "detected_spreads": self._spread_position + 1,
            "paper_blend_strength": self._config.paper_blend_strength,
            "preview_frames": sorted(self._preview_written),
            "uncertain_transition_frames": self._uncertain_transitions,
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        if self._uncertain_transitions:
            review_path = self.output_path.parent / f"{self.output_path.stem}_replacement_review.txt"
            review_path.write_text(
                "Niepewne przejścia między rozkładówkami (numery klatek):\n" +
                "\n".join(str(index) for index in self._uncertain_transitions) + "\n",
                encoding="utf-8",
            )

    def _create_preview_video(self) -> None:
        metadata = self._video_info(self._probe(self.output_path))
        start = max(0.0, (self._first_active_frame or 0) / metadata.fps - 0.5)
        preview_path = self.output_path.parent / "replaced_preview.mp4"
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{start:.3f}",
            "-i", str(self.output_path), "-t", "12", "-vf", "scale=960:-2", "-c:v", "libx264",
            "-preset", "fast", "-crf", "23", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart",
            str(preview_path),
        ]
        subprocess.run(command, check=True)
