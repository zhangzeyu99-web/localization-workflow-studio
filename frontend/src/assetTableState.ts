export const WIDE_TABLE_PAGE_SIZE = 100

// Run history / activity lists are usually much shorter than the wide term
// and translation-archive tables, so they use a smaller page.
export const HISTORY_TABLE_PAGE_SIZE = 50

export function normalizeWideSearch(value: unknown): string {
  return String(value ?? '').trim().toLocaleLowerCase()
}

export function wideRowMatches(fields: unknown[], query: string): boolean {
  const needle = normalizeWideSearch(query)
  if (!needle) return true
  return fields.some((field) => normalizeWideSearch(field).includes(needle))
}

export function pagedRows<T>(rows: T[], page: number, pageSize: number = WIDE_TABLE_PAGE_SIZE): T[] {
  const start = (page - 1) * pageSize
  return rows.slice(start, start + pageSize)
}
