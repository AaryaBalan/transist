// Pure presentation logic, shared with automated tests.
export function remaining(seconds) {
    const minutes = Math.max(0, Math.floor(seconds / 60));
    return minutes >= 1440 ? `${Math.floor(minutes / 1440)}d ${Math.floor(minutes % 1440 / 60)}h` : `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function fileRows(snapshot, page, query = '') {
    const search = query.trim().toLocaleLowerCase();
    return snapshot.files.filter(file => (page === 'active' ? file.status === 'active' : ['deleted', 'purged'].includes(file.status)) && file.name.toLocaleLowerCase().includes(search))
        .sort((a, b) => page === 'active' ? b.added - a.added : b.deleted - a.deleted)
        .map(file => {
            const active = page === 'active';
            const valid = file.status === 'deleted' && file.purge_at > snapshot.now;
            return {
                id: file.id, name: file.name,
                icon: active ? (file.permanent ? 'emblem-important-symbolic' : 'text-x-generic-symbolic') : 'document-open-recent-symbolic',
                subtitle: active ? (file.permanent ? 'Permanent · no expiry' : `${remaining(file.expires - snapshot.now)} remaining`) : `Deleted ${new Date(file.deleted * 1000).toLocaleString()} · ${valid ? `Recover for ${remaining(file.purge_at - snapshot.now)}` : 'Recovery period ended'}`,
                label: active ? (file.permanent ? 'Make Temporary' : 'Keep Permanently') : 'Restore · 5 hours',
                action: active ? (file.permanent ? 'unpin' : 'pin') : 'restore',
                enabled: active || valid,
            };
        });
}
