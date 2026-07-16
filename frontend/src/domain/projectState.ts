import { newestArtifact, runArtifacts } from './artifacts'
import type { Artifact, Project, Run } from '../types'

function hasObjectFields(value?: Record<string, unknown> | null): value is Record<string, unknown> {
  return Boolean(value && Object.keys(value).length)
}

function hasOwn(project: Project, field: keyof Project): boolean {
  return Object.prototype.hasOwnProperty.call(project, field)
}

export function mergeProjectSummary(existing: Project | undefined, summary: Project): Project {
  if (!existing) return summary
  const archivesOmitted = summary.archives_embedded === false
  return {
    ...existing,
    ...summary,
    profile: hasObjectFields(summary.profile) ? summary.profile : existing.profile,
    harness: hasObjectFields(summary.harness as Record<string, unknown> | undefined) ? summary.harness : existing.harness,
    artifacts: hasOwn(summary, 'artifacts') ? summary.artifacts : existing.artifacts,
    runs: hasOwn(summary, 'runs') ? summary.runs : existing.runs,
    glossary: archivesOmitted ? undefined : (hasOwn(summary, 'glossary') ? summary.glossary : existing.glossary),
    translations: archivesOmitted ? undefined : (hasOwn(summary, 'translations') ? summary.translations : existing.translations),
    announcement_tasks: hasOwn(summary, 'announcement_tasks') ? summary.announcement_tasks : existing.announcement_tasks,
  }
}

export function mergeProjectListSummaries(previous: Project[], loaded: Project[]): Project[] {
  const previousById = new Map(previous.map((project) => [project.id, project]))
  return loaded.map((project) => mergeProjectSummary(previousById.get(project.id), project))
}

export function preferredTranslationResultArtifact(project: Project | null | undefined, run?: Run | null): Artifact | null {
  if (!project) return null
  const pickFromRun = (candidate?: Run | null): Artifact | null => {
    if (!candidate || !['translation', 'qa'].includes(candidate.kind)) return null
    return newestArtifact(runArtifacts(project, candidate.id), ['qa_final_workbook', 'final_workbook', 'raw_translated_workbook'])
  }
  const direct = pickFromRun(run)
  if (direct) return direct
  for (const candidate of project.runs || []) {
    if (!['passed', 'failed'].includes(candidate.status)) continue
    const artifact = pickFromRun(candidate)
    if (artifact) return artifact
  }
  return null
}

export function artifactForProject(project: Project | null | undefined, artifact: Artifact | null): Artifact | null {
  if (!project || !artifact) return null
  if (artifact.project_id) return artifact.project_id === project.id ? artifact : null
  return (project.artifacts || []).some((candidate) => candidate.id === artifact.id) ? artifact : null
}

export function runForProject(project: Project | null | undefined, run: Run | null): Run | null {
  return project && run?.project_id === project.id ? run : null
}
