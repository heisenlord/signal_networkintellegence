import { useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import App from './App';
import { api, authenticationConfigURL, errorMessage } from './api';

export type AccessSession = { token: string; customer_id: string; role: string; subject: string };

export default function AccessGate() {
  const client = useQueryClient();
  const [mode, setMode] = useState<'demo' | 'oidc' | null>(null);
  const [session, setSession] = useState<AccessSession | null>(null);
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(authenticationConfigURL, { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error('Cannot load authentication settings. Reload to retry.');
      const config = await response.json();
      if (!['demo', 'oidc'].includes(config.authentication)) throw new Error('Invalid authentication settings.');
      setMode(config.authentication);
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, []);
  async function connect(event: React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      const identity = await api<Omit<AccessSession, 'token'>>('/session', token.trim());
      client.clear(); setSession({ ...identity, token: token.trim() }); setToken('');
    } catch (error) { setError(errorMessage(error)); }
    finally { setBusy(false); }
  }
  function signOut() { client.clear(); setSession(null); setToken(''); }
  if (mode === 'demo') return <App />;
  if (session) return <App session={session} onSignOut={signOut} />;
  return <main className="access-gate"><form className="card access-card" onSubmit={connect}>
    <h1>Signal workspace</h1>
    <p>{mode ? 'Enter the access token issued by your organization to open your assigned workspace.' : 'Connecting to your workspace…'}</p>
    {mode && <><label htmlFor="access-token">Access token</label><input id="access-token" type="password" autoComplete="off" maxLength={8192} value={token} onChange={event => setToken(event.target.value)} required /><button className="button" disabled={busy || !token.trim()} type="submit">{busy ? 'Verifying…' : 'Open workspace'}</button><p className="muted">The token stays in memory. Refreshing this page signs you out.</p></>}
    {error && <p role="alert">{error}</p>}
  </form></main>;
}
