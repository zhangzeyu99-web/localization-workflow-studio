import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

class ApiRequestError extends Error {
  constructor(status, message) { super(message); this.status = status }
}

// Run the actual import hook with deterministic requests and React state slots.
function importFlow(api) {
  const slots = [], effects = []
  let cursor = 0, changed = false
  const react = {
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; changed = true }]
    },
    useReducer(reducer, initial, init) {
      const [value, set] = react.useState(() => init ? init(initial) : initial)
      return [value, (action) => set((state) => reducer(state, action))]
    },
    useRef(value) {
      const index = cursor++
      if (!(index in slots)) slots[index] = { current: value }
      return slots[index]
    },
    useCallback(fn, deps) {
      const index = cursor++, old = slots[index]
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) slots[index] = { fn, deps }
      return slots[index].fn
    },
    useEffect(effect, deps) {
      const index = cursor++, old = slots[index]
      if (!old || deps.some((value, i) => !Object.is(value, old.deps[i]))) effects.push(() => {
        old?.cleanup?.()
        slots[index] = { deps, cleanup: effect() }
      })
    },
  }
  function load(file, imports) {
    const source = readFileSync(new URL(file, import.meta.url), 'utf8')
    const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText
    const module = { exports: {} }
    new Function('exports', 'require', 'module', output)(module.exports, (key) => {
      if (!(key in imports)) throw new Error(`Unexpected import: ${key}`)
      return imports[key]
    }, module)
    return module.exports
  }
  const domain = load('../src/domain/archiveImport.ts', {})
  const { useArchiveImportFlow } = load('../src/hooks/useArchiveImportFlow.ts', {
    react, '../apiClient': { api, ApiRequestError },
    '../domain/archiveImport': domain, '../domain/projectApi': {},
  })
  const options = { projectId: 'p', kind: 'glossary', defaultLanguage: 'en', initialArtifact: { id: 'a' } }
  let flow
  return async () => {
    for (let i = 0; i < 30; i++) {
      cursor = 0; changed = false
      flow = useArchiveImportFlow(options)
      while (effects.length) effects.shift()()
      await new Promise((resolve) => setImmediate(resolve))
      if (!changed) return flow
    }
    throw new Error('import flow did not settle')
  }
}

const inspection = { languages: ['en', 'fr'], sheet: '__csv__', source_rows: 1, columns: {}, warnings: [] }
const preview = { batch_id: 'b', token: 't', artifact: { id: 'a' }, sheet: '__csv__', mode: 'merge', dataset_key: 'd', languages: ['en'], summary: { insert: 1 }, changes: [], conflicts: [], can_commit: true }
const result = { batch_id: 'b', status: 'committed', summary: { insert: 1 }, languages: ['en'], changed_count: 1 }

test('manual language scope survives mapping reinspection and resets only with a new source', async () => {
  const render = importFlow(async (url) => url.endsWith('/inspect') ? inspection : { batches: [] })
  let flow = await render()
  assert.deepEqual(flow.state.settings.languages, ['en', 'fr'])
  flow.toggleLanguage('fr'); flow = await render()
  flow.updateSettings({ noteColumn: '备注' }); flow = await render()
  assert.deepEqual(flow.state.settings.languages, ['en'])
  flow.selectArtifact({ id: 'another' }); flow = await render()
  assert.deepEqual(flow.state.settings.languages, ['en', 'fr'])
})

test('a lost commit response is recovered from the persisted batch, without repeating the write', async () => {
  let committed = false, writes = 0
  const render = importFlow(async (url) => {
    if (url.endsWith('/inspect')) return inspection
    if (url.endsWith('/analyze')) return preview
    if (url.includes('/commit?')) { writes++; committed = true; throw new Error('response lost') }
    if (url.includes('/batches')) return { batches: committed ? [{ id: 'b', status: 'committed', result }] : [] }
    return { id: 'p' }
  })
  let flow = await render()
  await flow.analyze(); flow = await render()
  await flow.commit(); flow = await render()
  assert.equal(flow.state.stage, 'success')
  assert.equal(flow.state.result.batch_id, 'b')
  assert.equal(flow.state.readbackWarning, '')
  assert.equal(writes, 1)
})

test('unconfirmed commit preserves its token and offers same-batch recovery instead of a false no-write claim', async () => {
  let recovering = false, writes = 0
  const render = importFlow(async (url) => {
    if (url.endsWith('/inspect')) return inspection
    if (url.endsWith('/analyze')) return preview
    if (url.includes('/commit?')) { writes++; throw new Error('response lost') }
    if (url.includes('/batches')) {
      if (writes && !recovering) throw new Error('offline')
      return { batches: recovering ? [{ id: 'b', status: 'committed', result }] : [] }
    }
    return { id: 'p' }
  })
  let flow = await render()
  await flow.analyze(); flow = await render()
  await flow.commit(); flow = await render()
  assert.equal(flow.state.commitUncertain, true)
  assert.equal(flow.canAnalyze, false)
  assert.equal(flow.canCommit, true)
  assert.doesNotMatch(flow.state.message, /未.*写入/)
  flow.resetRowDecisions(); flow = await render()
  assert.equal(flow.canCommit, true, 'undo must not discard the recovery token')
  recovering = true
  await flow.commit(); flow = await render()
  assert.equal(flow.state.stage, 'success')
  assert.equal(writes, 1)
})

test('a recovery write rejected for state drift unlocks settings and requires a fresh preview', async () => {
  let writes = 0, recovering = false
  const render = importFlow(async (url) => {
    if (url.endsWith('/inspect')) return inspection
    if (url.endsWith('/analyze')) return preview
    if (url.includes('/commit?')) {
      writes++
      if (recovering) throw new ApiRequestError(409, '请重新分析')
      throw new Error('offline')
    }
    if (url.includes('/batches')) {
      if (writes && !recovering) throw new Error('offline')
      return { batches: [{ id: 'b', status: 'analyzed' }] }
    }
    return { id: 'p' }
  })
  let flow = await render()
  await flow.analyze(); flow = await render()
  await flow.commit(); flow = await render()
  assert.equal(flow.state.commitUncertain, true)
  recovering = true
  await flow.commit(); flow = await render()
  assert.equal(flow.state.commitUncertain, false)
  assert.equal(flow.state.stage, 'settings')
  assert.equal(flow.canAnalyze, true)
  assert.equal(flow.canCommit, false)
})

test('an invalid success response cannot become a committed result when readback also fails', async () => {
  let attempted = false
  const render = importFlow(async (url) => {
    if (url.endsWith('/inspect')) return inspection
    if (url.endsWith('/analyze')) return preview
    if (url.includes('/commit?')) { attempted = true; return {} }
    if (attempted) throw new Error('offline')
    return { batches: [] }
  })
  let flow = await render()
  await flow.analyze(); flow = await render()
  await flow.commit(); flow = await render()
  assert.equal(flow.state.commitUncertain, true)
  assert.equal(flow.state.result, null)
  assert.equal(flow.canCommit, true)
})
