import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { CitationOut } from '../types'
import { AnswerView } from './AnswerView'

const ART5: CitationOut = {
  chunk_id: 'eu-ai-act::5',
  doc_id: 'eu-ai-act',
  clause_label: 'EU AI Act — Article 5',
  text: 'The following AI practices shall be prohibited.',
  score: 8.2,
}

describe('AnswerView', () => {
  it('renders a citation chip labelled by clause_label and clicks through to the clause text', async () => {
    const user = userEvent.setup()
    render(
      <AnswerView answer="Certain practices are prohibited [eu-ai-act::5]." citations={[ART5]} />,
    )

    const chip = screen.getByRole('button', { name: 'EU AI Act — Article 5' })
    expect(chip).toBeInTheDocument()
    // The clause text is hidden until the chip is clicked (click-through is local, on demand).
    expect(screen.queryByText(ART5.text)).not.toBeInTheDocument()

    await user.click(chip)

    expect(screen.getByText(ART5.text)).toBeInTheDocument()
  })

  it('falls back to the chunk_id when a citation has no clause_label', () => {
    const unlabelled: CitationOut = { ...ART5, clause_label: null }
    render(<AnswerView answer="See [eu-ai-act::5]." citations={[unlabelled]} />)

    expect(screen.getByRole('button', { name: 'eu-ai-act::5' })).toBeInTheDocument()
  })

  it('leaves an unresolved [marker] as literal text, never inventing a chip', () => {
    render(<AnswerView answer="Mentions [eu-ai-act::999] only." citations={[]} />)

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText(/\[eu-ai-act::999\]/)).toBeInTheDocument()
  })
})
