import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import Composer from '../../src/components/Chat/Composer'

describe('Composer', () => {
  it('calls onSubmit on Enter', async () => {
    const onSubmit = vi.fn()
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={onSubmit} />)
    const input = screen.getByPlaceholderText('say something to the agent, or type / for a command…')
    await userEvent.type(input, 'hello')
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('hello')
  })

  it('shows slash menu when text starts with /', async () => {
    render(<Composer disabled={false} pending={[]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />)
    const input = screen.getByPlaceholderText('say something to the agent, or type / for a command…')
    await userEvent.type(input, '/ext')
    // The slash menu renders a .cmd span; the row2 chips also show /extract as <b>.
    // getAllByText handles both; check at least one is in the slashmenu.
    const matches = screen.getAllByText('/extract')
    expect(matches.length).toBeGreaterThanOrEqual(1)
    // The .cmd span inside .slashmenu should be present
    expect(matches.some(el => el.className === 'cmd')).toBe(true)
  })

  it('shows pending attachment chips', () => {
    render(<Composer disabled={false} pending={[{ filename: 'a.pdf' }]} onAttach={(_files: File[]) => {}} onSubmit={() => {}} />)
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })
})
