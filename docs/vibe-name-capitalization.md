# Vibe name capitalization — October 22, 2026 (Pacific)

Vibe names capitalize their first alphabetic character while preserving subsequent spelling. New tags resolve to existing Vibes before creation, so case variants reuse the same ID.

Existing names can be updated with `python scripts/capitalize_vibe_names.py /path/to/database.db`. The idempotent migration backs up the database and updates only Vibe names. IDs, post associations, themes, CSS slugs, and existing links remain intact.

Vibe pages already use case-insensitive name lookup. Regression checks cover lower, upper, and canonical URLs, duplicate tag reuse, and existing onboarding/pagination behavior.

Run `python tests/verify_vibe_case.py neonrest /home/sinbot/neonrest`, using matching Sandbox arguments for Sandbox. The suite uses disposable database copies and forbids outgoing email.

