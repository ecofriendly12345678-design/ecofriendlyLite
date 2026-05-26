// frontend/src/components/MeasureTool.tsx
import * as THREE from 'three'
import { calcDistanceMm } from '../lib/measure'
import type { MeasurePoint } from '../types'

// ── 3D scene part (used inside the R3F Canvas) ────────────────────────────────

interface MeasureSphereProps {
  points: MeasurePoint[]
  onAdd: (pos: THREE.Vector3) => void
  onRemoveNearest: (pos: THREE.Vector3) => void
}

export function MeasureSpheres({ points, onAdd, onRemoveNearest }: MeasureSphereProps) {
  return (
    <>
      {points.map(p => (
        <mesh key={p.id} position={p.pos}>
          <sphereGeometry args={[0.003, 8, 8]} />
          <meshBasicMaterial color="red" />
        </mesh>
      ))}
      {points.slice(0, -1).map((p, i) => {
        const next = points[i + 1]
        return (
          // @ts-ignore
          <line_ key={`line-${p.id}`}>
            <bufferGeometry>
              <bufferAttribute
                attach="attributes-position"
                args={[new Float32Array([...p.pos.toArray(), ...next.pos.toArray()]), 3]}
              />
            </bufferGeometry>
            <lineBasicMaterial color="red" />
          {/* @ts-ignore */}
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
