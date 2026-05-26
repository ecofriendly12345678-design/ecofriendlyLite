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
