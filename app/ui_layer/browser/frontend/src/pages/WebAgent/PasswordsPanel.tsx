import React, { useEffect, useState, useCallback } from 'react'
import { X, Trash2, Plus, KeyRound } from 'lucide-react'
import { getSocketClient } from '../../store/socket/socketInstance'
import styles from './PasswordsPanel.module.css'

interface VaultEntry {
  id: string
  site: string
  username: string
  label?: string
}

/**
 * Manage website logins the agent can use to sign you in.
 * Passwords are stored encrypted on the backend; they are NEVER sent back to
 * the UI (the list shows only site + username), so nothing sensitive lives here.
 */
export function PasswordsPanel({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [entries, setEntries] = useState<VaultEntry[]>([])
  const [site, setSite] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  useEffect(() => {
    if (!open) return
    const client = getSocketClient()
    const unsub = client.onMessage('vault_list', (data: unknown) => {
      const d = data as { entries?: VaultEntry[] }
      setEntries(d.entries ?? [])
    })
    client.send('vault_list', {})
    return () => unsub()
  }, [open])

  const add = useCallback((e: React.FormEvent) => {
    e.preventDefault()
    if (!site.trim() || !username.trim() || !password) return
    getSocketClient().send('vault_add', { site, username, password })
    setSite('')
    setUsername('')
    setPassword('')
  }, [site, username, password])

  const del = useCallback((id: string) => {
    getSocketClient().send('vault_delete', { id })
  }, [])

  if (!open) return null

  return (
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.modal} onClick={e => e.stopPropagation()}>
        <div className={styles.header}>
          <h3 className={styles.title}><KeyRound size={16} /> Saved passwords</h3>
          <button className={styles.closeBtn} onClick={onClose} aria-label="Close">
            <X size={16} />
          </button>
        </div>

        <p className={styles.hint}>
          Stored <strong>encrypted</strong> on this PC. The agent fills these to log you
          in — it never sees the password text. Say &ldquo;log me into &lt;site&gt;&rdquo;.
        </p>

        <div className={styles.list}>
          {entries.length === 0 ? (
            <div className={styles.empty}>No saved logins yet. Add one below.</div>
          ) : (
            entries.map(en => (
              <div key={en.id} className={styles.row}>
                <div className={styles.rowInfo}>
                  <span className={styles.rowSite}>{en.site || '(no site)'}</span>
                  <span className={styles.rowUser}>{en.username}</span>
                </div>
                <span className={styles.rowPw} aria-hidden>••••••••</span>
                <button
                  className={styles.delBtn}
                  onClick={() => del(en.id)}
                  title="Delete this login"
                  aria-label="Delete"
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))
          )}
        </div>

        <form className={styles.addForm} onSubmit={add}>
          <input
            className={styles.input}
            placeholder="Website (e.g. amazon.com)"
            value={site}
            onChange={e => setSite(e.target.value)}
            spellCheck={false}
          />
          <input
            className={styles.input}
            placeholder="Username / email"
            value={username}
            onChange={e => setUsername(e.target.value)}
            autoComplete="off"
            spellCheck={false}
          />
          <input
            className={styles.input}
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            autoComplete="new-password"
          />
          <button type="submit" className={styles.addBtn}>
            <Plus size={14} /> Save login
          </button>
        </form>
      </div>
    </div>
  )
}
