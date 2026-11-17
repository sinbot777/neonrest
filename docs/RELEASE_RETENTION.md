# Release artifact retention

This guide describes how to organize development and release artifacts so superseded builds do not become permanent hosting dependencies. It does not authorize deletion or deployment, and does not claim that a particular environment has been cleaned.

## What belongs in Git

Commit application source, fictional regression fixtures, tests, dependency pins, upstream license notices, build tools and deployment instructions. Record the source commit or pull request associated with a release.

Keep credentials, actual user data, database snapshots, uploaded artwork, private configuration and private repository history out of public commits. Preserve necessary private material in an access-controlled backup. Review source snapshots for sensitive content before publication; an untracked file or a missing public commit is not by itself a reason to publish it.

## Keep a release inventory

Each release should have a small manifest covering:

- Purpose and source commit.
- Intended environment and current deployment status.
- Artifact checksums and build dependencies.
- Validation results, including which candidate was tested.
- An access-controlled reference to its backup.
- Whether it is current, superseded, retained for recovery or eligible for retirement.

Keep private inventory fields in private storage. Publish only the fields appropriate for the repository's audience.

## Preserve before retiring

A public source commit does not replace a backup of private data, media, configuration or runtime dependencies. Back up the necessary material before removing its server-side copies.

Verify transfer success and archive readability. Compare the offsite copy's checksum with the recorded checksum before relying on it for cleanup. Record the verification method accurately: archive listing, checksum comparison and restore rehearsal provide different evidence. A local checksum alone does not prove the uploaded copy matches.

Use consistent database backup methods for live databases. Do not restore historical databases over new user activity as a routine source rollback.

## Check dependencies

Before retiring a directory, check application configuration, static mappings, symlinks, imported modules, environment configuration, scheduled services and Git alternate-object dependencies.

Separate runtime dependencies from historical test-fixture references. Preserve or relocate fixtures that remain necessary instead of retaining entire obsolete application copies solely for those tests.

Archive symlinks as links unless a deliberate, documented backup design requires following them. Do not traverse links into live media or unrelated storage accidentally.

## Remove in scoped batches

Start with verified, superseded standalone packages, redundant recovery archives and regenerable build output. Keep the current reviewed release package, deployment instructions, validation records and required rollback material until their retention purpose ends.

List exact paths for each proposed batch. Obtain authorization for the concrete deletion operation. Do not turn approval for selected files into recursive deletion of their parent directories.

Check allocated blocks and hardlink counts before estimating savings. Independently measured directory sizes can overlap; removing one hardlink does not free the shared file's blocks while other links remain.

Record what was actually removed, actual reclaimed space and any remaining dependencies. Label incomplete inspections as incomplete rather than treating them as deletion clearance.

## Deployment is a separate step

Storage cleanup does not imply release approval. Before deployment, recheck available space against the complete deployment budget, preserve the upload reserve, take fresh consistent backups and verify source/configuration hashes.

Keep build, validation, publication and deployment states explicit. Superseded staging copies should have a documented retirement decision rather than an indefinite unknown status.
