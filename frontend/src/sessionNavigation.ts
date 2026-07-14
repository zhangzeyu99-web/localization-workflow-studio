export const SESSION_NAVIGATION_KEY = 'lws.session-navigation'

export type SessionNavigation = {
  projectId: string
  view: 'overview' | 'wizard' | 'quick' | 'announcement'
  tab: 'meta' | 'glossary' | 'translation' | 'qa' | 'archive' | 'delivery'
  step: number
}

const views = new Set<SessionNavigation['view']>(['overview', 'wizard', 'quick', 'announcement'])
const tabs = new Set<SessionNavigation['tab']>(['meta', 'glossary', 'translation', 'qa', 'archive', 'delivery'])

export function parseSessionNavigation(raw: string | null): SessionNavigation | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Record<string, unknown>
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    if (typeof value.projectId !== 'string' || !value.projectId.trim()) return null
    if (typeof value.view !== 'string' || !views.has(value.view as SessionNavigation['view'])) return null
    if (typeof value.tab !== 'string' || !tabs.has(value.tab as SessionNavigation['tab'])) return null
    if (typeof value.step !== 'number' || !Number.isFinite(value.step)) return null
    return {
      projectId: value.projectId,
      view: value.view as SessionNavigation['view'],
      tab: value.tab as SessionNavigation['tab'],
      step: Math.min(9, Math.max(1, Math.trunc(value.step))),
    }
  } catch {
    return null
  }
}

export function readSessionNavigation(): SessionNavigation | null {
  if (typeof window === 'undefined') return null
  try {
    const parsed = parseSessionNavigation(window.localStorage.getItem(SESSION_NAVIGATION_KEY))
    if (!parsed) window.localStorage.removeItem(SESSION_NAVIGATION_KEY)
    return parsed
  } catch {
    return null
  }
}

export function writeSessionNavigation(navigation: SessionNavigation): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.setItem(SESSION_NAVIGATION_KEY, JSON.stringify({
      projectId: navigation.projectId,
      view: navigation.view,
      tab: navigation.tab,
      step: navigation.step,
    }))
  } catch {
    // Navigation persistence must never block the API-backed workbench.
  }
}

export function clearSessionNavigation(): void {
  if (typeof window === 'undefined') return
  try {
    window.localStorage.removeItem(SESSION_NAVIGATION_KEY)
  } catch {
    // Navigation persistence must never block the API-backed workbench.
  }
}
