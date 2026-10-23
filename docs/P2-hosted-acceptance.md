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

Release gates still to record: database backup integrity and additive migration
rehearsal, exact reviewed-file hashes, source installation, normal PythonAnywhere
reload, authenticated live smoke checks and temporary-preview retirement.
These test results alone do not claim deployment or mark roadmap tasks complete.
