import { Background, Controls, ReactFlow, MarkerType, type Node, type Edge } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { type Activity, label } from './api'

const positions: Record<string, [number, number]> = {
  intake: [0, 0], identify: [220, 0], retrieve: [440, 0], eligibility: [660, 0],
  proposal: [660, 130], approval: [440, 130], execute: [220, 130], verify: [0, 130],
  confirmation: [0, 260], clarification: [220, 260], rejected: [440, 260], escalated: [660, 260],
}
export const graphLinks = [
  ['intake', 'identify'], ['identify', 'retrieve'], ['identify', 'clarification'],
  ['clarification', 'identify'], ['retrieve', 'eligibility'], ['eligibility', 'proposal'],
  ['eligibility', 'rejected'], ['eligibility', 'escalated'], ['proposal', 'approval'],
  ['approval', 'execute'], ['approval', 'rejected'], ['execute', 'verify'],
  ['verify', 'confirmation'], ['verify', 'escalated'],
]

export function Flow({ events }: { events: Activity[] }) {
  const states = new Map<string, string>()
  for (const event of events) if (event.node && typeof event.data?.state === 'string') states.set(event.node, event.data.state)
  const nodes: Node[] = Object.entries(positions).map(([id, [x, y]]) => {
    const state = states.get(id) ?? 'idle'
    return { id, position: { x, y }, data: { label: <><strong>{label(id)}</strong><small>{state}</small></> }, className: `flow-node ${state}`, draggable: false }
  })
  const edges: Edge[] = graphLinks.map(([source, target]) => ({ id: `${source}-${target}`, source, target, markerEnd: { type: MarkerType.ArrowClosed }, animated: states.get(target) === 'running', style: { stroke: states.has(source) && states.has(target) ? '#087f77' : '#9aadb4', strokeWidth: 2 } }))
  return <section className="panel graph-panel" aria-label="Returns directed workflow">
    <div className="panel-heading"><div><p className="eyebrow">DIRECTED ORCHESTRATION</p><h2>Every step, connected.</h2></div><span className="chip">12 nodes</span></div>
    <div className="graph"><ReactFlow nodes={nodes} edges={edges} fitView fitViewOptions={{ padding: 0.2 }} minZoom={0.3} nodesConnectable={false} elementsSelectable={false} ariaLabelConfig={{ 'controls.zoomIn.ariaLabel': 'Zoom in workflow', 'controls.zoomOut.ariaLabel': 'Zoom out workflow', 'controls.fitView.ariaLabel': 'Fit workflow' }}><Background /><Controls showInteractive={false} /></ReactFlow></div>
    <p className="muted graph-note">Full demo topology · branches are visible before execution. Waiting for customer information creates a linked run.</p>
    <ul className="sr-only" aria-label="Workflow node states">{nodes.map(node => <li key={node.id}>{node.id}: {states.get(node.id) ?? 'idle'}</li>)}</ul>
  </section>
}
