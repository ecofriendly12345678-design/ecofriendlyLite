// frontend/src/components/Uploader.tsx
import { useEffect, useRef, useState } from 'react'

interface DropZoneProps {
  label: string
  required?: boolean
  onFile: (f: File | null) => void
  testId?: string
}

function DropZone({ label, required, onFile, testId }: DropZoneProps) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const validate = (f: File): string | null => {
    if (!['image/jpeg', 'image/png'].includes(f.type)) return '请选择 JPG 或 PNG 文件'
    if (f.size > 10 * 1024 * 1024) return '文件不能超过 10 MB'
    return null
  }

  const handle = (f: File) => {
    const err = validate(f)
    if (err) { setError(err); onFile(null); return }
    setError(null)
    if (preview) URL.revokeObjectURL(preview)
    setPreview(URL.createObjectURL(f))
    onFile(f)
  }

  useEffect(() => {
    return () => { if (preview) URL.revokeObjectURL(preview) }
  }, [preview])

  return (
    <div className="flex flex-col items-center gap-1 w-full">
      <div
        className="w-full h-32 border-2 border-dashed border-gray-300 rounded-lg flex flex-col items-center justify-center cursor-pointer hover:border-blue-400 relative overflow-hidden"
        onClick={() => inputRef.current?.click()}
        onDragOver={e => e.preventDefault()}
        onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handle(f) }}
      >
        {preview
          ? <img src={preview} className="object-cover w-full h-full absolute inset-0" alt="preview" />
          : <span className="text-sm text-gray-400">{label}{required && ' *'}</span>
        }
      </div>
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        data-testid={testId}
        onChange={e => { const f = e.target.files?.[0]; if (f) handle(f) }}
      />
      {error && <p className="text-xs text-red-500">{error}</p>}
    </div>
  )
}

interface UploaderProps {
  onSubmit: (front: File, left45: File | null, right45: File | null) => void
  isLoading: boolean
}

export function Uploader({ onSubmit, isLoading }: UploaderProps) {
  const [front,   setFront]   = useState<File | null>(null)
  const [left45,  setLeft45]  = useState<File | null>(null)
  const [right45, setRight45] = useState<File | null>(null)

  return (
    <div className="flex flex-col gap-4 p-4">
      <h2 className="text-lg font-semibold">上传照片</h2>
      <DropZone label="正面"     required onFile={setFront}   testId="file-front" />
      <DropZone label="左侧 45°"          onFile={setLeft45}  testId="file-left45" />
      <DropZone label="右侧 45°"          onFile={setRight45} testId="file-right45" />
      <p className="text-xs text-gray-500">* 必填；侧面照片可提升重建质量</p>
      <button
        className="mt-2 px-4 py-2 bg-blue-600 text-white rounded-lg disabled:opacity-40 disabled:cursor-not-allowed"
        disabled={!front || isLoading}
        onClick={() => front && onSubmit(front, left45, right45)}
      >
        {isLoading ? '生成中…' : '生成 3D 模型'}
      </button>
    </div>
  )
}
