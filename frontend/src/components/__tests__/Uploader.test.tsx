// frontend/src/components/__tests__/Uploader.test.tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Uploader } from '../Uploader'

// jsdom doesn't implement URL.createObjectURL
global.URL.createObjectURL = vi.fn(() => 'blob:mock')

const makeFile = (name: string, type: string, size: number) => {
  const f = new File(['x'.repeat(size)], name, { type })
  Object.defineProperty(f, 'size', { value: size })
  return f
}

describe('Uploader', () => {
  const onSubmit = vi.fn()

  it('renders three drop zones', () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    expect(screen.getByText(/正面/)).toBeInTheDocument()
    expect(screen.getByText(/左侧 45°/)).toBeInTheDocument()
    expect(screen.getByText(/右侧 45°/)).toBeInTheDocument()
  })

  it('submit button is disabled when front image not selected', () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    expect(screen.getByRole('button', { name: /生成/ })).toBeDisabled()
  })

  it('rejects non-image files with error message', async () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    const input = screen.getByTestId('file-front')
    const bad = makeFile('doc.pdf', 'application/pdf', 1024)
    await userEvent.upload(input, bad)
    expect(screen.getByText(/JPG 或 PNG/)).toBeInTheDocument()
  })

  it('rejects files over 10 MB', async () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    const input = screen.getByTestId('file-front')
    const big = makeFile('face.jpg', 'image/jpeg', 11 * 1024 * 1024)
    await userEvent.upload(input, big)
    expect(screen.getByText(/10 MB/)).toBeInTheDocument()
  })

  it('enables submit and calls onSubmit with front file', async () => {
    render(<Uploader onSubmit={onSubmit} isLoading={false} />)
    const input = screen.getByTestId('file-front')
    const good = makeFile('face.jpg', 'image/jpeg', 1024)
    await userEvent.upload(input, good)
    const btn = screen.getByRole('button', { name: /生成/ })
    expect(btn).not.toBeDisabled()
    fireEvent.click(btn)
    expect(onSubmit).toHaveBeenCalledWith(good, null, null)
  })
})
