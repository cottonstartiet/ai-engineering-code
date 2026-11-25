# Browser/API contract

All paths start with `/api`. This is a localhost-only synthetic demo, not an authenticated app.
JSON fields use snake_case. Frontend development proxies `/api` to `http://127.0.0.1:8000`.

- `GET /customers` -> `[{id,name}]`
- `GET /scenarios?customer_id=...&desk=delivery|returns` ->
  `[{id,title,customer_id,desk,order_id,item_id,message,reason,quantity}]`
- `GET /orders?customer_id=...` ->
  `[{id,customer_id,status,delivered_at,items:[{id,name,quantity,unit_price_cents}]}]`
- `POST /runs` body `{customer_id,desk,message,order_id?,item_id?,reason?,quantity:1}` -> Run
- `GET /runs?customer_id=...` -> Run[] (newest first; customer filter optional for demo reviewer)
- `GET /runs/{id}` -> Run
- `GET /runs/{id}/events` -> SSE with id = durable integer; event = `activity`; data = Event.
  Honor Last-Event-ID and `?after=...`. Connections stay open until client closes, emitting heartbeats.
- `POST /runs/{id}/information` body `{message,order_id?,item_id?,reason?,quantity?}` -> new linked Run.
- `POST /runs/{id}/retry` -> new linked Run (only failed/interrupted)
- `POST /runs/{id}/cancel` -> Run
- `GET /approvals` -> Proposal[] (pending only)
- `POST /approvals/{id}/decision` body `{decision:"approved"|"rejected"}` -> Proposal.
  Successful approval queues simulated execution; refresh run details after decision.
- `GET /health` -> `{status, database, policies_indexed}`; HTTP 503 when not ready.

Run:
`{id,case_id,parent_run_id,customer_id,desk,status,message,order_id,item_id,reason,quantity,
result:object|null,trace_id,created_at,updated_at,proposal:Proposal|null}`

Requests, run responses, information responses, and scenarios additionally support
`delivery_checks_confirmed:boolean` (default false). Delivery UI must collect this
explicitly as a checkbox, never infer it from agent-generated text.

Statuses: queued, running, awaiting_customer, awaiting_approval, completed, escalated,
rejected, cancelled, interrupted, failed.

Event: `{id,run_id,kind,actor,node,text,data:object,created_at}`.
Kinds include status, agent_message, agent_delta, speaker_selected, node, tool, evidence,
approval, action, error, clarification. `node` values for the returns visualization:
intake, identify, retrieve, eligibility, proposal, approval, execute, verify, confirmation,
clarification, rejected, escalated. Node data includes `state:"running"|"completed"|"waiting"|"failed"`.
Only agent_message/agent_delta contain agent display content; never render raw HTML.

Proposal:
`{id,run_id,case_id,customer_id,order_id,item_id,action:"refund"|"replacement",
quantity,amount_cents,currency:"USD",citations:string[],explanation,status:"pending"|"approved"|"rejected"|"executed"|"cancelled",
created_at,decided_at}`

Run result can include `{summary,question,citations:[{id,title,text}],termination_reason,error_type}`.
Errors use FastAPI's `{detail:string}` and non-2xx status codes.

Frontend routes: `/delivery`, `/returns`, `/approvals`, `/history`. Both desks use the same
backend simultaneously. SSE is observational; closing it never cancels a job.
