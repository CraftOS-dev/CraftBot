// CraftBot-owned housekeeping over the pinned, unchanged framework library.
// Reuse CLI commands or upstream atomic helpers for recorded parent blueprints.
import {
  closeSync, copyFileSync, existsSync, lstatSync, mkdirSync, openSync, readdirSync, readFileSync, readSync,
  realpathSync, renameSync, rmSync, statSync, truncateSync,
} from 'node:fs';
import { dirname, join, resolve, relative, isAbsolute } from 'node:path';
import { pathToFileURL } from 'node:url';

const [pkg, app, expectedId, operation, ...args] = process.argv.slice(2);
const lib = name => import(pathToFileURL(join(pkg, 'dist/lib', `${name}.js`)).href);
const { withLock } = await lib('lock');
const { loadProject } = await lib('project');
const { lifecycleLock, backupsDir, listBackups, assertNotServing, backupId } = await lib('lifecycle');
const { projectToolkit, installedToolkit } = await lib('toolkit');
const { copyDirAtomic, replaceDirAtomic } = await lib('fsx');
const root = realpathSync(app);
function inside(path) {
  const rel = relative(root, resolve(path));
  if (!rel || rel.startsWith('..') || isAbsolute(rel)) throw Error('Path escapes the selected app.');
  // Reject junctions/symlinks, including parents, before traversing or removing.
  let current = root;
  for (const part of rel.split(/[\\/]/)) {
    current = join(current, part);
    if (existsSync(current) && (lstatSync(current).isSymbolicLink() || realpathSync(current) !== current)) {
      throw Error('Linked maintenance paths are not supported.');
    }
  }
  return path;
}
function bytes(path) {
  inside(path);
  const stat = lstatSync(path);
  return stat.isDirectory() ? readdirSync(path).reduce((sum, child) => sum + bytes(join(path, child)), 0) : stat.size;
}
function entries() {
  const folder = inside(backupsDir(root));
  return listBackups(root).filter(id => /^\d{4}-\d{2}-\d{2}T[\w-]+$/.test(id))
    .map(id => {
      const path = inside(join(folder, id));
      const stat = lstatSync(path);
      if (!stat.isDirectory()) throw Error('Invalid backup directory.');
      const date = id.slice(0, 24).replace(/T(\d{2})-(\d{2})-(\d{2})-(\d{3})Z/, 'T$1:$2:$3.$4Z');
      return { filename: id, ts: Date.parse(date) || stat.mtimeMs, size: bytes(path) };
    }).reverse();
}
function layout() {
  let toolkit = projectToolkit(root);
  let mode = 'cli';
  // Some custom apps record their parent blueprint in a provenance lock but
  // ship without the custom toolkit. Use that explicit declaration, never a
  // guessed data folder. The installed, pinned parent supplies the contract.
  if (!toolkit && existsSync(join(root, 'framework.lock.json'))) {
    const lock = JSON.parse(readFileSync(inside(join(root, 'framework.lock.json')), 'utf8'));
    toolkit = installedToolkit(lock.blueprint);
    mode = 'parent-toolkit';
  }
  const dir = toolkit?.manifest.lifecycle?.dataDir;
  if (!dir) return { mode: null, reason: 'This app has no installed backup toolkit or recorded parent blueprint. Its data location is unknown.' };
  const data = inside(resolve(root, dir));
  if (!existsSync(data)) return { mode: null, reason: 'This app has no saved data yet. Launch it before creating a backup.' };
  return { mode, dataDir: dir };
}

