# Face3D Frontend (Phase 2 + 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the React + Vite + TypeScript frontend for the face3d-app: photo upload, 3D GLB viewer with morph-target sliders, click-to-measure raycasting, and 三庭五眼 reference line overlay.

**Architecture:** All state lives in `App.tsx` (useState); components receive props and callbacks. The Three.js mesh is accessed via a ref passed through props. Morph-target manipulation is entirely client-side (no server round-trips after GLB load). The backend proxy in Vite routes `/api/*` to `localhost:8000`.

**Tech Stack:** React 18 · TypeScript · Vite · Tailwind CSS · @react-three/fiber · @react-three/drei · Three.js · @mediapipe/tasks-vision · Vitest · @testing-library/react

---

## File Map

| Path | Responsibility |
|------|---------------|
| `frontend/vite.config.ts` | Vite dev server + `/api` proxy to `:8000` |
| `frontend/src/main.tsx` | React root mount |
| `frontend/src/App.tsx` | All shared state; three-column layout |
| `frontend/src/types.ts` | Shared TypeScript types |
| `frontend/src/components/Uploader.tsx` | Three drag-and-drop upload zones |
| `frontend/src/components/Viewer3D.tsx` | R3F canvas: face mesh + orbit + lights |
| `frontend/src/components/MorphSliders.tsx` | 12 grouped sliders → morphTargetInfluences |
| `frontend/src/components/MeasureTool.tsx` | Click-to-place points, distance in mm |
| `frontend/src/components/ReferenceLines.tsx` | MediaPipe landmarks → THREE.Line overlay |
| `frontend/src/components/__tests__/*.test.tsx` | Vitest + RTL component tests |
| `frontend/src/lib/mediapipe.ts` | Lazy MediaPipe FaceLandmarker loader |
| `frontend/src/lib/measure.ts` | Pure distance / nearest-point utilities |

---

## Task 1: Project Scaffold

**Files:**
- Create: `frontend/` (Vite project)
- Create: `frontend/vite.config.ts`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/src/main.tsx`

- [ ] **Step 1: Scaffold Vite project**

```bash
cd /Users/shenyi/Desktop/face3d-app
npm create vite@latest frontend -- --template react-ts
cd frontend
```

- [ ] **Step 2: Install runtime dependencies**

```bash
npm install @react-three/fiber @react-three/drei three @mediapipe/tasks-vision
```

- [ ] **Step 3: Install dev dependencies**

```bash
npm install -D tailwindcss postcss autoprefixer \
  @types/three \
  vitest @vitest/ui @testing-library/react @testing-library/jest-dom \
  @testing-library/user-event jsdom
npx tailwindcss init -p
```

- [ ] **Step 4: Configure Tailwind** — edit `frontend/tailwind.config.js`

```js
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: { extend: {} },
  plugins: [],
}
```

- [ ] **Step 5: Add Tailwind directives** — replace `frontend/src/index.css`

```css
@tailwind base;
@tailwind components;
@tailwind utilities;
```

- [ ] **Step 6: Configure Vite proxy + Vitest** — replace `frontend/vite.config.ts`

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
```

- [ ] **Step 7: Create test setup file** — `frontend/src/test-setup.ts`

```ts
import '@testing-library/jest-dom'
```

- [ ] **Step 8: Add test script** — edit `frontend/package.json`, add to `"scripts"`:

```json
"test": "vitest run",
"test:watch": "vitest",
"test:ui": "vitest --ui"
```

- [ ] **Step 9: Smoke test that Vite builds**

```bash
npm run build
```

Expected: `dist/` created, no errors.

- [ ] **Step 10: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: scaffold React + Vite + Tailwind + Vitest frontend"
```

---

## Task 2: Shared Types

**Files:**
- Create: `frontend/src/types.ts`

- [ ] **Step 1: Write the types**

```ts
// frontend/src/types.ts
import * as THREE from 'three'

export interface MeasurePoint {
  id: string
  pos: THREE.Vector3
  label: string
}

export type Phase = 'upload' | 'viewing'

export const MORPH_TARGETS = [
  'nose_bridge_height',
  'nose_tip_projection',
  'nose_wing_width',
  'eye_corner_outer',
  'eye_height',
  'double_eyelid',
  'jaw_width',
  'chin_length',
  'chin_projection',
  'cheekbone_width',
  'temple_width',
  'lip_fullness',
] as const

export type MorphTargetName = typeof MORPH_TARGETS[number]

export const MORPH_LABELS: Record<MorphTargetName, string> = {
  nose_bridge_height:  '山根高度',
  nose_tip_projection: '鼻尖投影',
  nose_wing_width:     '鼻翼宽度',
  eye_corner_outer:    '外眼角',
  eye_height:          '眼裂高度',
  double_eyelid:       '双眼皮',
  jaw_width:           '下颌角宽度',
  chin_length:         '下巴长度',
  chin_projection:     '下巴前突',
  cheekbone_width:     '颧骨宽度',
  temple_width:        '太阳穴宽度',
  lip_fullness:        '嘴唇丰满度',
}

export const MORPH_GROUPS: Record<string, MorphTargetName[]> = {
  'Nose 鼻部':         ['nose_bridge_height', 'nose_tip_projection', 'nose_wing_width'],
  'Eyes 眼部':         ['eye_corner_outer', 'eye_height', 'double_eyelid'],
  'Jaw & Chin 下颌':   ['jaw_width', 'chin_length', 'chin_projection'],
  'Contour 轮廓':      ['cheekbone_width', 'temple_width', 'lip_fullness'],
}
```

- [ ] **Step 2: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/types.ts
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: add shared TypeScript types"
```

---

## Task 3: Measure Utilities

