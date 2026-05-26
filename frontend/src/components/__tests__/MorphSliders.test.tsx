// frontend/src/components/__tests__/MorphSliders.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MorphSliders } from '../MorphSliders'
import { MORPH_TARGETS } from '../../types'

describe('MorphSliders', () => {
  const morphValues = Array(12).fill(0)
  const onChange = vi.fn()

  beforeEach(() => onChange.mockReset())

  it('renders 12 sliders', () => {
    render(<MorphSliders morphValues={morphValues} onChange={onChange} />)
    expect(screen.getAllByRole('slider')).toHaveLength(12)
  })

  it('renders all four group headings', () => {
    render(<MorphSliders morphValues={morphValues} onChange={onChange} />)
    expect(screen.getByText(/Nose/)).toBeInTheDocument()
    expect(screen.getByText(/Eyes/)).toBeInTheDocument()
    expect(screen.getByText(/Jaw/)).toBeInTheDocument()
    expect(screen.getByText(/Contour/)).toBeInTheDocument()
  })

  it('displays current value next to each slider', () => {
    const vals = Array(12).fill(0)
    vals[0] = 42
    render(<MorphSliders morphValues={vals} onChange={onChange} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('calls onChange with correct index and value when slider changes', () => {
    render(<MorphSliders morphValues={morphValues} onChange={onChange} />)
    const sliders = screen.getAllByRole('slider')
    fireEvent.change(sliders[0], { target: { value: '30' } })
    expect(onChange).toHaveBeenCalledWith(0, 30)
  })

  it('reset button calls onChange(i, 0) for all 12 targets', () => {
    const vals = Array(12).fill(50)
    render(<MorphSliders morphValues={vals} onChange={onChange} />)
    fireEvent.click(screen.getByText(/Reset/i))
    expect(onChange).toHaveBeenCalledTimes(12)
    MORPH_TARGETS.forEach((_, i) => {
      expect(onChange).toHaveBeenCalledWith(i, 0)
    })
  })
})
