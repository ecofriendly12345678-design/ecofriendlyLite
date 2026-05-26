// frontend/src/components/MorphSliders.tsx
import { MORPH_GROUPS, MORPH_LABELS, MORPH_TARGETS } from '../types'

interface MorphSlidersProps {
  morphValues: number[]            // length 12, range -100..100
  onChange: (index: number, value: number) => void
}

export function MorphSliders({ morphValues, onChange }: MorphSlidersProps) {
  const resetAll = () => {
    MORPH_TARGETS.forEach((_, i) => onChange(i, 0))
  }

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">审美参数</h2>
        <button
          onClick={resetAll}
          className="text-xs px-2 py-1 border rounded text-gray-600 hover:bg-gray-100"
        >
          Reset All
        </button>
      </div>

      {Object.entries(MORPH_GROUPS).map(([group, targets]) => (
        <div key={group}>
          <h3 className="text-sm font-medium text-gray-500 mb-2">{group}</h3>
          <div className="flex flex-col gap-3">
            {targets.map(name => {
              const idx = MORPH_TARGETS.indexOf(name)
              const val = morphValues[idx] ?? 0
              return (
                <div key={name} className="flex flex-col gap-1">
                  <div className="flex justify-between text-xs text-gray-700">
                    <span>{MORPH_LABELS[name]}</span>
                    <span className="tabular-nums w-8 text-right">{val}</span>
                  </div>
                  <input
                    type="range"
                    min={-100}
                    max={100}
                    value={val}
                    onChange={e => onChange(idx, Number(e.target.value))}
                    className="w-full accent-blue-600"
                  />
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
