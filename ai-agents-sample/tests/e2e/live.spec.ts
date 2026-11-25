import { test, expect } from '../../frontend/testing/browser'
import type { Customer, Desk, Order, Proposal, Run, Scenario } from '../../frontend/src/api'

test('real production UI queues both desks and observes history and review inbox without a worker', async ({ page }) => {
  test.skip(!process.env.RETAIL_LIVE_BASE_URL, 'Set RETAIL_LIVE_BASE_URL for an explicitly provisioned synthetic database.')
  test.setTimeout(60_000)
  const browserErrors: string[] = []
  const networkErrors: string[] = []
  let closedStreams = 0
  const created: { desk: Desk; run_id: string; order_id: string; item_id: string; status: string }[] = []
  page.on('console', message => { if (message.type() === 'error') browserErrors.push(message.text()) })
  page.on('pageerror', error => browserErrors.push(error.message))
  page.on('response', response => { if (response.status() >= 400) networkErrors.push(`${response.status()} ${response.url()}`) })
  page.on('requestfailed', request => {
    const failure = request.failure()?.errorText ?? 'Unknown network failure'
    if (new URL(request.url()).pathname.endsWith('/events') && failure.includes('ERR_ABORTED')) closedStreams++
    else networkErrors.push(`${failure} ${request.url()}`)
  })

  const customerResponse = await page.request.get('/api/customers')
  expect(customerResponse.ok()).toBe(true)
  const customers = await customerResponse.json() as Customer[]
  expect(customers.length).toBeGreaterThan(0)
  const customer = customers[0]
  const ordersResponse = await page.request.get(`/api/orders?customer_id=${encodeURIComponent(customer.id)}`)
  expect(ordersResponse.ok()).toBe(true)
  const orders = await ordersResponse.json() as Order[]
  const marker = `Browser smoke ${Date.now()}`
  for (const desk of ['delivery', 'returns'] as const) {
    const scenariosResponse = await page.request.get(`/api/scenarios?customer_id=${encodeURIComponent(customer.id)}&desk=${desk}`)
    expect(scenariosResponse.ok()).toBe(true)
    const scenarios = await scenariosResponse.json() as Scenario[]
    const scenario = scenarios.find(value => value.order_id && value.item_id && orders.some(order => order.id === value.order_id && order.items.some(item => item.id === value.item_id)))
    expect(scenario, `A complete ${desk} scenario is seeded`).toBeTruthy()
    if (!scenario?.order_id || !scenario.item_id) throw new Error('Complete synthetic scenario is required')
    const order = orders.find(value => value.id === scenario.order_id)!
    const item = order.items.find(value => value.id === scenario.item_id)!
    await page.goto(`/${desk}`)
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(desk === 'delivery' ? 'Delivery Incident Desk' : 'Returns & Refunds Desk')
    await page.getByLabel('Synthetic customer').selectOption(customer.id)
    await expect(page.getByLabel('Synthetic customer').locator('option:checked')).toContainText(customer.name)
    await page.getByLabel('Demo scenario').selectOption(scenario.id)
    await expect(page.getByLabel('Demo scenario').locator('option:checked')).toHaveText(scenario.title)
    await expect(page.getByRole('combobox', { name: 'Order', exact: true })).toHaveValue(order.id)
    await expect(page.getByRole('combobox', { name: 'Item', exact: true })).toHaveValue(item.id)
    await expect(page.getByRole('combobox', { name: 'Item', exact: true }).locator('option:checked')).toContainText(item.name)
    await page.getByLabel('Customer request').fill(`${scenario.message}\n${marker} ${desk}`)
    const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/runs') && response.request().method() === 'POST')
    await page.getByRole('button', { name: 'Start support run' }).click()
    const response = await responsePromise
    expect(response.status()).toBe(201)
    const run = await response.json() as Run
    expect(run).toMatchObject({ customer_id: customer.id, desk, status: 'queued', order_id: order.id, item_id: item.id, delivery_checks_confirmed: scenario.delivery_checks_confirmed })
    await expect(page.locator('.run-strip .status')).toHaveText('queued')
    await expect(page.getByLabel('Persisted activity timeline')).toContainText('Investigation queued.')
    await expect(page.getByText(run.trace_id, { exact: true })).toBeVisible()
    expect(run.trace_id).toMatch(/^[a-f0-9]{32}$/)
    await expect(page.getByRole('alert')).toHaveCount(0)
    created.push({ desk, run_id: run.id, order_id: order.id, item_id: item.id, status: run.status })
  }
  await page.getByRole('link', { name: /Run history/ }).click()
  for (const run of created) {
    const entry = page.locator('.history-list article').filter({ hasText: run.run_id })
    await expect(entry).toContainText(`${marker} ${run.desk}`)
    await expect(entry.locator('.status')).toHaveText('queued')
  }
  const approvalsPromise = page.waitForResponse(response => response.url().endsWith('/api/approvals'))
  await page.getByRole('link', { name: /Review inbox/ }).click()
  const approvalsResponse = await approvalsPromise
  expect(approvalsResponse.status()).toBe(200)
  const proposals = await approvalsResponse.json() as Proposal[]
  await expect(page.locator('.approval-list > section')).toHaveCount(proposals.length)
  if (!proposals.length) await expect(page.getByText('All caught up.')).toBeVisible()
  for (const proposal of proposals) await expect(page.locator('.approval-list')).toContainText(proposal.id)
  await expect(page.getByRole('alert')).toHaveCount(0)
  expect(browserErrors, 'Browser console/runtime errors').toEqual([])
  expect(networkErrors, 'Unexpected failed network requests or HTTP errors').toEqual([])
  console.log(JSON.stringify({ baseURL: process.env.RETAIL_LIVE_BASE_URL, created, history_verified: created.length, pending_proposals: proposals.length, browser_errors: browserErrors, network_errors: networkErrors, intentionally_closed_streams: closedStreams }))
})
