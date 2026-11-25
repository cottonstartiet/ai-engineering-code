import { useEffect, useRef, useState } from 'react'
import { type Activity, encoded, mergeEvents, readStored, store } from './api'

export function useActivity(runId: string | null, onActivity: () => void) {
  const [snapshot, setSnapshot] = useState<{ runId: string | null; events: Activity[]; connection: string }>({ runId: null, events: [], connection: 'Offline' })
  const callback = useRef(onActivity)
  callback.current = onActivity
  useEffect(() => {
    if (!runId) { setSnapshot({ runId: null, events: [], connection: 'Offline' }); return }
    let events = readStored<Activity[]>(`retail:events:${runId}`, []).filter(event => event.run_id === runId)
    setSnapshot({ runId, events, connection: 'Connecting' })
    const after = events.reduce((max, event) => Math.max(max, event.id), 0)
    const source = new EventSource(`/api/runs/${encoded(runId)}/events?after=${after}`)
    source.onopen = () => setSnapshot(current => current.runId === runId ? { ...current, connection: 'Live' } : current)
    source.onerror = () => setSnapshot(current => current.runId === runId ? { ...current, connection: 'Reconnecting — saved activity is preserved' } : current)
    const listener = (message: MessageEvent<string>) => {
      try {
        const event = JSON.parse(message.data) as Activity
        if (event.run_id !== runId || !Number.isInteger(event.id)) return
        const next = mergeEvents(events, event)
        if (next === events) return
        events = next
        store(`retail:events:${runId}`, events)
        setSnapshot({ runId, events, connection: 'Live' })
        callback.current()
      } catch {
        setSnapshot(current => current.runId === runId ? { ...current, connection: 'Unreadable activity received; reload to replay' } : current)
      }
    }
    source.addEventListener('activity', listener as EventListener)
    return () => { source.removeEventListener('activity', listener as EventListener); source.close() }
  }, [runId])
  return snapshot.runId === runId ? snapshot : { runId, events: [], connection: runId ? 'Connecting' : 'Offline' }
}
