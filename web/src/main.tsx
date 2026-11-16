import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { isTauriEnvironment, setMockBridge } from './lib/host.ts'
import { MemoryMockBridge } from './lib/mock_host.ts'

// Browser-only dev/test preview: wire the mock host (never reached inside the Tauri desktop app).
if (!isTauriEnvironment()) {
  const mock = new MemoryMockBridge();
  setMockBridge(mock);
  (window as unknown as { __mock: MemoryMockBridge }).__mock = mock; // observation hook for tests
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
