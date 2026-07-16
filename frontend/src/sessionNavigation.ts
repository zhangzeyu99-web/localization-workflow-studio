export const SESSION_NAVIGATION_KEY = 'lws.session-navigation'

export type SessionTaskScope =
  | { kind: 'formal'; taskId: string }
  | { kind: 'quick'; taskId: string; runId: string }
  | { kind: 'announcement'; taskId: string }

export type SessionNavigation = {
  projectId: string
  view: 'overview' | 'wizard' | 'quick' | 'announcement'
  tab: 'meta' | 'glossary' | 'translation' | 'qa' | 'archive' | 'delivery'
  step: number
  taskScope?: SessionTaskScope
}

const views = new Set<SessionNavigation['view']>(['overview', 'wizard', 'quick', 'announcement'])
const tabs = new Set<SessionNavigation['tab']>(['meta', 'glossary', 'translation', 'qa', 'archive', 'delivery'])

function parseTaskScope(value: unknown): SessionTaskScope | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined
  const scope = value as Record<string, unknown>
  const taskId = typeof scope.taskId === 'string' ? scope.taskId.trim() : ''
  if (!taskId) return undefined
  if (scope.kind === 'formal' || scope.kind === 'announcement') return { kind: scope.kind, taskId }
  if (scope.kind === 'quick') {
    const runId = typeof scope.runId === 'string' ? scope.runId.trim() : ''
    return runId ? { kind: 'quick', taskId, runId } : undefined
  }
  return undefined
}

export function parseSessionNavigation(raw: string | null): SessionNavigation | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Record<string, unknown>
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null
    if (typeof value.projectId !== 'string' || !value.projectId.trim()) return null
    if (typeof value.view !== 'string' || !views.has(value.view as SessionNavigation['view'])) return null
    if (typeof value.tab !== 'string' || !tabs.has(value.tab as SessionNavigation['tab'])) return null
    if (typeof value.step !== 'number' || !Number.isFinite(value.step)) return null
    const navigation: SessionNavigation = {
      projectId: value.projectId,
      view: value.view as SessionNavigation['view'],
      tab: value.tab as SessionNavigation['tab'],
      step: Math.min(9, Math.max(1, Math.trunc(value.step))),
    }
    const taskScope = parseTaskScope(value.taskScope)
    if (taskScope) navigation.taskScope = taskScope
    return navigation
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
    const stored: SessionNavigation = {
      projectId: navigation.projectId,
      view: navigation.view,
      tab: navigation.tab,
      step: navigation.step,
    }
    if (navigation.taskScope) stored.taskScope = navigation.taskScope
    window.localStorage.setItem(SESSION_NAVIGATION_KEY, JSON.stringify(stored))
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
