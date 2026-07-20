import { expect, test, type Page } from '@playwright/test'

test.describe.configure({ mode: 'serial' })

const adminInitialPassword = process.env.LWS_AUTH_E2E_ADMIN_PASSWORD || 'Admin-Initial-Password!'
const adminPassword = 'Admin-Changed-Password!'
const opsInitialPassword = 'Ops-Initial-Password!'
const opsPassword = 'Ops-Changed-Password!'
const memberInitialPassword = 'Member-Initial-Password!'
const memberPassword = 'Member-Changed-Password!'
const suffix = String(Date.now())
const opsUsername = `e2e-ops-${suffix}`
const memberUsername = `e2e-member-${suffix}`
const registeredUsername = `e2e-registered-${suffix}`
const registeredPassword = 'Registered-Member-Password!'
const duplicateUsername = `e2e-register-duplicate-${suffix}`
const recoveryUsername = `e2e-register-recovery-${suffix}`
const memberProjectName = `Member Project ${suffix}`
const registeredProjectName = `Registered Project ${suffix}`
const opsProjectName = `Ops Project ${suffix}`

async function login(page: Page, username: string, password: string) {
  await page.goto('/')
  await page.getByTestId('login-username').fill(username)
  await page.getByTestId('login-password').fill(password)
  await page.getByTestId('login-submit').click()
}

async function changePassword(page: Page, currentPassword: string, nextPassword: string) {
  await expect(page.getByRole('heading', { name: '首次登录请修改密码' })).toBeVisible()
  await page.getByTestId('change-password-current').fill(currentPassword)
  await page.getByTestId('change-password-new').fill(nextPassword)
  await page.getByTestId('change-password-confirm').fill(nextPassword)
  await page.getByTestId('change-password-submit').click()
  await expect(page.getByTestId('current-user-chip')).toBeVisible()
}

async function createProject(page: Page, name: string) {
  await page.locator('.new-project-btn').click()
  await page.locator('input[name="name"]').fill(name)
  await page.getByRole('button', { name: '创建', exact: true }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
}

async function openRegistration(page: Page) {
  await page.goto('/')
  await page.getByTestId('show-register').click()
  await expect(page.getByTestId('register-submit')).toBeVisible()
}

async function fillRegistration(page: Page, values: {
  username: string
  displayName?: string
  password: string
  passwordConfirm?: string
}) {
  await page.getByTestId('register-username').fill(values.username)
  await page.getByTestId('register-display-name').fill(values.displayName || '')
  await page.getByTestId('register-password').fill(values.password)
  await page.getByTestId('register-password-confirm').fill(values.passwordConfirm ?? values.password)
}

test('自助注册只发送一次注册请求并直接以 member 进入应用', async ({ page }) => {
  const registrationPayloads: unknown[] = []
  let loginRequestCount = 0
  page.on('request', (request) => {
    const pathname = new URL(request.url()).pathname
    if (request.method() === 'POST' && pathname === '/api/auth/register') {
      registrationPayloads.push(request.postDataJSON())
    }
    if (request.method() === 'POST' && pathname === '/api/auth/login') loginRequestCount += 1
  })

  await openRegistration(page)
  await expect(page.getByRole('heading', { name: '创建账号' })).toBeVisible()
  await expect(page.getByText('注册后以普通成员权限进入，管理员可以调整账号权限。')).toBeVisible()
  await page.getByTestId('register-username').fill(registeredUsername)
  await page.getByTestId('register-display-name').fill('E2E 自助成员')
  await page.getByTestId('register-password').fill(registeredPassword)
  await page.getByTestId('register-password-confirm').fill(registeredPassword)
  await page.getByTestId('register-submit').click()

  await expect(page.getByTestId('current-user-chip')).toContainText('E2E 自助成员')
  await expect(page.getByTestId('current-user-chip')).toContainText('成员')
  await expect(page.getByRole('heading', { name: '首次登录请修改密码' })).toHaveCount(0)
  expect(registrationPayloads).toEqual([{
    username: registeredUsername,
    display_name: 'E2E 自助成员',
    password: registeredPassword,
  }])
  expect(loginRequestCount).toBe(0)

  await expect(page.getByRole('button', { name: '设置', exact: true })).toHaveCount(0)
  await expect(page.getByTestId('open-user-management')).toHaveCount(0)
  await expect(page.locator('.new-project-btn')).toBeVisible()
  await createProject(page, registeredProjectName)
  await expect(page.getByTitle(/删除项目/)).toHaveCount(0)
  await expect(page.getByTestId('open-project-members')).toHaveCount(0)
  await expect(page.getByTestId('quick-task-entry')).toBeEnabled()
  await page.getByRole('button', { name: '术语表', exact: true }).click()
  await expect(page.getByTestId('manual-glossary-tools')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导入已确认术语', exact: true })).toHaveCount(0)
})

test('前端拦截所有无效注册字段且不发请求', async ({ page }) => {
  let registerRequestCount = 0
  await page.route('**/api/auth/register', async (route) => {
    registerRequestCount += 1
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: '测试不应到达服务端' }),
    })
  })
  await openRegistration(page)

  const invalidCases = [
    {
      values: { username: '   ', password: registeredPassword },
      message: '请输入用户名。',
    },
    {
      values: { username: 'u'.repeat(129), password: registeredPassword },
      message: '用户名不能超过 128 个字符。',
    },
    {
      values: { username: 'valid-user', displayName: 'd'.repeat(129), password: registeredPassword },
      message: '显示名称不能超过 128 个字符。',
    },
    {
      values: { username: 'valid-user', password: '1234567' },
      message: '密码长度必须为 8 到 128 个字符。',
    },
    {
      values: { username: 'valid-user', password: 'p'.repeat(129) },
      message: '密码长度必须为 8 到 128 个字符。',
    },
    {
      values: { username: 'valid-user', password: registeredPassword, passwordConfirm: 'Different-Password!' },
      message: '两次输入的密码不一致。',
    },
  ]

  for (const invalidCase of invalidCases) {
    await fillRegistration(page, invalidCase.values)
    await page.getByTestId('register-submit').click()
    await expect(page.getByTestId('register-error')).toHaveText(invalidCase.message)
    expect(registerRequestCount).toBe(0)
  }
})

