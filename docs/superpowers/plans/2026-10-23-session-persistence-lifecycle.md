# Session Persistence and Lifecycle Plan

**Goal:** Keep session-owned data discoverable across app restarts and working-directory changes; support one-click archive and unarchive.

**Architecture:** Anchor default runtime paths to the project directory while honoring caller-supplied paths. Keep SQLite metadata and local file stores; add the archived-to-active transition and expose it in the archived view.

**Tech Stack:** Python, SQLite, Streamlit, pytest.

## Tasks

1. Test default store paths against working-directory changes.
2. Test unarchive, continued messaging, and one-click UI behavior.
3. Anchor defaults and implement unarchive.
4. Run focused and full tests; inspect the diff without disturbing existing changes.
