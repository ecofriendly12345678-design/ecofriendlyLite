"""
InsightFace buffalo_l face detector + ArcFace alignment.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

_app = None


def _get_app():
    global _app
    if _app is None:
        from insightface.app import FaceAnalysis
        _app = FaceAnalysis(
            name="buffalo_l",
            providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
        )
        _app.prepare(ctx_id=0, det_size=(640, 640))
    return _app


def detect_and_align(
    image_input: str | Path | np.ndarray,
    target_size: int = 256,
) -> np.ndarray:
    """
    Detect and ArcFace-align the largest face in the image.

    Parameters
    ----------
    image_input : file path or BGR numpy array (H, W, 3)
    target_size : output square size in pixels (default 256)

    Returns
    -------
    RGB numpy array of shape (target_size, target_size, 3)

    Raises
    ------
    ValueError : no face detected, confidence too low, or face too small
    """
    if isinstance(image_input, (str, Path)):
        img = cv2.imread(str(image_input))
        if img is None:
            raise ValueError(f"Cannot read image: {image_input}")
    else:
        img = image_input

    app = _get_app()
    faces = app.get(img)

    if not faces:
        raise ValueError("No face detected — check lighting and orientation.")

    # Pick highest-confidence face
    face = max(faces, key=lambda f: f.det_score)

    if face.det_score < 0.7:
        raise ValueError(
            f"Face confidence {face.det_score:.2f} is below threshold 0.70. "
            "Please use a clearer photo."
        )

    h, w = img.shape[:2]
    x1, y1, x2, y2 = face.bbox
    face_area = (x2 - x1) * (y2 - y1)
    if face_area / (h * w) < 0.15:
        raise ValueError(
            f"Face occupies only {face_area / (h * w):.1%} of the frame "
            "(minimum 15%). Please move closer."
        )

    from insightface.utils import face_align
    aligned = face_align.norm_crop(img, landmark=face.kps, image_size=target_size)

    return cv2.cvtColor(aligned, cv2.COLOR_BGR2RGB)
