# T29: storage admission and growth checkpoint

October 25, 2026 (Pacific). **Foundation draft; no live limits enabled.**

## Implemented foundation

`storage_reservations.py` supplies explicit, durable upload reservations using a
separate SQLite connection/database. Importing the module creates no database,
changes no application configuration and registers no routes.

Admissions use `BEGIN IMMEDIATE` so competing workers cannot each claim the
same allowance. Both per-owner and shared aggregate limits include retained
objects plus all pending and started reservations. Prefix owners by environment
and identity type: Production user 1 and Sandbox user 1 are different owners.
Both apps must use the same provisioned ledger for a genuinely shared budget.
Limits are positive configurable byte values; tests use tiny fictional limits.
No production allowance is selected or enabled by this draft.

Reserve the complete hard output bound before any temporary file or derivative
is written. Mark the reservation started before writing. Application adapters
must enforce this bound while writing: the ledger cannot stop an unwrapped
filesystem write. Settle every retained image, poster, loop, MIDI or partial
output using opaque stable object keys and the exact charged bytes. Settlement
is atomic and idempotent only for the identical output manifest. Oversize,
colliding or wrong-owner settlements retain the original reservation charge.

A crash does not expire a reservation. An untouched reservation can be released;
a started one requires output reconciliation. Deleting a post, replacing an
avatar, losing a page role or retiring a media reference does not independently
release a physical-storage charge. Old bytes may remain for restoration or
evidence. This draft has no automatic physical-deletion or inventory-decrement
API. Operator reconciliation must be serialized against uploads and confirm
physical state and preservation obligations before freeing any allowance.

`storage_inventory.py` provides a read-only seed inventory. It rejects overlapping
roots, refuses symlinks and unsafe partial scans, counts hard-linked bytes once,
and retains all aliases for review. Unknown or conflicting ownership remains
explicitly unattributed and still consumes the aggregate allowance. Charged
inventory bytes use the greater of logical and allocated bytes. Application
adapters must use the same charging basis for new outputs and temporary files.
Inventory and database references must be captured consistently while uploads
are paused/serialized; a directory scan alone is not a migration lock.

This is a **media budget**, not the provider's full home-directory quota. Code,
databases, journals, email queues, evidence and backups also consume space.
Keep a separately measured provider headroom reserve and deny uploads when that
reserve is unavailable. `statvfs` alone cannot establish a user hosting quota.

## Validation completed

17 reservation tests pass, including eight actual competing processes against
one SQLite file (only three 30-byte requests admitted into a 100-byte budget),
restart persistence, crash retention, aggregate/per-owner boundaries, ownership,
duplicate keys, failed-settlement rollback, safe retry and a changed limit.
Nine filesystem-inventory tests pass, including hardlinks, unknown/conflicting
owners, file/directory/root symlinks, overlaps, missing roots and bounded scans.
Python compilation passes. These 26 tests use disposable local fixtures only;
they do not establish full application integration or hosting capacity.

## Next implementation and acceptance

1. Build reviewed ownership maps from both databases for post media, profile MIDI,
   avatars, legacy post images, Circle icons/covers and Vibe MIDI. Include retained and
   unreferenced physical bytes conservatively. Circle/page ownership transfers
   require a stable accounting owner policy; do not reset usage on transfer.
2. Connect bounded output writers and graceful upload-limit responses to every
   supported upload path, including all derivatives and temporary files. Keep
   consent/evidence submission budgets distinct so an ordinary media limit
   does not silently prevent a required safety submission.
3. Add private staff visibility and account-facing usage/help, without exposing
   filenames, other accounts' usage or provider paths. Choose launch allowances
   from measured capacity and keep upgrade headroom configurable.
4. Rehearse seeding/restoration and crash/ENOSPC/SQLite BUSY/FULL cases using
   disposable copies of each real application baseline. Ensure failed uploads
   preserve text, previous media and app transactions. No live fixtures required.
5. Review retention coverage by release/database/media/evidence set. Keep at
   least the current verified recovery set and predecessor, retain unresolved
   preservation obligations, and treat deletion of any unique copy as a separate
   exact review. No pruning is authorized or scheduled by this document.
6. Deploy only after complete integration and review, with private verified
   backups, independent source baselines and normal application reload.

## Subsequent queue checked

- T48 remains draft PR #55. GitHub reports it conflicts with current `main`.
  Reconcile against the current deletion fixes, then run real-app privacy,
  signed-cursor, inline-edit and deep-reply rendering checks before rollout.
- Ordinary-account privacy and actual-device/audio/reduced-motion acceptance
  remain open. Desktop emulation is not evidence of physical phone/audio output.
