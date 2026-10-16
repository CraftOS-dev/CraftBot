import { useCallback, useEffect, useRef, useState } from 'react'
import { useSettingsWebSocket } from './useSettingsWebSocket'
import styles from './CredentialsSettings.module.css'

type Profile = { id: string; label: string; state: string }
type Item = { credential_id: string; version: number; kind: string; service: string; account: string; origins: string[] }
type Activity = { action: string; outcome: string; grant_id: string | null }
type ItemPage = { items: Item[]; view_id: string; next_offset: number | null; total: number }
type Reply = { request_id: string | null; operation: string; ok: boolean; value?: unknown; error?: string }
const errors: Record<string, string> = {
  credential_host_unavailable: 'The credential service is unavailable. Finish installation or restart the host.',
  vault_locked: 'Unlock this profile to continue.',
  owner_verification_required: 'Owner verification was cancelled or unavailable. Use your Windows password at the owner prompt.',
  credential_changed: 'This item changed. Refresh its reference.',
  credential_use_denied: 'This request was not approved.',
  credential_busy: 'A credential request is dispatching. Try again shortly.',
}

// Metadata stays in this mounted view. Source fields are entered only in the
// protected native host dialog, never in React, Redux or WebSocket payloads.
export function CredentialsSettings() {
  const { send, onMessage, isConnected } = useSettingsWebSocket()
  const [profiles, setProfiles] = useState<Profile[]>([])
  const [profile, setProfile] = useState('')
  const [actionProfile, setActionProfile] = useState<string | null>(null)
  const [items, setItems] = useState<Item[]>([])
  const [activity, setActivity] = useState<Activity[]>([])
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [search, setSearch] = useState('')
  const [label, setLabel] = useState('')
  const [service, setService] = useState('')
  const [account, setAccount] = useState('')
  const [origins, setOrigins] = useState('')
  const [kind, setKind] = useState('login')
  const [fields, setFields] = useState('')
  const [editing, setEditing] = useState<Item | null>(null)
  const [replace, setReplace] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout>>()
  const pending = useRef<string | null>(null)
  const selected = profiles.find(p => p.id === profile)
  const sendRequest = useCallback((operation: string, parameters: Record<string, unknown>) => {
    const requestId = crypto.randomUUID()
    pending.current = requestId
    setBusy(true)
    clearTimeout(timer.current)
    send('credentials_request', { operation, parameters, request_id: requestId })
    timer.current = setTimeout(() => {
      setBusy(false); setNotice('The request timed out. Refresh before retrying; it may have completed.')
      setItems([]); pending.current = null
    }, 330_000)
  }, [send])

  useEffect(() => onMessage('credentials_result', (raw) => {
    const reply = raw as Reply
    if (!reply.request_id || reply.request_id !== pending.current) return
    pending.current = null
    clearTimeout(timer.current)
    setBusy(false)
    if (!reply.ok) { setNotice(errors[reply.error || ''] || 'The credential operation could not complete. Check the selected reference and installed helper.'); return }
    setNotice('')
    if (reply.operation === 'profiles') {
      const next = reply.value as Profile[]
      setProfiles(next)
      setProfile(current => next.some(p => p.id === current) ? current : next[0]?.id || '')
      if (next.find(p => p.id === profile)?.state !== 'ready') { setItems([]); setActivity([]) }
      sendRequest('action_profile', {})
    } else if (reply.operation === 'action_profile' || reply.operation === 'action_profile_set') {
      setActionProfile((reply.value as { profile_id: string | null }).profile_id)
    } else if (reply.operation === 'items' || reply.operation === 'items_page') {
      const page = reply.value as ItemPage
      setItems(previous => reply.operation === 'items' ? page.items : [...previous, ...page.items])
      if (page.next_offset !== null) {
        setBusy(true)
        sendRequest('items_page', { profile_id: profile, view_id: page.view_id, offset: page.next_offset })
      }
    }
    else if (reply.operation === 'activity') setActivity(reply.value as Activity[])
    else {
      setItems([]); setActivity([]); setEditing(null)
      setNotice(reply.operation === 'lock' ? 'All profiles are locked and credential workers have stopped.' : 'Saved. Refresh the list to see the latest state.')
      sendRequest('profiles', {})
    }
  }), [onMessage, sendRequest, profile])

  useEffect(() => {
    if (isConnected) sendRequest('profiles', {})
    return () => { clearTimeout(timer.current); pending.current = null }
  }, [isConnected, sendRequest])

  useEffect(() => {
    const interval = setInterval(() => {
      if (isConnected && pending.current === null) sendRequest('profiles', {})
    }, 30_000)
    return () => clearInterval(interval)
  }, [isConnected, sendRequest])

  function request(operation: string, parameters: Record<string, unknown>) {
    if (busy || !isConnected) return
    setBusy(true); setNotice('Complete the Windows owner prompt when it appears.')
    sendRequest(operation, parameters)
  }

  function edit(item: Item) {
    setEditing(item); setKind(item.kind); setService(item.service)
    setAccount(item.account); setOrigins(item.origins.join('\n')); setReplace(false)
  }

  return <section className={styles.panel} aria-labelledby="credentials-title">
    <h2 id="credentials-title">Credentials</h2>
    <p>Save logins, API keys and service secrets in a protected profile. Labels and origins are visible metadata. Enter secret values only in the protected dialog.</p>
    <div className={styles.row}>
      <label>Profile <select value={profile} disabled={busy} onChange={e => { setProfile(e.target.value); setItems([]); setActivity([]); setEditing(null) }}>
        {profiles.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
      </select></label>
      <span role="status">{selected?.state || 'unavailable'}</span>
      <button disabled={busy || !isConnected} onClick={() => request('profiles', {})}>Refresh</button>
      <button disabled={busy || !profile} onClick={() => { setItems([]); setActivity([]); request('lock', { profile_id: profile }) }}>Lock all profiles</button>
      <button disabled={busy || !profile} onClick={() => request('unlock', { profile_id: profile })}>Unlock</button>
      <button disabled={busy || !profile} onClick={() => request('initialize', { profile_id: profile })}>Initialize new profile</button>
    </div>
    <div className={styles.row}>
      <span>Profile for isolated agent actions: {profiles.find(p => p.id === actionProfile)?.label || 'disabled'}</span>
      <button disabled={busy || !profile} onClick={() => request('action_profile_set', { profile_id: profile })}>Use selected profile for agent actions…</button>
      <button disabled={busy || !actionProfile} onClick={() => request('action_profile_set', { profile_id: null })}>Disable agent credential actions…</button>
    </div>
    <form className={styles.row} onSubmit={e => { e.preventDefault(); request('profile_add', { label }) }}>
      <label>New profile <input value={label} maxLength={64} required onChange={e => setLabel(e.target.value)} /></label>
      <button disabled={busy || !label.trim()}>Create profile</button>
    </form>
    <p role="status" aria-live="polite">{notice}</p>
    <div className={styles.row}>
      <button disabled={busy || selected?.state !== 'ready'} onClick={() => request('items', { profile_id: profile })}>Show saved items</button>
      <button disabled={busy || !profile} onClick={() => request('activity', { profile_id: profile })}>Activity</button>
      <label>Search <input type="search" value={search} onChange={e => setSearch(e.target.value)} /></label>
    </div>
    <ul className={styles.list}>{items.filter(i => `${i.service} ${i.account} ${i.kind}`.toLowerCase().includes(search.toLowerCase())).map(item => <li key={item.credential_id}>
      <span><strong>{item.service}</strong> · {item.account} · {item.kind}<br /><small>{item.origins.join(', ')}</small><br />
        <input aria-label={`Reference for ${item.service} ${item.account}`} readOnly value={`craftbot-vault://${profile}/${item.credential_id}/${item.version}`} onFocus={e => e.target.select()} />
      </span>
      <button disabled={busy} onClick={() => edit(item)}>Edit</button>
      <button disabled={busy} onClick={() => request('view', { profile_id: profile, credential_id: item.credential_id, version: item.version })}>View privately…</button>
      <button disabled={busy} onClick={() => request('delete', { profile_id: profile, credential_id: item.credential_id, version: item.version })}>Delete…</button>
    </li>)}</ul>
    <form className={styles.form} onSubmit={e => {
      e.preventDefault()
      const metadata = { profile_id: profile, service, account, origins: origins.split(/[\n,]/).map(s => s.trim()).filter(Boolean) }
      if (editing) request('edit', { ...metadata, credential_id: editing.credential_id, version: editing.version, replace_fields: replace })
      else request('entry', { ...metadata, kind, fields: kind === 'service_secret' ? fields.split(',').map(s => s.trim()).filter(Boolean) : [] })
    }}>
      <h3>{editing ? 'Edit saved item' : 'Add credential'}</h3>
      <label>Type <select value={kind} disabled={!!editing} onChange={e => setKind(e.target.value)}><option value="login">Login</option><option value="api_key">API key</option><option value="service_secret">Service secret</option></select></label>
      <label>Service <input required maxLength={256} value={service} onChange={e => setService(e.target.value)} /></label>
      <label>Account label <input required maxLength={256} value={account} onChange={e => setAccount(e.target.value)} /></label>
      <label>Permitted HTTPS origins, one per line (required for network use) <textarea required={kind === 'login'} value={origins} onChange={e => setOrigins(e.target.value)} placeholder="https://api.example.com" /></label>
      {kind === 'service_secret' && !editing && <label>Field names, separated by commas <input required value={fields} onChange={e => setFields(e.target.value)} placeholder="client_id, client_secret" /></label>}
      {editing && <label><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} /> Replace secret fields in the protected dialog (blank fields keep their saved value)</label>}
      <div className={styles.row}><button disabled={busy || selected?.state !== 'ready'}>{editing ? 'Save changes…' : 'Enter values securely…'}</button>{editing && <button type="button" onClick={() => setEditing(null)}>Cancel edit</button>}</div>
    </form>
    {!!activity.length && <ul className={styles.list}>{activity.map((a, i) => <li key={i}><span>{a.action}: {a.outcome}</span>{a.grant_id && <button disabled={busy} onClick={() => request('revoke', { profile_id: profile, grant_id: a.grant_id })}>Revoke</button>}</li>)}</ul>}
  </section>
}
