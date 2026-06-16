export const API = import.meta.env.VITE_API_BASE_URL || ''

export function sanitizeUserFacingError(text: string, fallback = '\u64cd\u4f5c\u5931\u8d25\uff0c\u8bf7\u91cd\u8bd5\u3002'): string {
  const raw = String(text || '').trim()
  if (!raw) return fallback
  const unsupported = raw.match(/unsupported file format:\s*(\.\w+)/i)
  if (unsupported) {
    return `\u5f53\u524d\u5165\u53e3\u4e0d\u652f\u6301 ${unsupported[1]} \u6587\u4ef6\u3002\u8bed\u8a00\u5305\u7ffb\u8bd1\u8bf7\u4e0a\u4f20 XLSX/XLS/CSV \u8bed\u8a00\u8868\uff1bTXT/DOCX \u957f\u6587\u672c\u8bf7\u4f7f\u7528\u516c\u544a\u7ffb\u8bd1/\u5916\u6587\u672c\u6d41\u7a0b\u3002`
  }
  if (/another long-text AI job is active/i.test(raw)) {
    return '\u5df2\u6709\u4e00\u4e2a\u957f\u6587\u672c AI \u4efb\u52a1\u6b63\u5728\u8fd0\u884c\uff0c\u8bf7\u7b49\u5f85\u5b8c\u6210\u6216\u5148\u53d6\u6d88\u540e\u518d\u7ee7\u7eed\u3002'
  }
  if (/response\s+ids?\s+mismatch/i.test(raw)) {
    return 'AI 返回内容与原文行不匹配。请点击继续翻译重试当前批；如果重复出现，请检查 AI response 是否漏行、乱序或改了 ID。'
  }
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
    return title ? `\u64cd\u4f5c\u5931\u8d25\uff1a${title}` : fallback
  }
  if (/Traceback|command failed|python\.exe|run_translation_harness\.py|\bFile "[^\n]+", line/i.test(raw) || /[A-Za-z]:[\\/]/.test(raw)) {
    return '\u672c\u5730 workflow \u6267\u884c\u5931\u8d25\uff0c\u8bf7\u68c0\u67e5\u8f93\u5165\u6587\u4ef6\u683c\u5f0f\u548c\u5f53\u524d\u6b65\u9aa4\u662f\u5426\u5339\u914d\u3002'
  }
  if (/Failed to fetch/i.test(raw)) return '\u8fde\u63a5\u5de5\u4f5c\u53f0\u540e\u7aef\u5931\u8d25\uff0c\u8bf7\u786e\u8ba4\u540e\u7aef\u670d\u52a1\u5df2\u542f\u52a8\u3002'
  const singleLine = raw.replace(/\s+/g, ' ').trim()
  return singleLine.length > 240 ? `${singleLine.slice(0, 237)}...` : singleLine
}

export function apiErrorText(text: string, fallback: string): string {
  if (!text.trim()) return fallback
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
    if (typeof detail === 'string' && detail.trim()) return sanitizeUserFacingError(detail, fallback)
  } catch {
    // Keep the original text when the backend returns plain text.
  }
  return sanitizeUserFacingError(text, fallback)
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, init)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(apiErrorText(text, response.statusText))
  }
  return response.json()
}
