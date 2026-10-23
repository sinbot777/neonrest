# T19–T23 hosted acceptance — 2026-10-23

The combined candidate was tested with the actual installed Flask app and
dependencies in both Production and Sandbox source layouts, using disposable
SQLite backups, media directories and statistics sidecars. SMTP and external
network access were forbidden in fixture processes. No real account, agreement,
post, Vibe setting, date of birth or media preference was changed by these tests.

Each environment passed 52 full-app checks covering scoped editor permissions,
staff second-factor and fresh-auth gates, independent Day/Night saves and saved
restoration, gallery submission/review/privacy/download/remix/withdrawal, teen
credit aliases, media validation and private-file isolation, stale revisions,
account exports, and complete template rendering. The same checks passed again
after the final template corrections.

All 14 legacy regression-suite runs passed: Vibe management, reading tools,
Circle appearance, onboarding/discovery, resource recovery, network security,
and Vibe URL case handling in each environment. The test harness explicitly
redirected the prefixed statistics configuration to its temporary directory.

Edge checks on scrubbed fictional rendered pages verified Studio Undo, Redo,
Discard and its isolated unsaved preview, gallery attribution and isolated
preview, unchecked sharing acceptance, phone-width form layout, logo pause,
default-silent MIDI and explicit Play/Stop status transitions. A narrow-screen
overflow in gallery/atmosphere forms was fixed with a scoped shared layout.
Duplicate script markup in the Studio title was removed and its rendered title
is covered by the editor DOM check. No real sharing agreement was accepted.

Audio device output is subjective and is not certified by browser status alone.
Device/reduced-motion changes and audio-blocked behavior also have fixture DOM
and mocked-audio coverage. The unchanged existing MIDI player is reused.

Deployment complete: Production merged through 4940fd8de44d9b99a429e049c1320a782fc60b79 and Sandbox through c622271b52d90ffcfa0c47596678a0a44f93ca5f. All 41 installed files per app match the merged Git blobs. Fresh source and online database backups preceded the five-table additive initialization. Migration was idempotent and disposable restores matched every original row across 119 Production and 124 Sandbox tables. The actual Web reload completed. Both galleries and case-insensitive Day/Night Vibe routes pass live checks; Sandbox submission and media-preference screens render under the ordinary test account. Production Studio correctly demands fresh owner authentication, which is left for the owner; no credential or factor was bypassed. New tables remain empty, and only routine active_sessions/mail_worker_health records differ from pre-install backups. Public fixture previews were retired. Final CodeQL and both language analyses pass with no new alerts after safe_join plus resolved-path validation; 49 atmosphere checks per baseline include absolute-path and outside-static symlink rejection.
