from pathlib import Path

import numpy as np

from src.pipeline import BookCleanerPipeline, CleanerState


def test_clean_mode_still_passes_non_page_frame_unchanged() -> None:
    pipeline = BookCleanerPipeline(Path("input.mp4"), Path("output.mp4"), quality="fast")
    frame = np.zeros((180, 320, 3), np.uint8)
    noise = np.zeros_like(frame, dtype=np.float32)
    cleaned, _, confidence, active = pipeline._clean_frame(frame, CleanerState(), noise)
    assert not active
    assert confidence == 1.0
    assert np.array_equal(cleaned, frame)
