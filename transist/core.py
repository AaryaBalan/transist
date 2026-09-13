"""Transist: user-owned, recoverable, time-limited files. Python 3.10+."""
import contextlib
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import stat
import time
import uuid

TTL = 5 * 3600
LIFETIME_HOURS = (1, 5, 12, 24, 48, 72, 168)
RETENTION = 7 * 86400
QUIET = 30
IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.avif', '.bmp', '.tiff'}


def signature(s):
    return f'{s.st_dev}:{s.st_ino}:{s.st_size}:{s.st_mtime_ns}:{s.st_ctime_ns}'


def private_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    s = os.fstat(fd)
    if s.st_uid != os.getuid() or s.st_mode & 0o022:
        os.close(fd)
        raise ValueError(f'Directory must be owned by you and not writable by others: {path}')
    return fd


class Store:
    def __init__(self, home=None, data=None, clock=time.time):
        self.home = Path(home or Path.home()).absolute()
        self.root = self.home / '_transist'
        self.data = Path(data or Path(os.environ.get('XDG_DATA_HOME', self.home / '.local/share')) / 'transist')
        self.clock = clock

    @contextlib.contextmanager
    def session(self, *, uninstall=False, resume=False):
        datafd = private_directory(self.data)
        lockfd = os.open('lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=datafd)
        rootfd = vaultfd = db = None
        try:
            fcntl.flock(lockfd, fcntl.LOCK_EX)
            known_store = (self.data / 'state.sqlite3').exists()
            root_existed = os.path.lexists(self.root)
            dbfd = os.open('state.sqlite3', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=datafd)
            os.close(dbfd)
            db = sqlite3.connect(self.data / 'state.sqlite3', isolation_level=None)
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA synchronous=FULL')
            db.executescript("""
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lifecycle (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS files (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, dev INTEGER, ino INTEGER,
                  sig TEXT, stable REAL, added REAL, expires REAL, permanent INTEGER DEFAULT 0,
                  status TEXT, deleted REAL, purge_at REAL, destination TEXT);
                CREATE TABLE IF NOT EXISTS shots (name TEXT PRIMARY KEY, sig TEXT, stable REAL, eligible INTEGER);
            """)
            self.db, self.rootfd, self.vaultfd = db, None, None
            marker = self.data / 'folder-removal-requested'
            previous = {r['key']: json.loads(r['value']) for r in db.execute('SELECT * FROM lifecycle')}
            if not root_existed and ('root' not in previous or previous['root'] is not None):
                # Persist the reset even when deliberate removal keeps storage absent.
                self.reset_history()
            if resume or uninstall:
                marker.unlink(missing_ok=True)
            elif not root_existed and marker.exists():
                db.execute("INSERT OR REPLACE INTO lifecycle VALUES ('root', 'null')")
                self.storage_recreated = False
                yield self
                return
            vault_created = False
            if root_existed or not uninstall:
                rootfd = private_directory(self.root)
                if not uninstall:
                    try:
                        os.mkdir('.transist-recovery', 0o700, dir_fd=rootfd)
                        vault_created = True
                    except FileExistsError:
                        pass
                try:
                    vaultfd = os.open('.transist-recovery', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=rootfd)
                except FileNotFoundError:
                    if not uninstall:
                        raise
                if vaultfd is not None:
                    vs = os.fstat(vaultfd)
                    if vs.st_uid != os.getuid() or vs.st_mode & 0o077:
                        raise ValueError('Recovery directory must be private (mode 0700).')
            self.rootfd, self.vaultfd = rootfd, vaultfd
            root_identity = self.directory_identity(self.root)
            extension = self.home / '.local/share/gnome-shell/extensions/transist@aaryabalan.local'
            extension_identity = self.directory_identity(extension)
            root_changed = 'root' in previous and previous['root'] != root_identity
            extension_removed = previous.get('extension') is not None and extension_identity is None
            if uninstall or root_changed or extension_removed:
                self.reset_history(purge_recovery=uninstall or extension_removed)
            self.storage_recreated = known_store and vault_created and root_existed and not root_changed and not extension_removed
            for key, value in (('root', root_identity), ('extension', None if uninstall else extension_identity)):
                db.execute('INSERT OR REPLACE INTO lifecycle VALUES (?,?)', (key, json.dumps(value)))
            if not uninstall:
                self.reconcile()
                self.refresh_availability()
            yield self
        finally:
            if db is not None:
                db.close()
            for fd in (vaultfd, rootfd, lockfd, datafd):
                if fd is not None:
                    os.close(fd)

    @staticmethod
    def directory_identity(path):
        try:
            info = path.stat(follow_symlinks=False)
            return [info.st_dev, info.st_ino]
        except FileNotFoundError:
            return None

    def reset_history(self, *, purge_recovery=False):
        # Only remove known recovery copies, never active files or external Trash.
        if purge_recovery and self.vaultfd is not None:
            for row in self.db.execute('SELECT * FROM files').fetchall():
                if self.matches(self.vaultfd, row['id'], row):
                    os.unlink(row['id'], dir_fd=self.vaultfd)
            os.fsync(self.vaultfd)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('DELETE FROM files')
            self.db.execute('DELETE FROM shots')
            if self.settings()['capture_screenshots']:
                self.capture(baseline=True)
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    def settings(self):
        pictures = self.home / 'Pictures'
        # Read the XDG file as data, never execute shell contents.
        xdg = Path(os.environ.get('XDG_CONFIG_HOME', self.home / '.config')) / 'user-dirs.dirs'
        if xdg.is_file():
            for line in xdg.read_text().splitlines():
                if line.startswith('XDG_PICTURES_DIR="') and line.endswith('"'):
                    value = line.split('=', 1)[1][1:-1].replace('$HOME', str(self.home))
                    if Path(value).is_absolute():
                        pictures = Path(value)
        result = {'paused': False, 'capture_screenshots': False, 'theme': 'light',
                  'lifetime_hours': 5,
                  'screenshot_folder': str(pictures / 'Screenshots')}
        result.update({r['key']: json.loads(r['value']) for r in self.db.execute('SELECT * FROM settings')})
        return result

    def configure(self, key, value):
        if key not in self.settings():
            raise ValueError('Unknown setting')
        if key == 'theme' and value not in ('light', 'dark'):
            raise ValueError('Theme must be light or dark')
        if key in ('paused', 'capture_screenshots') and type(value) is not bool:
            raise ValueError('Expected true or false')
        if key == 'lifetime_hours' and (type(value) is not int or value not in LIFETIME_HOURS):
            raise ValueError('Choose 1, 5, 12, 24, 48, 72, or 168 hours (1 week)')
        if key == 'screenshot_folder':
            p = Path(value).expanduser().resolve()
            if not p.is_dir() or p == self.home or p == self.root or self.root in p.parents:
                raise ValueError('Choose an existing dedicated screenshot folder outside _transist.')
            value = str(p)
        old = self.settings()
        if old[key] == value:
            return
        self.db.execute('BEGIN IMMEDIATE')
        try:
            self.db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))
            if key == 'lifetime_hours':
                # Preserve each timer's start, including timers reset by unpinning.
                self.db.execute("UPDATE files SET expires=expires+? WHERE status='active' AND permanent=0",
                                ((value - old[key]) * 3600,))
            if key in ('capture_screenshots', 'screenshot_folder'):
                self.db.execute('DELETE FROM shots')
                if self.settings()['capture_screenshots']:
                    self.capture(baseline=True)
            self.db.execute('COMMIT')
        except Exception:
            self.db.execute('ROLLBACK')
            raise

    @staticmethod
    def info(fd, name):
        if name in ('.', '..') or '/' in name or '\x00' in name:
            raise ValueError('Invalid filename')
        try:
            s = os.stat(name, dir_fd=fd, follow_symlinks=False)
            return s if stat.S_ISREG(s.st_mode) else None
        except FileNotFoundError:
            return None

    def matches(self, fd, name, row):
        s = self.info(fd, name)
        return s is not None and (s.st_dev, s.st_ino) == (row['dev'], row['ino'])

    def refresh_availability(self):
        """History is not proof that the corresponding bytes still exist."""
        rows = self.db.execute("SELECT * FROM files WHERE status IN ('active','deleted','recovery_missing')").fetchall()
        for r in rows:
            if r['status'] == 'active':
                if not self.matches(self.rootfd, r['name'], r):
                    self.db.execute("UPDATE files SET status='missing' WHERE id=?", (r['id'],))
            else:
                status = 'deleted' if self.matches(self.vaultfd, r['id'], r) else 'recovery_missing'
                if status != r['status']:
                    self.db.execute('UPDATE files SET status=? WHERE id=?', (status, r['id']))

    def missing_recovery_count(self):
        return self.db.execute("SELECT COUNT(*) FROM files WHERE status='recovery_missing'").fetchone()[0]

    def reconcile(self):
        # Write intent before moving; after interruption either name is sufficient.
        for r in self.db.execute("SELECT * FROM files WHERE status IN ('expiring','restoring')").fetchall():
            restoring = r['status'] == 'restoring'
            srcfd, dstfd = (self.vaultfd, self.rootfd) if restoring else (self.rootfd, self.vaultfd)
            src, dst = (r['id'], r['destination']) if restoring else (r['name'], r['id'])
            if self.matches(dstfd, dst, r):
                if self.matches(srcfd, src, r):
                    os.unlink(src, dir_fd=srcfd)
                os.fsync(srcfd)
                os.fsync(dstfd)
                if restoring:
                    s = self.info(dstfd, dst)
                    now = self.clock()
                    self.db.execute("UPDATE files SET status='active',name=?,sig=?,stable=?,added=?,expires=?,permanent=0,deleted=NULL,purge_at=NULL,destination=NULL WHERE id=?",
                                    (dst, signature(s), now, now, now + self.settings()['lifetime_hours'] * 3600, r['id']))
                else:
                    self.db.execute("UPDATE files SET status='deleted' WHERE id=?", (r['id'],))
            elif self.matches(srcfd, src, r):
                self.db.execute('UPDATE files SET status=? WHERE id=?', ('deleted' if restoring else 'active', r['id']))
            else:
                self.db.execute("UPDATE files SET status='missing' WHERE id=?", (r['id'],))

    def move(self, r, restoring=False):
        now = self.clock()
        if restoring:
            if r['status'] == 'recovery_missing':
                raise ValueError('Recovery copy is unavailable. If you deleted or moved _transist, check system Trash. History alone cannot restore a file.')
            if r['status'] != 'deleted' or now >= r['purge_at']:
                raise ValueError('The recovery window has ended or this file is no longer recoverable.')
            if not self.matches(self.vaultfd, r['id'], r):
                raise ValueError('Recovery file is missing or was changed outside Transist.')
            name = r['name']
            # Never replace an existing file, directory, or symlink.
            while True:
                try:
                    os.stat(name, dir_fd=self.rootfd, follow_symlinks=False)
                    p = Path(r['name'])
                    name = f'{p.stem[:120]} (restored {uuid.uuid4().hex[:8]}){p.suffix[:30]}'
                except FileNotFoundError:
                    break
            self.db.execute("UPDATE files SET status='restoring',destination=? WHERE id=?", (name, r['id']))
            srcfd, dstfd, src, dst = self.vaultfd, self.rootfd, r['id'], name
        else:
            s = self.info(self.rootfd, r['name'])
            if not s or signature(s) != r['sig'] or s.st_nlink != 1:
                return
            self.db.execute("UPDATE files SET status='expiring',deleted=?,purge_at=? WHERE id=?", (now, now + RETENTION, r['id']))
            srcfd, dstfd, src, dst = self.rootfd, self.vaultfd, r['name'], r['id']
        # Hard-link + unlink is no-clobber; recovery is on the same filesystem.
        os.link(src, dst, src_dir_fd=srcfd, dst_dir_fd=dstfd, follow_symlinks=False)
        os.fsync(dstfd)
        self.reconcile()

    def scan(self):
        now = self.clock()
        lifetime = self.settings()['lifetime_hours'] * 3600
        rows = {r['name']: r for r in self.db.execute("SELECT * FROM files WHERE status='active'")}
        present = set()
        for name in os.listdir(self.rootfd):
            s = self.info(self.rootfd, name)
            if not s:
                continue
            present.add(name)
            old = rows.get(name)
            if old and (old['dev'], old['ino']) != (s.st_dev, s.st_ino):
                self.db.execute("UPDATE files SET status='missing' WHERE id=?", (old['id'],))
                old = None
            if old is None:
                self.db.execute('INSERT INTO files (id,name,dev,ino,sig,stable,added,expires,status) VALUES (?,?,?,?,?,?,?,?,?)',
                                (uuid.uuid4().hex, name, s.st_dev, s.st_ino, signature(s), now, now, now + lifetime, 'active'))
            elif old['sig'] != signature(s):
                self.db.execute('UPDATE files SET sig=?,stable=? WHERE id=?', (signature(s), now, old['id']))
        for name, r in rows.items():
            if name not in present:
                self.db.execute("UPDATE files SET status='missing' WHERE id=?", (r['id'],))

    def capture(self, baseline=False):
        cfg = self.settings()
        path = Path(cfg['screenshot_folder'])
        if path.resolve() == self.root.resolve() or self.root.resolve() in path.resolve().parents:
            raise ValueError('Screenshot source cannot be inside _transist.')
        try:
            fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return
        try:
            present = set()
            for name in os.listdir(fd):
                if Path(name).suffix.lower() not in IMAGE_EXTENSIONS:
                    continue
                s = self.info(fd, name)
                if not s or s.st_nlink != 1:
                    continue
                present.add(name)
                sig = signature(s)
                r = self.db.execute('SELECT * FROM shots WHERE name=?', (name,)).fetchone()
                if r is None:
                    self.db.execute('INSERT INTO shots VALUES (?,?,?,?)', (name, sig, self.clock(), 0 if baseline else 1))
                elif r['sig'] != sig:
                    self.db.execute('UPDATE shots SET sig=?,stable=? WHERE name=?', (sig, self.clock(), name))
                elif r['eligible'] and self.clock() - r['stable'] >= QUIET and not baseline:
                    self.import_shot(fd, name, s)
                    self.db.execute('DELETE FROM shots WHERE name=?', (name,))
            for r in self.db.execute('SELECT name FROM shots').fetchall():
                if r['name'] not in present:
                    self.db.execute('DELETE FROM shots WHERE name=?', (r['name'],))
        finally:
            os.close(fd)

    def import_shot(self, sourcefd, name, expected):
        import shutil
        temporary = 'capture-' + uuid.uuid4().hex
        infd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sourcefd)
        try:
            if signature(os.fstat(infd)) != signature(expected):
                return
            outfd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=self.vaultfd)
            try:
                with os.fdopen(os.dup(infd), 'rb') as src, os.fdopen(outfd, 'wb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                    dst.flush()
                    os.fsync(dst.fileno())
                current = self.info(sourcefd, name)
                if not current or signature(current) != signature(expected) or signature(os.fstat(infd)) != signature(expected):
                    return
                target = name
                while True:
                    try:
                        os.link(temporary, target, src_dir_fd=self.vaultfd, dst_dir_fd=self.rootfd, follow_symlinks=False)
                        break
                    except FileExistsError:
                        p = Path(name)
                        target = f'{p.stem[:120]} ({uuid.uuid4().hex[:8]}){p.suffix[:30]}'
                os.fsync(self.rootfd)
                current = self.info(sourcefd, name)
                if current and signature(current) == signature(expected):
                    os.unlink(name, dir_fd=sourcefd)
                    os.fsync(sourcefd)
            finally:
                os.unlink(temporary, dir_fd=self.vaultfd)
        finally:
            os.close(infd)

    def tick(self):
        if self.rootfd is None:
            return
        cfg = self.settings()
        if not cfg['paused'] and cfg['capture_screenshots']:
            self.capture()
        self.scan()
        if cfg['paused']:
            return
        now = self.clock()
        for r in self.db.execute("SELECT * FROM files WHERE status='active' AND permanent=0 AND expires<=? AND stable<=?", (now, now - QUIET)).fetchall():
            self.move(r)
        for r in self.db.execute("SELECT * FROM files WHERE status='deleted' AND purge_at<=?", (now,)).fetchall():
            if self.matches(self.vaultfd, r['id'], r):
                os.unlink(r['id'], dir_fd=self.vaultfd)
                os.fsync(self.vaultfd)
                self.db.execute("UPDATE files SET status='purged' WHERE id=?", (r['id'],))
            elif self.info(self.vaultfd, r['id']) is None:
                self.db.execute("UPDATE files SET status='purged' WHERE id=?", (r['id'],))

    def action(self, file_id, action):
        self.refresh_availability()
        r = self.db.execute('SELECT * FROM files WHERE id=?', (file_id,)).fetchone()
        if r is None:
            raise ValueError('File not found')
        if action == 'restore':
            self.move(r, restoring=True)
        elif action in ('pin', 'unpin'):
            if r['status'] != 'active' or not self.matches(self.rootfd, r['name'], r):
                raise ValueError('File is no longer active')
            self.db.execute('UPDATE files SET permanent=?,expires=? WHERE id=?', (int(action == 'pin'), self.clock() + self.settings()['lifetime_hours'] * 3600, file_id))
        else:
            raise ValueError('Unknown action')

    def snapshot(self):
        self.refresh_availability()
        return {'folder': str(self.root), 'settings': self.settings(),
                'folder_removed': self.rootfd is None,
                'folder_guard_installed': all((self.data.parent / 'nautilus-python/extensions' / name).is_file() for name in ('transist_guard.py', 'transist_guard_native.so')),
                'missing_recovery_count': self.missing_recovery_count(),
                'files': [dict(r) for r in self.db.execute('SELECT * FROM files ORDER BY added DESC')],
                'now': self.clock()}
