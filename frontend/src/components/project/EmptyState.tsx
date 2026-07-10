export function EmptyState({ onCreate, loading = false }: { onCreate: () => void; loading?: boolean }) {
  if (loading) {
    return <div className="empty" data-testid="project-list-loading"><h2>正在加载项目…</h2><p>正在从服务器同步项目列表。</p></div>
  }
  return <div className="empty"><h2>还没有项目</h2><p>先创建一个本地化项目，再进入完整工作流。</p><button className="btn btn-primary" onClick={onCreate}>新建项目</button></div>
}
