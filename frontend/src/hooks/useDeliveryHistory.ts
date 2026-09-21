import { useEffect, useState } from 'react'
import { api } from '../apiClient'
import { errorText } from '../appText'
import type { DeliverableTask, DeliveryHistory } from '../types'

export function useDeliveryHistory(projectId: string, projectUpdatedAt: string | undefined, deliverables: DeliverableTask[]) {
  const [state, setState] = useState<{ projectId: string; data: DeliveryHistory | null; loading: boolean; error: string }>({ projectId, data: null, loading: true, error: '' })
  const [revision, setRevision] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    setState((previous) => ({ projectId, data: previous.projectId === projectId ? previous.data : null, loading: true, error: '' }))
    api<DeliveryHistory>(`/api/projects/${projectId}/delivery-history`, { signal: controller.signal })
      .then((data) => {
        if (!controller.signal.aborted && data.project_id === projectId) setState({ projectId, data, loading: false, error: '' })
      })
      .catch((error) => {
        if (!controller.signal.aborted) setState({ projectId, data: null, loading: false, error: errorText(error) })
      })
    return () => controller.abort()
  }, [projectId, projectUpdatedAt, deliverables, revision])
  return {
    data: state.projectId === projectId ? state.data : null,
    loading: state.projectId !== projectId || state.loading,
    error: state.projectId === projectId ? state.error : '',
    refresh: () => setRevision((value) => value + 1),
  }
}
