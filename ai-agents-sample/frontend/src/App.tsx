import { createContext, useCallback, useContext, useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useSearchParams } from 'react-router-dom'
import { activeStatuses, api, ApiError, encoded, errorText, label, money, readStored, store, type Activity, type Customer, type Desk, type Input, type Order, type Proposal, type Run, type Scenario } from './api'
import { Flow } from './Flow'
import { useActivity } from './useActivity'

const Customers = createContext<Customer[]>([])
export function ErrorNotice({ message }: { message: string }) {
  return message ? <div className="notice error" role="alert"><strong>Something needs attention</strong><span>{message}</span></div> : null
}
function Status({ value }: { value: string }) { return <span className={`status status-${value}`}>{label(value)}</span> }
function CustomerSelect({ value, onChange, disabled = false, all = false }: { value: string; onChange: (value: string) => void; disabled?: boolean; all?: boolean }) {
  const customers = useContext(Customers)
  return <label>Synthetic customer<select value={value} onChange={event => onChange(event.target.value)} disabled={disabled || !customers.length}>
    <option value="">{all ? 'All synthetic customers' : 'Select a demo customer'}</option>
    {customers.map(customer => <option key={customer.id} value={customer.id}>{customer.name} · {customer.id}</option>)}
  </select></label>
}

