## Deployment review and guarded rollback completed

The copied retention defaults were corrected to Production-only consent and backup roots and covered by two environment tests. Corrected candidate passed 43 privacy tests, 17 baseline application checks, 24 intake/notice/restore checks, 40 QR checks, 63 authenticator replacement checks and 62 recovery-form checks. The replacement test's obsolete error-text assertion was updated and failed-code side-effect checks strengthened; authentication implementation stayed unchanged.

The 26-check rollback drill preserved post-migration data/holds, invalidated copied grants and paused older privacy tools/signup through a tested maintenance guard. A fresh private database checkpoint passed integrity verification; media was inventoried, not copied. See PRIVACY-DEPLOYMENT-REVIEW.md for scope, limitations, exact procedures and the Production child-app wrapper. Live Production and erasure activation remain unchanged; this branch is not a deployment.

# Privacy Production candidate - not deployed

This branch prepares reviewed privacy requests, preservation and private verification submission against the actual deployed Production source. Only source, templates, safe fixture tests and this record are exported. Runtime databases, source backup copies, document files, keys and invitation receipts are excluded. The existing Sandbox source stays on its separate branch.

The isolated candidate passed 43 privacy regression tests, 17 baseline full-application privacy checks and 24 intake/notice/signup/restore checks. Test application writes were confined to copies, and SMTP was disabled. Original user, post, comment, family-link, case and evidence rows in the copied Production database were checked unchanged after migration and the synthetic tests. Existing policy acceptance records were preserved; new signup uses the existing Production Terms version and proposed October 14 Production privacy version.

The candidate keeps permanent erasure and the combined retention job disabled. It does not close preserved Sandbox cases or authorize disposal. Live Production source and databases were not replaced. The read-only retention inventory on the parent branch records the legacy snapshot fingerprint mismatch and separate legacy/provider copy review.

Before deployment: confirm environment-specific source/WSGI/database/media/backup roots, capture and verify a current rollback point, rehearse migration rollback and the permission/security regressions affected by these changes, and review the exact source diff. The current tests establish privacy integration readiness, not final v0.8.0 acceptance. Document and backup cleanup remain operator tasks. Public routing, secure-cookie/authentication isolation, real owner staff controls and notice rendering need post-deployment acceptance.
