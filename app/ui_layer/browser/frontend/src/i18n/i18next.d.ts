// Compile-time typing for translation keys. English is the source of truth:
// every t('ns:key') is checked against these catalogs, so a missing or
// misspelled key is a tsc error rather than a blank string at runtime.
import 'i18next'

import type common from '../locales/en/common.json'
import type nav from '../locales/en/nav.json'
import type settings from '../locales/en/settings.json'
import type components from '../locales/en/components.json'
import type chat from '../locales/en/chat.json'
import type dashboard from '../locales/en/dashboard.json'
import type workspace from '../locales/en/workspace.json'
import type livingui from '../locales/en/livingui.json'
import type onboarding from '../locales/en/onboarding.json'
import type activity from '../locales/en/activity.json'
import type errors from '../locales/en/errors.json'
import type memory from '../locales/en/memory.json'
import type tour from '../locales/en/tour.json'

declare module 'i18next' {
  interface CustomTypeOptions {
    defaultNS: 'common'
    resources: {
      common: typeof common
      nav: typeof nav
      settings: typeof settings
      components: typeof components
      chat: typeof chat
      dashboard: typeof dashboard
      workspace: typeof workspace
      livingui: typeof livingui
      onboarding: typeof onboarding
      activity: typeof activity
      errors: typeof errors
      memory: typeof memory
      tour: typeof tour
    }
  }
}
