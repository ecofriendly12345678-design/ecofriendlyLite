"""
Deep3DFaceRecon_pytorch wrapper with multi-image coefficient averaging.

Single image  → subprocess call (simple, robust).
Multiple images → run each with --save_coeff, load coefficient .mat files via
                  scipy, average id + tex shape coefficients, then regenerate
                  the mesh using Deep3DFaceRecon's BFM Python API directly.

Assumes Deep3DFaceRecon_pytorch is cloned at:
    backend/Deep3DFaceRecon_pytorch/
See README.md for checkpoint and BFM setup.
"""
from __future__ import annotations

import os
import sys
import shutil
import subprocess
from pathlib import Path

import cv2
import numpy as np
import scipy.io

DEEP3D_DIR = Path(__file__).parent / "Deep3DFaceRecon_pytorch"
_RECON_NAME = "facerecon"
_EPOCH      = 20


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cuda_available() -> bool:
    try:
        import torch
        return torch.cuda.is_available()
    except ImportError:
        return False


def _setup_path() -> None:
    p = str(DEEP3D_DIR)
    if p not in sys.path:
        sys.path.insert(0, p)


def _gpu_flags() -> str:
    return "0" if _cuda_available() else "-1"


def _check_repo() -> None:
    if not DEEP3D_DIR.exists():
        raise RuntimeError(
            f"Deep3DFaceRecon_pytorch not found at {DEEP3D_DIR}.\n"
            "Run:  git clone https://github.com/sicxu/Deep3DFaceRecon_pytorch "
            "backend/Deep3DFaceRecon_pytorch"
        )


def _write_input_image(img_rgb: np.ndarray, folder: Path, name: str = "face") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    img_224 = cv2.resize(img_rgb, (224, 224), interpolation=cv2.INTER_AREA)
    img_bgr = cv2.cvtColor(img_224, cv2.COLOR_RGB2BGR)
    out = folder / f"{name}.png"
    cv2.imwrite(str(out), img_bgr)
    return out


def _run_deep3d(img_folder: Path, save_folder: Path, save_coeff: bool = False) -> None:
    cmd = [
        sys.executable, "test.py",
        f"--img_folder={img_folder}",
        f"--save_folder={save_folder}",
        f"--gpu_ids={_gpu_flags()}",
        f"--name={_RECON_NAME}",
        f"--epoch={_EPOCH}",
    ]
    if save_coeff:
        cmd.append("--save_coeff")

    result = subprocess.run(
        cmd,
        cwd=str(DEEP3D_DIR),
        capture_output=True,
        text=True,
        timeout=180,
        env={**os.environ},
    )
    if result.returncode != 0:
        tail = lambda s: s[-3000:]
        raise RuntimeError(
            f"Deep3DFaceRecon failed (exit {result.returncode}):\n"
            f"stdout: {tail(result.stdout)}\nstderr: {tail(result.stderr)}"
        )


def _find_outputs(search_root: Path) -> tuple[Path, Path | None, Path | None]:
    """Return (obj_path, tex_path, coeff_path) from the Deep3DFaceRecon output tree."""
    expected = search_root / _RECON_NAME / f"epoch_{_EPOCH}_output"
    root     = expected if expected.exists() else search_root

    obj_files   = sorted(root.rglob("*.obj"))
    coeff_files = sorted(root.rglob("*_coeff.mat"))

    if not obj_files:
        raise RuntimeError(
            f"No .obj file found under {search_root}. "
            f"Contents: {list(search_root.rglob('*'))}"
        )

    obj_path = obj_files[0]
    tex_candidates = [
        obj_path.with_name(obj_path.stem + "_color.png"),
        obj_path.with_suffix(".png"),
        *obj_path.parent.glob("*.png"),
    ]
    tex_path   = next((p for p in tex_candidates if p.exists()), None)
    coeff_path = coeff_files[0] if coeff_files else None

    return obj_path, tex_path, coeff_path


# ── Single-image path (subprocess) ───────────────────────────────────────────

