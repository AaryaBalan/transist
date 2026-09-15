<p align="center">
  <img src="assets/transit.svg" alt="Transit logo" width="120">
</p>

<div align="center">
<h1>Transit</h1>

**A simple GNOME extension for files you only need temporarily.**

Transit gives you a private `~/_transit` folder. Put temporary files there,
choose how long they should stay, and let Transit clean them up automatically.
Deleted files are kept in Transit recovery storage for seven days, so you can
restore them when needed.

</div>

## Screenshots

### Active files

See your files, search by filename, open a file, make it permanent, or restore
its temporary status.

![Transit Active Files](assets/transit-active.png)

### Recently Deleted

Open **Recently Deleted** to see files that have been automatically removed and
are still within the recovery period.

![Transit Recently Deleted](assets/transit-history.png)

### Settings

Choose the cleanup time, configure screenshots, pause cleanup, and view folder
safety information.

![Transit Settings](assets/transit-settings.png)

## Features

- Choose a cleanup time of **1, 5, 12, 24, 48, or 72 hours, or 1 week**.
- Files are automatically removed when their selected time ends.
- Removed files can be recovered for **seven days**.
- Restored files receive a new timer using your current cleanup setting.
- Mark individual files as permanent so they never expire.
- Search active files and recently removed files.
- Save GNOME screenshots directly into `_transit` or import screenshots from another folder.
- Pause automatic cleanup whenever you need to keep working in the folder.
- GNOME Files helps prevent accidental deletion of the whole `_transit` folder.

## How It Works

1. Open Transit preferences and choose a cleanup time in **Settings**.
2. Click **Open Folder** and place a file directly inside `~/_transit`.
3. Transit starts the timer when it notices the file.
4. When the timer ends, the file is moved out of the visible folder into Transit's private recovery storage.
5. The file appears in **Recently Deleted** and can be restored for seven days.
6. Restoring a file returns it to `_transit` with a fresh timer.
7. After seven days, its recovery copy is permanently removed.

The folder is intended for regular files placed directly inside `_transit`.
Subfolders and special files are left alone.

### Keep a file permanently

In **Active Files**, click **Keep Permanently** for a file. It stays in
`_transit` until you remove it yourself. Click **Make Temporary** later to
start a new timer.

### Restore a file

1. Open **Recently Deleted**.
2. Find the file you want to recover.
3. Click **Restore** before the seven-day recovery period ends.

The file returns to `~/_transit` and starts a new timer using the cleanup time
currently selected in **Settings**. For example, if your setting is one hour,
a restored file gets a new one-hour timer. Restoring does not continue the old
timer.

If the recovery copy is missing or the seven-day period has ended, the Restore
button is unavailable. A history entry by itself cannot recreate the file.

## Install

### Requirements

- GNOME Shell 45 or newer, with GTK 4 and libadwaita
- Python 3.10 or newer
- A systemd user session for automatic cleanup

For GNOME Files folder protection, the installer also needs `python3-nautilus`,
PyGObject, and a C compiler such as `gcc`.

### Install or upgrade

The installer migrates the previous project name to Transit, including the folder,
recovery storage, database, and direct-screenshot setting. Timers, permanent flags,
and history survive the rename. Close existing preferences before upgrading.
If both old and new storage folders exist, installation stops without merging or
overwriting them. Restart Files and log out/in afterward to load the new identity.


1. Download or extract the project.
2. Open a terminal in the project folder.
3. Run the installer as your normal user. Do not use `sudo`:

```bash
python3 install.py
```

4. Restart GNOME Files:

```bash
nautilus --quit
```

5. Log out and log in again so GNOME loads the extension.
6. Enable Transit and open its preferences:

```bash
env -u XDG_DATA_HOME -u XDG_CONFIG_HOME \
  gnome-extensions enable transit@aaryabalan.local

env -u XDG_DATA_HOME -u XDG_CONFIG_HOME \
  gnome-extensions prefs transit@aaryabalan.local
```

You can also open Transit from **GNOME Extensions**. There is no separate
desktop application.

### Optional installation choices

Install without GNOME Shell integration:

```bash
python3 install.py --no-extension
```

Install without GNOME Files folder protection:

```bash
python3 install.py --no-file-manager-guard
```

## Daily Use

1. Open **Transit preferences**.
2. Choose your cleanup time in **Settings**.
3. Click **Open Folder**.
4. Put temporary files directly inside `~/_transit`.
5. Use **Active Files** to open files or make selected files permanent.
6. Use **Recently Deleted** to restore a removed file within seven days.

Transit continues cleaning files while the preferences window is closed. The
list normally refreshes every few seconds. New or changing files are given a
short settling period before their timer can finish.

## Delete the `_transit` Folder

The folder contains both your visible files and Transit's recovery copies.
Deleting the whole folder removes access to those recovery copies. History is
not a backup.

### Delete it safely in GNOME Files

1. Open **GNOME Extensions**.
2. Disable **Transit**.
3. Open GNOME Files and move `~/_transit` to Trash or delete it.
4. Restart GNOME Files if it was already open:

```bash
nautilus --quit
```

When Transit is enabled, GNOME Files blocks deletion of the root folder to
help prevent accidents. Files inside the folder can still be removed normally.

### Delete it from a terminal

Stop the cleanup service first:

```bash
systemctl --user stop transit.service
rm -rf "$HOME/_transit"
```

Only run this command when you are certain that you no longer need the files or
their recovery copies.

## Uninstall

From the project folder, run:

```bash
python3 install.py --uninstall
```

Uninstalling stops the service and removes Transit's installed program files.
It keeps your active files, but removes Transit's recovery tracking and
history. Restart GNOME Files after uninstalling.

## Complete Workflow

```mermaid
flowchart TD
  A[Place a file in _transit] --> B[Choose cleanup time]
  B --> C[Timer starts]
  C --> D{Keep permanently?}
  D -->|Yes| E[File stays in _transit]
  D -->|No| F[Timer ends]
  F --> G[Move to Recently Deleted]
  G --> H{Restore within 7 days?}
  H -->|Yes| I[Restore to _transit]
  I --> C
  H -->|No| J[Recovery copy is permanently removed]
  E --> K[User removes file manually]
```

## License

MIT licensed. See [LICENSE](LICENSE).

### Delete, view recovery files, and empty Transit Trash

Each Active Files row has **Delete**, which moves that file to Recently Deleted
for seven-day recovery. This explicit action also works for permanent files and
while automatic cleanup is paused.

Recently Deleted has an **eye button** to open each available recovery copy in its
default application without restoring it. Missing and expired copies cannot be
opened. **Empty Trash** asks for confirmation, then permanently removes all Transit
recovery copies and clears its history, including entries hidden by search. It does
not delete active files or empty your desktop's system Trash.
