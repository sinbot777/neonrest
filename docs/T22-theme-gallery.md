# T22 — free theme gallery and independent remixes

Prepared October 22, 2026 (Pacific). Not deployed.

The owner selected **independent copies** for remixes. No live inheritance or
upstream changes are applied to installed themes. The existing application
source license is unchanged. The roadmap's accepted MIT direction applies to
explicitly shared theme code, with separate rights for fonts, images and music.

## Workflow

- Public gallery/detail/download routes expose only approved immutable snapshots
  and the contributor's chosen public credit, never account email/profile data.
- Verified, age-ready, active accounts may submit complete T20 style exports.
  No role/tier purchase is required. Sharing requires an unchecked explicit
  acceptance of versioned MIT terms. The actor, full terms, time and hash of
  the submitted style/metadata/credits are recorded atomically.
- Staff with existing `approve_vibes` permission review snapshots under
  `/manage/themes/gallery`, so the existing staff 2FA/fresh-auth surface guards
  apply. Approval needs an explicit review acknowledgement and reason. Every
  submission, decision and withdrawal is audited. Review notes are shown to
  the author and included in that author's account export.
- Public and staff sample previews use the T21 scriptless opaque-origin iframe
  and restrictive CSP. Submitted CSS is never applied to gallery/staff controls.
- Downloads are JSON attachments compatible with T20. Copyright notices and
  the full MIT text are embedded in CSS comments so ordinary editor save,
  import and export preserve them. A target Vibe slug can retarget the exact
  known mode class. Imported styles still require explicit review and Save.
- Remix submissions reference an approved source; the server derives parentage
  and retained credits. They receive their own snapshot, acceptance and review.
  Source withdrawal does not change an already-approved independent remix.
- Authors may withdraw gallery availability. Staff may remove listings. Earlier
  MIT grants and retained notices are not revoked. Snapshots cannot be edited;
  revisions must be submitted and reviewed independently.

The sharing assertion is not proof of asset ownership. Staff review remains
necessary. Existing saved themes are not automatically submitted or relicensed.
No real agreement was accepted and no real gallery entry was created in testing.

## Bounds and persistence

Three additive tables store entries, agreement records and review events; indexes
support status, owner and per-entry audit queries. Public, author and review
lists seek through 20-entry windows. Submissions are limited to five pending or
recent entries per account, with a 128 KiB package bound and per-field limits.
Invalid submissions keep entered text and show a readable error. Account export
includes only that account's gallery data and omits internal actor/owner IDs.

These limits do not establish hosting capacity. T29 storage quotas remain
separate. Agreement/audit retention and anonymization must be included in the
existing retention/erasure activation review before that disabled feature is
ever enabled. This change does not enable permanent erasure or Afterglow.

## Validation and remaining release gates

67 fictional checks exercise actual gallery routes, approval/CSRF/permissions,
account eligibility stubs, private pending entries, immutable snapshots,
versioned acceptance, safe downloads, inherited credits, independent withdrawal,
quotas, seek windows and the actual account-export hook. DOM checks run the
actual rendered gallery and validate attributed downloads through the T20
validator. T19–T21 editor, restoration, transfer, colors and preview regressions
also pass on both source baselines.

Tests use fictional SQLite and explicit identity/age stubs, not full application
sessions. They do not replace hosted privacy/age, staff 2FA/fresh-auth, export,
responsive/keyboard or migration/restore acceptance. Before rollout, take backups,
run disposable-copy full-app integration on both hosted environments, inspect
the real browser UI and perform the normal reload. Edge was unavailable during
preparation. T22 remains unchecked until those gates pass.
