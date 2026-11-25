import { expect, it, vi } from 'vitest'
import { api } from './api'

it('preserves FastAPI field validation details instead of hiding them behind a generic 422', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({
    detail: [
      { type: 'string_too_long', loc: ['body', 'message'], msg: 'String should have at most 4000 characters', input: 'not rendered' },
      { type: 'less_than_equal', loc: ['body', 'quantity'], msg: 'Input should be less than or equal to 20', input: 21 },
    ],
  }), { status: 422 })))
  await expect(api('/runs', {})).rejects.toMatchObject({
    status: 422,
    message: 'message: String should have at most 4000 characters; quantity: Input should be less than or equal to 20',
  })
})
