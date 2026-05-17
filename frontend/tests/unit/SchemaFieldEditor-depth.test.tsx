import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import SchemaFieldEditor from '../../src/components/QuickLook/SchemaFieldEditor'
import { useSchema } from '../../src/stores/schema'

const PID = 'p_depth'

describe('SchemaFieldEditor 3-level nesting', () => {
  it('renders array → items.object.properties → property.object.properties (line_items[].address.country)', () => {
    const fields = [{
      name: 'line_items',
      type: 'array',
      description: 'invoice line items',
      required: false,
      enum: null,
      properties: null,
      items: {
        name: null, type: 'object', description: 'one line', required: false, enum: null, format: null, items: null,
        properties: [{
          name: 'address',
          type: 'object',
          description: 'shipping address',
          required: false,
          enum: null,
          format: null,
          items: null,
          properties: [{
            name: 'country',
            type: 'string',
            description: 'ISO-3166 country code',
            required: false,
            enum: null,
            format: null,
            items: null,
            properties: null,
          }],
        }],
      },
    }]
    useSchema.setState({ byProject: { [PID]: fields } })
    render(<SchemaFieldEditor pid={PID} fields={fields as any} />)
    expect(screen.getByText('line_items')).toBeInTheDocument()
    expect(screen.getByText('address')).toBeInTheDocument()
    expect(screen.getByText('country')).toBeInTheDocument()
  })
})
