describe('OAuth Flow End-to-End', () => {
  beforeAll(async () => {
    // Start services
    await page.goto('http://localhost:3002');
  });

  it('should complete full OAuth login flow', async () => {
    // Click sign in button
    await page.click('button:has-text("Sign in with Authentik")');

    // Should redirect to Authentik
    await page.waitForURL(/authentik/);

    // Fill in credentials
    await page.fill('input[name="uid_field"]', 'testuser');
    await page.fill('input[name="password"]', 'testpassword');
    await page.click('button[type="submit"]');

    // Should redirect back to dashboard
    await page.waitForURL('http://localhost:3002/');

    // Should see user name in dashboard
    await expect(page.locator('text=Welcome back, testuser')).toBeVisible();

    // Should see dashboard content
    await expect(page.locator('text=Total Jobs')).toBeVisible();
    await expect(page.locator('text=Running Jobs')).toBeVisible();
  });

  it('should persist session after page reload', async () => {
    // Reload page
    await page.reload();

    // Should still be logged in
    await expect(page.locator('text=Welcome back')).toBeVisible();
    await expect(page.locator('text=Sign Out')).toBeVisible();
  });

  it('should logout successfully', async () => {
    // Click sign out
    await page.click('button:has-text("Sign Out")');

    // Should redirect to login
    await page.waitForURL(/login/);
    await expect(page.locator('text=Sign in with Authentik')).toBeVisible();
  });

  it('should not access protected routes when logged out', async () => {
    await page.goto('http://localhost:3002/');

    // Should redirect to login
    await page.waitForURL(/login/);
  });
});
