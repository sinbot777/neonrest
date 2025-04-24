# Changelog

## [0.4.2] – 2025-04-21
### Added
- Support for guestbook-style posts on user profiles
- Author attribution block including avatar, handle, codename, and timestamp
- Visual styling for guestbook posts authored *to others* when shown on your own profile

### Fixed
- Posts previously excluded or misattributed due to missing `target_user_id` logic are now visible
- Markdown content rendering restored on `/user_test/<id>` view
- Top 9 Friends sorting and drag-and-drop saving now working reliably via Sortable.js

### UI / Styling
- Posts authored to other users now show with `.guestbook-outbound` styling (subtle highlight and indentation)
- Top 9 grid supports placeholder states and empty slots for drag assignment
# Changelog