**Files:**
- Create: `frontend/src/lib/measure.ts`
- Create: `frontend/src/components/__tests__/measure.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// frontend/src/components/__tests__/measure.test.ts
import { describe, it, expect } from 'vitest'
import * as THREE from 'three'
import { calcDistanceMm, findNearestPoint } from '../../lib/measure'
import type { MeasurePoint } from '../../types'

describe('calcDistanceMm', () => {
  it('returns 0 for same point', () => {
    const a = new THREE.Vector3(0, 0, 0)
    expect(calcDistanceMm(a, a)).toBe(0)
  })

  it('converts 1 unit to 170 mm', () => {
    const a = new THREE.Vector3(0, 0, 0)
    const b = new THREE.Vector3(1, 0, 0)
    expect(calcDistanceMm(a, b)).toBeCloseTo(170)
  })

  it('calculates 3D distance correctly', () => {
    const a = new THREE.Vector3(0, 0, 0)
    const b = new THREE.Vector3(3, 4, 0)  // 5-unit hypotenuse
    expect(calcDistanceMm(a, b)).toBeCloseTo(850)
  })
})

describe('findNearestPoint', () => {
  const pts: MeasurePoint[] = [
    { id: '1', pos: new THREE.Vector3(0, 0, 0), label: '' },
    { id: '2', pos: new THREE.Vector3(10, 0, 0), label: '' },
    { id: '3', pos: new THREE.Vector3(5, 0, 0),  label: '' },
  ]

  it('returns null for empty list', () => {
    expect(findNearestPoint([], new THREE.Vector3())).toBeNull()
  })

  it('finds the nearest point', () => {
    const click = new THREE.Vector3(4, 0, 0)
    expect(findNearestPoint(pts, click)?.id).toBe('3')
  })
})
```

- [ ] **Step 2: Run — expect failure**

```bash
cd frontend && npx vitest run src/components/__tests__/measure.test.ts
```

Expected: FAIL — `measure` module not found.

- [ ] **Step 3: Implement**

```ts
// frontend/src/lib/measure.ts
import * as THREE from 'three'
import type { MeasurePoint } from '../types'

const MM_PER_UNIT = 170

export function calcDistanceMm(a: THREE.Vector3, b: THREE.Vector3): number {
  return a.distanceTo(b) * MM_PER_UNIT
}

export function findNearestPoint(
  points: MeasurePoint[],
  target: THREE.Vector3,
): MeasurePoint | null {
  if (points.length === 0) return null
  return points.reduce((best, p) =>
    p.pos.distanceTo(target) < best.pos.distanceTo(target) ? p : best
  )
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/measure.test.ts
```

Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/lib/measure.ts \
  frontend/src/components/__tests__/measure.test.ts
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: measure utility with distance and nearest-point helpers"
```

---

## Task 4: Uploader Component

**Files:**
- Create: `frontend/src/components/Uploader.tsx`
- Create: `frontend/src/components/__tests__/Uploader.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/components/__tests__/Uploader.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Uploader } from '../Uploader'

const makeFile = (name: string, type: string, size: number) => {
  const f = new File(['x'.repeat(size)], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

describe('Uploader', () => {
  const onSubmit = vi.fn()

  it('renders three drop zones', () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    expect(screen.getByText(/正面/)).toBeInTheDocument()
    expect(screen.getByText(/左侧 45°/)).toBeInTheDocument()
    expect(screen.getByText(/右侧 45°/)).toBeInTheDocument()
  })

  it('submit button is disabled when front image not selected', () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    expect(screen.getByRole('button', { name: /生成/ })).toBeDisabled()
  })

  it('rejects non-image files with error message', async () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    const input = screen.getAllByTestId('file-input')[0]
    const bad = makeFile('doc.pdf', 'application/pdf', 1024)
    await userEvent.upload(input, bad)
    expect(screen.getByText(/JPG 或 PNG/)).toBeInTheDocument()
  })

  it('rejects files over 10 MB', async () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    const input = screen.getAllByTestId('file-input')[0]
    const big = makeFile('face.jpg', 'image/jpeg', 11 * 1024 * 1024)
    await userEvent.upload(input, big)
    expect(screen.getByText(/10 MB/)).toBeInTheDocument()
  })

  it('enables submit and calls onSubmit with front file', async () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    const input = screen.getAllByTestId('file-input')[0]
    const good = makeFile('face.jpg', 'image/jpeg', 1024)
    await userEvent.upload(input, good)
    const btn = screen.getByRole('button', { name: /生成/ })
    expect(btn).not.toBeDisabled()
    fireEvent.click(btn)
    expect(onSubmit).toHaveBeenCalledWith(good, null, null)
  })
})
```

- [ ] **Step 2: Run — expect failure**

```bash
npx vitest run src/components/__tests__/Uploader.test.tsx
```

Expected: FAIL — `Uploader` module not found.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/Uploader.tsx
import { useRef, useState } from 'react'

interface DropZoneProps {
  label: string
  required?: boolean
  onFile: (f: File | null) => void
  testId?: string
}

function DropZone({ label, required, onFile, testId }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const validate = (f: File): string | null => {
    if (!['image/jpeg', 'image/png'].includes(f.type)) return '请选择 JPG 或 PNG 文件'
    if (f.size > 10 * 1024 * 1024) return '文件不能超过 10 MB'
    return null
  }

  const handle = (f: File) => {
    const err = validate(f)
    if (err) { setError(err); onFile(null); return }
    setError(null)
    setPreview(URL.createObjectURL(f))
    onFile(f)
  }

  return (
    <div className="flex flex-col items-center gap-1 w-full">
      <div
        className="w-full h-32 border-2 border-dashed border-gray-300 rounded-lg flex flex-col items-center justify-center cursor-pointer hover:border-blue-400 relative overflow-hidden"
        onClick={() => inputRef.current?.click()}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handle(f) }}
      >
        {preview
          ? <img src={preview} className="object-cover w-full h-full absolute inset-0" alt="preview" />
          : <span className="text-sm text-gray-400">{label}{required && ' *'}</span>
        }
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png"
        className="hidden"
        data-testid={testId}
        onChange={e => { const f = e.target.files?.[0]; if (f) handle(f) }}
      />
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  )
}

interface UploaderProps {
  onSubmit: (front: File, left45: File | null, right45: File | null) => void
  isLoading: boolean
}

export function Uploader({ onSubmit, isLoading }: UploaderProps) {
  const [front,  setFront]  = useState<File | null>(null)
  const [left45, setLeft45] = useState<File | null>(null)
  const [right45,setRight45]= useState<File | null>(null)

  return (
    <div className="flex flex-col gap-4 p-4">
      <h2 className="text-lg font-semibold">上传照片</h2>
      <DropZone label="正面"    required onFile={setFront}   testId="file-input" />
      <DropZone label="左侧 45°"         onFile={setLeft45}  testId="file-input" />
      <DropZone label="右侧 45°"         onFile={setRight45} testId="file-input" />
      <p className="text-xs text-gray-500">* 正面为必填；侧面可提升重建质量</p>
      <button
        className="mt-2 px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
        disabled={!front || isLoading}
        onClick={() => front && onSubmit(front, left45, right45)}
      >
        {isLoading ? '生成中…' : '生成 3D 模型'}
      </button>
    </div>
  )
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/Uploader.test.tsx
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/components/Uploader.tsx \
  frontend/src/components/__tests__/Uploader.test.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: Uploader component with validation and preview thumbnails"
```

