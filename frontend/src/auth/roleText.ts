// Display labels for the plan's three global roles (see docs/superpowers/
// plans/2026-07-15-account-permission-system.md §2.1). Kept separate from
// capabilities.ts since this is presentation-only, not part of the
// capability vocabulary the backend understands.
const ROLE_LABELS: Record<string, string> = {
  admin: '管理员',
  ops: '运营',
  member: '成员'
}

export function roleBadgeLabel(role?: string): string {
  return ROLE_LABELS[String(role || '')] || String(role || '')
}
