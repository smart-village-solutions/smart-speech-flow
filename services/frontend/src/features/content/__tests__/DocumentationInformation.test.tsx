import { screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { DocumentationInformation } from '@/features/content/DocumentationInformation';
import { renderWithProviders } from '@/test/renderWithProviders';
import { CATALOGUES } from '@/i18n';

const information = {
  locale: 'de-DE',
  version: 'test-version',
  sections: ['mode2Consent', 'guestRecordingRelease'].map((id) => ({
    id,
    headline: 'SSF',
    bodyHtml: '<p>Test wording</p>',
  })),
};

describe('documentation wording completeness', () => {
  const emptyBodies = [
    '<p><br></p>',
    '<p>&nbsp;</p>',
    '<p><strong> </strong><em><br></em></p>',
    '<script>hidden text</script>',
    '<style>hidden text</style>',
    '<iframe>hidden text</iframe><svg><text>hidden text</text></svg>',
    '<!-- hidden text --><img alt="hidden text" src="/example.png">',
    '<p><script>hidden text</script>&nbsp;</p>',
  ];
  it.each(['mode2Consent', 'guestRecordingRelease'])(
    'requires visible sanitized body text for %s',
    (id) => {
      for (const bodyHtml of emptyBodies) {
        const { unmount } = renderWithProviders(
          <DocumentationInformation
            information={{
              ...information,
              sections: information.sections.map((section) =>
                section.id === id ? { ...section, bodyHtml } : section
              ),
            }}
          />
        );
        expect(screen.queryByRole('region'), bodyHtml).not.toBeInTheDocument();
        unmount();
      }
    }
  );
  it.each(['mode2Consent', 'guestRecordingRelease'])('requires a nonblank %s headline', (id) => {
    renderWithProviders(
      <DocumentationInformation
        information={{
          ...information,
          sections: information.sections.map((section) =>
            section.id === id ? { ...section, headline: ' \u00a0 ' } : section
          ),
        }}
      />
    );
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });
  it('accepts visible text in unwrapped elements and safe formatting', () => {
    renderWithProviders(
      <DocumentationInformation
        information={{
          ...information,
          sections: information.sections.map((section) => ({
            ...section,
            bodyHtml: '<div><strong>Visible wording</strong></div><script>hidden text</script>',
          })),
        }}
      />
    );
    expect(within(screen.getByRole('region')).getAllByText('Visible wording')).toHaveLength(2);
    expect(screen.queryByText('hidden text')).not.toBeInTheDocument();
  });
});

it.each([
  ['ar-SA', 'rtl'],
  ['fa-IR', 'rtl'],
  ['de-DE', 'ltr'],
])('sets source direction for %s even when its heading starts with SSF', (locale, direction) => {
  renderWithProviders(
    <DocumentationInformation
      information={{
        ...information,
        locale,
        sections: information.sections.map((section) => ({
          ...section,
          bodyHtml: '<p>نص الاختبار</p>',
        })),
      }}
    />,
    { locale: 'en' }
  );
  const region = screen.getByRole('region');
  const wording = within(region).getAllByText('نص الاختبار')[0].closest('[lang]');
  expect(wording).toHaveAttribute('lang', locale);
  expect(wording).toHaveAttribute('dir', direction);
  expect(wording).not.toContainElement(
    within(region).getByText(CATALOGUES.en.legal.informationNotice)
  );
  expect(region).not.toHaveAttribute('lang');
  expect(region).not.toHaveAttribute('dir');
});
