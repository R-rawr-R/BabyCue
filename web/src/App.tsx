import { useCallback, useEffect, useState } from 'react';
import { BabyScreen } from './screens/BabyScreen';
import { LiveScreen } from './screens/LiveScreen';
import { SetupScreen } from './screens/SetupScreen';
import { babyName, loadPrefs, savePrefs, type Prefs } from './storage';

type Route = { screen: 'setup' } | { screen: 'baby' | 'live'; preview: boolean };

export default function App() {
  const [prefs, setPrefs] = useState<Prefs>(loadPrefs);
  const [route, setRoute] = useState<Route>(() => {
    if (import.meta.env.DEV) {
      if (location.hash === '#preview') return { screen: 'live', preview: true };
      if (location.hash === '#baby') return { screen: 'baby', preview: false };
    }
    return { screen: 'setup' };
  });

  const goSetup = useCallback(() => setRoute({ screen: 'setup' }), []);

  // The phone's back button leaves a session instead of closing the app.
  useEffect(() => {
    if (route.screen === 'setup') return;
    history.pushState({ babycue: route.screen }, '');
    const onPop = () => setRoute({ screen: 'setup' });
    window.addEventListener('popstate', onPop);
    return () => window.removeEventListener('popstate', onPop);
  }, [route.screen]);

  const name = babyName(prefs.name);
  const dark = route.screen === 'baby';
  useEffect(() => {
    document.body.style.background = dark ? 'var(--baby-bg)' : 'var(--bg)';
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? '#1f1b17' : '#f5ead8');
  }, [dark]);

  if (route.screen === 'setup') {
    return (
      <div className="app">
        <div className="screen">
          <SetupScreen
            initial={prefs}
            onConnect={(next) => {
              setPrefs(next);
              savePrefs(next);
              setRoute({ screen: next.role === 'baby' ? 'baby' : 'live', preview: false });
            }}
            onPreview={() => setRoute({ screen: 'live', preview: true })}
          />
        </div>
      </div>
    );
  }
  if (route.screen === 'baby') {
    return (
      <div className="app" style={{ background: 'var(--baby-bg)' }}>
        <div className="screen dark">
          <BabyScreen onStop={goSetup} />
        </div>
      </div>
    );
  }
  return <LiveScreen name={name} preview={route.preview} onLeave={goSetup} />;
}