export default function App() {
  const [customers, setCustomers] = useState<Customer[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError('')
    api<Customer[]>('/customers', undefined, controller.signal).then(setCustomers).catch(error => { if (!controller.signal.aborted) setError(errorText(error)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [attempt])
  return <Customers.Provider value={customers}>
    <a className="skip-link" href="#main">Skip to workspace</a>
    <header className="site-header">
      <div className="brand"><span className="brand-mark" aria-hidden="true">p<span>+</span>p</span><div><strong>parcel & pine</strong><span>RETAIL SUPPORT STUDIO</span></div></div>
      <div className="demo-badge"><span aria-hidden="true">●</span> Local simulated demo <small>No real payments · No authentication</small></div>
    </header>
    <div className="app-shell">
      <aside className="sidebar"><p className="eyebrow">YOUR WORKSPACE</p><nav aria-label="Main navigation">
        <NavLink to="/delivery"><span aria-hidden="true">◈</span> Delivery Incident Desk<small>Specialists in discussion</small></NavLink>
        <NavLink to="/returns"><span aria-hidden="true">⌘</span> Returns & Refunds Desk<small>A directed path to resolution</small></NavLink>
        <NavLink to="/approvals"><span aria-hidden="true">✓</span> Review inbox<small>Human decisions, exact actions</small></NavLink>
        <NavLink to="/history"><span aria-hidden="true">◷</span> Run history<small>Every case, in context</small></NavLink>
      </nav><div className="sidebar-note"><strong>Made for a safe sandbox.</strong><p>All customers, orders, decisions, and financial actions are synthetic. Activity shows concise specialist summaries, never hidden reasoning.</p></div></aside>
      <main id="main">
        {loading && <p role="status">Connecting to the local demo…</p>}
        <ErrorNotice message={error} />
        {error && <button className="secondary" onClick={() => setAttempt(value => value + 1)}>Reconnect to API</button>}
        {!loading && !error && !customers.length && <div className="notice">No synthetic customers are available. Seed the demo backend, then reconnect.<button onClick={() => setAttempt(value => value + 1)}>Refresh customers</button></div>}
        <Routes>
          <Route path="/delivery" element={<DeskPage key="delivery" desk="delivery" />} />
          <Route path="/returns" element={<DeskPage key="returns" desk="returns" />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="/history" element={<History />} />
          <Route path="*" element={<Navigate to="/delivery" replace />} />
        </Routes>
      </main>
    </div>
    <footer>PARCEL & PINE <span>Local-first retail support · Observe. Review. Resolve.</span></footer>
  </Customers.Provider>
}

type Selection = { customer: string; run: string }
const emptyInput: Input = { message: '', quantity: 1, delivery_checks_confirmed: false }
function DeliveryCheck({ checked, onChange }: { checked: boolean; onChange: (value: boolean) => void }) {
  return <label className="check-label"><input type="checkbox" checked={checked} onChange={event => onChange(event.target.checked)} /><span>I checked household members and safe delivery locations</span></label>
}
function DeskPage({ desk }: { desk: Desk }) {
  const [params, setParams] = useSearchParams()
  const [selection, setSelection] = useState<Selection>(() => params.has('customer') ? { customer: params.get('customer') ?? '', run: params.get('run') ?? '' } : readStored(`retail:selection:${desk}`, { customer: '', run: '' }))
  const { customer, run: selectedId } = selection
  const [orders, setOrders] = useState<Order[]>([])
  const [scenarios, setScenarios] = useState<Scenario[]>([])
  const [runs, setRuns] = useState<Run[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [input, setInput] = useState<Input>(emptyInput)
  const [scenarioId, setScenarioId] = useState('')
  const [loading, setLoading] = useState(false)
  const [runLoading, setRunLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [runError, setRunError] = useState('')
  const [continuation, setContinuation] = useState('')
  const [clarifyInput, setClarifyInput] = useState<Omit<Input, 'message'>>({ quantity: 1, delivery_checks_confirmed: false })
  const [reload, setReload] = useState(0)
  const context = useRef(selection)
  context.current = selection
  const detailVersion = useRef(0)
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const visibleRun = run?.id === selectedId && run.customer_id === customer && run.desk === desk ? run : null
  const choose = (next: Selection) => { setError(''); setRunError(''); setSelection(next); setParams({}, { replace: true }) }
  useEffect(() => { store(`retail:selection:${desk}`, selection) }, [selection, desk])

  useEffect(() => {
    setOrders([]); setScenarios([]); setRuns([]); setInput(emptyInput); setScenarioId(''); setContinuation(''); setError('')
    if (!customer) { setLoading(false); return }
    const controller = new AbortController()
    setLoading(true)
    Promise.all([
      api<Order[]>(`/orders?customer_id=${encoded(customer)}`, undefined, controller.signal),
      api<Scenario[]>(`/scenarios?customer_id=${encoded(customer)}&desk=${desk}`, undefined, controller.signal),
      api<Run[]>(`/runs?customer_id=${encoded(customer)}`, undefined, controller.signal),
    ]).then(([orders, scenarios, runs]) => {
      if (controller.signal.aborted) return
      setOrders(orders.filter(order => order.customer_id === customer))
      setScenarios(scenarios.filter(scenario => scenario.customer_id === customer && scenario.desk === desk))
      setRuns(runs.filter(run => run.customer_id === customer && run.desk === desk))
    }).catch(error => { if (!controller.signal.aborted) setError(errorText(error)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [customer, desk, reload])

  const loadRun = useCallback(async (signal?: AbortSignal) => {
    if (!selectedId || !customer) return
    const version = ++detailVersion.current
    const next = await api<Run>(`/runs/${encoded(selectedId)}`, undefined, signal)
    if (signal?.aborted || version !== detailVersion.current || context.current.customer !== customer || context.current.run !== selectedId) return
    if (next.customer_id !== customer || next.desk !== desk) throw new Error('This run belongs to a different customer or desk. Select a matching run from history.')
    setRun(next); setRunError('')
    setRuns(previous => [next, ...previous.filter(run => run.id !== next.id)])
  }, [selectedId, customer, desk])
  useEffect(() => {
    setRunError(''); setContinuation('')
    if (!selectedId || !customer) { setRunLoading(false); return }
    const controller = new AbortController()
    setRunLoading(true)
    const refresh = () => loadRun(controller.signal).catch(error => { if (!controller.signal.aborted) setRunError(errorText(error)) }).finally(() => { if (!controller.signal.aborted) setRunLoading(false) })
    void refresh()
    const timer = setInterval(refresh, 5000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [loadRun, selectedId, customer])
  const onActivity = useCallback(() => {
    if (refreshTimer.current) return
    refreshTimer.current = setTimeout(() => {
      refreshTimer.current = null
      void loadRun().catch(error => { if (context.current.run === selectedId) setRunError(errorText(error)) })
    }, 250)
  }, [loadRun, selectedId])
  useEffect(() => () => { if (refreshTimer.current) { clearTimeout(refreshTimer.current); refreshTimer.current = null } }, [selectedId, customer])
  const stream = useActivity(visibleRun?.id ?? null, onActivity)
  useEffect(() => {
    if (visibleRun) setClarifyInput({ order_id: visibleRun.order_id ?? undefined, item_id: visibleRun.item_id ?? undefined, reason: visibleRun.reason ?? undefined, quantity: visibleRun.quantity, delivery_checks_confirmed: visibleRun.delivery_checks_confirmed ?? false })
  }, [visibleRun?.id])

  async function mutate(path: string, body: unknown) {
    const original = { ...selection }
    ++detailVersion.current
    setBusy(true); setError('')
    try {
      const next = await api<Run>(path, body)
      if (context.current.customer !== original.customer || context.current.run !== original.run) return
      if (next.customer_id !== customer || next.desk !== desk) throw new Error('API returned a run for a different customer or desk.')
      ++detailVersion.current
      setRuns(previous => [next, ...previous.filter(run => run.id !== next.id)])
      setSelection({ customer, run: next.id }); setRun(next); setContinuation('')
    } catch (error) { if (context.current.customer === original.customer) setError(errorText(error)) }
    finally { setBusy(false) }
  }
  function applyScenario(id: string) {
    setScenarioId(id)
    const scenario = scenarios.find(value => value.id === id)
    setInput(scenario ? { message: scenario.message, order_id: scenario.order_id ?? undefined, item_id: scenario.item_id ?? undefined, reason: scenario.reason ?? undefined, quantity: scenario.quantity, delivery_checks_confirmed: scenario.delivery_checks_confirmed ?? false } : emptyInput)
  }
  const order = orders.find(order => order.id === input.order_id)
  const delivery = desk === 'delivery'
  return <>
    <div className="page-heading"><div><p className="eyebrow">{delivery ? '01 / COLLABORATIVE SUPPORT' : '02 / POLICY-GUIDED RESOLUTION'}</p><h1>{delivery ? 'Delivery Incident Desk' : 'Returns & Refunds Desk'}</h1><p>{delivery ? 'The right specialists. One shared conversation.' : 'From request to resolution, with a human in the loop.'}</p></div><span className="outline-badge">SIMULATED WORKSPACE</span></div>
    <div className="workspace">
      <section className="panel request-panel" aria-label="Start a support run">
        <div className="panel-heading"><div><p className="eyebrow">CASE INTAKE</p><h2>Let’s make it right.</h2></div></div>
        <CustomerSelect value={customer} disabled={busy} onChange={value => choose({ customer: value, run: '' })} />
        {loading && <p role="status">Loading this customer’s orders and scenarios…</p>}
        <form onSubmit={event => { event.preventDefault(); void mutate('/runs', { ...input, customer_id: customer, desk }) }}>
          <fieldset disabled={!customer || loading || busy}><legend className="sr-only">New support case</legend>
            <label>Demo scenario<select value={scenarioId} onChange={event => applyScenario(event.target.value)}><option value="">Write your own request</option>{scenarios.map(scenario => <option key={scenario.id} value={scenario.id}>{scenario.title}</option>)}</select></label>
            {!loading && customer && !scenarios.length && <p className="hint">No saved scenarios. Start with a custom request.</p>}
            <label>Order<select value={input.order_id ?? ''} onChange={event => setInput({ ...input, order_id: event.target.value || undefined, item_id: undefined })}><option value="">Not specified</option>{orders.map(order => <option key={order.id} value={order.id}>{order.id} · {label(order.status)}</option>)}</select></label>
            <label>Item<select value={input.item_id ?? ''} onChange={event => setInput({ ...input, item_id: event.target.value || undefined })} disabled={!order}><option value="">Not specified</option>{order?.items.map(item => <option key={item.id} value={item.id}>{item.name} · {money(item.unit_price_cents)} · {item.quantity} ordered</option>)}</select></label>
            <div className="form-row"><label>Reason<input maxLength={1000} value={input.reason ?? ''} placeholder={delivery ? 'e.g. missing package' : 'damaged: mug arrived cracked'} onChange={event => setInput({ ...input, reason: event.target.value || undefined })} /></label><label className="quantity">Quantity<input type="number" min="1" max="20" step="1" required value={input.quantity} onChange={event => setInput({ ...input, quantity: Number(event.target.value) })} /></label></div>
            {!delivery && <p className="hint">Use “damaged: description” or “defective: description”, for example “defective: kettle does not switch on”.</p>}
            {delivery && <><DeliveryCheck checked={input.delivery_checks_confirmed} onChange={value => setInput({ ...input, delivery_checks_confirmed: value })} /><p className="hint">This explicit customer confirmation is needed before a delivery replacement or refund. Leave unchecked if you still need help checking.</p></>}
            <label>Customer request<textarea rows={4} required maxLength={4000} placeholder={delivery ? 'Tell us what happened to your delivery…' : 'What would you like to return or replace?'} value={input.message} onChange={event => setInput({ ...input, message: event.target.value })} /></label>
            <button type="submit" className="primary full" disabled={!input.message.trim() || !Number.isInteger(input.quantity) || input.quantity < 1 || input.quantity > 20}>{busy ? 'Working…' : 'Start support run'} <span aria-hidden="true">↗</span></button>
          </fieldset>
        </form>
        {!customer && <p className="hint">Choose a synthetic customer to explore orders and scenarios.</p>}
        <ErrorNotice message={error} />
        {error && <button className="secondary" onClick={() => { setReload(value => value + 1); setError('') }}>Reload customer data</button>}
        <div className="recent-runs"><label>Selected run<select value={selectedId} disabled={!customer || busy} onChange={event => choose({ customer, run: event.target.value })}><option value="">No run selected</option>{selectedId && !runs.some(run => run.id === selectedId) && <option value={selectedId}>{selectedId}</option>}{runs.map(run => <option key={run.id} value={run.id}>{run.id} · {label(run.status)}</option>)}</select></label><p className="hint">Customer and run selections are saved separately for each desk.</p></div>
      </section>
      <div className="case-workspace">
        {!delivery && <Flow events={stream.events} />}
        {delivery && <section className="panel team-panel"><div><p className="eyebrow">GROUP DISCUSSION</p><h2>A small team. A shared goal.</h2><p className="muted">Specialists take turns as the case unfolds. Follow their concise updates below.</p></div><div className="team"><span><i>IN</i>Intake</span><span><i>OR</i>Orders</span><span><i>DL</i>Delivery</span><span><i>PL</i>Policy</span></div></section>}
        <section className="panel activity-panel">
          <div className="panel-heading"><div><p className="eyebrow">{delivery ? 'SPECIALIST CONVERSATION' : 'WORKFLOW ACTIVITY'}</p><h2>{visibleRun ? 'Resolution in motion' : 'Ready when you are'}</h2></div><span className={`connection ${stream.connection === 'Live' ? 'live' : ''}`} role="status">{selectedId ? stream.connection : 'No active stream'}</span></div>
          <ErrorNotice message={runError} />
          {runError && <button className="secondary" onClick={() => void loadRun().catch(error => setRunError(errorText(error)))}>Retry loading run</button>}
          {runLoading && <p role="status">Loading run details…</p>}
          {!selectedId && <div className="empty"><span aria-hidden="true">✦</span><h3>Your next resolution starts here.</h3><p>Pick a scenario or describe a customer request. Activity and evidence will appear here as specialists work.</p></div>}
          {visibleRun && <><div className="run-strip"><Status value={visibleRun.status} /><code>{visibleRun.id}</code><span>{visibleRun.quantity} item{visibleRun.quantity === 1 ? '' : 's'}</span></div><div className="request-quote"><span className="eyebrow">CUSTOMER REQUEST</span><p>{visibleRun.message}</p></div><Timeline events={stream.events} delivery={delivery} />{!stream.events.length && <p className="muted">No activity yet. Listening for saved and new events…</p>}</>}
        </section>
        {visibleRun && <section className="panel result-panel"><div className="panel-heading"><div><p className="eyebrow">CASE RECORD</p><h2>Outcome & evidence</h2></div><div className="actions">{activeStatuses.has(visibleRun.status) && <button className="secondary danger" disabled={busy} onClick={() => void mutate(`/runs/${encoded(visibleRun.id)}/cancel`, {})}>Cancel run</button>}{['failed', 'interrupted'].includes(visibleRun.status) && <button disabled={busy} onClick={() => void mutate(`/runs/${encoded(visibleRun.id)}/retry`, {})}>Retry run</button>}</div></div>
          <dl className="metadata"><div><dt>Case</dt><dd>{visibleRun.case_id}</dd></div><div><dt>Order / item</dt><dd>{visibleRun.order_id ?? 'Not specified'} / {visibleRun.item_id ?? 'Not specified'}</dd></div><div><dt>Trace ID</dt><dd><code>{visibleRun.trace_id}</code></dd></div>{visibleRun.parent_run_id && <div><dt>Previous run</dt><dd>{visibleRun.parent_run_id}</dd></div>}</dl>
          <p>{visibleRun.result?.summary ?? 'A final result will appear when the run reaches an outcome.'}</p>
          {visibleRun.result?.termination_reason && <p><strong>Termination:</strong> {label(visibleRun.result.termination_reason)}</p>}
          {visibleRun.result?.error_type && <div className="notice error" role="alert">Run error: {visibleRun.result.error_type}</div>}
          {!!visibleRun.result?.citations?.length && <div className="citations"><h3>Policy evidence</h3>{visibleRun.result.citations.map(citation => <details key={citation.id}><summary>{citation.title} <code>{citation.id}</code></summary><p>{citation.text}</p></details>)}</div>}
          {visibleRun.proposal && <ProposalDetails proposal={visibleRun.proposal} />}
          {visibleRun.status === 'awaiting_approval' && <p className="notice">A reviewer must approve the exact proposed action before simulated execution. <Link to="/approvals">Open review inbox →</Link></p>}
          {visibleRun.status === 'awaiting_customer' && <form className="clarification" onSubmit={(event: FormEvent) => {
            event.preventDefault()
            void mutate(`/runs/${encoded(visibleRun.id)}/information`, { ...clarifyInput, message: continuation })
          }}>
            <h3>A little more information</h3>
            <p>{visibleRun.result?.question ?? 'Please provide the missing details to continue.'}</p>
            <p className="hint">Continuing creates a linked run. Existing context is retained; choose a matching item if you change the order.</p>
            <fieldset disabled={busy}>
              <legend className="sr-only">Clarification details</legend>
              <label>Clarification order
                <select value={clarifyInput.order_id ?? ''} required={!!visibleRun.order_id} onChange={event => setClarifyInput({ ...clarifyInput, order_id: event.target.value || undefined, item_id: undefined })}>
                  <option value="" disabled={!!visibleRun.order_id}>Not specified</option>
                  {orders.map(order => <option key={order.id} value={order.id}>{order.id}</option>)}
                </select>
              </label>
              <label>Clarification item
                <select value={clarifyInput.item_id ?? ''} required={!!visibleRun.item_id} onChange={event => setClarifyInput({ ...clarifyInput, item_id: event.target.value || undefined })} disabled={!clarifyInput.order_id}>
                  <option value="" disabled={!!visibleRun.item_id}>Not specified</option>
                  {orders.find(order => order.id === clarifyInput.order_id)?.items.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
                </select>
              </label>
              <div className="form-row">
                <label>Clarification reason<input maxLength={1000} required={!!visibleRun.reason} value={clarifyInput.reason ?? ''} placeholder={delivery ? 'missing package' : 'damaged: describe the issue'} onChange={event => setClarifyInput({ ...clarifyInput, reason: event.target.value || undefined })} /></label>
                <label className="quantity">Clarification quantity<input type="number" min="1" max="20" step="1" required value={clarifyInput.quantity} onChange={event => setClarifyInput({ ...clarifyInput, quantity: Number(event.target.value) })} /></label>
              </div>
              {delivery && <DeliveryCheck checked={clarifyInput.delivery_checks_confirmed} onChange={value => setClarifyInput({ ...clarifyInput, delivery_checks_confirmed: value })} />}
              <label>Additional customer information<textarea required maxLength={4000} value={continuation} onChange={event => setContinuation(event.target.value)} /></label>
              <button disabled={busy || !continuation.trim() || !Number.isInteger(clarifyInput.quantity) || clarifyInput.quantity < 1 || clarifyInput.quantity > 20}>Continue case</button>
            </fieldset>
          </form>}
        </section>}
      </div>
    </div>
  </>
}

function Timeline({ events, delivery }: { events: Activity[]; delivery: boolean }) {
  return <ol className={`timeline ${delivery ? 'discussion' : ''}`} aria-label="Persisted activity timeline" aria-live="polite" aria-relevant="additions">{events.map(event => {
    const agent = event.kind === 'agent_message' || event.kind === 'agent_delta'
    return <li key={event.id} className={agent ? 'agent-event' : 'system-event'}><span className="avatar" aria-hidden="true">{agent ? event.actor?.slice(0, 2).toUpperCase() : '·'}</span><div className="event-content"><div className="event-meta"><strong>{agent ? event.actor : label(event.kind)}</strong>{event.node && <span>{label(event.node)}</span>}<time dateTime={event.created_at}>{new Date(event.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div><p>{event.text || `${label(event.kind)} update`}</p>{event.kind === 'evidence' && <span className="chip">Policy evidence</span>}</div></li>
  })}</ol>
}

export function ProposalDetails({ proposal }: { proposal: Proposal }) {
  return <div className="proposal-details"><div className="proposal-title"><h3>{proposal.action === 'refund' ? 'Simulated refund' : 'Simulated replacement'}</h3><Status value={proposal.status} /></div><dl className="proposal-grid"><div><dt>Exact amount</dt><dd>{money(proposal.amount_cents, proposal.currency)} <small>{proposal.currency}</small></dd></div><div><dt>Exact quantity</dt><dd>{proposal.quantity}</dd></div><div><dt>Order</dt><dd>{proposal.order_id}</dd></div><div><dt>Item</dt><dd>{proposal.item_id}</dd></div></dl><p>{proposal.explanation}</p>{proposal.citations.length > 0 && <p className="hint">Policy references: {proposal.citations.join(' · ')}</p>}<p className="hint">Proposal {proposal.id} · Customer {proposal.customer_id} · Case {proposal.case_id}</p></div>
}

function Approvals() {
  const [proposals, setProposals] = useState<Proposal[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState<string | null>(null)
  const [confirmation, setConfirmation] = useState<{ proposal: Proposal; decision: 'approved' | 'rejected' } | null>(null)
  const [reload, setReload] = useState(0)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    const controller = new AbortController()
    async function refresh() {
      try { const next = await api<Proposal[]>('/approvals', undefined, controller.signal); if (!controller.signal.aborted) setProposals(next) }
      catch (error) { if (!controller.signal.aborted) setError(errorText(error)) }
      finally { if (!controller.signal.aborted) setLoading(false) }
    }
    void refresh()
    const timer = setInterval(refresh, 5000)
    return () => { alive.current = false; controller.abort(); clearInterval(timer) }
  }, [reload])
  async function decide() {
    if (!confirmation) return
    const { proposal, decision } = confirmation
    setBusy(proposal.id); setError(''); setNotice('')
    try {
      await api<Proposal>(`/approvals/${encoded(proposal.id)}/decision`, { decision })
      if (alive.current) setNotice(`Proposal ${proposal.id} ${decision}. ${decision === 'approved' ? 'Simulated execution has been queued; open the run to follow progress.' : 'No action will be executed.'}`)
      try { await api<Run>(`/runs/${encoded(proposal.run_id)}`) }
      catch (error) { if (alive.current) setError(`Decision recorded, but run details could not refresh: ${errorText(error)}`) }
    } catch (error) {
      if (alive.current) setError(error instanceof ApiError && [404, 409, 410, 422].includes(error.status) ? `This proposal may be stale or already decided. ${error.message} The inbox has been refreshed; review the current action before trying again.` : errorText(error))
    } finally { if (alive.current) { setBusy(null); setConfirmation(null); setReload(value => value + 1) } }
  }
  return <><div className="page-heading"><div><p className="eyebrow">HUMAN IN THE LOOP</p><h1>Review inbox</h1><p>Review the exact action. You’re the final checkpoint.</p></div><button className="secondary" onClick={() => { setError(''); setLoading(true); setReload(value => value + 1) }}>Refresh inbox</button></div><div className="notice">Demo reviewer mode · All synthetic customers are visible here. No real money moves.</div><ErrorNotice message={error} />{notice && <p className="notice success" role="status">{notice}</p>}{loading && <p role="status">Loading pending proposals…</p>}{!loading && !proposals.length && <div className="panel empty"><span aria-hidden="true">✓</span><h2>All caught up.</h2><p>No pending approvals. Proposals awaiting review will appear here automatically.</p></div>}<div className="approval-list">{proposals.map(proposal => <section key={proposal.id} className="panel"><ProposalDetails proposal={proposal} /><div className="actions"><Link to={`/history?customer=${encoded(proposal.customer_id)}`}>Find related run</Link><button className="secondary danger" disabled={!!busy} onClick={() => setConfirmation({ proposal, decision: 'rejected' })}>Reject proposal</button><button disabled={!!busy} onClick={() => setConfirmation({ proposal, decision: 'approved' })}>Approve proposal</button></div>{confirmation?.proposal.id === proposal.id && <div className="confirm-box" role="group" aria-label="Confirm reviewer decision"><h3>Confirm {confirmation.decision === 'approved' ? 'approval' : 'rejection'}</h3><p>{label(proposal.action)} · {proposal.quantity} item{proposal.quantity === 1 ? '' : 's'} · {money(proposal.amount_cents, proposal.currency)} {proposal.currency} · {proposal.item_id}</p><p>This decision applies only to proposal {proposal.id}.</p><div className="actions"><button disabled={!!busy} onClick={() => void decide()}>{busy ? 'Submitting decision…' : `Confirm ${confirmation.decision === 'approved' ? 'approval' : 'rejection'}`}</button><button className="secondary" disabled={!!busy} onClick={() => setConfirmation(null)}>Keep reviewing</button></div></div>}</section>)}</div></>
}

function History() {
  const [params] = useSearchParams()
  const [customer, setCustomer] = useState(params.get('customer') ?? '')
  const [desk, setDesk] = useState('')
  const [runs, setRuns] = useState<Run[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setRuns([]); setLoading(true); setError('')
    api<Run[]>(`/runs${customer ? `?customer_id=${encoded(customer)}` : ''}`, undefined, controller.signal).then(runs => { if (!controller.signal.aborted) setRuns(runs.filter(run => !customer || run.customer_id === customer)) }).catch(error => { if (!controller.signal.aborted) setError(errorText(error)) }).finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [customer, reload])
  const filtered = runs.filter(run => !desk || run.desk === desk)
  return <><div className="page-heading"><div><p className="eyebrow">THE CASE ARCHIVE</p><h1>Run history</h1><p>Every conversation and decision leaves a clear trail.</p></div><button className="secondary" onClick={() => setReload(value => value + 1)}>Refresh history</button></div><section className="panel"><div className="filters"><CustomerSelect value={customer} onChange={setCustomer} all /><label>Desk<select value={desk} onChange={event => setDesk(event.target.value)}><option value="">Both desks</option><option value="delivery">Delivery Incident Desk</option><option value="returns">Returns & Refunds Desk</option></select></label></div><ErrorNotice message={error} />{loading && <p role="status">Loading run history…</p>}{!loading && !filtered.length && <div className="empty"><h2>No runs to show.</h2><p>Start a support run in either desk, or change the filters.</p></div>}<div className="history-list">{filtered.map(run => <article key={run.id}><div><span className="eyebrow">{run.desk === 'delivery' ? 'DELIVERY' : 'RETURNS & REFUNDS'} · {run.customer_id}</span><h3><Link to={`/${run.desk}?customer=${encoded(run.customer_id)}&run=${encoded(run.id)}`}>{run.message}</Link></h3><p className="hint">{run.id} · {new Date(run.created_at).toLocaleString()} {run.parent_run_id && '· Linked continuation'}</p></div><Status value={run.status} /></article>)}</div></section></>
}
