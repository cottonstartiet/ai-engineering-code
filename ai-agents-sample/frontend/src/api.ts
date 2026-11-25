export type Desk = 'delivery' | 'returns'
export type Customer = { id: string; name: string }
export type Order = { id: string; customer_id: string; status: string; delivered_at: string | null; items: { id: string; name: string; quantity: number; unit_price_cents: number }[] }
export type Scenario = { id: string; title: string; customer_id: string; desk: Desk; order_id: string | null; item_id: string | null; message: string; reason: string | null; quantity: number; delivery_checks_confirmed: boolean }
export type Proposal = { id: string; run_id: string; case_id: string; customer_id: string; order_id: string; item_id: string; action: 'refund' | 'replacement'; quantity: number; amount_cents: number; currency: 'USD'; citations: string[]; explanation: string; status: 'pending' | 'approved' | 'rejected' | 'executed' | 'cancelled'; created_at: string; decided_at: string | null }
export type RunStatus = 'queued' | 'running' | 'awaiting_customer' | 'awaiting_approval' | 'completed' | 'escalated' | 'rejected' | 'cancelled' | 'interrupted' | 'failed'
export type Run = { id: string; case_id: string; parent_run_id: string | null; customer_id: string; desk: Desk; status: RunStatus; message: string; order_id: string | null; item_id: string | null; reason: string | null; quantity: number; delivery_checks_confirmed: boolean; result: { summary?: string; question?: string; citations?: { id: string; title: string; text: string }[]; termination_reason?: string; error_type?: string } | null; trace_id: string; created_at: string; updated_at: string; proposal: Proposal | null }
export type Activity = { id: number; run_id: string; kind: string; actor: string; node: string | null; text: string; data: Record<string, unknown>; created_at: string }
export type Input = { message: string; order_id?: string; item_id?: string; reason?: string; quantity: number; delivery_checks_confirmed: boolean }

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message) }
}

export async function api<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method: body === undefined ? 'GET' : 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body), signal,
  })
  if (!response.ok) {
    const data = await response.json().catch(() => null)
    const detail = typeof data?.detail === 'string' ? data.detail : Array.isArray(data?.detail)
      ? data.detail.map((issue: { loc?: unknown[]; msg?: unknown }) => `${issue.loc?.filter(part => part !== 'body').join('.') || 'Request'}: ${typeof issue.msg === 'string' ? issue.msg : 'Invalid value'}`).join('; ')
      : `Request failed (${response.status}). Please try again.`
    throw new ApiError(response.status, detail)
  }
  return response.json() as Promise<T>
}
export const errorText = (error: unknown) => error instanceof Error ? error.message : 'Something went wrong. Please try again.'
export const money = (cents: number, currency = 'USD') => new Intl.NumberFormat('en-US', { style: 'currency', currency }).format(cents / 100)
export const label = (value: string) => value.replaceAll('_', ' ')
export const encoded = encodeURIComponent
export const activeStatuses = new Set<RunStatus>(['queued', 'running', 'awaiting_customer', 'awaiting_approval'])

export function readStored<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) ?? 'null') ?? fallback } catch { return fallback }
}
export function store(key: string, value: unknown) {
  try { localStorage.setItem(key, JSON.stringify(value)) } catch { /* Storage is optional in private browsing or at quota. */ }
}
export function mergeEvents(previous: Activity[], incoming: Activity): Activity[] {
  if (previous.some(event => event.id === incoming.id)) return previous
  return [...previous, incoming].sort((a, b) => a.id - b.id)
}
