import { API, api, apiErrorText, sanitizeUserFacingError } from '../apiClient'
import type { Artifact } from '../types'

const CHUNKED_UPLOAD_THRESHOLD_BYTES = 768 * 1024
const UPLOAD_CHUNK_BYTES = 512 * 1024

export async function uploadProjectFile(
  projectId: string,
  file: File,
  kind: string,
  purpose: string,
  onProgress: (done: number, total: number) => void
): Promise<Artifact> {
  if (file.size <= CHUNKED_UPLOAD_THRESHOLD_BYTES) {
    const data = new FormData()
    data.append('file', file)
    const query = new URLSearchParams({ kind })
    if (purpose) query.set('purpose', purpose)
    return api<Artifact>(`/api/projects/${projectId}/files?${query.toString()}`, {
      method: 'POST',
      body: data
    })
  }
  const total = Math.ceil(file.size / UPLOAD_CHUNK_BYTES)
  const uploadId = `${Date.now()}-${Math.random().toString(36).slice(2)}`
  for (let index = 0; index < total; index += 1) {
    const start = index * UPLOAD_CHUNK_BYTES
    const chunk = file.slice(start, Math.min(file.size, start + UPLOAD_CHUNK_BYTES))
    const data = new FormData()
    data.append('file', chunk, file.name)
    data.append('upload_id', uploadId)
    data.append('filename', file.name)
    data.append('kind', kind)
    data.append('purpose', purpose)
    data.append('index', String(index))
    data.append('total', String(total))
    let response: Response
    try {
      response = await fetch(`${API}/api/projects/${projectId}/files/chunk`, {
        method: 'POST',
        body: data
      })
    } catch (error) {
      throw new Error(sanitizeUserFacingError(error instanceof Error ? error.message : String(error)))
    }
    if (!response.ok) {
      const text = await response.text()
      const trimmed = text.trim()
      const contentType = response.headers.get('content-type') || ''
      if (response.status >= 500 && (!trimmed || (!contentType.includes('application/json') && /^(Internal Server Error|Error occurred while trying to proxy)/i.test(trimmed)))) {
        throw new Error('连接工作台后端失败。后端可能正在重启或未启动，请等几秒后重试；如果反复出现，请重启本地/局域网工作台。')
      }
      throw new Error(apiErrorText(text, response.statusText))
    }
    const payload = await response.json() as { complete?: boolean; artifact?: Artifact; received?: number; total?: number }
    onProgress(index + 1, total)
    if (payload.complete && payload.artifact) return payload.artifact
  }
  throw new Error('分片上传已完成，但后端没有返回文件记录。')
}