---

## Task 5: MorphSliders Component

**Files:**
- Create: `frontend/src/components/MorphSliders.tsx`
- Create: `frontend/src/components/__tests__/MorphSliders.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/components/__tests__/MorphSliders.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MorphSliders } from '../MorphSliders'
import { MORPH_TARGETS } from '../../types'

describe('MorphSliders', () => {
  const morphValues = Array(12).fill(0)
  const onChange = vi.fn()

  it('renders 12 sliders', () => {
    render(<MorphSliders morphValues={morphValues} onChange={onChange} />)
    expect(screen.getAllByRole('slider')).toHaveLength(12)
  })

  it('renders all four group headings', () => {
    render(<MorphSliders morphValues={morphValues} onChange={onChange} />)
    expect(screen.getByText(/Nose/)).toBeInTheDocument()
    expect(screen.getByText(/Eyes/)).toBeInTheDocument()
    expect(screen.getByText(/Jaw/)).toBeInTheDocument()
    expect(screen.getByText(/Contour/)).toBeInTheDocument()
  })

  it('displays current value next to each slider', () => {
    const vals = Array(12).fill(0)
    vals[0] = 42
    render(<MorphSliders morphValues={vals} onChange={onChange} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('calls onChange with correct index and value when slider changes', () => {
    render(<MorphSliders morphValues={morphValues} onChange={onChange} />)
    const sliders = screen.getAllByRole('slider')
    fireEvent.change(sliders[0], { target: { value: '30' } })
    expect(onChange).toHaveBeenCalledWith(0, 30)
  })

  it('reset button calls onChange(i, 0) for all 12 targets', () => {
    const vals = Array(12).fill(50)
    render(<MorphSliders morphValues={vals} onChange={onChange} />)
    fireEvent.click(screen.getByText(/Reset/i))
    expect(onChange).toHaveBeenCalledTimes(12)
    MORPH_TARGETS.forEach((_, i) => {
      expect(onChange).toHaveBeenCalledWith(i, 0)
    })
  })
})
```

- [ ] **Step 2: Run — expect failure**

```bash
npx vitest run src/components/__tests__/MorphSliders.test.tsx
```

Expected: FAIL — `MorphSliders` not found.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/MorphSliders.tsx
import { MORPH_GROUPS, MORPH_LABELS, MORPH_TARGETS } from '../types'

interface MorphSlidersProps {
  morphValues: number[]            // length 12, range -100..100
  onChange: (index: number, value: number) => void
}

