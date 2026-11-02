# Verifying an Archived Conversation

How an employee has a recorded conversation's translation checked by a
qualified reviewer, and what the reviewer and the readers see (#619). Studio
manages who may review: the `ssf.recording.review` permission, sworn status
(`ssf.recording.review.sworn`) and each reviewer's languages.

## Requesting a verification (employee)

1. Unlock your archive key and open the conversation in the archive.
2. Choose **Request verification**. You need a fresh second-factor sign-in.
   SSF sends you to sign in again if yours is older than a few minutes.
3. Pick a reviewer. By default the list shows only reviewers who cover every
   language of the conversation. Tick **Show all reviewers** to see the rest.
   Sworn reviewers carry a badge.
4. Compare the reviewer's fingerprint with them by phone, then choose
   **Assign**. Your browser encrypts every part of the conversation for that
   reviewer. Nobody else gains access.

Several reviewers may check the same conversation. A reviewer who declines, or
loses the permission, is shown as *Declined* or *Withdrawn*. Assign someone
else.

The button is missing when part of the conversation is not open to you, for
example parts recorded before you set up your key. Recover those parts first
(key recovery).

A supervisor who recovered a conversation through exceptional access can
request a verification the same way.

## Reviewing (reviewer)

1. Open **Reviews** from the user menu and unlock your key.
2. Open an assignment. You see every message with its original audio and
   speech recognition, the raw and refined machine translation, the final text
   and the translated audio, plus pauses, failed messages and amendments.
3. Choose **Start review**. **Decline** returns the assignment, before or
   during the review.
4. Add findings to any message: a category, a description and an optional
   correction. Add an overall note. **Save draft** stores your notes encrypted.
   They are also saved when you leave the screen. If you close the tab with
   unsaved notes, the browser asks first.
5. Choose **Decide**, pick *Approved* or *Not approved*, and submit. Your browser
   signs the decision with your key, and SSF timestamps it. The decision cannot
   be changed, and your access to the conversation ends with it.

You never see another reviewer's verdict. Entries added after you started, for
example a later amendment, are marked and are not part of your review.

## Reading results (employee, recovering supervisor)

- The archive list and the conversation header show a summary: *Not verified*,
  *In review* while any assignment is open, or the outcomes ("1 approved,
  1 not approved").
- The **Verification** card lists each record, with reviewer, sworn status,
  times and outcome. The overall note sits under it.
- Each message shows every reviewer's findings side by side.
- Before showing a decision, your browser checks that it is intact: the
  signature matches the reviewer key stored with the record, and the record
  belongs to the exact conversation version that was reviewed. A record that
  fails the check shows only a warning, never its content.
- The decision's timestamp is shown, but the timestamp authority's own
  signature is not checked yet.

## Security notes

- A reviewer who kept an encrypted copy while they had access can still read
  that copy later. Removing access stops future access only.
- The list of reviewers leaves out supervisors who recovered, or are
  recovering, the conversation. Someone who knows all reviewers could infer a
  recovery from that.
- The check on a decision detects damaged or mismatched records. It does not
  prove who the reviewer was: SSF stores the reviewer's key next to the record,
  so someone in control of the SSF server could replace both. Only the phone
  comparison of the fingerprint at assignment ties a key to a person.
- A nightly check removes access from reviewers and supervisors who lost their
  Studio permission (see the operations runbook `recording-revocation.md`).
