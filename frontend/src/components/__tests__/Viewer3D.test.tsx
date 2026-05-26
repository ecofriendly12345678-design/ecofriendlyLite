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