export function MorphSliders({ morphValues, onChange }: MorphSlidersProps) {
  const resetAll = () => {
    MORPH_TARGETS.forEach((_, i) => onChange(i, 0))
  }

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">审美参数</h2>
        <button
          onClick={resetAll}
          className="text-xs px-2 py-1 border rounded text-gray-600 hover:bg-gray-100"
        >
          Reset All
        </button>
      </div>

      {Object.entries(MORPH_GROUPS).map(([group, targets]) => (
        <div key={group}>
          <h3 className="text-sm font-medium text-gray-500 mb-2">{group}</h3>
          <div className="flex flex-col gap-3">
            {targets.map(name => {
              const idx = MORPH_TARGETS.indexOf(name)
              const val = morphValues[idx] ?? 0
              return (
                <div key={name} className="flex flex-col gap-1">
                  <div className="flex justify-between text-xs text-gray-700">
                    <span>{MORPH_LABELS[name]}</span>
                    <span className="tabular-nums w-8 text-right">{val}</span>
                  </div>
                  <input
                    type="range"
                    min={-100}
                    max={100}
                    value={val}
                    onChange={e => onChange(idx, Number(e.target.value))}
                    className="w-full accent-blue-600"
                  />
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/MorphSliders.test.tsx
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/components/MorphSliders.tsx \
  frontend/src/components/__tests__/MorphSliders.test.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: MorphSliders with 12 grouped sliders and reset"
```

---

## Task 6: MeasureTool Component

**Files:**
- Create: `frontend/src/components/MeasureTool.tsx`
- Create: `frontend/src/components/__tests__/MeasureTool.test.tsx`

- [ ] **Step 1: Write failing tests**

```tsx
// frontend/src/components/__tests__/MeasureTool.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import * as THREE from 'three'
import { MeasurePanel } from '../MeasureTool'
import type { MeasurePoint } from '../../types'

const pt = (id: string, x: number): MeasurePoint => ({
  id, pos: new THREE.Vector3(x, 0, 0), label: '',
})

describe('MeasurePanel', () => {
  it('shows no measurements when fewer than 2 points', () => {
    render(<MeasurePanel points={[pt('a', 0)]} onLabelChange={vi.fn()} onClearAll={vi.fn()} />)
    expect(screen.queryByText(/mm/)).toBeNull()
  })

  it('shows distance between consecutive point pairs', () => {
    // 1 unit apart → 170 mm
    render(<MeasurePanel points={[pt('a', 0), pt('b', 1)]} onLabelChange={vi.fn()} onClearAll={vi.fn()} />)
    expect(screen.getByText(/170\.0 mm/)).toBeInTheDocument()
  })

  it('shows distance for each consecutive pair', () => {
    // 3 points → 2 measurements
    render(<MeasurePanel
      points={[pt('a',0), pt('b',1), pt('c',2)]}
      onLabelChange={vi.fn()} onClearAll={vi.fn()}
    />)
    expect(screen.getAllByText(/170\.0 mm/)).toHaveLength(2)
  })

  it('calls onClearAll when Clear All clicked', () => {
    const clearAll = vi.fn()
    render(<MeasurePanel points={[pt('a',0), pt('b',1)]} onLabelChange={vi.fn()} onClearAll={clearAll} />)
    fireEvent.click(screen.getByText(/Clear All/i))
    expect(clearAll).toHaveBeenCalled()
  })

  it('calls onLabelChange when label input changes', () => {
    const labelChange = vi.fn()
    render(<MeasurePanel points={[pt('a',0), pt('b',1)]} onLabelChange={labelChange} onClearAll={vi.fn()} />)
    fireEvent.change(screen.getAllByRole('textbox')[0], { target: { value: 'nose width' } })
    expect(labelChange).toHaveBeenCalledWith('a', 'nose width')
  })
})
```

- [ ] **Step 2: Run — expect failure**

```bash
npx vitest run src/components/__tests__/MeasureTool.test.tsx
```

Expected: FAIL — `MeasureTool` not found.

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/MeasureTool.tsx
import { useRef } from 'react'
import type { ThreeEvent } from '@react-three/fiber'
import * as THREE from 'three'
import { calcDistanceMm, findNearestPoint } from '../lib/measure'
import type { MeasurePoint } from '../types'

// ── 3D scene part (used inside the R3F Canvas) ────────────────────────────────

interface MeasureSphereProps {
  points: MeasurePoint[]
  measureMode: boolean
  meshRef: React.MutableRefObject<THREE.Mesh | null>
  onAdd: (pos: THREE.Vector3) => void
  onRemoveNearest: (pos: THREE.Vector3) => void
}

export function MeasureSpheres({ points, measureMode, meshRef, onAdd, onRemoveNearest }: MeasureSphereProps) {
  return (
    <>
      {/* invisible click target on the mesh */}
      {measureMode && meshRef.current && (
        <primitive
          object={meshRef.current}
          onClick={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onAdd(e.point.clone()) }}
          onContextMenu={(e: ThreeEvent<MouseEvent>) => { e.stopPropagation(); onRemoveNearest(e.point.clone()) }}
        />
      )}
      {points.map(p => (
        <mesh key={p.id} position={p.pos}>
          <sphereGeometry args={[0.003, 8, 8]} />
          <meshBasicMaterial color="red" />
        </mesh>
      ))}
      {points.slice(0, -1).map((p, i) => {
        const next = points[i + 1]
        const mid = p.pos.clone().lerp(next.pos, 0.5)
        return (
          <line_ key={`line-${p.id}`}>
            <bufferGeometry>
              <bufferAttribute
                attach="attributes-position"
                args={[new Float32Array([...p.pos.toArray(), ...next.pos.toArray()]), 3]}
              />
            </bufferGeometry>
            <lineBasicMaterial color="red" />
          </line_>
        )
      })}
    </>
  )
}

// ── 2D panel part (used in the right sidebar) ─────────────────────────────────

interface MeasurePanelProps {
  points: MeasurePoint[]
  onLabelChange: (id: string, label: string) => void
  onClearAll: () => void
}

export function MeasurePanel({ points, onLabelChange, onClearAll }: MeasurePanelProps) {
  const pairs = points.slice(0, -1).map((p, i) => ({ a: p, b: points[i + 1] }))

  return (
    <div className="flex flex-col gap-3 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">测量记录</h3>
        {points.length > 0 && (
          <button onClick={onClearAll} className="text-xs text-red-500 hover:underline">
            Clear All
          </button>
        )}
      </div>
      {pairs.length === 0 && (
        <p className="text-xs text-gray-400">放置 2 个点以显示距离</p>
      )}
      {pairs.map(({ a, b }, i) => (
        <div key={`${a.id}-${b.id}`} className="flex flex-col gap-1 border rounded p-2">
          <div className="flex justify-between text-sm">
            <span className="text-gray-500">#{i + 1}</span>
            <span className="font-mono">{calcDistanceMm(a.pos, b.pos).toFixed(1)} mm</span>
          </div>
          <input
            type="text"
            value={a.label}
            placeholder="Add label…"
            className="text-xs border-b outline-none w-full"
            onChange={e => onLabelChange(a.id, e.target.value)}
          />
        </div>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/MeasureTool.test.tsx
```

Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/components/MeasureTool.tsx \
  frontend/src/components/__tests__/MeasureTool.test.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: MeasureTool with 3D spheres, lines, and distance panel"
```

---

## Task 7: MediaPipe Loader

**Files:**
- Create: `frontend/src/lib/mediapipe.ts`
- Create: `frontend/src/components/__tests__/mediapipe.test.ts`

- [ ] **Step 1: Write failing tests**

```ts
// frontend/src/components/__tests__/mediapipe.test.ts
import { describe, it, expect } from 'vitest'
import { landmarkToNDC, REFERENCE_LANDMARK_INDICES } from '../../lib/mediapipe'

describe('landmarkToNDC', () => {
  it('converts top-left corner to (-1, 1)', () => {
    const ndc = landmarkToNDC({ x: 0, y: 0, z: 0 })
    expect(ndc.x).toBeCloseTo(-1)
    expect(ndc.y).toBeCloseTo(1)
  })

  it('converts bottom-right corner to (1, -1)', () => {
    const ndc = landmarkToNDC({ x: 1, y: 1, z: 0 })
    expect(ndc.x).toBeCloseTo(1)
    expect(ndc.y).toBeCloseTo(-1)
  })

  it('converts center to (0, 0)', () => {
    const ndc = landmarkToNDC({ x: 0.5, y: 0.5, z: 0 })
    expect(ndc.x).toBeCloseTo(0)
    expect(ndc.y).toBeCloseTo(0)
  })
})

describe('REFERENCE_LANDMARK_INDICES', () => {
  it('has all required keys', () => {
    const required = ['hairline', 'browLine', 'noseBase', 'chin',
                      'outerLeftEye', 'innerLeftEye', 'noseCenter',
                      'innerRightEye', 'outerRightEye']
    required.forEach(k => expect(REFERENCE_LANDMARK_INDICES).toHaveProperty(k))
  })
})
```

- [ ] **Step 2: Run — expect failure**

```bash
npx vitest run src/components/__tests__/mediapipe.test.ts
```

- [ ] **Step 3: Implement**

```ts
// frontend/src/lib/mediapipe.ts
import type { FaceLandmarker } from '@mediapipe/tasks-vision'

// MediaPipe 468-point face model landmark indices for 三庭五眼
export const REFERENCE_LANDMARK_INDICES = {
  hairline:       10,
  browLine:       105,   // left brow center proxy
  noseBase:       2,
  chin:           152,
  outerLeftEye:   33,
  innerLeftEye:   133,
  noseCenter:     1,
  innerRightEye:  362,
  outerRightEye:  263,
} as const

export interface Landmark2D { x: number; y: number; z: number }

/** Convert MediaPipe normalised [0,1] landmark to Three.js NDC [-1,1] */
export function landmarkToNDC(lm: Landmark2D): { x: number; y: number } {
  return {
    x:  lm.x * 2 - 1,
    y: -(lm.y * 2 - 1),
  }
}

let _landmarker: FaceLandmarker | null = null

/** Lazily initialize the MediaPipe FaceLandmarker (downloads model on first call). */
export async function getFaceLandmarker(): Promise<FaceLandmarker> {
  if (_landmarker) return _landmarker

  const { FaceLandmarker, FilesetResolver } = await import('@mediapipe/tasks-vision')
  const vision = await FilesetResolver.forVisionTasks(
    'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm',
  )
  _landmarker = await FaceLandmarker.createFromOptions(vision, {
    baseOptions: {
      modelAssetPath:
        'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task',
      delegate: 'GPU',
    },
    runningMode: 'IMAGE',
    numFaces: 1,
  })
  return _landmarker
}

/**
 * Run MediaPipe on an image URL, return the first face's normalized landmarks.
 * Returns null if no face detected or on error.
 */
export async function detectLandmarks(imageUrl: string): Promise<Landmark2D[] | null> {
  try {
    const landmarker = await getFaceLandmarker()
    const img = new Image()
    img.src = imageUrl
    await new Promise<void>((res, rej) => {
      img.onload = () => res()
      img.onerror = rej
    })
    const result = landmarker.detect(img)
    return result.faceLandmarks?.[0] ?? null
  } catch {
    return null
  }
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/mediapipe.test.ts
```

Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/lib/mediapipe.ts \
  frontend/src/components/__tests__/mediapipe.test.ts
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: MediaPipe FaceLandmarker lazy loader with NDC converter"
```

---

## Task 8: ReferenceLines Component

**Files:**
- Create: `frontend/src/components/ReferenceLines.tsx`

> Note: this component renders inside the R3F Canvas and uses Three.js directly.
> Tests are limited to a smoke test since WebGL is unavailable in jsdom.

- [ ] **Step 1: Create the component**

```tsx
// frontend/src/components/ReferenceLines.tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { useThree } from '@react-three/fiber'
import { Line } from '@react-three/drei'
import * as THREE from 'three'
import {
  detectLandmarks,
  landmarkToNDC,
  REFERENCE_LANDMARK_INDICES,
  type Landmark2D,
} from '../lib/mediapipe'

interface ReferenceLinesProps {
  frontImageUrl: string | null   // object URL of the uploaded front photo
  meshRef: React.MutableRefObject<THREE.Mesh | null>
  visible: boolean
}

export function ReferenceLines({ frontImageUrl, meshRef, visible }: ReferenceLinesProps) {
  const { camera } = useThree()
  const raycaster = useMemo(() => new THREE.Raycaster(), [])
  const [linePoints, setLinePoints] = useState<{ horizontal: THREE.Vector3[][]; vertical: THREE.Vector3[][] }>({
    horizontal: [],
    vertical: [],
  })

  useEffect(() => {
    if (!visible || !frontImageUrl || !meshRef.current) return

    detectLandmarks(frontImageUrl).then(landmarks => {
      if (!landmarks || !meshRef.current) return

      const mesh = meshRef.current
      const bb   = new THREE.Box3().setFromObject(mesh)
      const Z    = (bb.min.z + bb.max.z) / 2  // mid-depth of face

      // Map a MediaPipe landmark to a 3D world point by raycasting
      const to3D = (lm: Landmark2D): THREE.Vector3 | null => {
        const ndc = landmarkToNDC(lm)
        raycaster.setFromCamera(ndc, camera)
        const hits = raycaster.intersectObject(mesh, false)
        return hits.length > 0 ? hits[0].point.clone() : null
      }

      const idx = REFERENCE_LANDMARK_INDICES
      const lms  = landmarks

      // Horizontal lines (三庭): hairline, brow, nose base, chin
      const hKeys = ['hairline', 'browLine', 'noseBase', 'chin'] as const
      const hLines = hKeys.map(k => {
        const pt = to3D(lms[idx[k]])
        if (!pt) return null
        return [
          new THREE.Vector3(bb.min.x, pt.y, Z),
          new THREE.Vector3(bb.max.x, pt.y, Z),
        ]
      }).filter(Boolean) as THREE.Vector3[][]

      // Vertical lines (五眼): 5 eye-width columns
      const vKeys = ['outerLeftEye', 'innerLeftEye', 'noseCenter', 'innerRightEye', 'outerRightEye'] as const
      const vLines = vKeys.map(k => {
        const pt = to3D(lms[idx[k]])
        if (!pt) return null
        return [
          new THREE.Vector3(pt.x, bb.min.y, Z),
          new THREE.Vector3(pt.x, bb.max.y, Z),
        ]
      }).filter(Boolean) as THREE.Vector3[][]

      setLinePoints({ horizontal: hLines, vertical: vLines })
    })
  }, [visible, frontImageUrl, meshRef, camera, raycaster])

  if (!visible) return null

  const color   = '#4CAF50'
  const opacity = 0.7

  return (
    <>
      {linePoints.horizontal.map((pts, i) => (
        <Line key={`h${i}`} points={pts} color={color} lineWidth={1} transparent opacity={opacity} />
      ))}
      {linePoints.vertical.map((pts, i) => (
        <Line key={`v${i}`} points={pts} color={color} lineWidth={1} transparent opacity={opacity} />
      ))}
    </>
  )
}
```

- [ ] **Step 2: Write a smoke test**

```tsx
// frontend/src/components/__tests__/ReferenceLines.test.tsx
import { describe, it, vi } from 'vitest'
// Three.js and R3F are mocked in jsdom — just ensure the module exports without crashing.
vi.mock('@react-three/fiber', () => ({ useThree: () => ({ camera: {} }) }))
vi.mock('@react-three/drei',  () => ({ Line: () => null }))
vi.mock('../../lib/mediapipe', () => ({
  detectLandmarks: vi.fn().mockResolvedValue(null),
  landmarkToNDC: vi.fn(),
  REFERENCE_LANDMARK_INDICES: {},
}))

describe('ReferenceLines', () => {
  it('imports without error', async () => {
    await import('../ReferenceLines')
  })
})
```

- [ ] **Step 3: Run tests**

```bash
npx vitest run src/components/__tests__/ReferenceLines.test.tsx
```

Expected: PASS (1 test).

- [ ] **Step 4: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/components/ReferenceLines.tsx \
  frontend/src/components/__tests__/ReferenceLines.test.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: ReferenceLines with MediaPipe landmarks and THREE.Line objects"
```

---

## Task 9: Viewer3D Component

**Files:**
- Create: `frontend/src/components/Viewer3D.tsx`
- Create: `frontend/src/components/__tests__/Viewer3D.test.tsx`

- [ ] **Step 1: Write smoke test**

```tsx
// frontend/src/components/__tests__/Viewer3D.test.tsx
import { describe, it, vi } from 'vitest'
vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: any) => <div>{children}</div>,
  useThree: () => ({ camera: {}, gl: {} }),
  useFrame: vi.fn(),
}))
vi.mock('@react-three/drei', () => ({
  OrbitControls: () => null,
  useGLTF: () => ({ scene: { traverse: vi.fn() } }),
  Line: () => null,
}))
vi.mock('../ReferenceLines', () => ({ ReferenceLines: () => null }))
vi.mock('../MeasureTool', () => ({ MeasureSpheres: () => null }))

describe('Viewer3D', () => {
  it('imports without error', async () => {
    await import('../Viewer3D')
  })
})
```

- [ ] **Step 2: Run — expect failure (module not found)**

```bash
npx vitest run src/components/__tests__/Viewer3D.test.tsx
```

- [ ] **Step 3: Implement**

```tsx
// frontend/src/components/Viewer3D.tsx
import { useEffect, useMemo, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { ReferenceLines } from './ReferenceLines'
import { MeasureSpheres } from './MeasureTool'
import type { MeasurePoint } from '../types'

interface FaceModelProps {
  jobId: string
  morphValues: number[]
  meshRef: React.MutableRefObject<THREE.Mesh | null>
  measureMode: boolean
  measurePoints: MeasurePoint[]
  onAddPoint: (pos: THREE.Vector3) => void
  onRemoveNearest: (pos: THREE.Vector3) => void
  showRefLines: boolean
  frontImageUrl: string | null
}

function FaceScene({
  jobId, morphValues, meshRef,
  measureMode, measurePoints, onAddPoint, onRemoveNearest,
  showRefLines, frontImageUrl,
}: FaceModelProps) {
  const { scene } = useGLTF(`/api/model/${jobId}`)

  const mesh = useMemo<THREE.Mesh | null>(() => {
    let found: THREE.Mesh | null = null
    scene.traverse(n => { if (!found && (n as THREE.Mesh).isMesh) found = n as THREE.Mesh })
    return found
  }, [scene])

  useEffect(() => {
    if (mesh) meshRef.current = mesh
  }, [mesh, meshRef])

  useEffect(() => {
    if (!mesh?.morphTargetInfluences) return
    morphValues.forEach((v, i) => { mesh.morphTargetInfluences![i] = v / 100 })
  }, [morphValues, mesh])

  return (
    <>
      <primitive object={scene} />
      <MeasureSpheres
        points={measurePoints}
        measureMode={measureMode}
        meshRef={meshRef}
        onAdd={onAddPoint}
        onRemoveNearest={onRemoveNearest}
      />
      <ReferenceLines
        frontImageUrl={frontImageUrl}
        meshRef={meshRef}
        visible={showRefLines}
      />
    </>
  )
}

interface Viewer3DProps extends FaceModelProps {}

export function Viewer3D(props: Viewer3DProps) {
  return (
    <Canvas
      camera={{ fov: 45, position: [0, 0, 2.5] }}
      style={{ background: '#f5f4f0' }}
      className="w-full h-full"
    >
      <ambientLight intensity={0.6} />
      <directionalLight position={[2, 3, 2]} intensity={0.8} />
      <OrbitControls enablePan={false} minDistance={1.5} maxDistance={5} />
      <FaceScene {...props} />
    </Canvas>
  )
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/Viewer3D.test.tsx
```

- [ ] **Step 5: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/components/Viewer3D.tsx \
  frontend/src/components/__tests__/Viewer3D.test.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: Viewer3D with R3F canvas, orbit controls, and morph sync"
```

---

## Task 10: App — State, Layout, Loading States

**Files:**
- Modify: `frontend/src/App.tsx` (full rewrite)
- Create: `frontend/src/components/__tests__/App.test.tsx`

- [ ] **Step 1: Write failing test for App flow**

```tsx
// frontend/src/components/__tests__/App.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

// Mock heavy components
vi.mock('../Viewer3D', () => ({ Viewer3D: () => <div data-testid="viewer3d" /> }))
vi.mock('../Uploader', () => ({
  Uploader: ({ onSubmit }: any) => (
    <button onClick={() => onSubmit(new File([''], 'f.jpg', { type: 'image/jpeg' }), null, null)}>
      upload
    </button>
  ),
}))
vi.mock('../MorphSliders', () => ({ MorphSliders: () => <div data-testid="sliders" /> }))
vi.mock('../MeasureTool', () => ({ MeasurePanel: () => <div data-testid="measure-panel" /> }))

// Mock fetch for /api/reconstruct
const fetchMock = vi.fn()
global.fetch = fetchMock

import App from '../../App'

describe('App', () => {
  beforeEach(() => { fetchMock.mockReset() })

  it('starts in upload phase — shows Uploader, not Viewer3D', () => {
    render(<App />)
    expect(screen.getByText('upload')).toBeInTheDocument()
    expect(screen.queryByTestId('viewer3d')).toBeNull()
  })

  it('shows spinner while reconstructing', async () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))  // never resolves
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    expect(await screen.findByText(/Building your 3D model/)).toBeInTheDocument()
  })

  it('transitions to viewing phase on success', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'abc123', status: 'done' }),
    })
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    expect(await screen.findByTestId('viewer3d')).toBeInTheDocument()
  })

  it('shows error message on API failure', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'No face detected' }),
    })
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    expect(await screen.findByText(/No face detected/)).toBeInTheDocument()
  })

  it('retry button resets to upload phase', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'fail' }),
    })
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    await screen.findByText(/fail/)
    fireEvent.click(screen.getByText(/重新上传|Retry/i))
    expect(screen.getByText('upload')).toBeInTheDocument()
  })
})
```

- [ ] **Step 2: Run — expect failure**

```bash
npx vitest run src/components/__tests__/App.test.tsx
```

- [ ] **Step 3: Implement App.tsx**

```tsx
// frontend/src/App.tsx
import { useRef, useState, useCallback } from 'react'
import * as THREE from 'three'
import { Uploader } from './components/Uploader'
import { Viewer3D } from './components/Viewer3D'
import { MorphSliders } from './components/MorphSliders'
import { MeasurePanel } from './components/MeasureTool'
import { MORPH_TARGETS } from './types'
import type { MeasurePoint, Phase } from './types'
import { findNearestPoint } from './lib/measure'

export default function App() {
  const [phase,           setPhase]           = useState<Phase>('upload')
  const [jobId,           setJobId]           = useState<string | null>(null)
  const [isLoading,       setIsLoading]       = useState(false)
  const [error,           setError]           = useState<string | null>(null)
  const [morphValues,     setMorphValues]     = useState<number[]>(Array(MORPH_TARGETS.length).fill(0))
  const [measureMode,     setMeasureMode]     = useState(false)
  const [measurePoints,   setMeasurePoints]   = useState<MeasurePoint[]>([])
  const [showRefLines,    setShowRefLines]    = useState(false)
  const meshRef        = useRef<THREE.Mesh | null>(null)
  const frontImageUrl  = useRef<string | null>(null)

  const handleSubmit = useCallback(async (front: File, left45: File | null, right45: File | null) => {
    setIsLoading(true)
    setError(null)
    frontImageUrl.current = URL.createObjectURL(front)

    const fd = new FormData()
    fd.append('front_image', front)
    if (left45)  fd.append('left45_image',  left45)
    if (right45) fd.append('right45_image', right45)

    try {
      const resp = await fetch('/api/reconstruct', { method: 'POST', body: fd })
      const data = await resp.json()
      if (!resp.ok) throw new Error(data.detail ?? '重建失败')
      setJobId(data.job_id)
      setPhase('viewing')
    } catch (e: any) {
      setError(e.message ?? '未知错误')
    } finally {
      setIsLoading(false)
    }
  }, [])

  const handleMorphChange = useCallback((index: number, value: number) => {
    setMorphValues(prev => { const next = [...prev]; next[index] = value; return next })
  }, [])

  const addPoint = useCallback((pos: THREE.Vector3) => {
    setMeasurePoints(prev => [...prev, { id: crypto.randomUUID(), pos, label: '' }])
  }, [])

  const removeNearestPoint = useCallback((pos: THREE.Vector3) => {
    setMeasurePoints(prev => {
      const nearest = findNearestPoint(prev, pos)
      return nearest ? prev.filter(p => p.id !== nearest.id) : prev
    })
  }, [])

  const updateLabel = useCallback((id: string, label: string) => {
    setMeasurePoints(prev => prev.map(p => p.id === id ? { ...p, label } : p))
  }, [])

  // ── Loading overlay ───────────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-full border-4 border-blue-600 border-t-transparent animate-spin" />
          <p className="text-gray-700 font-medium">Building your 3D model…</p>
          <p className="text-sm text-gray-400">Estimated time: 15–45 seconds</p>
        </div>
      </div>
    )
  }

  // ── Error screen ──────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="flex flex-col items-center gap-4 max-w-sm text-center">
          <p className="text-red-500 font-medium">{error}</p>
          <button
            className="px-4 py-2 bg-blue-600 text-white rounded-lg"
            onClick={() => { setError(null); setPhase('upload') }}
          >
            重新上传
          </button>
        </div>
      </div>
    )
  }

  // ── Upload phase ──────────────────────────────────────────────────────────
  if (phase === 'upload') {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="w-80 shadow-lg rounded-xl bg-white">
          <Uploader onSubmit={handleSubmit} isLoading={isLoading} />
        </div>
      </div>
    )
  }

  // ── Viewing phase: three-column layout ───────────────────────────────────
  return (
    <div className="flex h-screen overflow-hidden bg-[#f5f4f0]">
      {/* Left panel — 320px */}
      <aside className="w-80 shrink-0 bg-white border-r overflow-y-auto">
        <MorphSliders morphValues={morphValues} onChange={handleMorphChange} />
        <div className="px-4 pb-4">
          <button
            className={`w-full px-3 py-2 rounded-lg text-sm border ${
              measureMode ? 'bg-red-50 border-red-300 text-red-700' : 'hover:bg-gray-100'
            }`}
            onClick={() => setMeasureMode(m => !m)}
          >
            {measureMode ? '测量模式：开' : '测量模式：关'}
          </button>
        </div>
      </aside>

      {/* Center — viewer */}
      <main className="flex-1 min-w-0">
        {jobId && (
          <Viewer3D
            jobId={jobId}
            morphValues={morphValues}
            meshRef={meshRef}
            measureMode={measureMode}
            measurePoints={measurePoints}
            onAddPoint={addPoint}
            onRemoveNearest={removeNearestPoint}
            showRefLines={showRefLines}
            frontImageUrl={frontImageUrl.current}
          />
        )}
      </main>

      {/* Right panel — 280px */}
      <aside className="w-70 shrink-0 bg-white border-l overflow-y-auto">
        <div className="p-4 border-b">
          <button
            className={`w-full px-3 py-2 rounded-lg text-sm border ${
              showRefLines ? 'bg-green-50 border-green-300 text-green-700' : 'hover:bg-gray-100'
            }`}
            onClick={() => setShowRefLines(r => !r)}
          >
            三庭五眼 {showRefLines ? '开' : '关'}
          </button>
        </div>
        <MeasurePanel
          points={measurePoints}
          onLabelChange={updateLabel}
          onClearAll={() => setMeasurePoints([])}
        />
      </aside>
    </div>
  )
}
```

- [ ] **Step 4: Run — expect pass**

```bash
npx vitest run src/components/__tests__/App.test.tsx
```

Expected: PASS (5 tests).

- [ ] **Step 5: Run all tests to ensure nothing regressed**

```bash
npx vitest run
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/App.tsx \
  frontend/src/components/__tests__/App.test.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: App layout, loading states, error handling, and full state wiring"
```

---

## Task 11: Mobile Responsive Layout

**Files:**
- Modify: `frontend/src/App.tsx` (Tailwind breakpoints)

- [ ] **Step 1: Add mobile breakpoints to the three-column layout**

In `frontend/src/App.tsx`, replace the viewing-phase return with:

```tsx
  // ── Viewing phase: three-column layout (desktop) / stacked (mobile) ───────
  return (
    <div className="flex flex-col md:flex-row h-screen overflow-hidden bg-[#f5f4f0]">
      {/* On mobile: viewer appears first (order-first), panels below */}
      <main className="order-first md:order-2 flex-1 min-h-[50vh] md:min-h-0">
        {jobId && (
          <Viewer3D
            jobId={jobId}
            morphValues={morphValues}
            meshRef={meshRef}
            measureMode={measureMode}
            measurePoints={measurePoints}
            onAddPoint={addPoint}
            onRemoveNearest={removeNearestPoint}
            showRefLines={showRefLines}
            frontImageUrl={frontImageUrl.current}
          />
        )}
      </main>

      {/* Left panel */}
      <aside className="order-2 md:order-1 md:w-80 shrink-0 bg-white border-r md:border-r border-t md:border-t-0 overflow-y-auto">
        <MorphSliders morphValues={morphValues} onChange={handleMorphChange} />
        <div className="px-4 pb-4">
          <button
            className={`w-full px-3 py-2 rounded-lg text-sm border ${
              measureMode ? 'bg-red-50 border-red-300 text-red-700' : 'hover:bg-gray-100'
            }`}
            onClick={() => setMeasureMode(m => !m)}
          >
            {measureMode ? '测量模式：开' : '测量模式：关'}
          </button>
        </div>
      </aside>

      {/* Right panel */}
      <aside className="order-3 md:w-72 shrink-0 bg-white border-l md:border-l border-t md:border-t-0 overflow-y-auto">
        <div className="p-4 border-b">
          <button
            className={`w-full px-3 py-2 rounded-lg text-sm border ${
              showRefLines ? 'bg-green-50 border-green-300 text-green-700' : 'hover:bg-gray-100'
            }`}
            onClick={() => setShowRefLines(r => !r)}
          >
            三庭五眼 {showRefLines ? '开' : '关'}
          </button>
        </div>
        <MeasurePanel
          points={measurePoints}
          onLabelChange={updateLabel}
          onClearAll={() => setMeasurePoints([])}
        />
      </aside>
    </div>
  )
```

- [ ] **Step 2: Run all tests**

```bash
npx vitest run
```

Expected: all tests PASS.

- [ ] **Step 3: Start dev server and verify visually at 375px width**

```bash
# Terminal 1: start backend
cd /Users/shenyi/Desktop/face3d-app/backend && uvicorn main:app --reload --port 8000

# Terminal 2: start frontend
cd /Users/shenyi/Desktop/face3d-app/frontend && npm run dev
```

Open `http://localhost:5173` in browser DevTools → toggle to iPhone SE (375px) → confirm: viewer on top, panels stacked below.

- [ ] **Step 4: Commit**

```bash
git -C /Users/shenyi/Desktop/face3d-app add frontend/src/App.tsx
git -C /Users/shenyi/Desktop/face3d-app commit -m "feat: mobile-responsive layout with viewer-first stacking"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Covered by task |
|---|---|
| Three drop zones, front required | Task 4 Uploader |
| Preview thumbnails | Task 4 Uploader (DropZone `preview` state) |
| Validate JPG/PNG, max 10 MB | Task 4 Uploader `validate()` + tests |
| POST /api/reconstruct, poll for completion | Task 10 App `handleSubmit` (blocking fetch) |
| R3F Canvas fov=45, pos=[0,0,2.5] | Task 9 Viewer3D Canvas |
| useGLTF from /api/model/{job_id} | Task 9 Viewer3D FaceScene |
| OrbitControls: enablePan=false, dist 1.5–5 | Task 9 Viewer3D |
| Ambient 0.6 + directional [2,3,2] 0.8 | Task 9 Viewer3D |
| Background #f5f4f0 | Task 9 Viewer3D Canvas style |
| 12 sliders, -100 to 100 | Task 5 MorphSliders |
| Groups: Nose, Eyes, Jaw & Chin, Contour | Task 5 MORPH_GROUPS |
| Update morphTargetInfluences | Task 9 Viewer3D FaceScene useEffect |
| Reset all button | Task 5 MorphSliders |
| Show current value | Task 5 MorphSliders value span |
| Measure toggle | Task 10 App measureMode button |
| Left-click places red sphere (r=0.003) | Task 6 MeasureSpheres sphereGeometry |
| Distance in mm (1 unit = 170mm) | Task 3 measure.ts |
| Right-click removes nearest point | Task 6 MeasureSpheres onContextMenu + findNearestPoint |
| Panel with distance + label field | Task 6 MeasurePanel |
| Clear all button | Task 6 MeasurePanel |
| 三庭五眼 toggle | Task 10 App showRefLines button |
| 4 horizontal + 5 vertical lines | Task 8 ReferenceLines hLines/vLines |
| MediaPipe for landmark positions | Task 7 mediapipe.ts detectLandmarks |
| Color #4CAF50, opacity 0.7 | Task 8 ReferenceLines Line props |
| Left panel 320px | Task 10 App `md:w-80` |
| Right panel 280px | Task 10 App `md:w-72` |
| Mobile: stack vertically, viewer first | Task 11 flex-col + order-first |
| Loading spinner + status message | Task 10 App isLoading block |
| Estimated time 15–45 seconds | Task 10 App loading text |
| Error with retry button | Task 10 App error block + 重新上传 button |

**No gaps found.**

**Placeholder scan:** No TBD/TODO in any code step. All code blocks are complete.

**Type consistency:**
- `MeasurePoint` defined in `types.ts` Task 2, used identically in Tasks 3, 6, 9, 10. ✅
- `MORPH_TARGETS` array used as index source in MorphSliders and App identically. ✅
- `meshRef: React.MutableRefObject<THREE.Mesh | null>` passed consistently across Viewer3D, ReferenceLines, MeasureSpheres. ✅
- `onAddPoint`/`onRemoveNearest` signatures match between App and Viewer3D/MeasureSpheres. ✅