def _reconstruct_one(img_rgb: np.ndarray, work_dir: Path) -> tuple[Path, Path | None]:
    img_dir  = work_dir / "input_imgs"
    save_dir = work_dir / "recon_output"
    save_dir.mkdir(parents=True, exist_ok=True)

    _write_input_image(img_rgb, img_dir)
    _run_deep3d(img_dir, save_dir)

    obj_path, tex_path, _ = _find_outputs(save_dir)
    return obj_path, tex_path


# ── Multi-image path: average coefficients then regenerate mesh ───────────────

def _load_coeff_mat(path: Path) -> dict[str, np.ndarray]:
    mat = scipy.io.loadmat(str(path))
    return {k: np.array(v, dtype=np.float32) for k, v in mat.items()
            if not k.startswith("__")}


def _average_coeffs(mats: list[dict[str, np.ndarray]]) -> dict[str, np.ndarray]:
    """
    Average id (shape) and tex (texture) coefficients across all views.
    Keep exp, angle, gamma, trans from the front image (index 0).
    """
    avg = dict(mats[0])                         # start with front-image values
    for key in ("id", "tex"):
        if key in avg:
            avg[key] = np.mean([m[key] for m in mats if key in m], axis=0)
    return avg


def _save_averaged_coeff(coeffs: dict[str, np.ndarray], path: Path) -> None:
    scipy.io.savemat(str(path), coeffs)


def _mesh_from_coeff(
    coeff_path: Path,
    work_dir:   Path,
) -> tuple[Path, Path | None]:
    """
    Use Deep3DFaceRecon's BFM Python API to generate an OBJ from a coefficient
    .mat file, bypassing the full test.py pipeline.

    This function adds DEEP3D_DIR to sys.path and imports from
    models.bfm.bfm — the standard Deep3DFaceRecon module layout.
    """
    import torch

    _setup_path()
    from models.bfm.bfm import ParametricFaceModel          # type: ignore[import]

    device = torch.device("cuda:0" if _cuda_available() else "cpu")

    bfm = ParametricFaceModel(
        bfm_folder=str(DEEP3D_DIR / "BFM"),
        default_name="BFM_model_front.mat",
        recenter=True,
        camera_distance=10.0,
        focal=1015.0,
        center=112.0,
    ).to(device)
    bfm.eval()

    coeffs = _load_coeff_mat(coeff_path)

    def t(key: str) -> torch.Tensor:
        v = coeffs.get(key, np.zeros((1, 1), dtype=np.float32))
        return torch.tensor(v, dtype=torch.float32, device=device)

    with torch.no_grad():
        id_coeff  = t("id")      # (1, 80)
        exp_coeff = t("exp")     # (1, 64)
        tex_coeff = t("tex")     # (1, 80)
        angles    = t("angle")   # (1, 3)
        gamma     = t("gamma")   # (1, 27)
        trans     = t("trans")   # (1, 3)

        face_shape = bfm.compute_shape(id_coeff, exp_coeff)   # (1, N, 3)
        rotation   = bfm.compute_rotation(angles)             # (1, 3, 3)
        face_shape = bfm.transform(face_shape, rotation, trans)
        face_shape = bfm.to_camera(face_shape)
        face_color = bfm.compute_color(tex_coeff, face_shape, gamma)  # (1, N, 3)
        face_norm  = bfm.compute_norm(face_shape)

    verts  = face_shape.squeeze(0).cpu().numpy()  # (N, 3)
    colors = face_color.squeeze(0).cpu().numpy()  # (N, 3) in [0,1]
    faces  = bfm.face_buf.cpu().numpy()           # (F, 3) 0-indexed

    obj_path = work_dir / "averaged_face.obj"
    tex_path = work_dir / "averaged_face_vertex_color.png"

    # Write OBJ with vertex colours baked as vertex-colour (no UV needed here;
    # the fallback in export_glb will use baseColorFactor if tex_path missing)
    with open(obj_path, "w") as f:
        f.write(f"# averaged from {len(coeffs)} views\n")
        for v, c in zip(verts, colors):
            r, g, b = np.clip(c, 0, 1)
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f} {r:.4f} {g:.4f} {b:.4f}\n")
        for tri in faces + 1:                                # OBJ is 1-indexed
            f.write(f"f {tri[0]} {tri[1]} {tri[2]}\n")

    # Bake vertex colours to a tiny texture so export_glb can use it
    _bake_vertex_color_texture(verts, colors, faces, tex_path)

    return obj_path, tex_path


