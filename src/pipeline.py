from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from rich.console import Console
from tqdm import tqdm

console = Console()


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    frames: int
    duration: float
    has_audio: bool


@dataclass
class CleanerState:
    mask_probability: np.ndarray | None = None
    previous_surface: np.ndarray | None = None
    previous_active: bool = False
    active_segments: int = 0
    active_frames: int = 0
    low_confidence: list[tuple[int, float, str]] = field(default_factory=list)


@dataclass
class BookCleanerPipeline:
    input_path: Path
    output_path: Path
    device: str = "auto"
    quality: str = "balanced"
    preview_seconds: int = 0
    keep_work: bool = False
    debug_overlay: bool = False

    @property
    def backend_name(self) -> str:
        return "opencv_normalized_paper_reconstruction"

    def run(self) -> None:
        started = time.monotonic()
        self._ensure_tools()
        metadata = self._probe()
        info = self._video_info(metadata)
        effective_device = self._choose_device()
        if effective_device != "cpu":
            console.print("[yellow]CUDA model disabled for this build; using CPU paper reconstruction.[/yellow]")
            effective_device = "cpu"
        output_dir = self.output_path.parent
        work_dir = Path("work")
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)
        silent_path = work_dir / "cleaned_video_only.mp4"
        debug_name = "debug_overlay.mp4" if self.output_path.stem == "cleaned" else f"{self.output_path.stem}_debug_overlay.mp4"
        debug_path = output_dir / debug_name
        state = self._process_video(info, silent_path, debug_path if self.debug_overlay else None)
        self._mux_audio(silent_path, self.output_path)
        output_meta = self._probe(self.output_path)
        report: dict[str, Any] = {
            "status": "ok", "input": str(self.input_path), "output": str(self.output_path),
            "backend": self.backend_name, "requested_device": self.device,
            "effective_device": effective_device, "quality": self.quality,
            "source": {"duration_seconds": info.duration, "resolution": f"{info.width}x{info.height}",
                       "fps": info.fps, "frames": info.frames, "has_audio": info.has_audio},
            "result_streams": [s.get("codec_type") for s in output_meta.get("streams", [])],
            "page_scene_segments": state.active_segments, "processed_page_frames": state.active_frames,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "debug_overlay": str(debug_path) if self.debug_overlay else None,
        }
        report_name = "report.txt" if self.output_path.stem == "cleaned" else f"{self.output_path.stem}_report.txt"
        review_name = "review_frames.txt" if self.output_path.stem == "cleaned" else f"{self.output_path.stem}_review_frames.txt"
        (output_dir / report_name).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        self._write_review_frames(state, info.fps, output_dir / review_name)
        if not self.keep_work:
            silent_path.unlink(missing_ok=True)
        console.print(f"[bold green]Created:[/bold green] {self.output_path}")

    def _process_video(self, info: VideoInfo, silent_path: Path, debug_path: Path | None) -> CleanerState:
        capture = cv2.VideoCapture(str(self.input_path))
        if not capture.isOpened():
            raise RuntimeError(f"Cannot decode input video: {self.input_path}")
        frame_limit = info.frames
        if self.preview_seconds > 0:
            frame_limit = min(frame_limit, max(1, int(round(self.preview_seconds * info.fps))))
        encoder = self._open_encoder(silent_path, info, frame_limit)
        debug_encoder = self._open_encoder(debug_path, info, frame_limit, crf=22) if debug_path else None
        state = CleanerState()
        noise = self._paper_noise(info.height, info.width)
        try:
            for frame_index in tqdm(range(frame_limit), desc="Cleaning pages", unit="frame"):
                ok, frame = capture.read()
                if not ok:
                    break
                cleaned, overlay, confidence, active = self._clean_frame(frame, state, noise)
                if active:
                    state.active_frames += 1
                    if not state.previous_active:
                        state.active_segments += 1
                    if confidence < 0.62:
                        state.low_confidence.append((frame_index, confidence, "weak paper support or page turn"))
                state.previous_active = active
                encoder.stdin.write(cleaned.tobytes())
                if debug_encoder is not None:
                    debug_encoder.stdin.write(overlay.tobytes())
        finally:
            capture.release()
            self._close_encoder(encoder, "video encoder")
            if debug_encoder is not None:
                self._close_encoder(debug_encoder, "debug encoder")
        return state

    def _clean_frame(self, frame: np.ndarray, state: CleanerState, noise: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, bool]:
        height, width = frame.shape[:2]
        analysis_width = {"fast": 320, "balanced": 400, "best": 480}[self.quality]
        small_h = max(2, int(round(height * analysis_width / width)))
        small = cv2.resize(frame, (analysis_width, small_h), interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        h, s, v = cv2.split(hsv)
        warm = (h >= 4) & (h <= 42) & (s >= 12) & (s <= 145) & (v >= 82)
        neutral = (s < 42) & (v >= 105) & (small[:, :, 2] >= small[:, :, 0])
        candidate = (warm | neutral).astype(np.uint8) * 255
        seed_fraction = float(np.count_nonzero(candidate)) / candidate.size
        warm_fraction = float(np.count_nonzero(warm)) / warm.size
        active = warm_fraction >= 0.075 and seed_fraction >= 0.115
        if not active:
            state.mask_probability = None
            state.previous_surface = None
            overlay = frame.copy()
            cv2.putText(overlay, "PAGE: inactive", (24, 46), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (40, 180, 255), 2)
            return frame, overlay, 1.0, False

        close_size = max(17, int(round(analysis_width * 0.075)) | 1)
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_size, close_size)))
        candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
        contours, _ = cv2.findContours(candidate, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        page_mask = np.zeros_like(candidate)
        kept = [contour for contour in contours if cv2.contourArea(contour) >= candidate.size * 0.012]
        if kept:
            cv2.drawContours(page_mask, kept, -1, 255, thickness=cv2.FILLED)
        # Illustrations sometimes touch the video boundary, so their holes are not enclosed
        # contours.  A per-page convex envelope closes those remaining printed strips while
        # still following the outer silhouette of the left and right sheets.
        for x0, x1 in ((0, analysis_width // 2), (analysis_width // 2, analysis_width)):
            ys, xs = np.nonzero(candidate[:, x0:x1])
            if xs.size >= candidate.size * 0.025:
                points = np.column_stack((xs + x0, ys)).astype(np.int32)
                cv2.fillConvexPoly(page_mask, cv2.convexHull(points), 255)
        erosion = max(3, int(round(analysis_width * 0.008)))
        page_mask = cv2.erode(page_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erosion * 2 + 1,) * 2))
        center = analysis_width // 2
        spine_half = max(2, int(round(analysis_width * 0.0045)))
        page_mask[:, center - spine_half:center + spine_half + 1] = 0
        current_probability = page_mask.astype(np.float32) / 255.0
        if state.mask_probability is None or state.mask_probability.shape != current_probability.shape:
            state.mask_probability = current_probability
        else:
            state.mask_probability = 0.78 * current_probability + 0.22 * state.mask_probability
        stable_mask = (state.mask_probability > 0.38).astype(np.uint8) * 255

        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB)
        chroma_source = lab[warm]
        if chroma_source.size:
            median_a, median_b = np.median(chroma_source[:, 1:3], axis=0)
        else:
            median_a, median_b = 128.0, 142.0
        chroma_distance = np.sqrt((lab[:, :, 1].astype(np.float32) - median_a) ** 2 +
                                  (lab[:, :, 2].astype(np.float32) - median_b) ** 2)
        gradient = cv2.magnitude(cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3))
        paper_seed = ((warm | neutral) & (chroma_distance < 15.0) & (gradient < 42) & (v > 88)).astype(np.float32)
        paper_seed *= (stable_mask > 0).astype(np.float32)
        sigma = {"fast": 18.0, "balanced": 24.0, "best": 30.0}[self.quality]
        weight = cv2.GaussianBlur(paper_seed, (0, 0), sigmaX=sigma, sigmaY=sigma)
        channels = []
        for channel in cv2.split(small.astype(np.float32)):
            numerator = cv2.GaussianBlur(channel * paper_seed, (0, 0), sigmaX=sigma, sigmaY=sigma)
            channels.append(numerator / np.maximum(weight, 0.018))
        surface_small = np.clip(cv2.merge(channels), 0, 255)
        valid_values = small[paper_seed > 0.5]
        fallback = np.median(valid_values, axis=0) if valid_values.size else np.array([145, 175, 195])
        unsupported = np.clip((0.055 - weight) / 0.04, 0.0, 1.0)[:, :, None]
        surface_small = surface_small * (1.0 - unsupported) + fallback * unsupported
        if state.previous_surface is not None and state.previous_surface.shape == surface_small.shape:
            surface_small = 0.82 * surface_small + 0.18 * state.previous_surface
        state.previous_surface = surface_small.copy()
        surface = cv2.resize(surface_small, (width, height), interpolation=cv2.INTER_CUBIC)
        surface = np.clip(surface + noise, 0, 255).astype(np.uint8)
        alpha = cv2.resize(stable_mask, (width, height), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        feather = max(5, int(round(width * 0.004)))
        alpha = np.clip(cv2.GaussianBlur(alpha, (0, 0), sigmaX=feather, sigmaY=feather) * 1.08, 0.0, 1.0)[:, :, None]
        cleaned = np.clip(frame.astype(np.float32) * (1.0 - alpha) + surface.astype(np.float32) * alpha, 0, 255).astype(np.uint8)
        mask_area = max(1, np.count_nonzero(stable_mask))
        confidence = min(1.0, float(np.count_nonzero(paper_seed)) / mask_area * 2.0)
        overlay = frame.copy()
        tint = np.zeros_like(frame)
        tint[:, :, 1] = cv2.resize(stable_mask, (width, height), interpolation=cv2.INTER_NEAREST)
        overlay = cv2.addWeighted(overlay, 0.68, tint, 0.32, 0)
        cv2.putText(overlay, f"PAGE: active  confidence={confidence:.2f}", (24, 46),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        return cleaned, overlay, confidence, True

    @staticmethod
    def _paper_noise(height: int, width: int) -> np.ndarray:
        rng = np.random.default_rng(20260922)
        base = rng.normal(0.0, 1.0, (max(2, height // 4), max(2, width // 4))).astype(np.float32)
        base = cv2.resize(cv2.GaussianBlur(base, (0, 0), 0.7), (width, height), interpolation=cv2.INTER_CUBIC)
        fine = rng.normal(0.0, 0.45, (height, width)).astype(np.float32)
        texture = np.clip(base * 1.15 + fine, -2.2, 2.2)
        return np.repeat(texture[:, :, None], 3, axis=2)

    def _open_encoder(self, path: Path | None, info: VideoInfo, frames: int, crf: int = 18) -> subprocess.Popen:
        if path is None:
            raise ValueError("Encoder path cannot be empty")
        path.parent.mkdir(parents=True, exist_ok=True)
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{info.width}x{info.height}", "-r", f"{info.fps:.9f}", "-i", "-", "-an",
               "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
               "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        if process.stdin is None:
            raise RuntimeError("Could not open FFmpeg input pipe")
        return process

    @staticmethod
    def _close_encoder(process: subprocess.Popen, label: str) -> None:
        if process.stdin is not None:
            process.stdin.close()
        code = process.wait()
        if code != 0:
            raise RuntimeError(f"FFmpeg {label} failed with exit code {code}")

    def _mux_audio(self, video_path: Path, output_path: Path) -> None:
        # Do not use ``-shortest`` here. Phone recordings commonly contain an
        # audio track that ends a few milliseconds before the final video
        # packet; ``-shortest`` would silently discard those last video frames.
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video_path), "-i", str(self.input_path),
               "-map", "0:v:0", "-map", "1:a?", "-c:v", "copy", "-c:a", "copy", "-movflags", "+faststart", str(output_path)]
        subprocess.run(cmd, check=True)

    def _choose_device(self) -> str:
        if self.device == "cpu":
            return "cpu"
        try:
            cp = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], capture_output=True, text=True)
            if cp.returncode == 0 and cp.stdout.strip():
                return "cuda"
        except FileNotFoundError:
            pass
        if self.device == "cuda":
            console.print("[yellow]Requested CUDA, but no NVIDIA CUDA runtime was detected.[/yellow]")
        return "cpu"

    def _ensure_tools(self) -> None:
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise RuntimeError("ffmpeg/ffprobe not found. Run install_windows.ps1 or install a local FFmpeg build.")

    def _probe(self, path: Path | None = None) -> dict[str, Any]:
        target = path or self.input_path
        cp = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(target)],
                            capture_output=True, text=True, check=True)
        return json.loads(cp.stdout)

    @staticmethod
    def _video_info(meta: dict[str, Any]) -> VideoInfo:
        video = next((stream for stream in meta["streams"] if stream.get("codec_type") == "video"), None)
        if video is None:
            raise RuntimeError("Input has no video stream")
        numerator, denominator = (float(value) for value in (video.get("avg_frame_rate") or "30/1").split("/"))
        fps = numerator / denominator if denominator else 30.0
        duration = float(video.get("duration") or meta.get("format", {}).get("duration") or 0.0)
        frames = int(video.get("nb_frames") or math.ceil(duration * fps))
        return VideoInfo(int(video["width"]), int(video["height"]), fps, frames, duration,
                         any(stream.get("codec_type") == "audio" for stream in meta["streams"]))

    @staticmethod
    def _write_review_frames(state: CleanerState, fps: float, path: Path) -> None:
        if not state.low_confidence:
            path.unlink(missing_ok=True)
            return
        indices = sorted({item[0] for item in state.low_confidence})
        runs: list[tuple[int, int]] = []
        start = previous = indices[0]
        for index in indices[1:]:
            if index > previous + 2:
                runs.append((start, previous))
                start = index
            previous = index
        runs.append((start, previous))
        lines = ["Low-confidence page reconstruction intervals (inspect page turns):"]
        lines.extend(f"frames {start}-{end}; seconds {start / fps:.2f}-{end / fps:.2f}" for start, end in runs)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
