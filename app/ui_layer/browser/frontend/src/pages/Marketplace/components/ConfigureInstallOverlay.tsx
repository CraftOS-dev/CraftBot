import React, { useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import type { MarketplaceProduct } from '../types'
import styles from '../Marketplace.module.css'

interface ConfigureInstallOverlayProps {
  product: MarketplaceProduct
  onCancel: () => void
  onInstall: (product: MarketplaceProduct, fields: Record<string, string>) => void
}

/** Pre-install form for apps with customizable template fields (e.g. APP_TITLE). */
export function ConfigureInstallOverlay({ product, onCancel, onInstall }: ConfigureInstallOverlayProps) {
  const [values, setValues] = useState<Record<string, string>>({})

  useEffect(() => {
    const defaults: Record<string, string> = {}
    product.customFields?.forEach(f => { defaults[f.key] = f.default })
    setValues(defaults)
  }, [product])

  return (
    <div className={styles.configOverlay} onClick={onCancel}>
      <div className={styles.configCard} onClick={e => e.stopPropagation()}>
        <div className={styles.configHeader}>
          <h4>Configure: {product.name}</h4>
          <p>Customize before installing</p>
        </div>
        {product.customFields?.map(field => (
          <div key={field.key} className={styles.formGroup}>
            <label className={styles.label}>{field.label}</label>
            <input
              type={field.type || 'text'}
              className={styles.input}
              value={values[field.key] || ''}
              onChange={e => setValues(prev => ({ ...prev, [field.key]: e.target.value }))}
              placeholder={field.placeholder || field.default}
            />
          </div>
        ))}
        <div className={styles.configActions}>
          <button className={styles.configCancel} onClick={onCancel}>Cancel</button>
          <button className={styles.installBtn} onClick={() => onInstall(product, values)}>
            <Download size={14} /> Install
          </button>
        </div>
      </div>
    </div>
  )
}
