# face3d-app

3D facial aesthetics analysis platform — similar to lianjue.net.

**Stack:** FastAPI · Deep3DFaceRecon_pytorch · InsightFace · Three.js (Phase 2)

---

## Quick-start (Phase 1 backend only)

### 1. Conda environment

```bash
conda create -n face3d python=3.9 -y
conda activate face3d

# PyTorch with CUDA 11.8  (adjust for your CUDA version)
conda install pytorch==2.0.1 torchvision==0.15.2 pytorch-cuda=11.8 \
    -c pytorch -c nvidia -y

# CPU-only alternative:
# conda install pytorch==2.0.1 torchvision==0.15.2 cpuonly -c pytorch -y
```

### 2. Python dependencies

```bash
cd backend
pip install -r requirements.txt

# GPU machines: replace onnxruntime with onnxruntime-gpu
pip uninstall onnxruntime -y
pip install onnxruntime-gpu
```

### 3. Install Deep3DFaceRecon_pytorch

```bash
# From the repo root
git clone https://github.com/sicxu/Deep3DFaceRecon_pytorch \
    backend/Deep3DFaceRecon_pytorch
cd backend/Deep3DFaceRecon_pytorch
pip install -r requirements.txt
```

#### 3a. Download pretrained checkpoints

```bash
# Inside backend/Deep3DFaceRecon_pytorch/
mkdir -p checkpoints/facerecon

# Download from the project's Google Drive (see their README for the link),
# then place the files so the directory looks like:
#   checkpoints/facerecon/
#     epoch_20_net_Recon.pth
```

#### 3b. Download Basel Face Model (BFM)

```bash
# Inside backend/Deep3DFaceRecon_pytorch/
mkdir -p BFM

# 1. Register at https://faces.dmi.unibas.ch/bfm/main.php
# 2. Download "01_MorphableModel.mat"
# 3. Run the conversion script provided by Deep3DFaceRecon:
python convert_BFM.py   # produces BFM/BFM_model_front.mat
```

### 4. Download InsightFace buffalo_l model

InsightFace downloads it automatically on first run.  To pre-download:

```bash
python - <<'EOF'
from insightface.app import FaceAnalysis
app = FaceAnalysis(name="buffalo_l")
app.prepare(ctx_id=0, det_size=(640, 640))
print("buffalo_l ready")
EOF
```

### 5. Environment

```bash
cp backend/.env.example backend/.env
# Edit .env if needed (no keys required for Phase 1)
```

### 6. Run the backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Health check:

```bash
curl http://localhost:8000/api/health
# {"status":"ok","gpu":true}
```

### 7. Test end-to-end with a photo

```bash
curl -X POST http://localhost:8000/api/reconstruct \
  -F "front_image=@/path/to/your/photo.jpg" \
  | python -m json.tool
# {"job_id":"<uuid>","status":"done"}

# Download the GLB
curl http://localhost:8000/api/model/<uuid> -o face.glb
```

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| `GET`  | `/api/health` | Liveness check; reports GPU availability |
| `POST` | `/api/reconstruct` | Upload photo → detect → reconstruct → GLB |
| `GET`  | `/api/model/{job_id}` | Stream the generated GLB |

### POST /api/reconstruct

**Form fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `front_image` | ✅ | Front-facing photo (JPG/PNG, max 10 MB) |
| `left45_image` | ❌ | Left 45° photo (improves reconstruction) |
| `right45_image` | ❌ | Right 45° photo (improves reconstruction) |

**Response:**
```json
{ "job_id": "550e8400-e29b-...", "status": "done" }
```

**Error codes:**
- `400` — face not detected, confidence too low, or face too small
- `500` — reconstruction or export failed (check server logs)

---

## Project structure

```
face3d-app/
  backend/
    main.py          FastAPI app — three endpoints
    detect.py        InsightFace buffalo_l detector + ArcFace alignment
    reconstruct.py   Deep3DFaceRecon_pytorch subprocess wrapper
    export_glb.py    OBJ → GLB with 12 anatomical morph targets
    requirements.txt
    .env.example
  frontend/          Phase 2 (React + Vite + Three.js)
  README.md
```

### Morph targets (12 total, range -1 to 1)

| Target | Description |
|--------|-------------|
| `nose_bridge_height` | Raise / lower the nasal bridge |
| `nose_tip_projection` | Project / retract the nose tip |
| `nose_wing_width` | Expand / narrow the nostrils |
| `eye_corner_outer` | Extend / retract outer canthi |
| `eye_height` | Open / close palpebral fissure |
| `double_eyelid` | Deepen the upper eyelid crease |
| `jaw_width` | Widen / narrow the jaw angle |
| `chin_length` | Lengthen / shorten the chin |
| `chin_projection` | Project / retract the chin |
| `cheekbone_width` | Widen / narrow the zygomatic arch |
| `temple_width` | Widen / narrow the temples |
| `lip_fullness` | Increase / reduce lip volume |

---

## Phase 2 — Frontend (React + Vite + TypeScript)

### Setup

```bash
# From repo root
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install @react-three/fiber @react-three/drei three
npm install -D tailwindcss postcss autoprefixer @types/three
npx tailwindcss init -p
```

### Dev server

```bash
cd frontend
npm run dev          # starts on http://localhost:5173
```

Vite proxies `/api/*` to the FastAPI backend.  Add to `frontend/vite.config.ts`:

```ts
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
})
```

### Run backend + frontend concurrently

Install `concurrently` once:

```bash
npm install -g concurrently
```

Then from the repo root:

```bash
concurrently \
  "cd backend && uvicorn main:app --reload --port 8000" \
  "cd frontend && npm run dev"
```

Or add a `package.json` at the repo root:

```json
{
  "scripts": {
    "dev": "concurrently \"cd backend && uvicorn main:app --reload --port 8000\" \"cd frontend && npm run dev\""
  },
  "devDependencies": {
    "concurrently": "^8.0.0"
  }
}
```

Then just `npm run dev`.

### Components to implement

| File | Spec |
|------|------|
| `Uploader.tsx` | Drag-and-drop upload for front + 45° photos; POST to `/api/reconstruct`; poll until done |
| `Viewer3D.tsx` | R3F canvas, `useGLTF`, `OrbitControls` (enablePan=false, dist 1.5–5), ambient + directional light |
| `MorphSliders.tsx` | 12 sliders −100→100 mapped to `morphTargetInfluences`; grouped by Nose / Eyes / Jaw / Contour; Reset all |
| `MeasureTool.tsx` | Raycasting click-to-place points; distance in mm (1 unit = 170 mm); right-click removes nearest |
| `ReferenceLines.tsx` | 三庭五眼 overlay; MediaPipe landmarks → THREE.Line objects; color #4CAF50, opacity 0.7 |

---

## Known limitations (Phase 1)

- Morph target vertex displacements are anatomically motivated but not derived from a clinical dataset. Real displacements should come from BFM shape PCA modes in a future version.
- Models are stored in `/tmp/models` and are not persisted across server restarts.
- `_bake_vertex_color_texture` in `reconstruct.py` uses a simple planar UV projection; a proper UV unwrap would improve texture quality for the averaged mesh path.
