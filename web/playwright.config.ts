import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  use: {baseURL: 'http://127.0.0.1:18765', headless: true},
  webServer: {
    command: 'uv run --project .. kwa serve --config ../config.example.yaml --port 18765',
    url: 'http://127.0.0.1:18765/api/v1/health',
    reuseExistingServer: false,
    timeout: 30000
  }
});
