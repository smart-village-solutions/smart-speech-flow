import { useState } from 'react';
import { I18nextProvider } from 'react-i18next';
import { createI18n } from '../../src/i18n';
import { BrandContext } from '../../src/app/providers/brand';
import { ThemeProvider } from '../../src/app/providers/ThemeProvider';
import { AdminHeader } from '../../src/ui/patterns/AdminHeader';
import { ScreenShell } from '../../src/ui/patterns/ScreenShell';
import { Button } from '../../src/ui/primitives/Button';
import { IconButton } from '../../src/ui/primitives/IconButton';
import { TextField } from '../../src/ui/primitives/TextField';
import { Textarea } from '../../src/ui/primitives/Textarea';
import { Checkbox } from '../../src/ui/primitives/Checkbox';
import { StatusChip } from '../../src/ui/primitives/StatusChip';
import { InlineAlert } from '../../src/ui/patterns/InlineAlert';
import { EmptyState } from '../../src/ui/patterns/EmptyState';
import { StarRating } from '../../src/ui/patterns/StarRating';
import { ScaleInput } from '../../src/ui/patterns/ScaleInput';
import { CodeInput } from '../../src/ui/patterns/CodeInput';
import { ConfirmDialog } from '../../src/ui/patterns/ConfirmDialog';

const params = new URLSearchParams(location.search);
const locale = params.get('dir') === 'rtl' ? 'ar' : 'en';
const i18n = createI18n(locale);
document.documentElement.dir = locale === 'ar' ? 'rtl' : 'ltr';
document.documentElement.dataset.brand = 'kassel';
const noop = () => undefined;

export function Preview() {
  const [checked, setChecked] = useState(false);
  const [rating, setRating] = useState<number | null>(null);
  const [score, setScore] = useState<number | null>(null);
  const [code, setCode] = useState('');
  const [open, setOpen] = useState(false);
  const [actions, setActions] = useState(0);
  return (
    <I18nextProvider i18n={i18n}>
      <BrandContext.Provider
        value={{
          brand: 'kassel',
          displayName: 'KasselDIALOG',
          legal: { imprintUrl: null, privacyPolicyUrl: null, accessibilityStatementUrl: null },
          toggleBrand: noop,
        }}
      >
        <ThemeProvider initialTheme={params.get('theme') === 'dark' ? 'dark' : 'light'}>
          <ScreenShell className="gap-6 px-5 pb-10 pt-content-top">
            <AdminHeader
              onBack={noop}
              onHome={noop}
              onFeedback={noop}
              onSignOut={noop}
              accountUrl="https://example.invalid/account"
            />
            <h1 className="text-title font-bold">KasselDIALOG component gallery</h1>
            <p data-testid="default-copy">
              Shared controls, feedback patterns and their real states.
            </p>
            <output aria-label="Action count">{actions}</output>
            <div className="flex flex-wrap items-center gap-6">
              {(['small', 'medium', 'large'] as const).map((size) => (
                <IconButton
                  key={size}
                  size={size}
                  label={`${size} action`}
                  onClick={() => setActions((n) => n + 1)}
                >
                  <span aria-hidden>+</span>
                </IconButton>
              ))}
              <IconButton label="Selected action" aria-pressed>
                <span aria-hidden>+</span>
              </IconButton>
              <IconButton label="Disabled action" disabled>
                <span aria-hidden>+</span>
              </IconButton>
            </div>
            <TextField
              label="Default field"
              defaultValue="Alex Example"
              data-testid="field-default"
            />
            <TextField
              label="Compact field"
              density="compact"
              defaultValue="Alex Example"
              data-testid="field-compact"
            />
            <TextField
              label="Invalid field"
              error="Please check the value."
              data-testid="field-error"
            />
            <TextField label="Disabled field" disabled />
            <Textarea aria-label="Plain message" rows={3} placeholder="Enter a message" />
            <Textarea
              variant="field"
              aria-label="Field message"
              rows={3}
              placeholder="Enter a message"
            />
            <Textarea
              variant="field"
              aria-label="Invalid message"
              aria-invalid
              defaultValue="Please check this message"
            />
            <Textarea
              variant="field"
              aria-label="Disabled message"
              disabled
              defaultValue="Unavailable"
            />
            <Checkbox checked={checked} onCheckedChange={setChecked}>
              Agree to saving this conversation
            </Checkbox>
            <CodeInput value={code} onChange={setCode} />
            <div className="flex flex-wrap gap-3">
              {(['neutral', 'success', 'warning', 'danger'] as const).map((tone) => (
                <StatusChip key={tone} tone={tone}>
                  {tone} status
                </StatusChip>
              ))}
            </div>
            {(['neutral', 'success', 'warning', 'danger'] as const).map((tone) => (
              <InlineAlert key={tone} tone={tone} role="note" title={`${tone} notice`}>
                Readable details and next steps.
              </InlineAlert>
            ))}
            <EmptyState
              title="No conversations"
              description="Start a conversation to see it here."
              action={
                <Button
                  variant="compact"
                  className="bg-accent text-accent-on"
                  onClick={() => setActions((n) => n + 1)}
                >
                  Start conversation
                </Button>
              }
            />
            <fieldset>
              <legend className="text-label font-medium">Rating</legend>
              <StarRating min={1} max={5} value={rating} onChange={setRating} />
            </fieldset>
            <fieldset>
              <legend className="text-label font-medium">Recommendation</legend>
              <ScaleInput
                min={0}
                max={10}
                value={score}
                onChange={setScore}
                minLabel="Unlikely"
                maxLabel="Very likely"
              />
            </fieldset>
            <Button className="bg-accent text-accent-on" onClick={() => setOpen(true)}>
              Open dialog
            </Button>
            <Button variant="sheet" disabled className="bg-accent text-accent-on">
              Disabled sheet
            </Button>
            <ConfirmDialog
              open={open}
              title="End conversation?"
              body="The dialog uses the same typography and controls."
              confirmLabel="End"
              cancelLabel="Cancel"
              onConfirm={() => setOpen(false)}
              onCancel={() => setOpen(false)}
            />
          </ScreenShell>
        </ThemeProvider>
      </BrandContext.Provider>
    </I18nextProvider>
  );
}
