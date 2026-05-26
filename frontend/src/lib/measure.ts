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
