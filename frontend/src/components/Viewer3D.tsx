// frontend/src/components/Viewer3D.tsx
import { useEffect, useMemo, useRef } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import { ReferenceLines } from './ReferenceLines'
import { MeasureSpheres } from './MeasureTool'
import type { MeasurePoint } from '../types'

interface FaceSceneProps {
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
}: FaceSceneProps) {
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

type Viewer3DProps = FaceSceneProps

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
