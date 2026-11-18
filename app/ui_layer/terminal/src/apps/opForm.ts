/**
 * A form for one declared operation, generated from its typed parameters:
 * strings are text fields, numbers are checked as numbers, booleans toggle
 * with Space, enums cycle with Left/Right, lists take comma-separated values
 * and json is checked as JSON. Required fields must be filled before it runs.
 * Pure state + key handling, so it is unit tested.
 */
import type { Key } from 'ink'
import type { Operation, OpParam } from './view'
import { coerceParam } from './engine'
import * as TB from '../input/TextBuffer'
import { fieldKey } from '../ui/TextField'

export interface FormField {
  name: string
  param: OpParam
  value: TB.Buffer
}

export interface FormState {
  op: Operation
  fields: FormField[]
  index: number
  errors: Record<string, string>
}

export function initForm(op: Operation, prefill: Record<string, string> = {}): FormState {
  const fields = Object.entries(op.params ?? {}).map(([name, param]) => {
    let initial = prefill[name] ?? ''
    if (!initial && param.type === 'boolean') initial = 'false'
    if (!initial && param.type === 'enum' && param.values?.length && param.required) initial = param.values[0]
    return { name, param, value: TB.fromText(initial) }
  })
  // Start on the first field the person still has to fill.
  const firstEmpty = fields.findIndex(f => f.param.required && !f.value.text)
  return { op, fields, index: Math.max(0, firstEmpty), errors: {} }
}

export function validateForm(state: FormState): Record<string, string> {
  const errors: Record<string, string> = {}
  for (const f of state.fields) {
    const v = f.value.text.trim()
    if (f.param.required && !v) errors[f.name] = 'required'
    else if (v && f.param.type === 'number' && !Number.isFinite(Number(v))) errors[f.name] = 'number'
    else if (v && f.param.type === 'json') {
      try {
        JSON.parse(v)
      } catch {
        errors[f.name] = 'json'
      }
    }
  }
  return errors
}

/** The params to send, typed as declared: filled fields only (optional empty ones are left out). */
export function formParams(state: FormState): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const f of state.fields) {
    const v = f.value.text.trim()
    if (v || f.param.type === 'boolean') out[f.name] = coerceParam(f.param, v || 'false')
  }
  return out
}

/** The choices a field cycles through: an enum's values, or nothing. */
export function fieldChoices(param: OpParam): string[] {
  return param.type === 'enum' ? (param.values ?? []) : []
}

export type FormResult = { state: FormState; submit?: boolean; cancel?: boolean }

export function formKey(state: FormState, input: string, key: Key): FormResult {
  const field = state.fields[state.index]
  if (key.escape) return { state, cancel: true }
  const move = (delta: number): FormResult => ({
    state: { ...state, index: (state.index + delta + state.fields.length) % Math.max(1, state.fields.length) },
  })
  if (key.tab) return move(key.shift ? -1 : 1)
  if (key.upArrow) return move(-1)
  if (key.downArrow) return move(1)
  if (key.return) {
    // Enter moves on; on the last field (or with no fields) it submits.
    if (state.fields.length === 0 || state.index === state.fields.length - 1 || key.ctrl) {
      const errors = validateForm(state)
      if (Object.keys(errors).length > 0) {
        const first = state.fields.findIndex(f => errors[f.name])
        return { state: { ...state, errors, index: Math.max(0, first) } }
      }
      return { state: { ...state, errors: {} }, submit: true }
    }
    return move(1)
  }
  if (!field) return { state }
  const set = (text: string): FormResult => ({
    state: {
      ...state,
      fields: state.fields.map((f, i) => (i === state.index ? { ...f, value: TB.fromText(text) } : f)),
      errors: { ...state.errors, [field.name]: '' },
    },
  })
  if (field.param.type === 'boolean') {
    if (input === ' ' || key.leftArrow || key.rightArrow) return set(field.value.text === 'true' ? 'false' : 'true')
    return { state }
  }
  if (fieldChoices(field.param).length) {
    if (key.leftArrow || key.rightArrow || input === ' ') {
      const options = fieldChoices(field.param)
      const current = options.indexOf(field.value.text)
      const next = options[(current + (key.leftArrow ? -1 : 1) + options.length) % options.length] ?? ''
      return set(next)
    }
    return { state }
  }
  const next = fieldKey(field.value, input, key)
  if (!next) return { state }
  return {
    state: {
      ...state,
      fields: state.fields.map((f, i) => (i === state.index ? { ...f, value: next } : f)),
      errors: { ...state.errors, [field.name]: '' },
    },
  }
}
