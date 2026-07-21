import { expect, test } from '@playwright/test'

const expectedProfile = process.env.LWS_EXPECT_RUNTIME_PROFILE

test('extracted runtime matches its declared profile and UI boundary', async ({ page, request }) => {
  test.skip(!expectedProfile, 'LWS_EXPECT_RUNTIME_PROFILE is only set by extracted-package smoke jobs')
  expect(['local-off', 'cloud-required']).toContain(expectedProfile)

  const expected = expectedProfile === 'local-off'
    ? { deployment_mode: 'local', auth_mode: 'off', runtime_profile: 'local-off' }
    : { deployment_mode: 'cloud', auth_mode: 'required', runtime_profile: 'cloud-required' }
  const versionResponse = await request.get('/api/version')
  expect(versionResponse.ok()).toBe(true)
  expect(await versionResponse.json()).toMatchObject(expected)

  const anonymousProjects = await request.get('/api/projects')
  if (expectedProfile === 'local-off') {
    expect(anonymousProjects.ok()).toBe(true)
    await page.goto('/')
    await expect(page.getByTestId('login-submit')).toHaveCount(0)
    await expect(page.getByTestId('show-register')).toHaveCount(0)
    await expect(page.getByRole('button', { name: '设置', exact: true })).toBeVisible()
    return
  }

  expect(anonymousProjects.status()).toBe(401)
  const username = process.env.LWS_RUNTIME_SMOKE_USER
  const password = process.env.LWS_RUNTIME_SMOKE_PASSWORD
  expect(username, 'LWS_RUNTIME_SMOKE_USER is required for cloud-required smoke').toBeTruthy()
  expect(password, 'LWS_RUNTIME_SMOKE_PASSWORD is required for cloud-required smoke').toBeTruthy()

  await page.goto('/')
  await expect(page.getByTestId('login-submit')).toBeVisible()
  await expect(page.getByTestId('show-register')).toBeVisible()
  await page.getByTestId('login-username').fill(username!)
  await page.getByTestId('login-password').fill(password!)
  await page.getByTestId('login-submit').click()
  await expect(page.getByTestId('current-user-chip')).toBeVisible()
  await expect(page.getByRole('button', { name: '设置', exact: true })).toHaveCount(0)
})
