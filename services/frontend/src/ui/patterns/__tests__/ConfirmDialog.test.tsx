import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfirmDialog } from '@/ui/patterns/ConfirmDialog';

const props = {
  title: 'End the running conversation?',
  body: 'Starting a new conversation ends A1B2C3D4.',
  confirmLabel: 'Start anyway',
  cancelLabel: 'Cancel',
};

describe('ConfirmDialog', () => {
  it('renders nothing while closed', () => {
    render(<ConfirmDialog open={false} {...props} onConfirm={vi.fn()} onCancel={vi.fn()} />);
    expect(screen.queryByText(props.title)).not.toBeInTheDocument();
  });

  it('states the question and both answers', () => {
    render(<ConfirmDialog open {...props} onConfirm={vi.fn()} onCancel={vi.fn()} />);

    expect(screen.getByRole('dialog', { name: props.title })).toBeInTheDocument();
    expect(screen.getByText(props.body)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: props.confirmLabel })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: props.cancelLabel })).toBeInTheDocument();
  });

  it('confirms only when the confirming answer is chosen', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open {...props} onConfirm={onConfirm} onCancel={onCancel} />);

    await userEvent.click(screen.getByRole('button', { name: props.confirmLabel }));

    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it('cancels on the cancelling answer', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open {...props} onConfirm={onConfirm} onCancel={onCancel} />);

    await userEvent.click(screen.getByRole('button', { name: props.cancelLabel }));

    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it('cancels on Escape, so dismissing never starts anything', async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<ConfirmDialog open {...props} onConfirm={onConfirm} onCancel={onCancel} />);

    await userEvent.keyboard('{Escape}');

    expect(onCancel).toHaveBeenCalledOnce();
    expect(onConfirm).not.toHaveBeenCalled();
  });
});
