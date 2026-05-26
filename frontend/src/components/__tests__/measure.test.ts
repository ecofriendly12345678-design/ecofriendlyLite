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
