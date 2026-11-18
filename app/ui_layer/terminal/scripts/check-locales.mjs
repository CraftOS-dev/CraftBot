// Check that every language has every key of every terminal namespace, with
// the same {{placeholders}}, and that no string contains an em dash.
//   node scripts/check-locales.mjs        exits 1 on any problem
import { readdirSync, readFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..', 'locales')
const LANGS = ['en', 'ja', 'zh-CN', 'zh-TW', 'ko', 'es', 'id']
const PLURAL = /_(zero|one|two|few|many|other)$/

function flatten(obj, prefix = '', out = {}) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object') flatten(v, key, out)
    else out[key] = String(v)
  }
  return out
}

const placeholders = s => [...s.matchAll(/\{\{\s*(\w+)\s*\}\}/g)].map(m => m[1]).sort().join(',')
const base = k => k.replace(PLURAL, '')

let problems = 0
const report = msg => {
  problems++
  console.log(msg)
}

const namespaces = readdirSync(join(root, 'en')).filter(f => f.endsWith('.json'))
for (const file of namespaces) {
  const en = flatten(JSON.parse(readFileSync(join(root, 'en', file), 'utf8')))
  const enBases = new Set(Object.keys(en).map(base))
  for (const [k, v] of Object.entries(en)) if (v.includes('—')) report(`en/${file}: ${k} contains an em dash`)
  for (const lang of LANGS.slice(1)) {
    const path = join(root, lang, file)
    if (!existsSync(path)) {
      report(`${lang}/${file}: missing file`)
      continue
    }
    const tr = flatten(JSON.parse(readFileSync(path, 'utf8')))
    const trBases = new Set(Object.keys(tr).map(base))
    for (const b of enBases) if (!trBases.has(b)) report(`${lang}/${file}: missing ${b}`)
    for (const b of trBases) if (!enBases.has(b)) report(`${lang}/${file}: extra ${b}`)
    for (const [k, v] of Object.entries(tr)) {
      if (v.includes('—')) report(`${lang}/${file}: ${k} contains an em dash`)
      const enValue = en[k] ?? en[`${base(k)}_other`] ?? en[base(k)]
      if (enValue !== undefined && placeholders(enValue) !== placeholders(v)) {
        report(`${lang}/${file}: ${k} placeholders differ (${placeholders(enValue)} vs ${placeholders(v)})`)
      }
    }
  }
}
console.log(problems ? `${problems} problem(s)` : `locales OK (${namespaces.length} namespaces x ${LANGS.length} languages)`)
process.exit(problems ? 1 : 0)
