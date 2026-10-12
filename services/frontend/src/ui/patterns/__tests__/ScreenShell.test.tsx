import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ScreenShell } from '@/ui/patterns/ScreenShell';

function shell(keyboardOpen?: boolean) {
  const { container } = render(
    <ScreenShell keyboardOpen={keyboardOpen}>
      <p>content</p>
    </ScreenShell>
  );
  return container.firstElementChild as HTMLElement;
}

describe('ScreenShell', () => {
  it('compacts the header for everything inside while the keyboard is open', () => {
    const root = shell(true);

    expect(root).toHaveAttribute('data-keyboard', 'open');
    expect(root).toHaveClass('group/shell');
    expect(root.style.getPropertyValue('--spacing-header')).toBe('var(--spacing-header-compact)');
    expect(root.style.getPropertyValue('--spacing-content-top')).toBe(
      'var(--spacing-content-top-compact)'
    );
  });

  it('leaves the header tokens alone otherwise', () => {
    const root = shell();

    expect(root).not.toHaveAttribute('data-keyboard');
    expect(root.style.getPropertyValue('--spacing-header')).toBe('');
  });
});
