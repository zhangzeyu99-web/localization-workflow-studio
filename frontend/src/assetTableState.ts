export const WIDE_TABLE_PAGE_SIZE = 100

export function normalizeWideSearch(value: unknown): string {
  return String(value ?? '').trim().toLocaleLowerCase()
}

export function wideRowMatches(fields: unknown[], query: string): boolean {
  const needle = normalizeWideSearch(query)
  if (!needle) return true
  return fields.some((field) => normalizeWideSearch(field).includes(needle))
}

export function pagedRows<T>(rows: T[], page: number): T[] {
  const start = (page - 1) * WIDE_TABLE_PAGE_SIZE
  return rows.slice(start, start + WIDE_TABLE_PAGE_SIZE)
}
