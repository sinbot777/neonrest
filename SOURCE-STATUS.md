# T16 Production source update — October 21, 2026 (Pacific)

This update ports only the reviewed T16 following and private friend-label changes from Sandbox PR #39, preserving Production-specific code and configuration. Sandbox source is not merged into main. Production and Sandbox were tested with separate database copies. Runtime data, uploaded media and credentials are excluded. No new release tag is declared.

# Source status — October 20, 2026 (Pacific)

Production source was compared against main after PR #37 (1527402652e9ecd2bad01521222f22f6bd9cca90). All present tracked application files match, except the local Last.fm credential assignment; the repository retains environment-variable configuration instead of a deployed credential. Repository-only licensing, README and test files are retained.

The public development log and CHANGELOG record the latest pagination, video, deletion return, stress testing, storage housekeeping and resource-failure recovery work. No release tag is moved or newly declared.

Sandbox is independently checkpointed on sandbox/source-checkpoint-20261020. It retains Afterglow and its own package prefixes, templates and behavior. This branch is a source checkpoint, not a proposal to merge Sandbox into Production. Features recorded as Production-only in the logs must not be inferred to exist in Sandbox.

Exports exclude databases, uploaded media, private records, deployment secrets, caches and rollback archives. The Last.fm source assignment is normalized to LASTFM_API_KEY in the environment. Production runtime configuration is unchanged by this documentation sync. Earlier release branches and tags retain their history.
