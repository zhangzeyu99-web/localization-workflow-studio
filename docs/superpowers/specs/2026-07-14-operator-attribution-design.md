# Online Operator Attribution Design

## Goal

Give every cloud user an independent, always-visible nickname entry and show who owns each active AI job, without restoring the hidden API settings button or adding an account system.

## Decisions

- Add a compact operator control to the header for both cloud and local deployments.
- When unset it reads `设置昵称`; when set it displays the current nickname. Clicking it opens a focused nickname dialog.
- Keep the nickname in browser `localStorage` and send it through the existing `X-Operator` header.
- Remove nickname editing from `SettingsModal`; operator identity has one visible entry point and no dependency on API settings access.
- In cloud mode, all background AI start/resume endpoints reject requests without a nickname before changing task state.
- Local mode remains permissive for development and automated tests unless a test explicitly enables cloud mode.
- Persist the nickname on the project job lease. Existing databases receive an additive nullable `operator_name` column migration.
- Expose `operator_name` from `/api/system/active-jobs` and include it in same-project conflict details.
- Show project, task type, operator and elapsed time in the active-jobs panel.
- A missing owner on an old/stale lease is displayed as `未署名用户`.
- Nicknames are attribution only. They do not authenticate a person, grant permissions, or prevent another browser from cancelling a task.

## User Flow

1. A cloud user opens the workbench and sees `设置昵称` in the header.
2. Clicking it opens a small dialog with one required field, a 40-character limit and a short explanation that this is a team label, not an account.
3. Saving updates the header immediately; subsequent API calls carry `X-Operator`.
4. If the user starts or resumes an AI task without a nickname, the backend returns `请先设置操作人昵称，再启动 AI 任务。` The inline status offers `设置昵称` and opens the same dialog.
5. If another user already owns a job for the project, the second user sees `该项目正在由“张三”执行任务（翻译任务），请等它完成或先取消。` and can open the active-jobs panel.
6. The active-jobs panel shows `项目 · 任务类型 · 操作人 · 已运行时间` for every running job.

## Architecture

### Frontend

- `OperatorIdentityControl` owns the lightweight dialog and current browser nickname.
- `operator.ts` remains the storage boundary and emits a browser event after changes so visible controls stay synchronized.
- `apiClient.ts` continues to attach `X-Operator`; it recognizes the operator-required error for the inline action.
- `ActionStatus` exposes either `设置昵称` or `查看活跃任务` according to the current status message.

### Backend

- `operator_context.require_operator_for_cloud()` enforces the cloud-only start gate.
- `jobs.start_singleton_job()` snapshots the current operator before starting the worker and stores it with the lease.
- Job conflict payloads carry `operator_name`; `_job_conflict_detail()` renders the owner when available.
- The active-jobs endpoint returns the persisted owner for every lease.

### Persistence

- Extend `job_leases` with nullable text column `operator_name`.
- Migration is additive and idempotent; old rows remain valid.
- Lease acquisition/replacement writes the current operator and release keeps existing cleanup semantics.

## Error Handling

- Cloud missing nickname: reject before status becomes `queued`.
- Existing lease without nickname: display `未署名用户` without failing the panel.
- Nickname storage unavailable in the browser: the dialog stays usable, but the next cloud start request is rejected rather than silently running anonymously.
- Global capacity rejection keeps its existing copy and points users to the enriched active-jobs panel.

## Verification

- Backend tests cover migration, lease attribution, active-jobs response, owner-aware conflicts and cloud-only nickname enforcement.
- Frontend tests cover the always-visible header control, save/update behavior, operator-required action and owner rendering.
- Run focused tests red-to-green, then the complete backend suite, compileall, Ruff, frontend build and Playwright E2E.
- Bump the user-visible version from `1.3.2` to `1.3.3`, build the release archive, inspect its manifest and run the package verification tests.

## Out of Scope

- Login, SSO, roles, permissions and ownership-based cancellation.
- A server-managed user directory.
- Parallel AI jobs inside one project.
