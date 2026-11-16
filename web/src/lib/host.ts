import type { HostBridge } from '../types';
import { ProductionTauriBridge } from './production_host';

export function isTauriEnvironment(): boolean {
  return typeof window !== 'undefined' && ('__TAURI_INTERNALS__' in window || '__TAURI__' in window);
}

let activeBridge: HostBridge | null = null;
let mockBridgeInstance: HostBridge | null = null;

export function setMockBridge(b: HostBridge) {
  mockBridgeInstance = b;
}

export function host(): HostBridge {
  if (!activeBridge) {
    if (isTauriEnvironment()) {
      activeBridge = new ProductionTauriBridge();
    } else if (mockBridgeInstance) {
      activeBridge = mockBridgeInstance;
    } else {
      throw new Error("Production desktop runtime required. Stdio sidecar IPC unavailable in browser.");
    }
  }
  return activeBridge;
}
