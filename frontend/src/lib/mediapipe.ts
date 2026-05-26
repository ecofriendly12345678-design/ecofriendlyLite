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