test('登录注册切换会清除密码、错误和忙碌状态', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('login-password').fill('temporary-login-password')
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('login-error')).toHaveText('请输入用户名和密码。')

  await page.getByTestId('show-register').click()
  await expect(page.getByTestId('register-password')).toHaveValue('')
  await expect(page.getByTestId('register-error')).toHaveCount(0)
  await fillRegistration(page, {
    username: 'switch-state-user',
    password: registeredPassword,
    passwordConfirm: 'Different-Password!',
  })
  await page.getByTestId('register-submit').click()
  await expect(page.getByTestId('register-error')).toHaveText('两次输入的密码不一致。')

  await page.getByTestId('show-login').click()
  await expect(page.getByTestId('login-password')).toHaveValue('')
  await expect(page.getByTestId('login-error')).toHaveCount(0)
  await expect(page.getByTestId('login-submit')).toBeEnabled()

  let releaseRequest = () => {}
  const requestGate = new Promise<void>((resolve) => { releaseRequest = resolve })
  await page.route('**/api/auth/register', async (route) => {
    await requestGate
    await route.abort('failed')
  })
  await page.getByTestId('show-register').click()
  await fillRegistration(page, { username: 'switch-busy-user', password: registeredPassword })
  await page.getByTestId('register-submit').click()
  await expect(page.getByTestId('register-submit')).toContainText('注册中...')
  try {
    await page.getByTestId('show-login').click()
    await page.getByTestId('show-register').click()
    await expect(page.getByTestId('register-password')).toHaveValue('')
    await expect(page.getByTestId('register-error')).toHaveCount(0)
    await expect(page.getByTestId('register-submit')).toBeEnabled()
    await expect(page.getByTestId('register-submit')).toContainText('创建账号')
  } finally {
    releaseRequest()
  }
})

test('同步重复提交只发送一次注册请求', async ({ page }) => {
  let registerRequestCount = 0
  let releaseRequests = () => {}
  const requestGate = new Promise<void>((resolve) => { releaseRequests = resolve })
  await page.route('**/api/auth/register', async (route) => {
    registerRequestCount += 1
    await requestGate
    await route.continue()
  })
  await openRegistration(page)
  await fillRegistration(page, { username: duplicateUsername, password: registeredPassword })

  await page.getByTestId('register-submit').evaluate((button) => {
    const form = button.closest('form')
    form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    form?.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
  })
  try {
    await expect.poll(() => registerRequestCount).toBeGreaterThan(0)
    await page.waitForTimeout(100)
    expect(registerRequestCount).toBe(1)
  } finally {
    releaseRequests()
  }
  await expect(page.getByTestId('current-user-chip')).toContainText(duplicateUsername)
})

