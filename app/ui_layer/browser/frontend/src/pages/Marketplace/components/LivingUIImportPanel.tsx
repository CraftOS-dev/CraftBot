import React, { useState } from 'react'
import { FolderInput, Loader2, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { useSettingsWebSocket } from '../../Settings/useSettingsWebSocket'
import styles from '../Marketplace.module.css'

/** "Import External App" flow — GitHub URL, local path, or exported ZIP.
 *  Extracted from the old CreateLivingUIModal import tab. */
export function LivingUIImportPanel() {
  const { send } = useSettingsWebSocket()
  const navigate = useNavigate()
  const [importSource, setImportSource] = useState('')
  const [importing, setImporting] = useState(false)
  const [dropActive, setDropActive] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Upload ZIP → stage on server → hand to the importer agent via WebSocket
  const handleZipUpload = async (file: File) => {
    setImporting(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const zipName = file.name.replace('.zip', '').replace(/^livingui_/, '').replace(/_[a-f0-9]+$/, '')
      formData.append('name', zipName)
      const resp = await fetch('/api/living-ui/import', { method: 'POST', body: formData })
      const result = await resp.json()
      if (result.success && result.path) {
        send('living_ui_import', { source: result.path, name: result.name || zipName })
        navigate('/')
      } else {
        setError(result.error || 'Upload failed')
      }
    } catch (err) {
      setError('Upload failed: ' + (err instanceof Error ? err.message : String(err)))
    } finally {
      setImporting(false)
    }
  }

  const handleImportSource = () => {
    send('living_ui_import', {
      source: importSource.trim(),
      name: importSource.trim().split('/').pop()?.replace('.git', '') || 'External App',
    })
    setImportSource('')
    navigate('/')
  }

  return (
    <div className={styles.panelWrap}>
    <div className={styles.panelForm}>
      <div className={styles.formGroup}>
        <label className={styles.label}>GitHub URL or Local Path</label>
        <input
          type="text"
          className={styles.input}
          placeholder="https://github.com/user/repo or /path/to/local/app"
          value={importSource}
          onChange={e => setImportSource(e.target.value)}
        />
        <span className={styles.hint}>
          Go · Node.js · Python · Rust · Docker · Static sites
        </span>
      </div>

      <div className={styles.orDivider}><span>or</span></div>

      <div
        className={`${styles.dropZone} ${dropActive ? styles.dropZoneDragOver : ''}`}
        onClick={() => {
          const input = document.createElement('input')
          input.type = 'file'
          input.accept = '.zip'
          input.onchange = (e) => {
            const file = (e.target as HTMLInputElement).files?.[0]
            if (file) handleZipUpload(file)
          }
          input.click()
        }}
        onDragOver={(e) => { e.preventDefault(); setDropActive(true) }}
        onDragLeave={() => setDropActive(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDropActive(false)
          const file = e.dataTransfer.files[0]
          if (file && file.name.endsWith('.zip')) handleZipUpload(file)
        }}
      >
        {importing ? (
          <>
            <Loader2 size={24} className={styles.spinner} />
            <p className={styles.dropZoneSub}>Importing...</p>
          </>
        ) : (
          <>
            <Upload size={24} className={styles.dropZoneIcon} />
            <p className={styles.dropZoneLabel}>Drop a ZIP file here or click to browse</p>
            <p className={styles.dropZoneSub}>Import a previously exported Living UI</p>
          </>
        )}
      </div>

      {error && <span className={styles.errorText}>{error}</span>}

      <div className={styles.panelActions}>
        <button
          className={styles.panelSubmit}
          disabled={!importSource.trim() || importing}
          onClick={handleImportSource}
        >
          {importing
            ? <><Loader2 size={16} className={styles.spinner} /> Importing...</>
            : <><FolderInput size={16} /> Import App</>}
        </button>
      </div>
    </div>
    </div>
  )
}
