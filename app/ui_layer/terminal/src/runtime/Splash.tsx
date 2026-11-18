/**
 * Shown until the backend greets the client. The client paints at once and
 * keeps retrying (the backend may still be booting: models, MCP servers,
 * skills). After the browser's 90-second budget it says so and points at
 * the backend log.
 */
import { Box, Text, useApp, useInput } from 'ink'
import { useTranslation } from 'react-i18next'
import { useAppSelector } from '../state/hooks'
import { config } from '../config'
import { ink, spinnerFrames } from '../theme/theme'
import { useTicker } from '../ui/useTicker'
import { requestQuit } from './actions'

export const LOGO: [string, string][] = [
  [' ██████╗██████╗  █████╗ ███████╗████████╗', '██████╗  ██████╗ ████████╗'],
  ['██╔════╝██╔══██╗██╔══██╗██╔════╝╚══██╔══╝', '██╔══██╗██╔═══██╗╚══██╔══╝'],
  ['██║     ██████╔╝███████║█████╗     ██║   ', '██████╔╝██║   ██║   ██║   '],
  ['██║     ██╔══██╗██╔══██║██╔══╝     ██║   ', '██╔══██╗██║   ██║   ██║   '],
  ['╚██████╗██║  ██║██║  ██║██║        ██║   ', '██████╔╝╚██████╔╝   ██║   '],
  [' ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝        ╚═╝   ', '╚═════╝  ╚═════╝    ╚═╝   '],
]

const STARTED = Date.now()
const UNRESPONSIVE_MS = 90_000

export function Splash() {
  const { t } = useTranslation('tui')
  const { exit } = useApp()
  const tick = useTicker(120)
  const connected = useAppSelector(s => s.connection.connected)
  const attempt = useAppSelector(s => s.connection.reconnectAttempt)
  useInput((input, key) => {
    if (key.ctrl && (input === 'c' || input === 'd')) requestQuit(exit)
  })
  const late = Date.now() - STARTED > UNRESPONSIVE_MS
  const frames = spinnerFrames()
  const wide = (process.stdout.columns ?? 80) >= 70
  return (
    <Box flexDirection="column" paddingY={1}>
      {wide
        ? LOGO.map(([craft, bot], i) => (
            <Text key={i}>
              <Text color={ink.brand}>{craft}</Text>
              <Text>{bot}</Text>
            </Text>
          ))
        : <Text bold color={ink.brand}>CraftBot</Text>}
      <Text> </Text>
      {late ? (
        <Box flexDirection="column">
          <Text color={ink.error}>{t('connect.unresponsive')}</Text>
          {config().logFile ? <Text color={ink.muted}>{t('connect.seeLog', { path: config().logFile })}</Text> : null}
          <Text color={ink.muted}>{t('connect.stopHint')}</Text>
        </Box>
      ) : (
        <Text color={ink.muted}>
          {frames[tick % frames.length]} {connected ? t('connect.greeting') : attempt > 0 ? t('connect.waiting') : t('connect.connecting')}
        </Text>
      )}
    </Box>
  )
}
