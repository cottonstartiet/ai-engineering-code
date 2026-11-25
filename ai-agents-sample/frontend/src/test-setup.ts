import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

const saved = new Map<string, string>()
vi.stubGlobal('localStorage', {
  getItem: (key: string) => saved.get(key) ?? null,
  setItem: (key: string, value: string) => { saved.set(key, String(value)) },
  removeItem: (key: string) => { saved.delete(key) },
  clear: () => saved.clear(),
  key: (index: number) => [...saved.keys()][index] ?? null,
  get length() { return saved.size },
} satisfies Storage)
afterEach(() => { cleanup(); localStorage.clear() })
