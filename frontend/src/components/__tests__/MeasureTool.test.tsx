// frontend/src/components/__tests__/MeasureTool.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import * as THREE from 'three'
import { MeasurePanel } from '../MeasureTool'
import type { MeasurePoint } from '../../types'

const pt = (id: string, x: number): MeasurePoint => ({
  id, pos: new THREE.Vector3(x, 0, 0), label: '',
})

describe('MeasurePanel', () => {
  it('shows no measurements when fewer than 2 points', () => {
    render(<MeasurePanel points={[pt('a', 0)]} onLabelChange={vi.fn()} onClearAll={vi.fn()} />)
    expect(screen.queryByText(/mm/)).toBeNull()
  })

  it('shows distance between consecutive point pairs', () => {
    // 1 unit apart → 170 mm
    render(<MeasurePanel points={[pt('a', 0), pt('b', 1)]} onLabelChange={vi.fn()} onClearAll={vi.fn()} />)
    expect(screen.getByText(/170\.0 mm/)).toBeInTheDocument()
  })

  it('shows distance for each consecutive pair', () => {
    // 3 points → 2 measurements
    render(<MeasurePanel
      points={[pt('a',0), pt('b',1), pt('c',2)]}
      onLabelChange={vi.fn()} onClearAll={vi.fn()}
    />)
    expect(screen.getAllByText(/170\.0 mm/)).toHaveLength(2)
  })

  it('calls onClearAll when Clear All clicked', () => {
    const clearAll = vi.fn()
    render(<MeasurePanel points={[pt('a',0), pt('b',1)]} onLabelChange={vi.fn()} onClearAll={clearAll} />)
    fireEvent.click(screen.getByText(/Clear All/i))
    expect(clearAll).toHaveBeenCalled()
  })

  it('calls onLabelChange when label input changes', () => {
    const labelChange = vi.fn()
    render(<MeasurePanel points={[pt('a',0), pt('b',1)]} onLabelChange={labelChange} onClearAll={vi.fn()} />)
    fireEvent.change(screen.getAllByRole('textbox')[0], { target: { value: 'nose width' } })
    expect(labelChange).toHaveBeenCalledWith('a', 'nose width')
  })
})
