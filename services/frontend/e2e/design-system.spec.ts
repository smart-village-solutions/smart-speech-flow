import { expect, test } from '@playwright/test';
import contract from '../design-system.contract.json' with { type: 'json' };

for (const theme of ['light', 'dark'] as const) {
  test(`${theme}: runtime tokens match the Figma contract`, async ({ page }) => {
    await page.goto(`/design-system.html?theme=${theme}`);
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const account = page.getByRole('button', { name: 'User account', exact: true });
    await account.focus();
    await expect(account).toHaveCSS('outline-color', 'rgb(29, 83, 139)');
    await account.click();
    await page.keyboard.press('Tab');
    const accountLink = page.getByRole('link', { name: /Account settings/ });
    await expect(accountLink).toBeFocused();
    await expect(accountLink).toHaveCSS(
      'outline-color',
      theme === 'light' ? 'rgb(29, 83, 139)' : 'rgb(121, 184, 246)'
    );
    await account.click();
    const mismatches = await page.evaluate(
      ({ tokens, theme }) => {
        const probe = document.createElement('span');
        document.body.append(probe);
        const failures: string[] = [];
        for (const token of tokens) {
          if (!getComputedStyle(probe).getPropertyValue(token.css).trim()) {
            failures.push(`${token.css}: missing variable`);
            continue;
          }
          const values = token.values as Record<string, unknown>;
          const expected = values[theme] ?? values.default;
          if (token.type === 'COLOR') {
            probe.style.color = `var(${token.css})`;
            const color = getComputedStyle(probe).color;
            const channels = color.match(/[\d.]+/g)?.map(Number) ?? [];
            const rgba = expected as { r: number; g: number; b: number; a: number };
            const want = [rgba.r * 255, rgba.g * 255, rgba.b * 255, rgba.a];
            if (channels.length === 3) channels.push(1);
            if (
              channels.length !== 4 ||
              channels.some((n, i) => Math.abs(n - want[i]) > (i === 3 ? 1 / 255 : 1))
            )
              failures.push(`${token.css}: ${color}`);
          } else {
            probe.style.width = `var(${token.css})`;
            const actual = parseFloat(getComputedStyle(probe).width);
            const wanted = Number(expected);
            if (
              !Number.isFinite(actual) ||
              !Number.isFinite(wanted) ||
              Math.abs(actual - wanted) > 0.02
            )
              failures.push(token.css);
          }
        }
        probe.remove();
        return failures;
      },
      { tokens: contract.tokens, theme }
    );
    expect(mismatches).toEqual([]);
    const contrasts = await page.evaluate(() => {
      const probe = document.createElement('span');
      document.body.append(probe);
      function luminance(css: string) {
        probe.style.color = `var(${css})`;
        const channels = getComputedStyle(probe)
          .color.match(/[\d.]+/g)!
          .map(Number);
        const alpha = channels[3] ?? 1;
        // Field surfaces are translucent and render over the page surface.
        probe.style.color = 'var(--surface-page)';
        const page = getComputedStyle(probe)
          .color.match(/[\d.]+/g)!
          .slice(0, 3)
          .map(Number);
        const rgb = channels.slice(0, 3).map((n, i) => n * alpha + page[i] * (1 - alpha));
        return rgb
          .map((n) => n / 255)
          .map((n) => (n <= 0.04045 ? n / 12.92 : ((n + 0.055) / 1.055) ** 2.4))
          .reduce((sum, n, i) => sum + n * [0.2126, 0.7152, 0.0722][i], 0);
      }
      const pairs: [string, string, number][] = [
        ['--fg-muted', '--surface-page', 4.5],
        ['--fg-muted', '--surface-card', 4.5],
        ['--fg-placeholder', '--surface-field', 4.5],
        ['--fg-success', '--surface-success', 4.5],
        ['--fg-warning', '--surface-warning', 4.5],
        ['--fg-status-alert', '--surface-alert', 4.5],
        ['--border-field', '--surface-field', 3],
      ];
      const result = pairs.map(([fg, bg, minimum]) => {
        const a = luminance(fg),
          b = luminance(bg);
        return { fg, bg, minimum, ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05) };
      });
      probe.remove();
      return result;
    });
    for (const pair of contrasts)
      expect(pair.ratio, `${pair.fg} on ${pair.bg}`).toBeGreaterThanOrEqual(pair.minimum);
  });
}

