// frontend/src/components/ReferenceLines.tsx
import { useEffect, useMemo, useState } from 'react'
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
  mesh: THREE.Mesh | null
  visible: boolean
}

export function ReferenceLines({ frontImageUrl, mesh, visible }: ReferenceLinesProps) {
  const { camera } = useThree()
  const raycaster = useMemo(() => new THREE.Raycaster(), [])
  const [linePoints, setLinePoints] = useState<{ horizontal: THREE.Vector3[][]; vertical: THREE.Vector3[][] }>({
    horizontal: [],
    vertical: [],
  })

  useEffect(() => {
    if (!visible || !frontImageUrl || !mesh) return

    detectLandmarks(frontImageUrl).then(landmarks => {
      if (!landmarks || !mesh) return

      const bb   = new THREE.Box3().setFromObject(mesh)
      const Z    = (bb.min.z + bb.max.z) / 2

      const to3D = (lm: Landmark2D): THREE.Vector3 | null => {
        const ndc = landmarkToNDC(lm)
        raycaster.setFromCamera(ndc, camera as THREE.Camera)
        const hits = raycaster.intersectObject(mesh, false)
        return hits.length > 0 ? hits[0].point.clone() : null
      }

      const idx = REFERENCE_LANDMARK_INDICES
      const lms  = landmarks

      const hKeys = ['hairline', 'browLine', 'noseBase', 'chin'] as const
      const hLines = hKeys.map(k => {
        const pt = to3D(lms[idx[k]])
        if (!pt) return null
        return [
          new THREE.Vector3(bb.min.x, pt.y, Z),
          new THREE.Vector3(bb.max.x, pt.y, Z),
        ]
      }).filter(Boolean) as THREE.Vector3[][]

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
  }, [visible, frontImageUrl, mesh, camera, raycaster])

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
