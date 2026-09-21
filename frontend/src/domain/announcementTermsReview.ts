import type { AnnouncementTask } from '../types'

export function announcementTermsVersion(task: AnnouncementTask | null): string {
  return String(task?.metadata?.terms_artifact_id || '')
}

function reviewKey(task: AnnouncementTask): string {
  return `lws.announcement-terms-review:${task.project_id}:${task.id}`
}

export function announcementReviewStep(task: AnnouncementTask): number {
  if (task.status !== 'terms_ready') return task.current_step || 1
  const version = announcementTermsVersion(task)
  try {
    if (version && sessionStorage.getItem(reviewKey(task)) === version) return 5
  } catch { /* Storage restrictions must not block the workflow. */ }
  return 4
}

export function confirmAnnouncementTerms(task: AnnouncementTask): void {
  const version = announcementTermsVersion(task)
  if (!version) return
  try {
    sessionStorage.setItem(reviewKey(task), version)
  } catch { /* The current page can still continue without persistence. */ }
}
