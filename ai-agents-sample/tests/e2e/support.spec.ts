import { test, expect, type Page } from '../../frontend/testing/browser'
import { eventFixture, proposal, runFixture } from '../../frontend/src/test-fixtures'
import type { Run } from '../../frontend/src/api'

async function mockApi(page: Page) {
  let runs: Run[] = []
  let pending = false
  let failNext = false
  let staleNext = false
  let approvalReads = 0
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api', '')
    const body = route.request().postDataJSON()
    const reply = (value: unknown, status = 200) => route.fulfill({ status, json: value })
    if (path === '/customers') return reply([{ id: 'customer-1', name: 'Alex Chen' }, { id: 'customer-2', name: 'Jordan Lee' }])
    if (path === '/orders') return reply([{ id: 'order-1', customer_id: 'customer-1', status: 'delivered', delivered_at: '2026-11-18', items: [{ id: 'item-1', name: 'Ceramic mug', quantity: 2, unit_price_cents: 2299 }] }])
    if (path === '/scenarios') return reply([{ id: 'scenario-1', title: 'Try a sample case', customer_id: 'customer-1', desk: url.searchParams.get('desk'), message: url.searchParams.get('desk') === 'returns' ? 'Two mugs arrived damaged.' : 'My package is missing.', order_id: 'order-1', item_id: 'item-1', quantity: 2, reason: url.searchParams.get('desk') === 'returns' ? 'damaged: mugs arrived cracked' : 'missing package', delivery_checks_confirmed: url.searchParams.get('desk') === 'delivery' }])
    if (path === '/runs' && route.request().method() === 'POST') {
      if (failNext) { failNext = false; return reply({ detail: 'Demo service unavailable. Please retry.' }, 503) }
      const run = runFixture({ ...body, id: `run-${runs.length + 1}`, status: body.desk === 'returns' ? 'awaiting_approval' : 'awaiting_customer', proposal: body.desk === 'returns' ? proposal : null, result: body.desk === 'returns' ? null : { question: 'Which entrance should the courier check?' } })
      pending = body.desk === 'returns'
      runs.unshift(run)
      return reply(run)
    }
    if (path === '/runs') return reply(runs.filter(run => !url.searchParams.get('customer_id') || run.customer_id === url.searchParams.get('customer_id')))
    if (path === '/approvals') {
      approvalReads++
      return reply(pending ? [{ ...proposal, run_id: runs.find(run => run.desk === 'returns')?.id }] : [])
    }
    if (path.endsWith('/decision')) {
      pending = false
      if (staleNext) {
        staleNext = false
        runs = runs.map(run => run.desk === 'returns' ? { ...run, status: 'rejected', proposal: { ...proposal, status: 'rejected' } } : run)
        return reply({ detail: 'Approval is stale or already decided.' }, 409)
      }
      runs = runs.map(run => run.desk === 'returns' ? {
        ...run,
        status: body.decision === 'approved' ? 'completed' : 'rejected',
        proposal: { ...proposal, status: body.decision === 'approved' ? 'executed' : 'rejected' },
        result: body.decision === 'approved' ? {
          summary: 'Simulated refund complete.',
          citations: [{ id: 'policy-returns-30', title: 'Damaged items', text: 'Damaged goods qualify within the demo return window.' }],
        } : { summary: 'Reviewer rejected the proposed action.' },
      } : run)
      return reply({ ...proposal, status: body.decision })
    }
    if (path.endsWith('/events')) {
      const runId = path.split('/')[2]
      const events = [
        eventFixture({ run_id: runId }),
        eventFixture({ id: 2, run_id: runId, kind: 'node', node: 'approval', text: 'Waiting for a reviewer decision.', data: { state: 'waiting' } }),
      ]
      return route.fulfill({ contentType: 'text/event-stream', headers: { 'Cache-Control': 'no-cache' }, body: events.map(event => `id: ${event.id}\nevent: activity\ndata: ${JSON.stringify(event)}\n\n`).join('') })
    }
    const id = path.split('/')[2]
    const run = runs.find(run => run.id === id)
    if (path.endsWith('/information') && run) {
      const next = { ...run, ...body, message: `${run.message}\nCustomer update: ${body.message}`.slice(-4000), id: `run-${runs.length + 1}`, parent_run_id: run.id, status: 'completed' as const, result: { summary: 'The courier found your package at the side entrance.', citations: [{ id: 'shipping-1', title: 'Delivery checks', text: 'Check the safe place before reporting a lost delivery.' }] } }
      run.status = 'completed'
      run.result = { summary: 'Continued in a linked investigation.' }
      runs.unshift(next)
      return reply(next)
    }
    if (path.endsWith('/cancel') && run) { run.status = 'cancelled'; return reply(run) }
    if (run) return reply(run)
    return reply({ detail: 'Run not found.' }, 404)
  })
  return {
    failNext: () => { failNext = true },
    staleNext: () => { staleNext = true },
    approvalReads: () => approvalReads,
  }
}

async function startScenario(page: Page, desk: 'delivery' | 'returns') {
  await page.goto(`/${desk}`)
  await page.getByLabel('Synthetic customer').selectOption('customer-1')
  await page.getByLabel('Demo scenario').selectOption('scenario-1')
  await page.getByRole('button', { name: 'Start support run' }).click()
}