test('注册错误按状态提示且网络恢复后可以重试', async ({ page }) => {
  type Failure = { status: number; expected: string } | { status: 'network'; expected: string }
  let currentFailure: Failure | null = null
  await page.route('**/api/auth/register', async (route) => {
    if (currentFailure?.status === 'network') {
      await route.abort('failed')
      return
    }
    if (currentFailure) {
      await route.fulfill({
        status: currentFailure.status,
        contentType: 'application/json',
        body: JSON.stringify({ detail: '服务端原始错误不应直接展示' }),
      })
      return
    }
    await route.continue()
  })
  await openRegistration(page)

  const failures: Failure[] = [
    { status: 409, expected: '用户名已存在，请更换后重试。' },
    { status: 422, expected: '注册信息不符合要求，请检查后重试。' },
    { status: 429, expected: '注册请求过多，请稍后再试。' },
    { status: 403, expected: '当前环境未开放注册，请使用已有账号登录。' },
    { status: 500, expected: '注册服务暂时不可用，请稍后重试。' },
    { status: 'network', expected: '网络连接失败，请检查网络后重试。' },
  ]

  for (const [index, failure] of failures.entries()) {
    currentFailure = failure
    await fillRegistration(page, {
      username: `failed-register-${index}-${suffix}`,
      password: registeredPassword,
    })
    await page.getByTestId('register-submit').click()
    await expect(page.getByTestId('register-error')).toHaveText(failure.expected)
    await expect(page.getByTestId('register-submit')).toBeEnabled()
    await expect(page.getByTestId('register-submit')).toContainText('创建账号')
    await page.getByTestId('register-username').fill(`retry-register-${index}-${suffix}`)
    await expect(page.getByTestId('register-error')).toHaveCount(0)
  }

  currentFailure = null
  await fillRegistration(page, { username: recoveryUsername, password: registeredPassword })
  await page.getByTestId('register-submit').click()
  await expect(page.getByTestId('current-user-chip')).toContainText(recoveryUsername)
})

test('管理员首次登录后强制改密并进入应用', async ({ page }) => {
  await login(page, 'e2e-admin', adminInitialPassword)
  await expect(page.getByRole('heading', { name: '首次登录请修改密码' })).toBeVisible()
  await page.getByTestId('change-password-current').fill(adminInitialPassword)
  await page.getByTestId('change-password-new').fill(adminInitialPassword)
  await page.getByTestId('change-password-confirm').fill(adminInitialPassword)
  await page.getByTestId('change-password-submit').click()
  await expect(page.getByText('新密码不能与当前密码相同')).toBeVisible()
  await changePassword(page, adminInitialPassword, adminPassword)
  await expect(page.getByTestId('current-user-chip')).toContainText('e2e-admin')
  await expect(page.getByTestId('current-user-chip')).toContainText('管理员')
  await expect(page.getByTestId('operator-identity-trigger')).toHaveCount(0)
  await page.getByRole('button', { name: '设置' }).click()
  await expect(page.getByText('操作人昵称（可选）')).toHaveCount(0)
  await page.getByRole('button', { name: '关闭' }).click()
})

test('管理员通过用户管理界面创建 ops 和 member', async ({ page }) => {
  await login(page, 'e2e-admin', adminPassword)
  await page.getByTestId('open-user-management').click()
  await expect(page.getByRole('heading', { name: '用户管理' })).toBeVisible()
  await expect(page.getByTestId('create-user-username')).toHaveAttribute('maxlength', '128')
  const currentAdminRow = page.getByTestId('user-row-e2e-admin')
  await expect(currentAdminRow.getByRole('combobox', { name: 'e2e-admin 角色' })).toBeDisabled()
  await expect(currentAdminRow.getByRole('button', { name: '停用' })).toBeDisabled()

  await page.getByTestId('create-user-username').fill(opsUsername)
  await page.getByTestId('create-user-display-name').fill('E2E 运营')
  await page.getByTestId('create-user-role').selectOption('ops')
  await page.getByTestId('create-user-password').fill(opsInitialPassword)
  await page.getByTestId('create-user-submit').click()
  await expect(page.getByTestId('initial-password-reminder')).toContainText(opsInitialPassword)

  await page.getByTestId('create-user-username').fill(memberUsername)
  await page.getByTestId('create-user-display-name').fill('E2E 成员')
  await page.getByTestId('create-user-role').selectOption('member')
  await page.getByTestId('create-user-password').fill(memberInitialPassword)
  await page.getByTestId('create-user-submit').click()
  await expect(page.getByTestId('initial-password-reminder')).toContainText(memberInitialPassword)
  await expect(page.getByTestId(`user-row-${memberUsername}`)).toContainText('成员')
})

