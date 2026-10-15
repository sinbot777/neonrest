# Neonrest v0.8.1

Security maintenance for Production and Sandbox, October 15, 2026 (Pacific).

- Upgrade Flask to 3.1.3, Pillow to 12.3.0, cryptography to 50.0.2 and Requests to 2.33.1; record the complete tested environment in requirements-lock.txt. Use a dedicated Python 3.13 application environment instead of changing the hosting platform's shared libraries.
- Replace eight browser-referrer redirects with server-generated Feed or Friends destinations.
- Bound opaque-ID matching to the existing 16-character identifier format, retaining at least one ASCII letter, and replace regex-based CSS comment removal with a forward parser that rejects unfinished comments.
- Replace client-side URL navigation in the Vibe picker with a GET form. The server selects only an authorized Vibe and a supported mode, then generates the editor URL.
- Bring Production's dev log up to date with Sandbox and apply its readable page width to both logs.

Validation uses disposable databases and private synthetic state: 244 security checks per environment, plus authenticator replacement, recovery-origin, confirmation-feedback, privacy workflows, private document intake, environment boundaries and full application privacy smoke suites. No real authentication factors or secrets are changed by those suites. GitHub scanning results are verified separately; no alert is dismissed solely to reduce the count.

Permanent erasure remains disabled. Production-only main layout is retained, and the annotated v0.8.0 tag remains unchanged. A code rollback restores the backed-up files; an environment rollback clears the Web virtualenv setting and restores worker commands, without restoring a database or private keys.