test('delivery clarification retains order, item, reason, quantity and explicit checkbox after reload', async ({ page }) => {
  await mockApi(page)
  await startScenario(page, 'delivery')
  await expect(page.getByText('Which entrance should the courier check?')).toBeVisible()
  await expect(page.getByText('I located the shipment and checked its tracking history.')).toBeVisible()
  await page.reload()
  await expect(page.getByText('I located the shipment and checked its tracking history.')).toHaveCount(1)
  await expect(page.getByLabel('Clarification order')).toHaveValue('order-1')
  await expect(page.getByLabel('Clarification item')).toHaveValue('item-1')
  await expect(page.getByLabel('Clarification reason')).toHaveValue('missing package')
  await expect(page.getByLabel('Clarification quantity')).toHaveValue('2')
  await expect(page.getByRole('group', { name: 'Clarification details' }).getByLabel('I checked household members and safe delivery locations')).toBeChecked()
  await page.getByLabel('Additional customer information').fill('The side entrance, please.')
  const informationRequest = page.waitForRequest(request => request.url().endsWith('/runs/run-1/information'))
  await page.getByRole('button', { name: 'Continue case' }).click()
  expect((await informationRequest).postDataJSON()).toEqual({
    order_id: 'order-1', item_id: 'item-1', reason: 'missing package',
    quantity: 2, delivery_checks_confirmed: true, message: 'The side entrance, please.',
  })
  await expect(page.getByText('The courier found your package at the side entrance.')).toBeVisible()
  await page.getByText('Delivery checks', { exact: false }).click()
  await expect(page.getByText('Check the safe place before reporting a lost delivery.')).toBeVisible()
  await expect(page.getByText('trace-demo-001')).toBeVisible()
  await page.getByRole('link', { name: /Run history/ }).click()
  await expect(page.getByRole('link', { name: /My package is missing./ })).toHaveCount(2)
  await page.getByRole('link', { name: /My package is missing. Customer update:/ }).click()
  await expect(page.getByText('The courier found your package at the side entrance.')).toBeVisible()
  await page.getByLabel('Synthetic customer').selectOption('customer-2')
  await expect(page.getByText('The courier found your package at the side entrance.')).toHaveCount(0)
  await expect(page.getByText('I located the shipment and checked its tracking history.')).toHaveCount(0)
  await expect(page.getByText('Your next resolution starts here.')).toBeVisible()
})

test('returns graph, exact approval, executed result, and separate desk state', async ({ page }) => {
  await mockApi(page)
  await startScenario(page, 'returns')
  await expect(page.getByLabel('Returns directed workflow')).toBeVisible()
  await expect(page.getByLabel('Workflow node states').getByText('approval: waiting')).toBeAttached()
  await expect(page.getByText('awaiting approval', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: /Delivery Incident Desk/ }).click()
  await expect(page.getByLabel('Synthetic customer')).toHaveValue('')
  await page.getByRole('link', { name: /Returns & Refunds Desk/ }).click()
  await expect(page.getByLabel('Synthetic customer')).toHaveValue('customer-1')
  await page.getByRole('link', { name: 'Open review inbox →' }).click()
  await expect(page.getByText('$45.98')).toBeVisible()
  await expect(page.getByText('Exact quantity').locator('..')).toContainText('2')
  await page.getByRole('button', { name: 'Approve proposal' }).click()
  await expect(page.getByRole('group', { name: 'Confirm reviewer decision' })).toContainText('2 items · $45.98 USD')
  await page.getByRole('button', { name: 'Confirm approval' }).click()
  await expect(page.getByText(/Simulated execution has been queued/)).toBeVisible()
  await page.getByRole('link', { name: /Returns & Refunds Desk/ }).click()
  await expect(page.getByText('Simulated refund complete.')).toBeVisible()
  await expect(page.getByText('completed', { exact: true })).toBeVisible()
})

test('rejects a proposal and displays API errors without losing the request', async ({ page }) => {
  const mock = await mockApi(page)
  await page.goto('/returns')
  await page.getByLabel('Synthetic customer').selectOption('customer-1')
  await page.getByLabel('Demo scenario').selectOption('scenario-1')
  mock.failNext()
  await page.getByRole('button', { name: 'Start support run' }).click()
  await expect(page.getByRole('alert')).toContainText('Demo service unavailable. Please retry.')
  await expect(page.getByLabel('Customer request')).toHaveValue('Two mugs arrived damaged.')
  await page.getByRole('button', { name: 'Start support run' }).click()
  await page.getByRole('link', { name: 'Open review inbox →' }).click()
  await page.getByRole('button', { name: 'Reject proposal' }).click()
  await page.getByRole('button', { name: 'Confirm rejection' }).click()
  await expect(page.getByText(/No action will be executed/)).toBeVisible()
  await page.getByRole('link', { name: /Returns & Refunds Desk/ }).click()
  await expect(page.getByText('Reviewer rejected the proposed action.')).toBeVisible()
})

test('stale approval error remains visible after the inbox successfully refreshes', async ({ page }) => {
  const mock = await mockApi(page)
  await startScenario(page, 'returns')
  await page.getByRole('link', { name: 'Open review inbox →' }).click()
  await page.getByRole('button', { name: 'Approve proposal' }).click()
  mock.staleNext()
  const readsBefore = mock.approvalReads()
  await page.getByRole('button', { name: 'Confirm approval' }).click()
  await expect(page.getByRole('alert')).toContainText('Approval is stale or already decided.')
  await expect.poll(mock.approvalReads).toBeGreaterThan(readsBefore)
  await expect(page.getByText('All caught up.')).toBeVisible()
  await expect(page.getByRole('alert')).toContainText('The inbox has been refreshed')
  await expect(page.getByRole('alert')).toContainText('Approval is stale or already decided.')
  await expect(page.getByRole('button', { name: 'Confirm approval' })).toHaveCount(0)
})
