# T23 — Vibe logos, gentle motion and optional background MIDI

Prepared October 23, 2026 (Pacific). Not deployed.

## Behavior

Scoped Vibe editors use `/manage/vibes/<slug>/atmosphere`, linked from Theme
Studio. This stays under the existing management 2FA/fresh-auth surface and
uses the existing Vibe settings permission. Day and Night can select separate
existing local static PNG, JPEG or still WebP assets. Empty falls back to the
shared Vibe logo. Paths are normalized, confined to the static directory and
validated as still images up to 2 MiB and 4096 pixels per side. This does not
add arbitrary remote logo loading or a new logo upload pipeline.

Optional CSS motion is Still, Gentle movement or Gentle glow. The default is
Still. Device reduced-motion, a visitor's logo-animation Off preference, or
GIF “Don’t play automatically” suppresses it. Visitors can pause/resume permitted
animation; hidden pages pause motion. CSS also disables it under reduced motion
when JavaScript is unavailable. This supports motion on still logos, not new
animated-image formats.

Vibe music uploads use the existing real Standard MIDI validator: 256 KiB and
10-minute bounds. The existing MIDI widget/player handles it alongside posts
and profiles, honoring each visitor's MIDI autoplay preference. Default remains
click-to-play, and only one MIDI plays at a time. No new autoplay preference is
silently enabled, no looping is added, and no sound/font player dependency is
introduced. Browser sound activation still applies.

Tracks are newly uploaded Vibe-owned public assets, not references to existing
private post/profile media. A separate serving route checks the exact Vibe/file
binding and approved, active Vibe state on every request. Pending, archived,
unlinked or mismatched tracks return 404. Mode logos/music are not included in
T22 style licenses or gallery exports; their asset rights remain separate.

## Persistence and failure behavior

Two additive tables store Vibe atmosphere and visitor motion preferences.
Revision checks reject stale concurrent edits. Only a successfully created new
upload is eligible for failure cleanup; filename collisions preserve the
pre-existing file. DB errors and partial storage-write failures roll back state
and remove the failed operation's own new file. Replacement/removal unlinks old
tracks from serving without deleting their bytes. Reviewed retention/quota work
remains T29; these bounds do not establish hosting capacity.

Account export includes the visitor's motion preference and Vibe settings last
saved by that account, excluding other editors' records. Existing theme style
and shared identity storage is unchanged. No real asset, preference or agreement
was modified during preparation.

## Validation and remaining acceptance

47 fictional checks exercise actual routes, real image/MIDI validation, scoped
permission stubs, CSRF, normalized variants, active/pending/archive media access,
private-file isolation, stale revisions, DB failure, simulated storage-full
cleanup, collision safety, replacement/removal, preferences, actual account
export and template bindings. Actual logo-widget DOM tests cover pause/resume,
live device changes, visitor/GIF preferences and hidden-page behavior. Tests of
the real MIDI widget/player cover default silence, explicit Play, existing
autoplay opt-in and no repeated attempts after browser-blocked sound. The Vibe
track's template binding is isolated so it cannot replace a later post's URL.
T19–T22 editor/gallery/transfer/preview regressions also pass.

Fixtures stub identity and permission dependencies and simulate the audio
context. Before rollout, run hosted disposable-copy full-app privacy/staff-auth,
media and export regressions; verify migration/restore, real MIDI sound, Day/Night
and narrow layouts in the browser; then perform backed-up installation and the
normal reload. Edge availability must be rechecked for that work. No live source
or database was changed; T23 remains unchecked pending these gates. Permanent
erasure remains disabled and Afterglow remains Sandbox-only.