// A live backup copies a running app's data without stopping it, so its share
// links stay up. It writes the framework's own backup format (a plain mirror of
// the data directory, published atomically under .a2app/backups/<id>), which
// `restore` reads unchanged. Each SQLite database is copied through SQLite:
// VACUUM INTO reads one transaction-consistent snapshot without blocking a
// WAL-mode writer, and folds in the -wal/-shm/-journal companions, so those are
// skipped. Any other file is copied again until it held still during the copy.
const SQLITE_HEADER = Buffer.from('SQLite format 3\0', 'latin1');
const COMPANIONS = ['-wal', '-shm', '-journal'];
const sleep = ms => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const gone = error => error?.code === 'ENOENT';
function isSqlite(path) {
  const fd = openSync(path, 'r');
  try {
    const head = Buffer.alloc(SQLITE_HEADER.length);
    return readSync(fd, head, 0, head.length, 0) === head.length && head.equals(SQLITE_HEADER);
  } finally {
    closeSync(fd);
  }
}
function stamp(path) {
  const stat = statSync(path, { bigint: true });
  return `${stat.ino}:${stat.size}:${stat.mtimeNs}`;
}
function walk(dir, found = { dirs: [], files: [] }) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = inside(join(dir, entry.name));
    if (entry.isDirectory()) {
      found.dirs.push(path);
      walk(path, found);
    } else found.files.push(path);
  }
  return found;
}
function copyStable(from, to) {
  for (let attempt = 1; attempt <= 5; attempt++) {
    try {
      const before = stamp(from);
      copyFileSync(from, to);
      if (stamp(from) === before) return;
    } catch (error) {
      // Removed while backing up (a temp file of an atomic write): not data.
      if (gone(error)) return rmSync(to, { force: true });
      throw error;
    }
    sleep(attempt * 20);
  }
  throw Error(`${relative(root, from)} kept changing while it was backed up. Try again.`);
}
async function liveBackup(data, dest) {
  const { DatabaseSync } = await import('node:sqlite');
  const folder = dirname(dest);
  mkdirSync(folder, { recursive: true });
  // An interrupted live backup leaves its staging folder; the lifecycle lock
  // held here rules out one still running.
  for (const name of readdirSync(folder).filter(name => name.includes('.staging-live-'))) {
    rmSync(inside(join(folder, name)), { recursive: true, force: true });
  }
  const staged = `${dest}.staging-live-${process.pid}`;
  const target = file => join(staged, relative(data, file));
  const { dirs, files } = walk(data);
  const databases = new Set(files.filter(file => {
    try { return isSqlite(file); } catch (error) { if (gone(error)) return false; throw error; }
  }));
  try {
    mkdirSync(staged);
    for (const dir of dirs) mkdirSync(target(dir), { recursive: true });
    for (const file of databases) {
      const source = new DatabaseSync(file, { readOnly: true });
      try {
        source.exec('PRAGMA busy_timeout = 15000');
        source.exec(`VACUUM INTO '${target(file).replace(/'/g, "''")}'`);
      } finally {
        source.close();
      }
      const copy = new DatabaseSync(target(file), { readOnly: true });
      try {
        if (copy.prepare('PRAGMA quick_check').get().quick_check !== 'ok') {
          throw Error(`The copy of ${relative(root, file)} failed its integrity check.`);
        }
      } finally {
        copy.close();
      }
    }
    for (const file of files) {
      const companion = COMPANIONS.some(end => file.endsWith(end) && databases.has(file.slice(0, -end.length)));
      if (!databases.has(file) && !companion) copyStable(file, target(file));
    }
    // A virus scanner can briefly hold a just-written file on Windows.
    for (let attempt = 1; ; attempt++) {
      try {
        renameSync(staged, dest);
        break;
      } catch (error) {
        if (process.platform !== 'win32' || !['EPERM', 'EACCES', 'EBUSY'].includes(error.code) || attempt >= 10) throw error;
        sleep(attempt * 20);
      }
    }
  } catch (error) {
    rmSync(staged, { recursive: true, force: true });
    throw error;
  }
}

try {
  inside(join(root, '.a2app'));
  const project = loadProject(root);
  if (project.manifest.id !== expectedId) throw Error('App identity changed.');
  const result = await withLock(lifecycleLock(root), async () => {
    if (operation === 'list') return { ok: true, backups: entries(), backupSupport: layout() };
    if (operation === 'layout') return { ok: true, backupSupport: layout() };
    if (operation === 'backup-live') {
      // Deliberately no assertNotServing: this copy is safe while the app runs.
      const support = layout();
      if (!support.mode) throw Error(support.reason);
      const id = backupId(new Date());
      const path = inside(join(backupsDir(root), id));
      await liveBackup(inside(resolve(root, support.dataDir)), path);
      return { ok: true, backup: id, path };
    }
    if (operation === 'backup-parent' || operation === 'restore-parent') {
      const support = layout();
      if (support.mode !== 'parent-toolkit') throw Error('The backup toolkit changed. Refresh the app settings.');
      await assertNotServing(project, 'back up or restore its data');
      const data = inside(resolve(root, support.dataDir));
      // Reuse the framework's atomic copy/replace primitives and its backup
      // format. No toolkit files, project metadata or upstream code are edited.
      if (operation === 'backup-parent') {
        const id = backupId(new Date());
        const path = inside(join(backupsDir(root), id));
        copyDirAtomic(data, path);
        return { ok: true, backup: id, path };
      }
      const id = args[0];
      if (!entries().some(entry => entry.filename === id)) throw Error('Choose an existing user backup.');
      const safety = backupId(new Date(), 'pre-restore');
      const rollback = inside(join(backupsDir(root), safety));
      copyDirAtomic(data, rollback);
      try { replaceDirAtomic(inside(join(backupsDir(root), id)), data); }
      catch (error) { replaceDirAtomic(rollback, data); throw error; }
      return { ok: true, restored: id, rollback: safety };
    }
    if (operation === 'delete') {
      const allowed = new Set(entries().map(item => item.filename));
      if (!args.length || args.some(id => !allowed.has(id))) throw Error('Choose an existing user backup.');
      for (const id of args) rmSync(inside(join(backupsDir(root), id)), { recursive: true });
      return { ok: true };
    }
    if (operation === 'clean-logs') {
      return withLock(join(root, '.a2app', 'serve.lock'), async () => {
        await assertNotServing(project, 'clean its logs');
        const log = inside(join(root, '.a2app', 'serve.log'));
        if (existsSync(log)) {
          if (!lstatSync(log).isFile() || lstatSync(log).nlink !== 1) throw Error('The log must be an ordinary unlinked file.');
          truncateSync(log, 0);
        }
        return { ok: true };
      });
    }
    throw Error('Unknown housekeeping action.');
  });
  process.stdout.write(JSON.stringify(result));
} catch (error) {
  process.stderr.write(error.message);
  process.exitCode = 1;
}
