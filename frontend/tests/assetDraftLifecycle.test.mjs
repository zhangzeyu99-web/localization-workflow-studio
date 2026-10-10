import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

// Exercise the actual row components and callbacks without starting a backend.
function renderRow(file, name) {
  const slots = [], effects = []
  let cursor = 0, changed = false
  const react = {
    memo: (component) => component,
    useState(initial) {
      const index = cursor++
      if (!(index in slots)) slots[index] = typeof initial === 'function' ? initial() : initial
      return [slots[index], (value) => {
        const next = typeof value === 'function' ? value(slots[index]) : value
        if (!Object.is(slots[index], next)) changed = true
        slots[index] = next
      }]
    },
    useRef(value) {
      const index = cursor++
      if (!(index in slots)) slots[index] = { current: value }
      return slots[index]
    },
    useEffect(effect, deps) {
      const index = cursor++, before = slots[index]
      if (!before || deps.some((value, i) => !Object.is(value, before[i]))) effects.push(effect)
      slots[index] = deps
    },
  }
  react.default = react
  const languages = ['en', 'fr', 'de'].map((code) => ({ code, short: code.toUpperCase(), targetHeader: code.toUpperCase() }))
  const imports = {
    react,
    'react/jsx-runtime': { jsx: (type, props) => ({ type, props }), jsxs: (type, props) => ({ type, props }), Fragment: 'fragment' },
    '../../languages': { supportedLanguages: languages, languageSpec: (code) => languages.find((item) => item.code === code) },
    '../../domain/projectAssets': { normalizeGlossaryNote: (value) => String(value || '') },
  }
  const source = readFileSync(new URL(file, import.meta.url), 'utf8') + `\nexport { ${name} as __subject };\n`
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText
  const module = { exports: {} }
  new Function('exports', 'require', 'module', output)(module.exports, (key) => imports[key] || {}, module)
  return (props) => {
    for (let iteration = 0; iteration < 10; iteration += 1) {
      cursor = 0; changed = false
      const tree = module.exports.__subject(props)
      while (effects.length) effects.shift()()
      if (!changed) return tree
    }
    throw new Error('row did not settle')
  }
}

function nodes(tree, type) {
  if (Array.isArray(tree)) return tree.flatMap((item) => nodes(item, type))
  if (!tree || typeof tree !== 'object') return []
  return [...(tree.type === type ? [tree] : []), ...nodes(tree.props?.children, type)]
}
function text(tree) {
  if (Array.isArray(tree)) return tree.map(text).join('')
  if (tree && typeof tree === 'object') return text(tree.props?.children)
  return String(tree ?? '')
}
function button(tree, label) { return nodes(tree, 'button').find((node) => text(node) === label) }
const settle = () => new Promise((resolve) => setImmediate(resolve))

test('glossary editing loads newly displayed languages without clearing existing drafts or writing hidden languages', async () => {
  const render = renderRow('../src/components/assets/ProjectAssetTabs.tsx', 'WideGlossaryTermRowImpl')
  const en = { target: 'Hero', record: { id: 'en-1' } }, fr = { target: 'Héros', record: { id: 'fr-1' } }
  let saved
  const props = {
    row: { source_key: 'hero', term_key: '1', source: '勇者', category: '', note: '', translations: { en }, conflicts: [] },
    visibleLanguages: ['en'], selectedLanguage: 'en',
    onSave: async (row, draft, languages) => { saved = { row, draft, languages }; return true },
  }
  button(render(props), '编辑').props.onClick()
  nodes(render(props), 'input')[2].props.onChange({ target: { value: 'Hero edited' } })
  props.row = { ...props.row, translations: { en, fr } }
  props.visibleLanguages = ['en', 'fr']
  const expanded = render(props)
  assert.equal(nodes(expanded, 'input')[2].props.value, 'Hero edited')
  assert.equal(nodes(expanded, 'input')[3].props.value, 'Héros')
  button(expanded, '保存').props.onClick()
  await settle()
  const payload = Object.fromEntries(saved.languages.filter((language) => saved.row.translations[language]?.record).map((language) => [language, saved.draft.targets[language] || '']))
  assert.deepEqual(payload, { en: 'Hero edited', fr: 'Héros' })
  assert.equal(Object.hasOwn(payload, 'de'), false)
})

test('glossary hiding and showing an edited language retains its draft', () => {
  const render = renderRow('../src/components/assets/ProjectAssetTabs.tsx', 'WideGlossaryTermRowImpl')
  const en = { target: 'Hero', record: { id: 'en-1' } }, fr = { target: 'Héros', record: { id: 'fr-1' } }
  const props = { row: { source_key: 'hero', source: '勇者', translations: { en, fr }, conflicts: [] }, visibleLanguages: ['en', 'fr'], selectedLanguage: 'en' }
  button(render(props), '编辑').props.onClick()
  nodes(render(props), 'input')[3].props.onChange({ target: { value: 'Héros édité' } })
  props.row = { ...props.row, translations: { en } }
  props.visibleLanguages = ['en']
  render(props)
  props.row = { ...props.row, translations: { en, fr } }
  props.visibleLanguages = ['en', 'fr']
  assert.equal(nodes(render(props), 'input')[3].props.value, 'Héros édité')
})

test('cancelled candidate edits never appear as saved text or change the subsequent accepted value', async () => {
  const render = renderRow('../src/components/glossary/GlossaryCandidateReview.tsx', 'GlossaryCandidateReviewRow')
  let stored = 'Old Hero', accepted
  const props = {
    candidate: { id: 'candidate-1', term_key: '1', source: '勇者', target: stored, category: '', note: '' },
    batchId: 'batch-1', busy: false, canCurate: true,
    onUpdateCandidate: async (_, updates) => { stored = updates.target; return true },
    onResolveCandidates: async () => { accepted = stored },
  }
  button(render(props), '编辑').props.onClick()
  nodes(render(props), 'input')[2].props.onChange({ target: { value: 'Cancelled Hero' } })
  button(render(props), '取消').props.onClick()
  const cancelled = render(props)
  assert.ok(text(cancelled).includes('Old Hero'))
  assert.ok(!text(cancelled).includes('Cancelled Hero'))
  button(cancelled, '加入').props.onClick()
  assert.equal(accepted, 'Old Hero')
  button(render(props), '编辑').props.onClick()
  assert.equal(nodes(render(props), 'input')[2].props.value, 'Old Hero')
  nodes(render(props), 'input')[2].props.onChange({ target: { value: 'Saved Hero' } })
  button(render(props), '保存并加入').props.onClick()
  await settle()
  assert.equal(accepted, 'Saved Hero')
})
