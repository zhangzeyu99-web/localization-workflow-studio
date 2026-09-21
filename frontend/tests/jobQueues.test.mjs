import assert from 'node:assert/strict'
import test from 'node:test'
import { queueJobStatusText } from '../src/domain/jobQueues.ts'

test('archive commit is shown as finishing instead of still cancelable work', () => {
  assert.equal(queueJobStatusText({ status: 'running', operator_name: '测试员', archive_committed: true }), '归档已提交，正在完成 · 操作人 测试员')
})

test('ordinary running and waiting jobs keep their existing status text', () => {
  assert.equal(queueJobStatusText({ status: 'running', operator_name: '测试员' }), '运行中 · 操作人 测试员')
  assert.equal(queueJobStatusText({ status: 'queued', position: 2, ahead: 1 }), '排队第 2 位、前方 1 个 · 操作人 未署名用户')
})
