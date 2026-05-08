import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import ToolCallCard from '../../src/components/Chat/ToolCallCard'

describe('ToolCallCard', () => {
  it('shows tool name folded by default', () => {
    render(
      <ToolCallCard event={{ type: 'tool_call', tool_name: 'derive_schema', tool_input: { x: 1 }, tool_result: { y: 2 }, ok: true }} />
    )
    expect(screen.getByText('derive_schema')).toBeInTheDocument()
    expect(screen.queryByText(/"x"/)).not.toBeInTheDocument()
  })

  it('expands on click and reveals input/result', async () => {
    render(
      <ToolCallCard event={{ type: 'tool_call', tool_name: 'extract_one', tool_input: { x: 1 }, tool_result: { y: 2 }, ok: true }} />
    )
    await userEvent.click(screen.getByRole('button'))
    expect(screen.getByText(/"x": 1/)).toBeInTheDocument()
    expect(screen.getByText(/"y": 2/)).toBeInTheDocument()
  })

  it('renders red border when ok is false', () => {
    const { container } = render(
      <ToolCallCard event={{ type: 'tool_call', tool_name: 'extract_one', tool_input: {}, tool_result: { error_code: 'x' }, ok: false }} />
    )
    expect(container.querySelector('[data-ok="false"]')).toBeInTheDocument()
  })
})
