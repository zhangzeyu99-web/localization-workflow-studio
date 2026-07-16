import { getOperatorName } from './operator'
import { broadcastMustChangePassword, broadcastUnauthorized } from './auth/authEvents'

const MUST_CHANGE_PASSWORD_DETAIL = '首次登录请先修改密码'

export const API = import.meta.env.VITE_API_BASE_URL || ''

export class ApiRequestError extends Error {
  readonly status: number
  readonly detail: unknown
  readonly responseText: string

  constructor(message: string, status: number, detail: unknown, responseText: string) {
    super(message)
    this.name = 'ApiRequestError'
    this.status = status
    this.detail = detail
    this.responseText = responseText
  }
}

function structuredErrorDetail(text: string): unknown {
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown }
    return payload.detail ?? payload.message ?? payload.error ?? null
  } catch {
    return null
  }
}

function isProjectBusyMessage(text: string): boolean {
  return text.includes('该项目正在执行任务') || (text.includes('该项目正在由') && text.includes('执行任务'))
}

function defaultFailureText(operation?: string): string {
  return operation ? `\u300c${operation}\u300d\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002` : '\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002'
}

export function sanitizeUserFacingError(text: string, fallback?: string, operation?: string): string {
  const effectiveFallback = fallback ?? defaultFailureText(operation)
  const raw = String(text || '').trim()
  if (!raw) return effectiveFallback
  if (/http proxy error|ECONNREFUSED|connect ECONNREFUSED|NetworkError|Failed to fetch/i.test(raw)) {
    return '连接工作台后端失败。后端可能正在重启或未启动，请等几秒后重试；如果反复出现，请重启本地/局域网工作台。'
  }
  const unsupported = raw.match(/unsupported file format:\s*(\.\w+)/i)
  if (unsupported) {
    return `\u5f53\u524d\u5165\u53e3\u4e0d\u652f\u6301 ${unsupported[1]} \u6587\u4ef6\u3002\u8bed\u8a00\u5305\u7ffb\u8bd1\u8bf7\u4e0a\u4f20 XLSX/XLS/CSV \u8bed\u8a00\u8868\uff1bTXT/DOCX \u957f\u6587\u672c\u8bf7\u4f7f\u7528\u516c\u544a\u7ffb\u8bd1/\u5916\u6587\u672c\u6d41\u7a0b\u3002`
  }
  const missingTargetColumn = raw.match(/target column not found in sheet:\s*([^,;\r\n]+)/i)
  if (missingTargetColumn) {
    const sheet = missingTargetColumn[1].trim().replace(/^['"]|['"]$/g, '')
    return `所选工作表“${sheet}”中找不到目标译文列。请确认译文列存在，或返回“判定输入”重新选择语言表。`
  }
  if (/another long-text AI job is active/i.test(raw)) {
    // Legacy pre-M2 message (single global lease); kept as a fallback in case
    // an older backend build is still deployed alongside this frontend.
    return '\u5df2\u6709\u4e00\u4e2a\u957f\u6587\u672c AI \u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u8bf7\u7b49\u5f85\u5b8c\u6210\u6216\u5148\u53d6\u6d88\u540e\u518d\u7ee7\u7eed\u3002'
  }
  if (isProjectBusyMessage(raw)) {
    // Post-M2 per-project lease rejection; backend detail is already a
    // complete, user-facing Chinese sentence (e.g. "该项目正在由“Alice”执行任务（翻译任务），
    // 请等它完成或先取消"), so pass it through unless it grew unexpectedly long.
    return raw.length <= 200 ? raw : '该项目正在执行任务，请等它完成或先取消。'
  }
  if (/工作台已有.*个任务在跑/.test(raw)) {
    // Post-M2 global concurrency-limit rejection (max_concurrent_ai_jobs).
    return raw.length <= 200 ? raw : '工作台并发任务已达上限，请稍后再试。'
  }
  if (/response\s+ids?\s+mismatch/i.test(raw)) {
    return 'AI 返回内容与原文行不匹配。请点击继续翻译重试当前批；如果重复出现，请检查 AI response 是否漏行、乱序或改了 ID。'
  }
  if (/^权限不足$/.test(raw)) return '当前账号权限不足，无法执行此操作，请联系项目运营或管理员。'
  if (raw === MUST_CHANGE_PASSWORD_DETAIL) return '首次登录需要先修改密码，请在改密页面完成后再继续。'
  if (/project not found/i.test(raw)) return '项目不存在或已被删除，列表已刷新后请重新选择项目。'
  if (/artifact file missing|delivery file missing|batch file not found/i.test(raw)) return '文件记录还在，但本地文件缺失。请重新生成交付文件或重新上传来源文件。'
  if (/artifact not found|input artifact not found/i.test(raw)) return '找不到所选文件，请重新上传或重新选择文件。'
  if (/project or artifact not found|project, run, or artifact not found|run or artifact not found/i.test(raw)) return '当前任务引用的项目或文件不存在，请返回上一步重新选择输入文件。'
  if (/Internal Server Error/i.test(raw)) return '后台执行失败。请检查当前步骤输入是否完整；如果重复出现，请查看后台日志。'
  if (/413 Request Entity Too Large|Request Entity Too Large/i.test(raw)) {
    return '\u6587\u4ef6\u592a\u5927\uff0c\u5f53\u524d\u4e0a\u4f20\u94fe\u8def\u62d2\u7edd\u4e86\u5355\u6b21\u8bf7\u6c42\u3002\u8bf7\u91cd\u8bd5\uff1b\u5de5\u4f5c\u53f0\u4f1a\u81ea\u52a8\u4f7f\u7528\u5206\u7247\u4e0a\u4f20\u3002'
  }
  if (/<html[\s>]/i.test(raw) || /<body[\s>]/i.test(raw)) {
    const title = raw.match(/<title[^>]*>(.*?)<\/title>/i)?.[1]?.replace(/\s+/g, ' ').trim()
    return title ? `\u64cd\u4f5c\u5931\u8d25\uff1a${title}` : effectiveFallback
  }
  if (/Traceback|command failed|python\.exe|run_translation_harness\.py|\bFile "[^\n]+", line/i.test(raw) || /[A-Za-z]:[\\/]/.test(raw)) {
    return '\u672c\u5730 workflow \u6267\u884c\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8f93\u5165\u6587\u4ef6\u683c\u5f0f\u548c\u5f53\u524d\u6b65\u9aa4\u662f\u5426\u5339\u914d\u3002'
  }
  const singleLine = raw.replace(/\s+/g, ' ').trim()
  return singleLine.length > 240 ? `${singleLine.slice(0, 237)}...` : singleLine
}

export function apiErrorText(text: string, fallback: string, operation?: string): string {
  if (!text.trim()) return operation ? `\u300c${operation}\u300d\u5931\u8d25\uff1a${fallback}` : fallback
  try {
    const payload = JSON.parse(text) as { detail?: unknown; message?: unknown; error?: unknown }
    const detail = payload.detail ?? payload.message ?? payload.error
    if (Array.isArray(detail)) {
      const missingFields = detail
        .filter((item) => item && typeof item === 'object' && String((item as { type?: unknown }).type || '').includes('missing'))
        .map((item) => ((item as { loc?: unknown }).loc || []))
      const flat = missingFields.flatMap((loc) => Array.isArray(loc) ? loc.map(String) : [])
      if (flat.includes('input_artifact_id')) return '请先选择或上传语言表，再继续当前步骤。'
      if (flat.includes('artifact_id')) return '请先选择或上传文件，再继续当前步骤。'
      if (flat.includes('language')) return '请先选择目标语言，再继续当前步骤。'
      if (flat.length) return `请求缺少必要信息：${Array.from(new Set(flat.filter((item) => item !== 'body'))).join(' / ')}`
    }
    if (typeof detail === 'string' && detail.trim()) return sanitizeUserFacingError(detail, undefined, operation)
    if (detail && typeof detail === 'object' && typeof (detail as { message?: unknown }).message === 'string') {
      return sanitizeUserFacingError(String((detail as { message: string }).message), undefined, operation)
    }
  } catch {
    // Keep the original text when the backend returns plain text.
  }
  return sanitizeUserFacingError(text, undefined, operation)
}

function withOperatorHeader(init?: RequestInit): RequestInit | undefined {
  const operator = getOperatorName()
  if (!operator) return init
  const headers = new Headers(init?.headers)
  headers.set('X-Operator', encodeURIComponent(operator))
  return { ...init, headers }
}

export async function api<T>(path: string, init?: RequestInit, operation?: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${API}${path}`, { credentials: 'include', ...withOperatorHeader(init) })
  } catch (error) {
    throw new Error(sanitizeUserFacingError(error instanceof Error ? error.message : String(error), undefined, operation))
  }
  if (!response.ok) {
    const text = await response.text()
    // Session died mid-session (expired/revoked) -- the login endpoint's own
    // 401 (wrong password) must not bounce the gate away from the login
    // screen it is already showing, so it is excluded here.
    if (response.status === 401 && path !== '/api/auth/login') {
      broadcastUnauthorized()
    }
    if (response.status === 403 && text.includes(MUST_CHANGE_PASSWORD_DETAIL)) {
      broadcastMustChangePassword()
    }
    if (response.status >= 500) {
      const trimmed = text.trim()
      const contentType = response.headers.get('content-type') || ''
      // Only a proxy failure (or an empty reply) means the backend is actually
      // unreachable. A bare "Internal Server Error" body means the backend is
      // alive but crashed on this request — telling the user to restart the
      // workbench would send them down the wrong path, so let that fall through
      // to sanitizeUserFacingError's dedicated 500 message instead.
      if (!trimmed || (!contentType.includes('application/json') && /^Error occurred while trying to proxy/i.test(trimmed))) {
        throw new Error('连接工作台后端失败。后端可能正在重启或未启动，请等几秒后重试；如果反复出现，请重启本地/局域网工作台。')
      }
    }
    throw new ApiRequestError(
      apiErrorText(text, response.statusText, operation),
      response.status,
      structuredErrorDetail(text),
      text,
    )
  }
  return response.json()
}
