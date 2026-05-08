import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import Composer from '../../src/components/Chat/Composer'

describe('Composer', () => {
  it('calls onSubmit on Enter', async () => {
    const onSubmit = vi.fn()
    render(<Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={onSubmit} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, 'hello')
    await userEvent.keyboard('{Enter}')
    expect(onSubmit).toHaveBeenCalledWith('hello')
  })

  it('shows slash menu when text starts with /', async () => {
    render(<Composer disabled={false} pending={[]} onAttach={() => {}} onSubmit={() => {}} />)
    const input = screen.getByRole('textbox')
    await userEvent.type(input, '/ext')
    expect(screen.getByText('/extract')).toBeInTheDocument()
  })

  it('shows pending attachment chips', () => {
    render(<Composer disabled={false} pending={[{ filename: 'a.pdf' }]} onAttach={() => {}} onSubmit={() => {}} />)
    expect(screen.getByText('a.pdf')).toBeInTheDocument()
  })
})
