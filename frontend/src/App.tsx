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
  const [phase,         setPhase]         = useState<Phase>('upload')
  const [jobId,         setJobId]         = useState<string | null>(null)
  const [isLoading,     setIsLoading]     = useState(false)
  const [error,         setError]         = useState<string | null>(null)
  const [morphValues,   setMorphValues]   = useState<number[]>(Array(MORPH_TARGETS.length).fill(0))
  const [measureMode,   setMeasureMode]   = useState(false)
  const [measurePoints, setMeasurePoints] = useState<MeasurePoint[]>([])
  const [showRefLines,  setShowRefLines]  = useState(false)
  const meshRef       = useRef<THREE.Mesh | null>(null)
  const frontImageUrl = useRef<string | null>(null)

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
    setMeasurePoints(prev => [...prev, { id: Math.random().toString(36).slice(2), pos, label: '' }])
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

  if (phase === 'upload') {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-50">
        <div className="w-80 shadow-lg rounded-xl bg-white">
          <Uploader onSubmit={handleSubmit} isLoading={isLoading} />
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[#f5f4f0]">
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

      <aside className="w-72 shrink-0 bg-white border-l overflow-y-auto">
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
