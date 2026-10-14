# Neonrest v0.8.0 release checkpoint — 2026-10-14

Completed: deployed source baseline; mail worker; five real inbox deliveries and authentication review; completed diagnostic fixture; read-only cleanup retest (11 checks); separate Production confirmation failure messages; owner confirmed Production login; fresh isolated current-source acceptance suites.

Still open: owner Production Vibe-management confirmation; owner recovery/replacement and recovery-code browser acceptance; substantive rights/preservation and guardian-evidence policy review; retention decision (automatic erasure remains disabled); exposed-credential rotation and access-log reconciliation; hosting storage remediation; release branch/layout decision; displayed version and release notes; final deployment acceptance and v0.8.0 tag.

The email-form regression tests use disposable database copies and mocked SMTP. The live password-reset acceptance rendered the received link without setting a usable Production password. Full password changes were tested on disposable copies. This checkpoint does not claim full stable release acceptance.

Live Last.fm source still differs from the sanitized snapshots because its embedded API key is excluded from GitHub. Private runtime data and test receipts are excluded. Main is unchanged.
