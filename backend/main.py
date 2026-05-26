"""
Face3D FastAPI backend.

Run:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

TMP_DIR = Path("/tmp/models")
TMP_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Face3D API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _decode_upload(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Cannot decode image — ensure it is a valid JPEG or PNG.")
    return img


@app.get("/api/health")
def health():
    try:
        import torch
        gpu = torch.cuda.is_available()
    except ImportError:
        gpu = False
    return {"status": "ok", "gpu": gpu}


@app.post("/api/reconstruct")
async def reconstruct_endpoint(
    front_image: UploadFile = File(...),
    left45_image: Optional[UploadFile] = File(None),
    right45_image: Optional[UploadFile] = File(None),
):
    """
    Run the full detect → reconstruct → export_glb pipeline.

    Returns { job_id, status: "done" } on success.
    The GLB is retrievable via GET /api/model/{job_id}.
    """
    from detect import detect_and_align
    from reconstruct import reconstruct
    from export_glb import export_glb

    job_id = str(uuid.uuid4())
    work_dir = TMP_DIR / job_id
    work_dir.mkdir(parents=True)

    try:
        aligned_images: list[np.ndarray] = []

        uploads = [front_image, left45_image, right45_image]
        labels = ["front", "left45", "right45"]

        for upload, label in zip(uploads, labels):
            if upload is None:
                continue
            raw = await upload.read()
            try:
                bgr = _decode_upload(raw)
                aligned = detect_and_align(bgr)
                aligned_images.append(aligned)
            except ValueError as exc:
                if label == "front":
                    raise HTTPException(
                        status_code=400,
                        detail=f"Front image rejected: {exc}",
                    )
                # 45° images are optional — skip silently if face not found
                continue

        obj_path, tex_path = reconstruct(aligned_images, work_dir)

        glb_path = TMP_DIR / f"{job_id}.glb"
        export_glb(obj_path, tex_path, glb_path)

        return {"job_id": job_id, "status": "done"}

    except HTTPException:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise
    except ValueError as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(exc))
    except Exception as exc:
        shutil.rmtree(work_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {type(exc).__name__}: {exc}",
        )


@app.get("/api/model/{job_id}")
def get_model(job_id: str):
    """Stream the GLB file for a completed reconstruction job."""
    if not job_id.replace("-", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid job_id")

    glb_path = TMP_DIR / f"{job_id}.glb"
    if not glb_path.exists():
        raise HTTPException(status_code=404, detail="Model not found")

    return FileResponse(
        str(glb_path),
        media_type="application/octet-stream",
        filename=f"{job_id}.glb",
        headers={"Content-Disposition": f'attachment; filename="{job_id}.glb"'},
    )
