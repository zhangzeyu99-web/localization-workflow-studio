export type TranslationActionScope = { projectId: string; taskId: string }

// Capture object identity, not just IDs: leaving and reopening the same task
// must not revive an operation from its previous screen/session.
export function captureTranslationActionScope(
  scopeRef: { current: TranslationActionScope },
  environmentRef: { current: object },
  ownsTask: () => boolean,
): () => boolean {
  const scope = scopeRef.current
  const environment = environmentRef.current
  return () => scopeRef.current === scope && environmentRef.current === environment && ownsTask()
}
