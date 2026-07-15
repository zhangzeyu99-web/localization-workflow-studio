// Mirrors backend/app/authz.py's capability vocabulary. Kept as plain string
// constants (not an enum) so they compare directly against the string array
// GET /api/auth/me returns -- no translation layer needed between the two.
export const PROJECT_READ = 'project:read'
export const TASK_RUN = 'task:run'
export const ASSETS_CURATE = 'assets:curate'
export const PROJECT_MANAGE = 'project:manage'
export const ADMIN = 'admin:*'
