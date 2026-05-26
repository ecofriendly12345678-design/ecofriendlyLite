"""
OBJ + texture → GLB with 12 morph targets and optional Draco compression.

Architecture (as specified):
  - trimesh  : loads the OBJ and provides vertex normals
  - DracoPy  : compresses base mesh geometry (KHR_draco_mesh_compression)
  - pygltflib: assembles the GLTF structure + adds morph target accessors

Draco + morph targets note:
  Draco may reorder vertices during quantization.  We decode the Draco blob
  immediately, build an original→draco index map via KD-tree, and reorder
  the morph-target delta arrays to match Draco's vertex ordering before
  packing them into the uncompressed portion of the GLTF buffer.

  If DracoPy is not installed the GLB is written uncompressed and a warning
  is emitted.  Install with:  pip install DracoPy
"""
from __future__ import annotations

import io
import warnings
from pathlib import Path

import numpy as np
import trimesh
import pygltflib
from PIL import Image

try:
    import DracoPy
    _HAS_DRACO = True
except ImportError:
    _HAS_DRACO = False
    warnings.warn(
        "DracoPy not installed — GLB will be uncompressed. "
        "Install with: pip install DracoPy",
        stacklevel=1,
    )

# ── Morph target registry ─────────────────────────────────────────────────────

MORPH_TARGETS = [
    "nose_bridge_height",
    "nose_tip_projection",
    "nose_wing_width",
    "eye_corner_outer",
    "eye_height",
    "double_eyelid",
    "jaw_width",
    "chin_length",
    "chin_projection",
    "cheekbone_width",
    "temple_width",
    "lip_fullness",
]


# ── Mesh loading via trimesh ───────────────────────────────────────────────────

