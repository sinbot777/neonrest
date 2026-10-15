# Neonrest v0.8.0

Neonrest is a social platform inspired by older social media, with customizable profiles, Vibes, account security, moderation, privacy and family-request workflows.

Main contains the verified v0.8.0 Production application at the repository root. The package directory should be named neonrest, with its parent on Python's import path. Sandbox source is maintained separately and is not included in this tree.

See [release notes](RELEASE-NOTES-v0.8.0.md), the [release checklist](RELEASE-CHECKLIST-v0.8.0.md) and [privacy workflows](PRIVACY-WORKFLOWS.md). Requirements reflect the recorded release runtime dependencies; configure private deployment state separately. This repository update does not deploy PythonAnywhere.

The annotated v0.8.0 tag preserves the git@github.com:sinbot777/neonrest.gital two-environment release snapshot at cf8b9e9ab952e9738178526056449de13f84e4fb. Production application files here are byte-for-byte identical to that commit's neonrest/ subtree. Repository documentation and dependency metadata describe this Production-only layout.

Databases, user uploads, credentials, private configuration, verification documents, caches and backup archives are excluded. The Last.fm integration reads LASTFM_API_KEY from the environment in this sanitized source. A checkout is not a complete operational backup.

Permanent account erasure and combined automatic retention remain disabled. Document removal and backup rotation remain staff-managed; preservation and legacy-copy reviews are prerequisites to future erasure activation.

License terms are in LICENSE.source-available and LICENSE.themes-only; see COPYRIGHT.md and CLA.md.
