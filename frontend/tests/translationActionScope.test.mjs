import assert from 'node:assert/strict'
import test from 'node:test'
import { captureTranslationActionScope } from '../src/domain/translationActionScope.ts'

function setup() {
  const scope = { current: { projectId: 'project-a', taskId: 'translation-task-a' } }
  const environment = { current: {} }
  return { scope, environment, accept: captureTranslationActionScope(scope, environment, () => true) }
}

test('current action remains accepted without replacing its scope', () => {
  const { accept } = setup()
  assert.equal(accept(), true)
})

test('task A to B to A never revives an earlier response', () => {
  const { scope, accept } = setup()
  scope.current = { projectId: 'project-a', taskId: 'translation-task-b' }
  scope.current = { projectId: 'project-a', taskId: 'translation-task-a' }
  assert.equal(accept(), false)
})

test('project or view session replacement rejects an earlier response', () => {
  const { environment, accept } = setup()
  environment.current = {}
  assert.equal(accept(), false)
})

test('cancel or repair of the same task replaces the previous operation guard', () => {
  const { scope, environment, accept } = setup()
  scope.current = { ...scope.current }
  const next = captureTranslationActionScope(scope, environment, () => true)
  assert.equal(accept(), false)
  assert.equal(next(), true)
})

test('wizard or quick-task ownership still has to accept the operation', () => {
  const { scope, environment } = setup()
  let owned = true
  const accept = captureTranslationActionScope(scope, environment, () => owned)
  assert.equal(accept(), true)
  owned = false
  assert.equal(accept(), false)
})