def _load_mesh(obj_path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Load OBJ with trimesh.  Returns (vertices, faces, normals, uvs) as float32/uint32.
    trimesh handles the v/vt vertex-split internally so all arrays share the same index.
    """
    loaded = trimesh.load(str(obj_path), process=False, force="mesh")

    if isinstance(loaded, trimesh.Scene):
        # Multiple geometry objects — concatenate
        meshes = list(loaded.geometry.values())
        loaded = trimesh.util.concatenate(meshes)

    vertices = np.array(loaded.vertices, dtype=np.float32)
    faces    = np.array(loaded.faces,    dtype=np.uint32)
    normals  = np.array(loaded.vertex_normals, dtype=np.float32)

    if hasattr(loaded.visual, "uv") and loaded.visual.uv is not None:
        uvs = np.array(loaded.visual.uv, dtype=np.float32)
        uvs[:, 1] = 1.0 - uvs[:, 1]   # flip V-axis for GLTF
    else:
        uvs = np.zeros((len(vertices), 2), dtype=np.float32)

    return vertices, faces, normals, uvs


# ── Morph target displacements ────────────────────────────────────────────────

def _make_morph_deltas(v_norm: np.ndarray, name: str, scale: float) -> np.ndarray:
    """
    Anatomically-motivated vertex displacement for one morph target.
    v_norm  : (N,3) vertices normalised so the longest axis spans [-1,1]
    scale   : half-extent of the original mesh in original units
    Returns (N,3) float32 delta in original (un-normalised) units.
    """
    x, y, z = v_norm[:, 0], v_norm[:, 1], v_norm[:, 2]
    d   = np.zeros_like(v_norm)
    mag = scale * 0.04  # ~4 % of face half-size per unit influence

    def g2(cx, cy, sx, sy):
        return np.exp(-((x - cx)**2 / (2*sx**2)) - ((y - cy)**2 / (2*sy**2)))

    if   name == "nose_bridge_height":  d[:,2]  =  g2(0,.15,.10,.20)*(z>.1)  * mag
    elif name == "nose_tip_projection": d[:,2]  =  g2(0,-.20,.10,.12)*(z>.15)* mag
    elif name == "nose_wing_width":
        w = g2(0,-.18,.18,.10)*(np.abs(x)>.05)*(z>.05)
        d[:,0] = np.sign(x)*w*mag
    elif name == "eye_corner_outer":
        w = g2(0,.22,.40,.07)*(np.abs(x)>.20)
        d[:,0] = np.sign(x)*w*mag*.8;  d[:,1] = w*mag*.4
    elif name == "eye_height":          d[:,1]  =  g2(0,.28,.35,.06)*(z>-.15)*mag*.7
    elif name == "double_eyelid":       d[:,2]  =  g2(0,.26,.28,.025)*(z>-.10)*mag*.5
    elif name == "jaw_width":
        w = g2(0,-.45,.45,.15)*(np.abs(x)>.25)*(y<-.25)
        d[:,0] = np.sign(x)*w*mag*1.2
    elif name == "chin_length":         d[:,1]  = -g2(0,-.68,.15,.08)*(y<-.55)*mag
    elif name == "chin_projection":     d[:,2]  =  g2(0,-.65,.12,.10)*mag*.8
    elif name == "cheekbone_width":
        w = g2(0,.05,.45,.15)*(np.abs(x)>.28)*(y>-.15)
        d[:,0] = np.sign(x)*w*mag*1.1
    elif name == "temple_width":
        w = g2(0,.40,.40,.12)*(np.abs(x)>.25)
        d[:,0] = np.sign(x)*w*mag
    elif name == "lip_fullness":        d[:,2]  =  g2(0,-.38,.22,.07)*(z>0.)*mag*.7

    return d.astype(np.float32)


# ── Draco compression ─────────────────────────────────────────────────────────

def _draco_compress(
    vertices: np.ndarray,
    faces:    np.ndarray,
    normals:  np.ndarray,
) -> tuple[bytes, dict[str, int], np.ndarray]:
    """
    Compress the base mesh with Draco.

    Returns
    -------
    draco_bytes   : compressed binary
    attr_ids      : {"POSITION": 0, "NORMAL": 1, ...} for KHR_draco_mesh_compression
    vertex_remap  : int array of length N_draco; vertex_remap[i] = original vertex index
                    so that morph_delta[vertex_remap] reorders deltas to match Draco output.
    """
    encoded = DracoPy.encode_mesh_to_buffer(
        vertices.flatten().tolist(),
        faces.flatten().tolist(),
        normal=normals.flatten().tolist(),
        quantization_bits=11,
        compression_level=1,   # speed over ratio
    )
    draco_bytes = bytes(encoded)

    # Decode to discover how Draco reordered vertices
    decoded = DracoPy.decode_buffer_to_mesh(draco_bytes)
    draco_verts = np.array(decoded.points, dtype=np.float64).reshape(-1, 3)

    from scipy.spatial import cKDTree
    _, vertex_remap = cKDTree(vertices.astype(np.float64)).query(draco_verts, k=1)

    attr_ids = {"POSITION": 0, "NORMAL": 1}
    return draco_bytes, attr_ids, vertex_remap.astype(np.int64)


# ── GLTF helpers ──────────────────────────────────────────────────────────────

def _pad4(b: bytes) -> bytes:
    r = len(b) % 4
    return b if r == 0 else b + b"\x00" * (4 - r)


def export_glb(obj_path: Path, tex_path: Path | None, out_path: Path) -> Path:
    """
    Full pipeline: OBJ → GLB with morph targets (+ Draco if DracoPy installed).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Load OBJ via trimesh
    vertices, faces, normals, uvs = _load_mesh(obj_path)
    n_verts = len(vertices)
    n_faces = len(faces)

    # 2. Morph target deltas (computed in original vertex order)
    v_min   = vertices.min(0);  v_max = vertices.max(0)
    scale   = float((v_max - v_min).max()) / 2
    v_norm  = (vertices - (v_min + v_max) / 2) / (scale + 1e-8)
    morph_deltas_orig = [_make_morph_deltas(v_norm, n, scale) for n in MORPH_TARGETS]

    # 3. Draco compression (optional)
    use_draco = _HAS_DRACO
    if use_draco:
        try:
            draco_bytes, draco_attr_ids, vertex_remap = _draco_compress(vertices, faces, normals)
            # Reorder morph deltas to match Draco's vertex order
            morph_deltas = [d[vertex_remap] for d in morph_deltas_orig]
            n_draco_verts = len(vertex_remap)
        except Exception as exc:
            warnings.warn(f"Draco compression failed ({exc}); falling back to uncompressed GLB.")
            use_draco = False

    if not use_draco:
        morph_deltas = morph_deltas_orig
        n_draco_verts = n_verts  # unused but keeps mypy happy

    # 4. Texture bytes
    if tex_path and Path(tex_path).exists():
        buf = io.BytesIO()
        Image.open(tex_path).convert("RGB").save(buf, format="JPEG", quality=90)
        tex_bytes: bytes | None = buf.getvalue()
    else:
        tex_bytes = None

    # 5. Pack binary blob
    #    Draco path:    [draco_data | norm | uv | morph×12 | tex?]
    #    No-Draco path: [vert | norm | uv | index | morph×12 | tex?]
    chunks: list[bytes] = []
    if use_draco:
        chunks += [draco_bytes, normals.tobytes(), uvs.tobytes()]
    else:
        chunks += [vertices.tobytes(), normals.tobytes(), uvs.tobytes(),
                   faces.flatten().tobytes()]

    for d in morph_deltas:
        chunks.append(d.tobytes())
    if tex_bytes:
        chunks.append(tex_bytes)

    padded  = [_pad4(c) for c in chunks]
    offsets = []
    off     = 0
    for p in padded:
        offsets.append(off)
        off += len(p)
    blob = b"".join(padded)

    # 6. Build GLTF with pygltflib
    g        = pygltflib.GLTF2()
    g.asset  = pygltflib.Asset(version="2.0", generator="觅美-face3d")
    g.buffers.append(pygltflib.Buffer(byteLength=len(blob)))
    if use_draco:
        g.extensionsUsed     = ["KHR_draco_mesh_compression"]
        g.extensionsRequired = ["KHR_draco_mesh_compression"]

    _bv = 0
    def add_bv(offset, length, target=None):
        nonlocal _bv
        kw = dict(buffer=0, byteOffset=offset, byteLength=length)
        if target is not None:
            kw["target"] = target
        g.bufferViews.append(pygltflib.BufferView(**kw))
        i = _bv;  _bv += 1;  return i

    _ac = 0
    def add_acc(bv, count, ctype, atype, mn=None, mx=None):
        nonlocal _ac
        kw = dict(bufferView=bv, byteOffset=0, componentType=ctype, count=count, type=atype)
        if mn is not None: kw["min"] = mn
        if mx is not None: kw["max"] = mx
        g.accessors.append(pygltflib.Accessor(**kw))
        i = _ac;  _ac += 1;  return i

    def add_stub_acc(count, ctype, atype, mn=None, mx=None):
        """Accessor without bufferView — required for Draco-compressed attributes."""
        nonlocal _ac
        kw = dict(byteOffset=0, componentType=ctype, count=count, type=atype)
        if mn is not None: kw["min"] = mn
        if mx is not None: kw["max"] = mx
        g.accessors.append(pygltflib.Accessor(**kw))
        i = _ac;  _ac += 1;  return i

    AB  = pygltflib.ARRAY_BUFFER
    EAB = pygltflib.ELEMENT_ARRAY_BUFFER
    i   = 0

    if use_draco:
        bv_draco = add_bv(offsets[i], len(chunks[i]));              i += 1
        bv_norm  = add_bv(offsets[i], len(chunks[i]), AB);          i += 1
        bv_uv    = add_bv(offsets[i], len(chunks[i]), AB);          i += 1

        # Stub accessors for Draco-compressed pos + index
        acc_v = add_stub_acc(n_draco_verts, pygltflib.FLOAT, "VEC3",
                             vertices.min(0).tolist(), vertices.max(0).tolist())
        acc_f = add_stub_acc(n_faces * 3, pygltflib.UNSIGNED_INT, "SCALAR")
        # Normal + UV stay uncompressed in regular buffer views
        acc_n = add_acc(bv_norm, n_draco_verts, pygltflib.FLOAT, "VEC3")
        acc_u = add_acc(bv_uv,   n_draco_verts, pygltflib.FLOAT, "VEC2")

        draco_ext = {
            "bufferView": bv_draco,
            "attributes": draco_attr_ids,
        }
    else:
        bv_v = add_bv(offsets[i], len(chunks[i]), AB);  i += 1
        bv_n = add_bv(offsets[i], len(chunks[i]), AB);  i += 1
        bv_u = add_bv(offsets[i], len(chunks[i]), AB);  i += 1
        bv_f = add_bv(offsets[i], len(chunks[i]), EAB); i += 1

        acc_v = add_acc(bv_v, n_verts, pygltflib.FLOAT, "VEC3",
                        vertices.min(0).tolist(), vertices.max(0).tolist())
        acc_f = add_acc(bv_f, n_faces * 3, pygltflib.UNSIGNED_INT, "SCALAR")
        acc_n = add_acc(bv_n, n_verts, pygltflib.FLOAT, "VEC3")
        acc_u = add_acc(bv_u, n_verts, pygltflib.FLOAT, "VEC2")
        draco_ext = None

    # Morph target accessors (always uncompressed)
    morph_accs: list[int] = []
    for d in morph_deltas:
        bv_m  = add_bv(offsets[i], len(chunks[i]), AB);  i += 1
        acc_m = add_acc(bv_m, len(d), pygltflib.FLOAT, "VEC3",
                        d.min(0).tolist(), d.max(0).tolist())
        morph_accs.append(acc_m)

    # Texture
    has_tex = tex_bytes is not None
    if has_tex:
        bv_tex = add_bv(offsets[i], len(chunks[i]))
        g.images.append(pygltflib.Image(bufferView=bv_tex, mimeType="image/jpeg"))
        g.samplers.append(pygltflib.Sampler(
            magFilter=pygltflib.LINEAR,
            minFilter=pygltflib.LINEAR_MIPMAP_LINEAR,
            wrapS=pygltflib.REPEAT,
            wrapT=pygltflib.REPEAT,
        ))
        g.textures.append(pygltflib.Texture(source=0, sampler=0))
        pbr = pygltflib.PbrMetallicRoughness(
            baseColorTexture=pygltflib.TextureInfo(index=0),
            metallicFactor=0.0, roughnessFactor=0.8,
        )
    else:
        pbr = pygltflib.PbrMetallicRoughness(
            baseColorFactor=[0.82, 0.71, 0.60, 1.0],
            metallicFactor=0.0, roughnessFactor=0.8,
        )
    g.materials.append(pygltflib.Material(
        name="face_material", pbrMetallicRoughness=pbr, doubleSided=True,
    ))

    primitive = pygltflib.Primitive(
        attributes=pygltflib.Attributes(
            POSITION=acc_v, NORMAL=acc_n, TEXCOORD_0=acc_u,
        ),
        indices=acc_f,
        material=0,
        targets=[{"POSITION": a} for a in morph_accs],
        extensions={"KHR_draco_mesh_compression": draco_ext} if draco_ext else None,
    )

    g.meshes.append(pygltflib.Mesh(
        name="face",
        primitives=[primitive],
        weights=[0.0] * len(MORPH_TARGETS),
        extras={"targetNames": MORPH_TARGETS},
    ))

    g.nodes.append(pygltflib.Node(mesh=0, name="face_node"))
    g.scenes.append(pygltflib.Scene(nodes=[0], name="scene"))
    g.scene = 0

    g.set_binary_blob(blob)
    g.save(str(out_path))
    return out_path
