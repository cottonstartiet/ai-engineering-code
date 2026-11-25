import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useActivity } from './useActivity'
import { eventFixture } from './test-fixtures'
import { store } from './api'

class FakeSource {
  static instances: FakeSource[] = []
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  listener: ((event: MessageEvent) => void) | null = null
  close = vi.fn()
  constructor(public url: string) { FakeSource.instances.push(this) }
  addEventListener(_type: string, listener: (event: MessageEvent) => void) { this.listener = listener }
  removeEventListener() { this.listener = null }
  emit(data: unknown) { this.listener?.(new MessageEvent('activity', { data: JSON.stringify(data) })) }
}
beforeEach(() => { FakeSource.instances = []; vi.stubGlobal('EventSource', FakeSource) })

describe('durable activity stream', () => {
  it('resumes saved events, deduplicates replay, preserves order, and reports reconnecting', async () => {
    store('retail:events:run-1', [eventFixture({ id: 3 })])
    const changed = vi.fn()
    const { result, unmount } = renderHook(() => useActivity('run-1', changed))
    const source = FakeSource.instances[0]
    expect(source.url).toContain('after=3')
    act(() => {
      source.emit(eventFixture({ id: 3 }))
      source.emit(eventFixture({ id: 5 }))
      source.emit(eventFixture({ id: 4 }))
      source.emit(eventFixture({ id: 6, run_id: 'other' }))
      source.onerror?.()
    })
    expect(result.current.events.map(event => event.id)).toEqual([3, 4, 5])
    expect(changed).toHaveBeenCalledTimes(2)
    expect(result.current.connection).toMatch(/Reconnecting/)
    expect(JSON.parse(localStorage.getItem('retail:events:run-1')!).length).toBe(3)
    act(() => source.onopen?.())
    await waitFor(() => expect(result.current.connection).toBe('Live'))
    unmount()
    expect(source.close).toHaveBeenCalledOnce()
  })

  it('closes on run switch and unmount without mixing customer activity', () => {
    const { result, rerender, unmount } = renderHook(({ id }) => useActivity(id, () => {}), { initialProps: { id: 'run-1' as string | null } })
    const old = FakeSource.instances[0]
    act(() => old.emit(eventFixture()))
    rerender({ id: 'run-2' })
    expect(old.close).toHaveBeenCalledOnce()
    expect(result.current.events).toEqual([])
    expect(FakeSource.instances[1].url).toContain('run-2/events?after=0')
    rerender({ id: null })
    expect(FakeSource.instances[1].close).toHaveBeenCalledOnce()
    expect(result.current.connection).toBe('Offline')
    unmount()
  })
})