test('member 只能看到自己的项目且无维护入口', async ({ page }) => {
  await login(page, memberUsername, memberInitialPassword)
  await changePassword(page, memberInitialPassword, memberPassword)
  await createProject(page, memberProjectName)

  await expect(page.locator('.project-list .project-item')).toHaveCount(1)
  await expect(page.getByRole('button', { name: memberProjectName })).toBeVisible()
  await expect(page.getByTitle(/删除项目/)).toHaveCount(0)
  await expect(page.getByRole('button', { name: '设置', exact: true })).toHaveCount(0)
  await expect(page.getByTestId('open-user-management')).toHaveCount(0)
  await page.getByRole('button', { name: '术语表', exact: true }).click()
  await expect(page.getByTestId('manual-glossary-tools')).toHaveCount(0)
  await expect(page.getByRole('button', { name: '导入已确认术语', exact: true })).toHaveCount(0)
  await expect(page.getByTestId('open-project-members')).toHaveCount(0)
})

test('ops 建项目并把 member 加入项目', async ({ page, browser }) => {
  await login(page, opsUsername, opsInitialPassword)
  await changePassword(page, opsInitialPassword, opsPassword)
  await createProject(page, opsProjectName)

  let releaseMembersLoad = () => {}
  const membersLoadGate = new Promise<void>((resolve) => { releaseMembersLoad = resolve })
  const membersRoute = '**/api/projects/*/members*'
  await page.route(membersRoute, async (route) => {
    if (route.request().method() === 'GET') await membersLoadGate
    await route.continue()
  })
  await page.getByTestId('open-project-members').click()
  try {
    await expect(page.getByTestId('project-members-loading')).toBeVisible()
    await expect(page.getByText('暂无可添加的 active 用户。')).toHaveCount(0)
    await expect(page.getByText('当前项目还没有成员。')).toHaveCount(0)
  } finally {
    releaseMembersLoad()
  }
  await expect(page.getByTestId('project-members-error')).toHaveCount(0)
  await expect(page.getByTestId('addable-member-select')).toBeEnabled()
  await page.unroute(membersRoute)
  await page.getByTestId('addable-member-select').selectOption({ label: `E2E 成员 (${memberUsername})` })
  await page.getByTestId('add-project-member').click()
  await expect(page.getByTestId(`project-member-${memberUsername}`)).toBeVisible()

  const memberContext = await browser.newContext()
  const memberPage = await memberContext.newPage()
  await login(memberPage, memberUsername, memberPassword)
  await expect(memberPage.getByRole('button', { name: opsProjectName })).toBeVisible()
  await memberContext.close()
})

test('登出后返回登录页', async ({ page }) => {
  await login(page, opsUsername, opsPassword)
  await page.getByRole('button', { name: '退出' }).click()
  await expect(page.getByTestId('login-submit')).toBeVisible()
})

test('管理员修改角色后旧会话失效', async ({ page, browser }) => {
  await login(page, opsUsername, opsPassword)
  await expect(page.getByTestId('current-user-chip')).toContainText('运营')

  const adminContext = await browser.newContext()
  const adminPage = await adminContext.newPage()
  await login(adminPage, 'e2e-admin', adminPassword)
  await adminPage.getByTestId('open-user-management').click()
  await adminPage.getByRole('combobox', { name: `${opsUsername} 角色` }).selectOption('member')
  await expect(adminPage.getByTestId('initial-password-reminder')).toContainText(`账号 ${opsUsername} 已更新。`)

  await page.reload()
  await expect(page.getByTestId('login-submit')).toBeVisible()
  await adminContext.close()
})