- Afterglow remains Sandbox-only. Sandbox retains `messaging.py`, its compact
  window template and focused tests. Review recipient controls, age/block gates,
  retention/export, presence, delivery expectations and the separate mobile-app
  scope before a Production rollout decision. No messaging switch was changed.

## October 26 integration candidate

The ordinary-media integration now routes avatars, legacy post images, still
images, all three GIF derivatives, post/profile MIDI, Circle icons/covers and
Vibe MIDI through bounded encoding and a shared reservation adapter. Combined
post image/MIDI uploads validate and encode every attachment before admission.
Incoming multipart files remain memory-backed within the existing 26 MiB total
request bound; they do not create unreserved hosting-disk spool files.

`storage_writers.py` provides exclusive, owner-only output creation. It refuses
existing files and symlink destinations, reserves the whole output batch, fsyncs
successful writes and settles logical/allocated byte usage. Certain complete
failure cleanup settles an empty manifest; failed or uncertain cleanup retains
the reservation for review. Avatar replacements use new opaque names, preserving
old bytes and references if an upload fails. Removing an application reference
never decrements the ledger automatically.

`storage_uploads.py` uses environment-prefixed personal-account owners. New
Circle and Vibe artwork remains charged to the uploader after a role/ownership
change. Its cross-app lock prevents an inventory/headroom check from racing
another controlled upload. The account-wide allocation scan includes code,
databases, backups, symlinks and directories, deduplicates inodes, and fails
closed if incomplete. It is a conservative local allocation estimate, not a
provider capacity guarantee. The provider quota and separate headroom are
explicitly configured. The read-only October 26 scan took about 4.8 seconds;
this is upload-path overhead, not ordinary-page latency or capacity acceptance.

Private `/account/storage` displays only the signed-in account's accounted
usage. `/manage/storage` requires the existing Site Operations permission and
fresh password/second-factor confirmation, and displays aggregate, unattributed
and outstanding usage without filenames or other accounts' detail. Both pages
use private/no-store responses. Consent and case documents retain their separate
submission rules and do not consume an ordinary attachment allowance.

`storage_ownership.py` attributes existing bytes only from matching internal
avatar, post-media, profile-MIDI and legacy-image references. Unknown, conflicting,
external and wrong-environment references do not gain arbitrary owners. Existing
Circle/Vibe artwork with unknown original uploaders remains unattributed and
still consumes shared space. A provisional, read-only inventory found 21 physical
objects and 12,427,264 charged bytes; 3,616,768 bytes were unattributed. Four
currently absent empty storage roots remain explicit until the paused final
scan. These are dated provisional observations, not an activated seed.

### Activation and recovery boundary

- Policies are operator-provisioned, owner-only private JSON. There is no
  automatic ledger creation, expiry, reset, pruning or silent fallback from a
  configured ledger failure. A disposable DB/instance cannot inherit the live
  ledger even when regressions run after activation.
- Deployment must first install the tested adapter in both environments with
  `ready: false` and normally reload, so ordinary upload creation is paused.
  Create missing roots, serialize the final DB-reference/physical inventory,
  provision and verify the shared ledger, then switch to `ready: true` and reload.
  A resumed app must use the same protected ledger and environment namespace.
- Proposed conservative launch configuration is 16 MiB per personal account,
  24 MiB shared ordinary-media budget and 32 MiB provider headroom. Existing bytes
  are retained even if over an allowance; growth is denied. Per-file limits do
  not promise that every file fits the currently available shared/account budget.
- Back up source, policy, application DBs and accounting state as a reviewed set.
  Rehearse ledger seed idempotence, SQLite integrity and restart/restore with an
  outstanding reservation. Never restore an older ledger into a running service:
  pause uploads and reconcile all physical outputs first, including unmatched
  files from the interval after the backup. Application-DB rollback alone must
  not rewind independent storage accounting.
- The stored object key is a stable environment/root/filename key. Seed and new
  writers use the same namespace. Any later reclaim requires actual filesystem
  and preservation review, including hard-linked backups and protected copies;
  deleting a post or losing a delegate role is insufficient evidence.

Hosted candidate checks currently pass 31 real-app assertions per environment,
covering auth/privacy, incoming spool behavior, accountable ownership, grouped
GIFs, invalid second attachments, avatar preservation, quota/headroom denial,
lock contention, uncertain scans, ledger BUSY and ENOSPC handling. The independent
foundation/writer/ownership suites total 39 checks. Final related regressions,
seed/restore rehearsal, rendered UI review and live activation remain required.
Hosted audio/video, downloadable-media policy and object-storage migration remain
separate unfinished T29 scope. Afterglow remains shelved.
