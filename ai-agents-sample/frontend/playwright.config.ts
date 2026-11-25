import { defineConfig, devices } from '@playwright/test'

const liveBaseURL = process.env.RETAIL_LIVE_BASE_URL

export default defineConfig({
  testDir: '../tests/e2e',
  fullyParallel: true,
  reporter: 'list',
  use: { baseURL: liveBaseURL || 'http://127.0.0.1:4173', trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: liveBaseURL ? undefined : { command: 'npm run dev -- --port 4173 --strictPort', url: 'http://127.0.0.1:4173', reuseExistingServer: !process.env.CI },
})
