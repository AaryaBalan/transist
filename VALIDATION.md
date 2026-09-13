# Validation — selectable cleanup window and file opening

## Completed

- **31 Python tests passed:** all seven cleanup windows, changing existing timers,
  pause/resume, persistence, restoration, collision handling, recovery deadlines,
  permanent files, screenshot capture, crash reconciliation, installer, and CLI settings.
- **7 JavaScript tests passed:** active/history actions, search, recovery cutoff,
  literal filenames, time labels, all seven restore labels, and integration source checks.
- Python compilation and JavaScript module syntax checks passed.
- Local GJS introspection confirmed ComboRow, StringList, and accessible-label APIs.
- Archive integrity checks passed.

The installer test simulates an upgrade from the old desktop app. It verifies
that the old launcher and GUI sources are removed, the headless command works
without PyGObject, and user files/history survive upgrade and uninstall.

## Not verified in this environment

The native preferences window has **not been launched or visually verified** for
this update. Opening files in their default applications still needs a live check.
JavaScript tests cover presentation
logic and source invariants, not actual GTK widget behavior. The systemd operations
are mocked in installer tests. GitHub CI has not been run.

## Live checks before publishing

- Close the old app, install this update, and log out/in. Confirm the Transist
  application-menu entry disappears and only the GNOME extension UI remains.
- Open preferences through GNOME Extensions, the Shell menu, and
  `gnome-extensions prefs transist@aaryabalan.local`.
- Confirm Active Files, Recently Deleted, and Settings appear in a single window.
- Change GNOME's system appearance between light and dark. Verify native controls
  and text; no Transist-specific stylesheet or palette should override it.
- Test search, no-results state, long/unusual filenames, keyboard navigation,
  narrow windows, and Show more with over 100 entries.
- Select each cleanup window (1, 5, 12, 24, 48, 72 hours, 1 week). Confirm countdowns
  and restore labels update, the selection survives reopening, and shorter windows
  apply to elapsed time without resetting timers.
- Exercise pin/unpin and restore with disposable samples. Confirm a new timer using
  the selected window and no overwrite when a filename already exists.
- Click the eye icon on temporary and permanent files, including spaces, Unicode,
  and special characters in filenames. Confirm the correct default app opens;
  unavailable files or missing app associations should show an error toast.
- Test capture toggle, folder apply, pause, service status, and error messages.
  Periodic refresh must not overwrite a folder edit that has not been applied.
- Close preferences during an operation and reopen. Confirm the operation completes
  or is safely reconciled; no repeated polling remains after the window closes.
- Confirm cleanup continues when preferences close or the Shell icon is disabled.
- Test missing/stopped service and recovery after reinstall/restart.
- Recheck each declared GNOME version before advertising compatibility.
