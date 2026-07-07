import { useAgentAware } from '../agent/hooks'
import { AppShell, Section, CardGrid, SkeletonCard } from './ui'
import type { AppController } from '../AppController'

interface MainViewProps {
  controller: AppController
}

/**
 * MainView - Primary view component
 *
 * This is the template scaffold. Rebuild it as YOUR app's layout wireframe
 * (Phase 1.5): keep the AppShell/Section assembly — the layout kit owns
 * page structure, gutters, and spacing — and replace the sections below
 * with one <Section> per planned region, each holding SkeletonCard /
 * SkeletonRow placeholders until its real component takes over.
 */
export function MainView({ controller }: MainViewProps) {
  // CRAFTBOT:TEMPLATE-PLACEHOLDER — explicit sentinel: while this comment
  // exists, the app is the untouched scaffold (the platform's completeness
  // gate and pace guard key on it). The Phase 1.5 wireframe rewrite
  // removes it along with the rest of this file.
  // Wire `controller` up when components replace this scaffold.
  void controller

  // Make this component agent-aware
  useAgentAware('MainView', {
    currentSection: 'main',
  })

  return (
    <AppShell>
      <Section title="Welcome to your Living UI" meta="Start building your custom interface here.">
        <CardGrid>
          <SkeletonCard count={6} />
        </CardGrid>
      </Section>
    </AppShell>
  )
}
