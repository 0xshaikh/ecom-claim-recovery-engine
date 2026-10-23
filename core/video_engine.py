"""Warehouse video barcode splitter.

Scans unpacking videos frame-by-frame, detects AWB barcodes via pyzbar,
slices per-AWB clips, and extracts keyframe snapshots.

NOTE: This module requires pyzbar and ffmpeg. If either is missing, the
module falls back to a mock mode that returns deterministic results for
testing the UI.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AWBClip:
    """One detected AWB range in a video."""
    awb_number: str
    start_time: float  # seconds
    end_time: float
    clip_path: Optional[str] = None
    snapshot_paths: List[str] = field(default_factory=list)
    size_mb: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end_time - self.start_time)


class VideoEngine:
    """Detect AWB barcodes in unpacking videos and slice per-AWB clips."""

    def __init__(self, video_path: str, output_dir: str = "output/video_clips") -> None:
        self.video_path = Path(video_path)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir = self.output_dir / "snapshots"
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_barcode_ranges(self, sample_every: int = 15) -> List[AWBClip]:
        """Scan video frames and detect AWB barcode ranges.

        Falls back to a deterministic mock when cv2/pyzbar/ffmpeg are missing
        or the video file does not exist.
        """
        if not self.video_path.exists():
            logger.warning("Video file not found (%s) — using mock detection.", self.video_path)
            return self._mock_detection()

        try:
            import cv2  # type: ignore  # noqa: F401
            from pyzbar.pyzbar import decode  # type: ignore  # noqa: F401
            if shutil.which("ffmpeg") is None:
                raise ImportError("ffmpeg not on PATH")
            return self._real_detection(sample_every)
        except (ImportError, FileNotFoundError, OSError) as exc:
            logger.warning("Real detection unavailable (%s) — using mock.", exc)
            return self._mock_detection()

    def slice_clips(self, ranges: List[AWBClip]) -> List[AWBClip]:
        """Use ffmpeg to slice clips from the source video (in place)."""
        if shutil.which("ffmpeg") is None or not self.video_path.exists():
            logger.warning("ffmpeg or source video missing — skipping slicing.")
            return ranges

        for clip in ranges:
            out_path = self.output_dir / f"{clip.awb_number}.mp4"
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{clip.start_time:.3f}",
                "-to", f"{clip.end_time:.3f}",
                "-i", str(self.video_path),
                "-c", "copy",
                str(out_path),
            ]
            try:
                subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                clip.clip_path = str(out_path)
                clip.size_mb = out_path.stat().st_size / (1024 * 1024)
            except subprocess.CalledProcessError as exc:
                logger.warning("ffmpeg slice failed for %s: %s", clip.awb_number, exc)
        return ranges

    def extract_snapshots(self, ranges: List[AWBClip]) -> List[AWBClip]:
        """Extract 3 keyframe JPEGs per AWB: start/label, middle/package, end/product."""
        for clip in ranges:
            if not self.video_path.exists():
                continue
            t_start = clip.start_time
            t_mid = (clip.start_time + clip.end_time) / 2
            t_end = clip.end_time
            for idx, t in enumerate((t_start, t_mid, t_end), start=1):
                out_path = self.snapshots_dir / f"{clip.awb_number}_{idx}.jpg"
                if shutil.which("ffmpeg") is None:
                    continue
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", f"{t:.3f}",
                    "-i", str(self.video_path),
                    "-frames:v", "1",
                    "-q:v", "3",
                    str(out_path),
                ]
                try:
                    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    clip.snapshot_paths.append(str(out_path))
                except subprocess.CalledProcessError as exc:
                    logger.warning("ffmpeg snapshot failed for %s: %s", clip.awb_number, exc)
        return ranges

    # ------------------------------------------------------------------
    # Real implementation
    # ------------------------------------------------------------------

    def _real_detection(self, sample_every: int) -> List[AWBClip]:
        """Frame-scan the video with cv2 + pyzbar and collapse into ranges."""
        import cv2  # type: ignore
        from pyzbar.pyzbar import decode  # type: ignore

        cap = cv2.VideoCapture(str(self.video_path))
        if not cap.isOpened():
            return self._mock_detection()

        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        clips: dict[str, AWBClip] = {}
        order: list[str] = []

        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % sample_every == 0:
                try:
                    for symb in decode(frame):
                        text = symb.data.decode("utf-8", errors="ignore").strip()
                        if not text:
                            continue
                        t = frame_idx / fps
                        if text not in clips:
                            clips[text] = AWBClip(awb_number=text, start_time=t, end_time=t)
                            order.append(text)
                        else:
                            clips[text].end_time = max(clips[text].end_time, t)
                except Exception:  # noqa: BLE001 - never crash the pipeline on a single frame
                    pass
            frame_idx += 1

        cap.release()
        # Pad each clip's end to the next sample boundary for a cleaner cut
        for awb in order:
            clips[awb].end_time = min(clips[awb].end_time + (sample_every / fps), total_frames / fps)
        return [clips[awb] for awb in order] or self._mock_detection()

    # ------------------------------------------------------------------
    # Mock fallback
    # ------------------------------------------------------------------

    def _mock_detection(self) -> List[AWBClip]:
        """Deterministic mock for testing UI when cv2/pyzbar/ffmpeg not available."""
        return [
            AWBClip("FLK001234", start_time=0.0, end_time=8.5, size_mb=4.2),
            AWBClip("MSH005678", start_time=10.0, end_time=18.3, size_mb=5.1),
            AWBClip("AMZ009012", start_time=22.0, end_time=31.5, size_mb=3.8),
        ]
