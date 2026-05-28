// BenchHeadline — the big "best 91.2% · supplier-hint × gemini-flash"
// strip at the top of the bench body, plus the right-hand counts.
//
// score formatting: 0.912 → "91.2%" (one decimal, never trailing zeros that
// look like "91.20%"). Null score collapses to em-dash so we don't flash a
// "0.0%" before the first eval lands.
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import BenchHeadline from '../BenchHeadline'

describe('BenchHeadline', () => {
  it('formats the best score as one-decimal percentage when present', () => {
    render(
      <BenchHeadline
        bestScore={0.912}
        bestPromptLabel="supplier-hint"
        bestModelLabel="gemini-flash"
        experimentCount={6}
        promptCount={4}
        modelCount={3}
        reviewedCount={56}
      />,
    )
    expect(screen.getByText(/91\.2/)).toBeInTheDocument()
    expect(screen.getByText('supplier-hint')).toBeInTheDocument()
    expect(screen.getByText('gemini-flash')).toBeInTheDocument()
  })

  it('renders em-dash placeholder when bestScore is null (no eval yet)', () => {
    render(
      <BenchHeadline
        bestScore={null}
        bestPromptLabel={null}
        bestModelLabel={null}
        experimentCount={0}
        promptCount={0}
        modelCount={0}
        reviewedCount={0}
      />,
    )
    expect(screen.getByTestId('bench-headline-score')).toHaveTextContent('—')
  })

  it('renders prompt/model counts using i18n template', () => {
    render(
      <BenchHeadline
        bestScore={0.5}
        bestPromptLabel="a"
        bestModelLabel="b"
        experimentCount={2}
        promptCount={3}
        modelCount={4}
        reviewedCount={10}
      />,
    )
    // counts strip — "3 prompts × 4 models"
    expect(screen.getByText(/3/)).toBeInTheDocument()
    expect(screen.getByText(/prompts/i)).toBeInTheDocument()
    expect(screen.getByText(/models/i)).toBeInTheDocument()
  })
})
