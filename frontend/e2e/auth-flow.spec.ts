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
const memberProjectName = `Member Project ${suffix}`
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
