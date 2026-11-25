import type { Activity, Proposal, Run } from './api'

export const proposal: Proposal = {
  id: 'proposal-1', run_id: 'run-1', case_id: 'case-1', customer_id: 'customer-1',
  order_id: 'order-1', item_id: 'item-1', action: 'refund', quantity: 2,
  amount_cents: 4598, currency: 'USD', citations: ['policy-returns-30'],
  explanation: 'Two damaged mugs qualify for a refund under the demo policy.',
  status: 'pending', created_at: '2026-11-20T12:00:00Z', decided_at: null,
}
export const runFixture = (overrides: Partial<Run> = {}): Run => ({
  id: 'run-1', case_id: 'case-1', parent_run_id: null, customer_id: 'customer-1',
  desk: 'delivery', status: 'running', message: 'My package is missing.',
  order_id: 'order-1', item_id: 'item-1', reason: 'missing', quantity: 2, delivery_checks_confirmed: false,
  result: null, trace_id: 'trace-demo-001', created_at: '2026-11-20T12:00:00Z',
  updated_at: '2026-11-20T12:00:00Z', proposal: null, ...overrides,
})
export const eventFixture = (overrides: Partial<Activity> = {}): Activity => ({
  id: 1, run_id: 'run-1', kind: 'agent_message', actor: 'Delivery specialist',
  node: 'identify', text: 'I located the shipment and checked its tracking history.',
  data: {}, created_at: '2026-11-20T12:01:00Z', ...overrides,
})
