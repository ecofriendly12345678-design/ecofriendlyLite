// frontend/src/components/__tests__/App.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

// Mock heavy components
vi.mock('../Viewer3D', () => ({ Viewer3D: () => <div data-testid="viewer3d" /> }))
vi.mock('../Uploader', () => ({
  Uploader: ({ onSubmit }: any) => (
    <button onClick={() => onSubmit(new File([''], 'f.jpg', { type: 'image/jpeg' }), null, null)}>
      upload
    </button>
  ),
}))
vi.mock('../MorphSliders', () => ({ MorphSliders: () => <div data-testid="sliders" /> }))
vi.mock('../MeasureTool', () => ({ MeasurePanel: () => <div data-testid="measure-panel" /> }))

// Mock fetch for /api/reconstruct
const fetchMock = vi.fn()
global.fetch = fetchMock

// Mock URL.createObjectURL (not available in jsdom)
global.URL.createObjectURL = vi.fn(() => 'blob:mock')

import App from '../../App'

describe('App', () => {
  beforeEach(() => { fetchMock.mockReset() })

  it('starts in upload phase — shows Uploader, not Viewer3D', () => {
    render(<App />)
    expect(screen.getByText('upload')).toBeInTheDocument()
    expect(screen.queryByTestId('viewer3d')).toBeNull()
  })

  it('shows spinner while reconstructing', async () => {
    fetchMock.mockImplementation(() => new Promise(() => {}))  // never resolves
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    expect(await screen.findByText(/Building your 3D model/)).toBeInTheDocument()
  })

  it('transitions to viewing phase on success', async () => {
    fetchMock.mockResolvedValue({
      ok: true,
      json: async () => ({ job_id: 'abc123', status: 'done' }),
    })
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    expect(await screen.findByTestId('viewer3d')).toBeInTheDocument()
  })

  it('shows error message on API failure', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'No face detected' }),
    })
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    expect(await screen.findByText(/No face detected/)).toBeInTheDocument()
  })

  it('retry button resets to upload phase', async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      json: async () => ({ detail: 'fail' }),
    })
    render(<App />)
    fireEvent.click(screen.getByText('upload'))
    await screen.findByText(/fail/)
    fireEvent.click(screen.getByText(/重新上传|Retry/i))
    expect(screen.getByText('upload')).toBeInTheDocument()
  })
})
