import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, expect, it, vi } from 'vitest'
import App from './App'
import { proposal, runFixture } from './test-fixtures'
import { store } from './api'

vi.mock('./Flow', () => ({ Flow: () => <div aria-label="Returns directed workflow">Returns workflow</div> }))
class FakeSource {
  onopen = null
  onerror = null
  addEventListener() {}
  removeEventListener() {}
  close() {}
}
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
let request: ReturnType<typeof vi.fn>
beforeEach(() => {
  vi.stubGlobal('EventSource', FakeSource)
  request = vi.fn(async (url: string, options?: RequestInit): Promise<Response> => {
    if (url === '/api/customers') return json([{ id: 'customer-1', name: 'Alex Chen' }, { id: 'customer-2', name: 'Jordan Lee' }])
    if (url.startsWith('/api/orders')) return json([{ id: 'order-1', customer_id: 'customer-1', status: 'delivered', delivered_at: null, items: [{ id: 'item-1', name: 'Ceramic mug', quantity: 2, unit_price_cents: 2299 }] }])
    if (url.startsWith('/api/scenarios')) return json([{ id: 'scenario-1', title: 'Missing package', desk: 'delivery', customer_id: 'customer-1', order_id: 'order-1', item_id: 'item-1', message: 'My package is missing.', reason: 'missing', quantity: 2, delivery_checks_confirmed: true }])
    if (url === '/api/runs' && options?.method === 'POST') return json(runFixture({ status: 'awaiting_customer', result: { question: 'Where should we look for the package?' } }))
    if (url === '/api/runs/run-1/information') return json(runFixture({ id: 'run-2', parent_run_id: 'run-1', status: 'completed', result: { summary: 'A replacement has been arranged.' } }))
    if (url === '/api/runs/run-2') return json(runFixture({ id: 'run-2', parent_run_id: 'run-1', status: 'completed', result: { summary: 'A replacement has been arranged.' } }))
    if (url === '/api/runs/run-1') return json(runFixture({ status: 'awaiting_customer', result: { question: 'Where should we look for the package?' } }))
    if (url === '/api/approvals') return json([proposal])
    if (url.startsWith('/api/runs?')) return json([])
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal('fetch', request)
})
function mount(path = '/delivery') { return render(<MemoryRouter initialEntries={[path]}><App /></MemoryRouter>) }

it('creates an exact scenario request and continues clarification as a linked run', async () => {
  const user = userEvent.setup()
  mount()
  await screen.findByRole('option', { name: /Alex Chen/ })
  await user.selectOptions(screen.getByLabelText('Synthetic customer'), 'customer-1')
  await screen.findByRole('option', { name: 'Missing package' })
  await user.selectOptions(screen.getByLabelText('Demo scenario'), 'scenario-1')
  expect(screen.getByLabelText('I checked household members and safe delivery locations')).toBeChecked()
  await user.click(screen.getByRole('button', { name: /Start support run/ }))
  expect(JSON.parse(request.mock.calls.find(([url, opts]) => url === '/api/runs' && opts?.method === 'POST')![1].body)).toEqual({
    customer_id: 'customer-1', desk: 'delivery', message: 'My package is missing.', order_id: 'order-1', item_id: 'item-1', reason: 'missing', quantity: 2, delivery_checks_confirmed: true,
  })
  await screen.findByText('Where should we look for the package?')
  await user.type(screen.getByLabelText('Additional customer information'), 'Please check the porch.')
  await user.click(screen.getByRole('group', { name: 'Clarification details' }).querySelector('input[type="checkbox"]')!)
  await user.click(screen.getByRole('button', { name: 'Continue case' }))
  await screen.findByText('A replacement has been arranged.')
  expect(JSON.parse(request.mock.calls.find(([url]) => url.endsWith('/information'))![1].body)).toMatchObject({ quantity: 2, delivery_checks_confirmed: true })
  expect(screen.getByText('run-1', { selector: 'dd' })).toBeInTheDocument()
  expect(screen.queryByLabelText('Additional customer information')).not.toBeInTheDocument()
})

it('never displays a saved run belonging to another customer and isolates desk selection', async () => {
  store('retail:selection:delivery', { customer: 'customer-2', run: 'run-1' })
  const user = userEvent.setup()
  mount()
  await screen.findByText(/This run belongs to a different customer/)
  expect(screen.queryByText('My package is missing.')).not.toBeInTheDocument()
  await user.click(screen.getByRole('link', { name: /Returns & Refunds Desk/ }))
  expect(screen.getByLabelText('Synthetic customer')).toHaveValue('')
  expect(screen.getByLabelText('Returns directed workflow')).toBeInTheDocument()
  await user.click(screen.getByRole('link', { name: /Delivery Incident Desk/ }))
  expect(screen.getByLabelText('Synthetic customer')).toHaveValue('customer-2')
})

it('shows exact proposal values, confirms a decision, and handles a stale approval explicitly', async () => {
  request.mockImplementation(async (url: string, options?: RequestInit) => {
    if (url === '/api/customers') return json([])
    if (url === '/api/approvals') return json([proposal])
    if (url.endsWith('/decision')) {
      expect(JSON.parse(options?.body as string)).toEqual({ decision: 'approved' })
      return json({ detail: 'Proposal is already rejected.' }, 409)
    }
    return json({})
  })
  const user = userEvent.setup()
  mount('/approvals')
  await screen.findByText('$45.98')
  expect(screen.getByText('Exact quantity').nextElementSibling).toHaveTextContent('2')
  await user.click(screen.getByRole('button', { name: 'Approve proposal' }))
  expect(request.mock.calls.some(([url]) => url.endsWith('/decision'))).toBe(false)
  await user.click(screen.getByRole('button', { name: 'Confirm approval' }))
  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('stale or already decided')
  expect(screen.getByRole('alert')).toHaveTextContent('Proposal is already rejected.')
  await waitFor(() => expect(request.mock.calls.filter(([url]) => url === '/api/approvals').length).toBeGreaterThan(1))
})

it('does not infer delivery confirmation from customer text', async () => {
  const user = userEvent.setup()
  mount()
  await screen.findByRole('option', { name: /Alex Chen/ })
  await user.selectOptions(screen.getByLabelText('Synthetic customer'), 'customer-1')
  await waitFor(() => expect(screen.getByLabelText('Customer request')).toBeEnabled())
  await user.type(screen.getByLabelText('Customer request'), 'I checked every safe delivery location.')
  expect(screen.getByLabelText('I checked household members and safe delivery locations')).not.toBeChecked()
  await user.click(screen.getByRole('button', { name: /Start support run/ }))
  await screen.findByText('Where should we look for the package?')
  expect(JSON.parse(request.mock.calls.find(([url, opts]) => url === '/api/runs' && opts?.method === 'POST')![1].body).delivery_checks_confirmed).toBe(false)
})

it('retries a failed run as a linked run and explicitly cancels the new attempt', async () => {
  store('retail:selection:delivery', { customer: 'customer-1', run: 'run-1' })
  const standard = request.getMockImplementation()! as (url: string, options?: RequestInit) => Promise<Response>
  let cancelled = false
  request.mockImplementation(async (url: string, options?: RequestInit) => {
    if (url === '/api/runs/run-1') return json(runFixture({ status: 'failed', result: { summary: 'The demo carrier service did not respond.', error_type: 'carrier_timeout' } }))
    if (url === '/api/runs/run-1/retry') return json(runFixture({ id: 'run-2', parent_run_id: 'run-1' }))
    if (url === '/api/runs/run-2/cancel') { cancelled = true; return json(runFixture({ id: 'run-2', status: 'cancelled' })) }
    if (url === '/api/runs/run-2') return json(runFixture({ id: 'run-2', status: cancelled ? 'cancelled' : 'running' }))
    return standard(url, options)
  })
  const user = userEvent.setup()
  mount()
  await screen.findByRole('alert')
  expect(screen.getByRole('alert')).toHaveTextContent('carrier_timeout')
  await user.click(screen.getByRole('button', { name: 'Retry run' }))
  await screen.findByRole('button', { name: 'Cancel run' })
  expect(request.mock.calls.find(([url]) => url.endsWith('/retry'))?.[1].method).toBe('POST')
  await user.click(screen.getByRole('button', { name: 'Cancel run' }))
  await screen.findByText('cancelled', { selector: '.status' })
  expect(screen.queryByRole('button', { name: 'Cancel run' })).not.toBeInTheDocument()
})
