# Private verification documents and retention — Sandbox operating rules

Effective Sandbox version: 2026-10-14. Production promotion is separate. These are Neonrest operating choices, not fixed statutory minimums. They implement a limited-purpose collection and documented retention process; they do not reopen under-13 signup or activate account erasure.

## Responsibility and collection

The operator and staff with `manage_roles` permission own the request and review queue. Check new and stalled requests promptly, and review document-removal eligibility and managed-backup rotation at least weekly. An unresolved request must receive a documented decision rather than remaining open indefinitely simply to retain its documents.

Ask only for evidence necessary for the particular request. Explain what is needed and why; allow unrelated fields and identification numbers to be redacted when unnecessary. A document, family link or upload invitation alone does not establish current parental authority or justify disclosing every account record. Record the review result and evidence reference without copying raw identity details into notes. Never ask for passwords, authenticator secrets or recovery codes.

## Invite-only submission

Use **Privacy requests → Private verification documents**. Record the request first, including the original receipt time and safe reply method. Confirm the intended recipient/channel, explain the limited evidence required, and generate a one-file invitation. Share its full URL privately with the instructions. No account is required and this screen sends no email.

Invitations expire after 24 hours, accept one PDF/PNG/JPEG up to 5 MiB and are invalidated when replaced or revoked. Closed/declined requests cannot upload. Keep the invitation out of public notes and AI prompts. Its secret is carried in the URL fragment, removed from the browser address after loading, and submitted only in the protected form body. Only a hash is stored in the database. No third-party resources load on the upload page.

Documents are stored encrypted outside public/static directories. Private folders and keys use restrictive permissions. Images are decoded and re-encoded; uploaded filenames are not used for storage. Downloads require authorized staff, recent authentication, intact encrypted content and matching content fingerprints. They are attachments with private-cache and browser security headers. PDF acceptance is not a malware-free certification; use normal safe document-handling practices on staff devices.

Possession of an invitation permits only submission. It grants no login, document retrieval, guardian status, export access or right to change another account. Staff separately review identity, authority, disclosure and any applicable restrictions.

## Retention targets and preservation

| Item | Rule |
|---|---|
| New raw privacy-request documents | Eligible for staff-confirmed removal 30 days after document review and final request/appeal resolution, with later related hold releases extending the window. An unresolved request, unreviewed document, pending appeal or preservation blocker prevents removal. |
| Request and review records | 90-day target after final request/appeal resolution. Unremoved associated documents and preservation requirements prevent cleanup. Old appeal dates do not shorten the period following a later appeal decision. |
| Invitation database records | Eligible seven days after expiry, subject to preservation/cleanup controls. Independent hashed use/revocation receipts remain outside database restores; never replace them with an older ledger. |
| Managed rolling database backups | 30-day rotation target, retaining a verified usable restore point and exceptions for preservation. Rotate only the managed backup set, not arbitrary release/rollback/legacy folders. |
| Legacy signed family-consent evidence | Separate existing relationship/consent review and any explicit schedule. New submission rules do not silently shorten retention of ongoing consent evidence. |
| Moderation evidence and documented holds | Preserve while a specific issue/obligation remains unresolved. Review holds at their recorded dates. Finalize applicable cases/appeals and release separate manual holds explicitly. No silent expiry or automatic moderation-evidence erasure. |

Document removal is staff-confirmed with a typed confirmation and fresh authorization. Recheck eligibility and holds immediately before file removal. A durable purge-intent record supports retry/recovery if file I/O fails; a purging or removed file cannot be downloaded. Keep the minimal review/removal audit record. Do not store raw submissions in routine source exports or database backup bundles, or casually copy them into email, AI services or ordinary workstation backups. Protect and dispose of authorized local working copies under the same purpose/hold rules.

The existing combined retention job and permanent account erasure remain disabled. The metadata planner reflects the 90-day final-resolution rule, but automatic cleanup is not promised. Document removal and managed-backup rotation are operator tasks. Review due items weekly and record any preservation exception and next review. Do not use the combined `--apply` routine as a shortcut: it can include account erasure and requires its own separate activation/review.

## Encryption keys, backups and restores

Keep a separately secured recovery copy of the document key. It is stored outside the document directory and is not part of ordinary source/database exports. Do not publish it, paste it into chat or restore an older key over the current key. Missing keys fail closed; the application refuses to create a new key over existing document files. Retain a key while its protected documents need to remain readable.

Routine database backup files contain request metadata, grant hashes and possibly reviewed export snapshots, not new raw document files or their encryption key. Treat them as private. Preserve held evidence separately before deciding whether a routine snapshot can rotate; do not delete a held copy merely because it is 30 days old. Hosting-provider snapshots, old archives and operator downloads need their own inventory and retention review; do not claim that application rotation removes those copies.

For any restore:

1. Keep the restored copy offline. Do not immediately replace the live database or open traffic.
2. Preserve current encryption keys and independent invitation receipts. Never restore an old receipt ledger over the current one.
3. Reconcile preservation holds, final case dispositions, deletion decisions, document removals and other changes made after the backup. Confirm the private-file inventory and applicable keys. Missing or purged files must not be resurrected from an old archive.
4. Run current additive migrations and the privacy restore preflight against the **offline copy**, with the operator's decisions/files checks completed. It invalidates restored upload invitations, export grants, sessions and email recovery/change/verification tokens. The CLI refuses the configured live database.
5. Check database integrity, grant rejection, document access, preservation and removed-file behavior. Existing mail-worker restore safeguards and independent delivery ledgers remain necessary to avoid resending old mail.
6. Promote only the reviewed, sanitized copy through the normal deployment process, with rollback coverage. This procedure does not authorize automatic restoration, production deployment or account erasure.

Operator command, only during an actual offline-copy restore from the PythonAnywhere Bash console with the project import path configured:

```bash
python3.13 -m flask --app neonrest_sandbox.app privacy-restore-preflight --restored-database /ABSOLUTE/PATH/offline-restored.db --decisions-reconciled --files-checked
```

The flags attest that the checks were performed; they do not perform those human reviews. Do not run the command against the current live DB or check flags merely to get past a requirement.

## Basis and scope

The FTC recommends collecting only necessary information and documenting its protection, retention and disposal. Neonrest's 30/90/30-day operating choices are not periods prescribed by that guidance. Specific obligations and preservation needs can require a different documented result.

Source: [FTC, Protecting Personal Information: A Guide for Business](https://www.ftc.gov/business-guidance/resources/protecting-personal-information-guide-business), sections “Scale down,” “Lock it” and “Pitch it.”
