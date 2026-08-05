// SYSTEM FILE — managed by tooling, never edited by agents (spec P1/K4).
import { createRoot } from 'react-dom/client';
import { StrictMode } from 'react';
import { LoginGate, Shell } from './kit/index.ts';
import { AUTH_MODE } from './config.gen.ts';
import { App } from './app/App.tsx';
import './app.css';

const rootEl = document.getElementById('root');
if (rootEl === null) throw new Error('missing #root element');

createRoot(rootEl).render(
  <StrictMode>
    <Shell>
      {AUTH_MODE === 'multi-user' ? (
        <LoginGate>
          <App />
        </LoginGate>
      ) : (
        <App />
      )}
    </Shell>
  </StrictMode>,
);
