# T30 — Media export policy and packaging

Decision date: October 27, 2026 (Pacific). Owner approved inclusion of uploaded media. This completes the policy/design task; the current `/account/export` route still returns JSON only. Media archive implementation and deployment are separate acceptance work.

## Included files and privacy boundary

An account export includes every existing file personally uploaded by the requesting account, across all file types and site areas: avatars, post attachments, GIF/MIDI and other supported media, Page/Circle artwork, theme/gallery uploads and privately submitted documents. Include available retained originals and derivatives, deduplicated by file identity with all eligible source references in the manifest. The boundary is the actual uploader, not who owns the destination Page/Circle today. Include the account's own attributable upload even when its post is private, a listing is archived or Circle membership ended. Do not reconstruct deleted/expired files or fetch remote embeds. Upload attribution does not establish copyright or grant new reuse rights.

A privately submitted document personally uploaded by this user is included as their original submission; do not append staff review notes, another person's documents or the internal evidence bundle built around it. The export is private and freshly authenticated, and warns that the download may contain sensitive documents. A specific applicable legal restriction can require withholding/review, with an appropriate manifest explanation; a retention hold alone is not an automatic reason to deny the uploader a copy.

Exclude other members' uploads, incoming shared-post media uploaded by someone else, remote links, staff-created evidence/notes, backups, generated system records, credentials, authentication secrets, internal storage paths and provider secrets. Purchased creator products use their separate order entitlement rather than upload ownership. Unattributed legacy files require review, never a guess from filename, current Page owner or timestamps. Missing files are clearly recorded where safe, not silently treated as included.

Each candidate is checked against authoritative upload/account attribution and any specific release restriction. The manifest distinguishes included, missing, unattributed and restricted items using non-sensitive reasons. Restricted items must not leak names or references the requester is not entitled to learn. An all-or-nothing failure is not silently reported as a complete export.

## Package and access contract

Keep the existing JSON export available; add an explicit 'Include my uploaded media' option. POST requires authenticated owner, CSRF and fresh reauthentication. A background job builds a ZIP with `account.json`, `manifest.json`, `README.txt` and generated relative names under `media/`. Manifest records source record/public reference where permitted, export-relative filename, MIME type, byte count and SHA-256. Generate paths independently of user-provided filenames; reject traversal, symlinks, unexpected roots and non-regular files. Copy files safely while checking size/hash consistency; abort or clearly mark a changed file rather than packaging a different person's replacement. Never write ZIP members from absolute paths.

Archives are private, outside public/static directories. A download requires the same currently authenticated owner and rechecks active account/access restrictions. The opaque expiring handle is not bearer authorization on its own. Ready archives expire after 24 hours; status and download responses use no-store and download disposition. Logout/session revocation prevents use of an old download link. Passwords, TOTP, recovery codes, SMTP/provider secrets and unrelated recipient data must not enter the archive.

Use one active job per account, bounded queue/concurrency, measured bytes and available temporary-space checks preserving the existing provider reserve. Do not bypass T29 accounting by storing large duplicate archives indefinitely. Initial operational limit: 64 MiB of source media per package, one worker, no more than two ready packages site-wide; reconsider only after headroom measurements. Exceeding the bound gives a clear response and a future paged/package option, not a partial archive labeled complete. Generated archive bytes count toward provider use; original upload allowances are unchanged. Failures clean only the job's temporary files and preserve uploads/JSON export. No automatic account/content erasure is enabled. Expired archive cleanup must be audited and scoped to generated export artifacts.

## Required acceptance before enabling media ZIPs

- Owner/fresh-auth/CSRF checks, cross-account job/status/download denial and expired/revoked-session denial.
- Every supported personally uploaded file type included, including private documents and own Circle/Page/theme uploads; another person's guestbook/shared/Circle/Page upload excluded; legacy unknown ownership reviewed.
- Own private-document originals included without staff/evidence additions; specifically restricted files explained; nested secrets excluded from JSON and archive metadata.
- Traversal, symlink, duplicate name, hostile filename, file replacement and missing-file cases.
- Package byte limits, provider reserve, full disk, interruption, concurrent jobs, failure cleanup and retry behavior.
- Deterministic manifest validation, SHA-256 round trip and ZIP extraction on Windows; Unicode filenames in metadata.
- Existing JSON export, privacy/account regressions, disposable database tests, private rollback and exact-source rollout in both environments.

Implementation sequence: audit existing JSON fields and upload attribution; build bounded packaging worker and authenticated delivery; add explicit UI; test and deploy. Do not call the policy checkmark a live media-export feature.
