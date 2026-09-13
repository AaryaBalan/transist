import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
const source = await readFile(new URL('../extension/view-model.js', import.meta.url), 'utf8');
const {fileRows, remaining, lifetimeOptions, lifetimeLabel} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const snapshot = {now: 1000, files: [
    {id: 'a', name: '<b>notes</b>.txt', status: 'active', permanent: 0, expires: 19000, added: 1},
    {id: 'p', name: 'Keep.PNG', status: 'active', permanent: 1, expires: 0, added: 2},
    {id: 'd', name: 'recover.pdf', status: 'deleted', deleted: 800, purge_at: 1100},
    {id: 'e', name: 'overdue.pdf', status: 'deleted', deleted: 700, purge_at: 1000},
    {id: 'x', name: 'purged.pdf', status: 'purged', deleted: 100, purge_at: 900},
]};
test('active entries offer pin and unpin, newest first', () => {
    assert.deepEqual(fileRows(snapshot, 'active').map(r => [r.id, r.action]), [['p', 'unpin'], ['a', 'pin']]);
});
test('history allows restore only strictly inside recovery window', () => {
    assert.deepEqual(fileRows(snapshot, 'history').map(r => [r.id, r.enabled]), [['d', true], ['e', false], ['x', false]]);
});
test('missing recovery copies stay in history with an explanation and no restore action', () => {
    const missing = {...snapshot, files: [{id: 'm', name: 'missing.png', status: 'recovery_missing', deleted: 800, purge_at: 2000}]};
    const row = fileRows(missing, 'history')[0];
    assert.equal(row.enabled, false);
    assert.equal(row.label, 'Unavailable');
    assert.match(row.subtitle, /check system Trash/);
    assert.equal(fileRows(missing, 'active').length, 0);
});
test('case-insensitive search includes all entries before pagination', () => {
    assert.equal(fileRows(snapshot, 'active', ' keep.png ')[0].id, 'p');
    assert.equal(fileRows(snapshot, 'history', 'unknown').length, 0);
});
test('filenames remain literal; GTK rows disable markup', async () => {
    assert.equal(fileRows(snapshot, 'active', 'notes')[0].name, '<b>notes</b>.txt');
    const prefs = await readFile(new URL('../extension/prefs.js', import.meta.url), 'utf8');
    assert.match(prefs, /title: item.name, subtitle: item.subtitle, use_markup: false/);
});
test('duration labels clamp overdue timers', () => {
    assert.equal(remaining(-60), '0h 0m');
    assert.equal(remaining(18000), '5h 0m');
    assert.equal(remaining(7 * 86400), '7d 0h');
});
test('all selectable windows have matching restore labels', () => {
    assert.deepEqual(lifetimeOptions, [1, 5, 12, 24, 48, 72, 168]);
    assert.equal(lifetimeLabel(1), '1 hour');
    assert.equal(lifetimeLabel(168), '1 week');
    assert.equal(fileRows(snapshot, 'history')[0].label, 'Restore · 5 hours');
    for (const hours of lifetimeOptions) {
        const configured = {...snapshot, settings: {lifetime_hours: hours}};
        assert.equal(fileRows(configured, 'history')[0].label, `Restore · ${lifetimeLabel(hours)}`);
    }
});
test('native preferences own the UI with no standalone GUI or CSS override', async () => {
    const prefs = await readFile(new URL('../extension/prefs.js', import.meta.url), 'utf8');
    const shell = await readFile(new URL('../extension/extension.js', import.meta.url), 'utf8');
    assert.match(shell, /this.openPreferences\(\)/);
    assert.match(prefs, /Recently Deleted/);
    assert.match(prefs, /close-request/);
    assert.doesNotMatch(prefs, /CssProvider|set_color_scheme|['"]gui['"]/);
    assert.doesNotMatch(shell, /['"]gui['"]/);
});
