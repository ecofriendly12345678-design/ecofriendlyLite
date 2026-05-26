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
