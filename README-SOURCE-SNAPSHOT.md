# Neonrest deployed source baseline

Captured from PythonAnywhere on October 14, 2026, before repairing the authenticator enrollment 403. This dedicated snapshot branch contains the actual current `neonrest_sandbox/` and `neonrest/` packages independently. It is not an instruction to deploy or merge the snapshot into either running site. Existing repository branches and history are preserved. The package-folder layout preserves their different import namespaces, URL prefixes and configuration defaults.

Application modules, routes, templates, application assets, available tests and notices are included. Database contents, user uploads, private consent evidence, private configuration, credentials, recovery codes, sessions, mail state, caches, archive backups and abandoned patch/smoke scripts are excluded. Never publish real runtime state or credentials.

The two `utils/lastfm.py` copies deliberately replace the deployed hard-coded API key with `LASTFM_API_KEY` environment access. This is an export-only redaction; live code and credentials were not changed. Source and exported hashes and the redaction exception are recorded in SOURCE-MANIFEST.json. Configure required private state before using a disposable checkout. RUNTIME-DEPENDENCIES.json records the relevant installed package versions; the deployed requirements files are captured as-is.

Known issue at this checkpoint: Account safety sets Referrer-Policy to no-referrer while the global POST guard rejects a null Origin. Real-browser 2FA enable has been reported as Forbidden. The repair belongs in a subsequent commit and requires isolated confirmation, CSRF/origin, recent-authorization, replay/recovery and account-preservation verification.

Earlier completed work captured by these packages includes profile/media styling and controls, nearby-age and parent safeguards, birthday clocks, verification/recovery/email changes, moderation and staff roles, opaque public IDs, persistent Sandbox mail, retention and operations safeguards, policy acceptance, selected Production import feature code and authenticator QR enrollment. Actual account/profile/DOB/content imports are private database data and are excluded. Full Production launch acceptance remains open.

## Follow-up: authenticator form repair deployed

The subsequent fix changes Account safety's Referrer-Policy to same-origin in both packages, retaining the existing CSRF and strict Origin guards. Both previous 403 cases were reproduced with valid disposable codes before the change. After the repair, 80 QR/origin checks and 142 account-lifecycle checks passed; live verification and preserved account/factor fingerprints are recorded privately, with only non-sensitive code hashes and check results in FIX-VERIFICATION.json. No real credentials or enabled factors were changed. Refresh Account safety and complete your own enrollment privately. The pre-fix SOURCE-MANIFEST.json remains a historical capture record.
