# T34 — Collaborative Zines and print publishing (Sandbox)

October 28, 2026 (Pacific). Independent Flask/SQLite/Jinja publication system; no new JavaScript framework. Zines are an independently addressable destination with stable publication and issue IDs. The still-comic and motion tooling also tracked in T34 remains future work.

## User workflow

Open Zines, create a private publication, optionally upload cover artwork, select visibility and enable publication print permission. Owners designate existing eligible editors or contributors by @handle. Create an issue, edit its front/back covers, add/reorder interior pages, and save issue print permission. Contributors save their own submissions and submit them for editorial review; an editor accepts a submission as an interior page or returns it. Publish, read the issue, then open Download / print.

Private publications are restricted to editorial members. Unlisted publications require the link; public publications also appear in the directory after publishing. Existing verified-account, birthday/consent, contact, blocking, muting and moderation eligibility is reevaluated. Private draft pages and PDFs require owner/editor authorization. Contributor access to a workspace does not grant access to another contributor's draft or editorial pages. Role removal/downgrade is immediate.

Published issues remain fixed until returned to draft. Returning to draft revokes public reading/PDF access; saved versions can be copied from the latest 20 editorial snapshots. Atomic revision checks reject stale forms and preserve copyable unsaved text. Multiple page forms require a reload after each save; this initial editor is asynchronous.

## Print implementation

Structured version-1 heading/text/image/caption/layout content is reused in the digital reader and ReportLab renderer. No screenshots, remote URLs, arbitrary HTML, remote stylesheet fetching or server-side user file paths are accepted. Text is escaped in Jinja and PDF paragraphs.

Standard PDF uses portrait Letter or A4 in original reading order. Booklet PDF uses two upright half-letter or A5 pages on a landscape sheet, outside then inside for each sheet. If padded length is N, sheet k uses (N-1-2k,2k) then (2k+1,N-2-2k), zero-based. Blank pages are inserted immediately before the back cover; the front and back covers remain the outer pair. Eight pages produce 8|1, 2|7, 6|3, 4|5. The print page previews the actual arrangement including blanks.

Booklet instructions: actual size, landscape, duplex flip on short edge, one PDF page per printed side, no additional booklet/two-up mode. Standard portrait editions normally use long-edge duplex. Geometry and actual PDF text coordinates are tested; no physical printer test is claimed. Printer feed/driver variations warrant a one-sheet physical check.

On-demand PDFs are in memory only, no persistent rendered copies. A process semaphore rejects concurrent rendering; 8 downloads/user or hashed guest-network/hour. At most 64 pages, 6,000 body characters/page, 8 MiB distinct print image bytes, 12 million decoded image pixels and 32 MiB PDF output. Text overflow or unsupported print-font characters produces an editable error rather than clipping. Optional original page numbers; fixed 30-point margins. Font: system DejaVu Sans, with bundled ReportLab Vera fallback. Complex-script shaping/emoji coverage is not promised.

## Data and storage

Seven additive tables: zines, zine_members, zine_issues, zine_pages, zine_submissions, zine_revisions, zine_assets. No existing content schema is replaced. Owners may create 20 publications, 100 issues/publication, 20 submissions/author/issue. Authored text/submission/history metadata is limited to 4 MiB per publication owner; 20 latest issue snapshots are retained. Files are private managed WebP artwork: 2 MiB input, 512 KiB processed, 64 assets/publication. Existing durable admission, uploader attribution, per-user/aggregate limits and provider headroom apply through the zines namespace. No original image bytes are retained. Retained processed artwork continues counting toward quotas; automatic pruning is not implemented.

Protected image reads use the existing no-follow regular-file reader and verify size/hash. An image is public only when used by an accessible published issue or publication cover associated with such an issue. Own account JSON exports include owned publication metadata, memberships, personally authored pages/submissions and own upload metadata. Existing bounded media ZIP exports include personally attributed Zine artwork, never another uploader's bytes.

## Source and operations

Runtime ReportLab 4.4.5. pypdf 6.1.3 is used only for test inspection. Sandbox runtime dependency files live under _zine_vendor; they are not committed or installed into the shared Production environment. Source requirements documents ReportLab. Deployment must preserve the source hash baseline and back up the SQLite database online immediately before the additive migration; rehearse on a restored snapshot first. Recovery material contains private source/database files and must never enter public Git.

Changed integration surfaces: app registration, base navigation, storage upload namespace, media export namespace, account JSON export, user guide, development log and changelog. New modules: zines_core.py, zines.py, zines_pdf.py; templates/zines.html; static/zines.css; tests/verify_zines_full_app.py.

## Validation

Focused actual-application tests use a disposable online database copy, fictional accounts, separate secret/instance/statistics/upload-ledger paths and disabled SMTP. The initial 258 checks passed; the final 287-check suite adds managed image validation, confidentiality, quota/export attribution, rendered image objects and page-count bounds. PDF checks inspect actual text and coordinates for 4,8,12,16 and 2,3,5,7,9,15 pages, both paper sizes, standard reading order, exact eight-page arrangement, blanks and cover positions. Negative checks cover malformed text/images, oversize input, foreign/path assets, CSRF, stale revisions, editorial escalation, age/block/revocation, unpublished reader/PDF/history and print settings.

Existing Seller Studio, catalog, media/test-order, media export, identity Pages, privacy and recovery regressions are run against the same candidate; final exit codes and deployment status are recorded separately in the release log. Existing test scripts with a T25/T30/T31-specific release-path guard are run with only that guard adapted in memory to the T34 candidate. Their assertions remain unchanged.

## Deferred scope

Real-time coediting; multiple independent blocks/page; crop/bleed/creep, custom margins, grayscale; arbitrary fonts/complex-script layout; member invitations/acceptance and team notifications; Circle/Page associations; audio/MIDI/animation embeds and static alternatives beyond the reserved print_alternative field; physical fulfillment, payment and Marketplace entitlements. Content IDs and structured versioning leave room for these features. No paid access or payment processing is implemented. Existing page removal/archiving and automated artwork cleanup need a deliberate retention design.

Final candidate acceptance: 287 focused checks passed. All eight suite exit codes were zero. Migration rehearsal preserved all 153 original tables, added exactly seven empty tables, passed integrity/foreign-key checks and repeated initialization. Sandbox browser walkthrough and live installation are recorded separately after deployment.

## Hosted installation checkpoint

Installed October 28, 2026 at 20:02 Pacific from initial commit 37a59061d243abc9e733c25ec8e10c3d47c869be. Draft PR #116 targets sandbox/source-checkpoint-20261020. The hosted directory, navigation, creation form and 390px directory layout (no horizontal overflow) were checked. The shared dispatcher required the normal PythonAnywhere Web reload; touching the WSGI file alone did not activate the routes. Production source hashes remained unchanged. New tables remained empty at the checkpoint. The owner browser creation attempt correctly redirected to thirty-minute password/authenticator confirmation before inserting a publication. The final real-browser create/publish/read/download walkthrough awaits that user confirmation; do not mark the feature acceptance complete yet.
