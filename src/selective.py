from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .main import find_input
from .pipeline import BookCleanerPipeline, CleanerState


@dataclass
class Reference:
    name: str
    shape: tuple[int, int]
    keypoints: list
    descriptors: np.ndarray
    foreground_mask: np.ndarray


@dataclass
class DetectedRegion:
    name: str
    quad: np.ndarray
    inliers: int


@dataclass
class SelectiveIllustrationPipeline(BookCleanerPipeline):
    reference_dir: Path = Path("work/illustration_references")

    def __post_init__(self) -> None:
        self._sift = cv2.SIFT_create(nfeatures=3000, contrastThreshold=0.025)
        self._matcher = cv2.FlannBasedMatcher(dict(algorithm=1, trees=5), dict(checks=64))
        self._references: list[Reference] = []
        self._frame_index = 0
        self._tracked_mask: np.ndarray | None = None
        self._previous_gray: np.ndarray | None = None
        self._track_age = 0
        self._last_detected_regions: dict[str, DetectedRegion] = {}
        self._detection_updated = False

    @property
    def backend_name(self) -> str:
        return "sift_reference_homography_selective_inpainting"

    def run(self) -> None:
        self._load_references()
        super().run()

    def _load_references(self) -> None:
        paths = sorted(self.reference_dir.glob("*.png"))
        if not paths:
            raise FileNotFoundError(f"No PNG reference images found in {self.reference_dir}")
        for path in paths:
            image = cv2.imread(str(path))
            if image is None:
                continue
            scale = min(1.0, 600.0 / max(image.shape[:2]))
            resized = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            keypoints, descriptors = self._sift.detectAndCompute(gray, None)
            if descriptors is None or len(keypoints) < 8:
                continue
            mask = self._reference_foreground_mask(resized)
            self._references.append(Reference(path.name, gray.shape, keypoints, descriptors, mask))
        if not self._references:
            raise RuntimeError("Reference images contain too few visual features")

    @staticmethod
    def _reference_foreground_mask(image: np.ndarray) -> np.ndarray:
        # The user-provided crop is authoritative: clean its complete rectangular area.
        return np.full(image.shape[:2], 255, dtype=np.uint8)

    def _clean_frame(
        self, frame: np.ndarray, state: CleanerState, noise: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray, float, bool]:
        index = self._frame_index
        self._frame_index += 1
        height, width = frame.shape[:2]
        tracking_size = (480, int(round(height * 480 / width)))
        tracking_frame = cv2.resize(frame, tracking_size, interpolation=cv2.INTER_AREA)
        tracking_gray = cv2.cvtColor(tracking_frame, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(tracking_frame, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        warm = (h >= 4) & (h <= 42) & (s >= 12) & (s <= 145) & (v >= 82)
        open_page = float(np.count_nonzero(warm)) / warm.size >= 0.075
        if not open_page:
            self._tracked_mask = None
            self._previous_gray = tracking_gray
            self._track_age = 0
            overlay = frame.copy()
            cv2.putText(overlay, "ILLUSTRATIONS: inactive", (24, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 180, 255), 2)
            return frame, overlay, 1.0, False

        tracked = self._flow_mask(self._tracked_mask, self._previous_gray, tracking_gray)
        detect_now = index % 4 == 0 or self._tracked_mask is None
        self._detection_updated = detect_now
        matches = 0
        if detect_now:
            detected, matches = self._detect_mask(frame, tracking_size)
            if matches:
                current_mask = detected
                self._track_age = 0
            elif tracked is not None and self._track_age < 8:
                current_mask = tracked
                self._track_age += 1
            else:
                current_mask = np.zeros(tracking_size[::-1], np.uint8)
                self._track_age += 1
        else:
            current_mask = tracked if tracked is not None else np.zeros(tracking_size[::-1], np.uint8)
            self._track_age += 1
        self._tracked_mask = current_mask
        self._previous_gray = tracking_gray

        if np.count_nonzero(current_mask) < 100:
            overlay = frame.copy()
            cv2.putText(overlay, "ILLUSTRATIONS: searching", (24, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 180, 255), 2)
            return frame, overlay, 0.0, False

        surface = self._paper_surface(frame, current_mask, noise)
        alpha = cv2.resize(current_mask, (width, height), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=3.0, sigmaY=3.0)
        alpha = np.clip(alpha * 1.12, 0.0, 1.0)[:, :, None]
        cleaned = np.clip(frame.astype(np.float32) * (1.0 - alpha) + surface.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
        overlay = frame.copy()
        tint = np.zeros_like(frame)
        tint[:, :, 1] = cv2.resize(current_mask, (width, height), interpolation=cv2.INTER_NEAREST)
        overlay = cv2.addWeighted(overlay, 0.68, tint, 0.32, 0)
        cv2.putText(overlay, f"ILLUSTRATIONS: {matches} matched", (24, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        confidence = min(1.0, 0.55 + 0.12 * matches) if matches else 0.48
        return cleaned, overlay, confidence, True

    def _detect_mask(self, frame: np.ndarray, tracking_size: tuple[int, int]) -> tuple[np.ndarray, int]:
        match_width = 960
        match_height = int(round(frame.shape[0] * match_width / frame.shape[1]))
        image = cv2.resize(frame, (match_width, match_height), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        frame_keypoints, frame_descriptors = self._sift.detectAndCompute(gray, None)
        union = np.zeros((match_height, match_width), np.uint8)
        detected_regions: dict[str, DetectedRegion] = {}
        if frame_descriptors is None:
            self._last_detected_regions = detected_regions
            return cv2.resize(union, tracking_size, interpolation=cv2.INTER_NEAREST), 0
        matched_references = 0
        for reference in self._references:
            pairs = self._matcher.knnMatch(reference.descriptors, frame_descriptors, k=2)
            good = [first for first, second in pairs if first.distance < 0.70 * second.distance]
            if len(good) < 7:
                continue
            source = np.float32([reference.keypoints[m.queryIdx].pt for m in good])
            destination = np.float32([frame_keypoints[m.trainIdx].pt for m in good])
            homography, inliers = cv2.findHomography(source, destination, cv2.RANSAC, 3.0)
            inlier_count = int(inliers.sum()) if inliers is not None else 0
            if homography is None or inlier_count < 14 or inlier_count / len(good) < 0.48:
                continue
            ref_h, ref_w = reference.shape
            corners = cv2.perspectiveTransform(np.float32([[[0, 0], [ref_w, 0], [ref_w, ref_h], [0, ref_h]]]), homography)[0]
            area = abs(cv2.contourArea(corners))
            if not (1000 < area < match_width * match_height * 0.8) or not cv2.isContourConvex(corners.astype(np.int32)):
                continue
            warped = cv2.warpPerspective(reference.foreground_mask, homography, (match_width, match_height), flags=cv2.INTER_LINEAR)
            union = cv2.max(union, warped)
            scale = np.array([tracking_size[0] / match_width, tracking_size[1] / match_height], np.float32)
            detected_regions[reference.name] = DetectedRegion(reference.name, corners.astype(np.float32) * scale, inlier_count)
            matched_references += 1
        self._last_detected_regions = detected_regions
        union = cv2.dilate(union, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        return cv2.resize(union, tracking_size, interpolation=cv2.INTER_AREA), matched_references

    @staticmethod
    def _flow_mask(mask: np.ndarray | None, previous: np.ndarray | None, current: np.ndarray) -> np.ndarray | None:
        if mask is None or previous is None or previous.shape != current.shape:
            return None
        flow = cv2.calcOpticalFlowFarneback(previous, current, None, 0.5, 3, 17, 3, 5, 1.1, 0)
        grid_x, grid_y = np.meshgrid(np.arange(current.shape[1]), np.arange(current.shape[0]))
        map_x = (grid_x - flow[:, :, 0]).astype(np.float32)
        map_y = (grid_y - flow[:, :, 1]).astype(np.float32)
        return cv2.remap(mask, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)

    @staticmethod
    def _paper_surface(frame: np.ndarray, target_mask: np.ndarray, noise: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        small = cv2.resize(frame, (480, target_mask.shape[0]), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
        h, s, v = cv2.split(hsv)
        warm = (h >= 4) & (h <= 42) & (s >= 12) & (s <= 120) & (v >= 88)
        source = lab[warm]
        median_a, median_b = np.median(source[:, 1:3], axis=0) if source.size else (128.0, 142.0)
        distance = np.sqrt((lab[:, :, 1].astype(np.float32) - median_a) ** 2 + (lab[:, :, 2].astype(np.float32) - median_b) ** 2)
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
        seed = (warm & (distance < 15) & (gradient < 42)).astype(np.float32)
        seed[target_mask > 8] = 0.0
        weight = cv2.GaussianBlur(seed, (0, 0), 30.0)
        channels = []
        for channel in cv2.split(small.astype(np.float32)):
            numerator = cv2.GaussianBlur(channel * seed, (0, 0), 30.0)
            channels.append(numerator / np.maximum(weight, 0.018))
        surface = np.clip(cv2.merge(channels), 0, 255)
        values = small[seed > 0.5]
        fallback = np.median(values, axis=0) if values.size else np.array([145, 175, 195])
        unsupported = np.clip((0.055 - weight) / 0.04, 0.0, 1.0)[:, :, None]
        surface = surface * (1.0 - unsupported) + fallback * unsupported
        surface = cv2.resize(surface, (width, height), interpolation=cv2.INTER_CUBIC)
        return np.clip(surface + noise, 0, 255).astype(np.uint8)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Remove only reference illustrations while preserving text and ornaments.")
    parser.add_argument("--input", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path("output/illustrations_removed.mp4"))
    parser.add_argument("--references", type=Path, default=Path("work/illustration_references"))
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--quality", choices=["fast", "balanced", "best"], default="best")
    parser.add_argument("--preview-seconds", type=int, default=0)
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--debug-overlay", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.input or find_input()
    SelectiveIllustrationPipeline(source, args.output, args.device, args.quality, args.preview_seconds,
                                  args.keep_work, args.debug_overlay, args.references).run()


if __name__ == "__main__":
    main()