def _bake_vertex_color_texture(
    verts:    np.ndarray,
    colors:   np.ndarray,
    faces:    np.ndarray,
    out_path: Path,
    size:     int = 512,
) -> None:
    """Rasterise vertex colours onto a small UV-unwrapped texture image (simple planar UV)."""
    from PIL import Image as PILImage

    canvas = np.zeros((size, size, 3), dtype=np.uint8)

    # Planar UV: normalise X and Y to [0,1]
    x, y = verts[:, 0], verts[:, 1]
    u = (x - x.min()) / (x.max() - x.min() + 1e-8)
    v = 1 - (y - y.min()) / (y.max() - y.min() + 1e-8)  # flip Y

    px = (u * (size - 1)).astype(int)
    py = (v * (size - 1)).astype(int)

    # Paint each vertex colour
    for i in range(len(verts)):
        r, g, b = (np.clip(colors[i], 0, 1) * 255).astype(np.uint8)
        canvas[py[i], px[i]] = [r, g, b]

    PILImage.fromarray(canvas).save(str(out_path))


def _reconstruct_multi(
    images:   list[np.ndarray],
    work_dir: Path,
) -> tuple[Path, Path | None]:
    """
    Run Deep3DFaceRecon on each view with --save_coeff, average id+tex,
    then generate the final mesh from averaged coefficients using the BFM API.
    Falls back to front-image-only if coefficient files are not found.
    """
    coeff_mats: list[dict] = []

    for i, img_rgb in enumerate(images):
        sub_dir      = work_dir / f"view_{i}"
        img_dir      = sub_dir / "input_imgs"
        save_dir     = sub_dir / "recon_output"
        save_dir.mkdir(parents=True, exist_ok=True)

        label = {0: "front", 1: "left45", 2: "right45"}.get(i, str(i))
        _write_input_image(img_rgb, img_dir, name=label)
        _run_deep3d(img_dir, save_dir, save_coeff=True)

        _, _, coeff_path = _find_outputs(save_dir)
        if coeff_path:
            coeff_mats.append(_load_coeff_mat(coeff_path))

    if len(coeff_mats) < 2:
        # --save_coeff not supported by this Deep3DFaceRecon version, or only
        # one image succeeded — fall back to front image subprocess result.
        obj_dir  = work_dir / "view_0" / "recon_output"
        obj_path, tex_path, _ = _find_outputs(obj_dir)
        return obj_path, tex_path

    avg_coeffs     = _average_coeffs(coeff_mats)
    avg_coeff_path = work_dir / "averaged_coeff.mat"
    _save_averaged_coeff(avg_coeffs, avg_coeff_path)

    mesh_dir = work_dir / "averaged_mesh"
    mesh_dir.mkdir(exist_ok=True)
    return _mesh_from_coeff(avg_coeff_path, mesh_dir)


# ── Public API ────────────────────────────────────────────────────────────────

def reconstruct(
    aligned_images: list[np.ndarray],
    work_dir:       Path,
) -> tuple[Path, Path | None]:
    """
    Reconstruct a 3D face mesh from 1–3 aligned RGB face images (256×256).

    Single image  → subprocess inference (fast, simple).
    Multiple images → extract per-view BFM coefficients, average id+tex shape
                      coefficients, generate mesh from the averaged values.

    Returns (obj_path, tex_path).  tex_path may be None if no texture was found.
    """
    _check_repo()

    if not aligned_images:
        raise ValueError("At least one aligned face image is required.")

    if len(aligned_images) == 1:
        return _reconstruct_one(aligned_images[0], work_dir)

    return _reconstruct_multi(aligned_images, work_dir)
