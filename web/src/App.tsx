import { useState, useEffect, useCallback } from 'react';
import { host } from './lib/host';
import { errorText } from './lib/errors';
import { ScreenShell, ErrorNote, primaryBtn } from './components/ScreenShell';
import { WelcomeScreen } from './components/WelcomeScreen';
import { CreateVaultScreen } from './components/CreateVaultScreen';
import { UnlockScreen } from './components/UnlockScreen';
import { RecoveryScreen } from './components/RecoveryScreen';
import { Workspace } from './components/Workspace';
import { QuickAccess } from './components/QuickAccess';

type Screen =
  | { name: 'loading' }
  | { name: 'error'; message: string }
  | { name: 'welcome' }
  | { name: 'create' }
  | { name: 'unlock'; path: string }
  | { name: 'recover'; path: string }
  | { name: 'vault'; demo: boolean };

const IDLE_MS = 5 * 60 * 1000; // mirrors the backend's authoritative idle lock
const ACTIVITY = ['keydown', 'mousedown', 'mousemove', 'wheel'] as const;

function MainApp() {
  const [screen, setScreen] = useState<Screen>({ name: 'loading' });

  // The backend is the single source of truth for which screen to show.
  const refresh = useCallback(async () => {
    try {
      const s = await host().getStartupState();
      if (s.state === 'unlocked') setScreen({ name: 'vault', demo: s.demo });
      else if (s.state === 'locked' && s.path) setScreen({ name: 'unlock', path: s.path });
      else if (s.state === 'missing' && s.path) setScreen({ name: 'recover', path: s.path });
      else setScreen({ name: 'welcome' });
    } catch (e) {
      // Dead/unreachable sidecar: fail closed, never fall through to Unlock or an open vault.
      setScreen({ name: 'error', message: errorText(e, 'Không đọc được trạng thái két sắt.') });
    }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  const lock = useCallback(async () => {
    await host().lock();
    await refresh();
  }, [refresh]);

  const inVault = screen.name === 'vault';
  useEffect(() => {
    if (!inVault) return;
    let timer: ReturnType<typeof setTimeout>;
    let lastTouch = 0;
    const bump = () => {
      clearTimeout(timer);
      timer = setTimeout(lock, IDLE_MS);
      const now = Date.now();
      if (now - lastTouch > 30_000) {
        lastTouch = now;
        host().touch();
      }
    };
    bump();
    ACTIVITY.forEach((ev) => window.addEventListener(ev, bump, { passive: true }));
    return () => {
      clearTimeout(timer);
      ACTIVITY.forEach((ev) => window.removeEventListener(ev, bump));
    };
  }, [inVault, lock]);

  // The backend can lock on its own (Windows session lock, suspend, idle, sidecar restart). Poll its real state
  // (this call does not count as activity) so the view never lingers on a vault that is already locked.
  useEffect(() => {
    if (!inVault) return;
    const id = setInterval(async () => {
      try {
        const s = await host().getStartupState();
        if (s.state !== 'unlocked') refresh();
      } catch {
        refresh(); // unreachable backend -> the error screen, never stale data
      }
    }, 3000);
    return () => clearInterval(id);
  }, [inVault, refresh]);

  switch (screen.name) {
    case 'loading':
      return <ScreenShell><p className="text-sm text-slate-500 text-center" role="status">Đang kiểm tra két sắt…</p></ScreenShell>;
    case 'error':
      return (
        <ScreenShell>
          <ErrorNote>{screen.message}</ErrorNote>
          <button type="button" onClick={refresh} className={`${primaryBtn} mt-4`}>Thử lại</button>
        </ScreenShell>
      );
    case 'welcome':
      return (
        <WelcomeScreen
          onCreate={() => setScreen({ name: 'create' })}
          onPicked={(path) => setScreen({ name: 'unlock', path })}
          onEntered={refresh}
        />
      );
    case 'create':
      return <CreateVaultScreen onBack={refresh} onCreated={refresh} />;
    case 'unlock':
      return <UnlockScreen key={screen.path} path={screen.path} onUnlocked={refresh} />;
    case 'recover':
      return (
        <RecoveryScreen
          path={screen.path}
          onPicked={(path) => setScreen({ name: 'unlock', path })}
          onRetry={refresh}
          onCreate={() => setScreen({ name: 'create' })}
        />
      );
    case 'vault':
      return <Workspace demo={screen.demo} onLock={lock} />;
  }
}

export function App() {
  return window.location.hash === '#quick' ? <QuickAccess /> : <MainApp />;
}

export default App;
