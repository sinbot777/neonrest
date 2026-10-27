# Provider headroom includes account-owned temporary storage

Upload admission counts the account home tree plus entries owned by the current UID under `/tmp` and `/var/tmp`. Shared parent allocations and other users' entries are excluded. One device/inode set prevents double charging directory aliases and hardlinks across roots. Symlinks are counted as links and never traversed.

The existing bounded scan applies across all roots. Missing shared roots, permission errors on owned data and incomplete scans deny admission through the existing recoverable upload-busy response. Temporary entries disappearing during traversal are ignored; the home-tree scan remains strict.

The provider reserve, personal and shared attachment allowances, pending-reservation accounting and upload locks are unchanged. This inventory reads metadata only and does not remove temporary data.

Validation: nine filesystem tests cover ownership, aliases, hardlinks, symlinks, nested temporary trees, disappearing entries, denied scans, the shared traversal budget and a capacity boundary where the earlier home-only measurement would admit an upload. Both isolated applications also pass the existing 42-assertion storage route suite.
