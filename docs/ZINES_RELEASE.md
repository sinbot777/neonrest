# Zines release candidate

Zines adds collaborative publications, reader single/spread/scroll views, Standard/Custom/Advanced composition tools, artwork, bounded linked stories, named frame styles, master elements, issue sizes, snapshots, sharing previews, and reading/booklet/mini-eight PDFs. Screen atmospheres remain separate from document design and print. Clicking the composition canvas explicitly focuses it for keyboard movement; changed assets have a new cache version. Reader controls use opaque ground-colored surfaces so patterns cannot cross their text; black/white surround ink is selected by relative luminance. Presets and 256 gray backgrounds are checked against a 4.5:1 text contrast minimum.

Private/public/unlisted access, contributor/owner/editor permissions, account eligibility, age/contact restrictions, blocks/mutes, CSRF, revisions, upload quotas and private artwork checks remain in force. Managed master/style edits must be updated at the source or detached. Saved layouts and preferences are isolated between Sandbox and Production.

## Candidate status

This is a review candidate, not a Production deployment. The host candidate passed 470 actual-app acceptance checks against disposable copies, plus appearance, folding, page size, sharing, authoring and release-guard suites. Authenticated desktop/mobile visual acceptance remains open because the connected local browser is unavailable. The reconciled source also passed 470 actual-app checks in the patched runtime, and the application security suite passed 245 checks. Its stale deletion redirect test now uses real disposable SQLite. All ten isolated runtime packages returned no matching OSV advisories in this check.

## Dependencies

Install the existing app requirements and `requirements-zines-release.txt` into a separate candidate environment, then test the entire application before replacing the shared Production environment. The installed older Pillow, Flask and Jinja2 versions had published advisories; the candidate pins patched versions. ReportLab 4.4.5 matches the official wheel and had no matching OSV advisory at this check. Preserve ReportLab's BSD notice in `THIRD_PARTY_NOTICES/reportlab-4.4.5.txt`; upstream fonts retain their own notices. Installing official distributions preserves their license metadata. This adds no new license to Neonrest itself.

The `_zine_vendor` fallback is optional when ReportLab is installed normally. Do not point Production at a temporary test directory. Keep the existing DejaVu system fonts available for PDF rendering.

## Tests

Component checks: run `python test_authoring.py`, `python test_sharing.py`, and `python test_readiness.py` from the package root with Flask, Pillow, ReportLab and pypdf available. Identity, age and CSRF adapters in the component fixture are fictional and do not replace actual-app authorization acceptance.

Host full-app check: `python tests/verify_zines_full_app.py neonrest /home/sinbot/releases/T34-REVIEW/neonrest`. It requires a staged package under a T34 release directory. The bootstrap reads the real database through a read-only SQLite connection and backs it up to a temporary database, redirects mail/instance/secrets/statistics, prohibits SMTP, and writes only fixture data. Never run this against the live source path or change the safety assertions to make it run there. `tests/zines_host_bootstrap.py` contains the isolated setup, without unrelated statistics acceptance tests.

## Deployment and rollback

Before deployment, finish signed-in desktop/mobile and keyboard checks, confirm storage headroom, take SQLite-consistent backups of the Production database and upload ledger, record deployed source/runtime hashes, and verify no concurrent changes. Review this candidate without merging unrelated Sandbox differences.

Install reviewed source and the tested dependency environment, run additive initialization once, reload, and perform controlled smoke checks. New Zines tables are initially empty; do not copy Sandbox users, artwork or tutorial data into Production as a schema migration.

On source rollback, restore the previous source and environment while preserving new Zines tables and media. Do not restore an old database over new user work. Patch apply/reversal was tested in a disposable source copy; final live smoke checks remain a deployment step.

## Known feature limits

Linked stories reflow on save and support plain text only. Named styles cover whole-frame typography; masters are issue-scoped elements rather than full master pages. Recovery is browser-local plus explicit server saves and 20 retained issue snapshots. Professional typography, live flow, drawing/effects, CMYK/PDF-X, tagged PDF, comments/suggestions and live coediting remain future work. Existing inline artwork, two-up reading, booklet and mini-eight folding are implemented.
