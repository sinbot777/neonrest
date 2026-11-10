# Neonrest release requirements

For every user-interface change, complete the styling review in
[docs/ui-release-checklist.md](docs/ui-release-checklist.md) before calling the
change accepted. Review the actual rendered page, including linked workspace,
management, composer and error views affected by the same template. Passing
component tests alone does not complete visual acceptance. Record any view or
browser/device check that could not be performed as outstanding.

Keep credentials, databases, private deployment configuration and customer
payloads out of GitHub. Preserve unrelated differences between Sandbox and
Production during scoped deployments.