for (const theme of ['light', 'dark'])
  for (const width of [320, 390, 800])
    for (const dir of ['ltr', 'rtl']) {
      test(`${theme} ${width}px ${dir}: shared controls and states`, async ({ page }) => {
        await page.setViewportSize({ width, height: 950 });
        await page.goto(`/design-system.html?theme=${theme}&dir=${dir}`);
        await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
        await expect(page.getByTestId('default-copy')).toHaveCSS('font-size', '16px');
        await expect(page.getByTestId('default-copy')).toHaveCSS('font-family', /Inter/);

        const field = page.getByTestId('field-default');
        const compact = page.getByTestId('field-compact');
        await expect(field).toHaveCSS('height', '46px');
        await expect(compact).toHaveCSS('height', '42px');
        await expect(field).toHaveCSS('line-height', '24px');
        await expect(field.locator('..')).toHaveCSS('gap', '6px');
        await expect(page.getByLabel('Disabled field', { exact: true })).toBeDisabled();
        await expect(page.getByLabel('Disabled field', { exact: true })).toHaveCSS(
          'opacity',
          '0.5'
        );
        await expect(page.getByRole('button', { name: 'Disabled sheet' })).toHaveCSS(
          'opacity',
          '0.4'
        );

        const invalid = page.getByTestId('field-error');
        await invalid.focus();
        await expect(invalid).toHaveCSS('outline-width', '2px');
        await expect(invalid).toHaveCSS(
          'border-top-color',
          theme === 'light' ? 'rgb(180, 35, 24)' : 'rgb(253, 162, 155)'
        );
        await expect(invalid).toHaveAccessibleDescription('Please check the value.');
        const textarea = page.getByRole('textbox', { name: 'Field message', exact: true });
        await textarea.focus();
        await expect(textarea).toHaveCSS('outline-width', '2px');
        await expect(textarea).toHaveCSS('line-height', '25.6px');
        await expect(page.getByRole('textbox', { name: 'Disabled message' })).toBeDisabled();

        const checkbox = page.getByRole('checkbox');
        await checkbox.focus();
        await expect(checkbox.locator('+ span')).toHaveCSS('outline-width', '2px');
        await page.keyboard.press('Space');
        await expect(checkbox).toBeChecked();

        const small = page.getByRole('button', { name: 'small action', exact: true });
        await small.scrollIntoViewIfNeeded();
        const rect = await small.boundingBox();
        if (!rect) throw new Error('Small action has no hit area');
        // Outside the visible 32px circle, inside its 44px pseudo-element hit area.
        await page.mouse.click(dir === 'ltr' ? rect.x - 4 : rect.x + rect.width + 4, rect.y + 16);
        await expect(page.getByLabel('Action count')).toHaveText('1');
        await expect(page.getByRole('button', { name: 'Selected action' })).toHaveAttribute(
          'aria-pressed',
          'true'
        );

        for (const group of ['Rating', 'Recommendation']) {
          const buttons = page.getByRole('group', { name: group, exact: true }).getByRole('button');
          await expect(buttons.first()).toHaveCSS('width', '44px');
          await expect(buttons.first()).toHaveCSS('height', '44px');
          await buttons.first().click();
          await expect(buttons.first()).toHaveAttribute('aria-pressed', 'true');
        }

        await page.getByRole('button', { name: 'Open dialog', exact: true }).click();
        const dialog = page.getByRole('dialog');
        await expect(dialog).toHaveCSS('font-family', /Inter/);
        await page.keyboard.press('Escape');
        await expect(dialog).not.toBeVisible();
        await page.getByRole('button', { name: 'Open rating dialog', exact: true }).click();
        const ratingDialog = page.getByRole('dialog', { name: 'Rating feedback' });
        await page.keyboard.press('Tab');
        expect(
          await ratingDialog.evaluate((node) => node.closest('[data-screen-shell]'))
        ).toBeNull();
        for (const group of ['Portal rating', 'Portal recommendation']) {
          const option = ratingDialog
            .getByRole('group', { name: group, exact: true })
            .getByRole('button')
            .nth(1);
          await option.focus();
          await expect(option).toHaveCSS('outline-width', '2px');
          await expect(option).toHaveCSS(
            'outline-color',
            theme === 'light' ? 'rgb(29, 83, 139)' : 'rgb(121, 184, 246)'
          );
          await page.keyboard.press('Space');
          await expect(option).toHaveAttribute('aria-pressed', 'true');
        }
        await page.keyboard.press('Escape');
        await expect(ratingDialog).not.toBeVisible();
        await expect
          .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth))
          .toBe(true);
      });
    }
