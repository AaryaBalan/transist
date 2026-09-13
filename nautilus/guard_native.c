/* Tiny in-process GFile dispatcher. No Python callbacks run on Files workers.
 * GIO function pointers and interface slots are supplied from its installed
 * typelib by transit_guard.py; opaque GIO objects are never dereferenced here. */
#define _POSIX_C_SOURCE 200809L
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <fcntl.h>
#include <spawn.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

typedef int (*Operation)(void *, void *, void *);
typedef int (*Equal)(void *, void *);
typedef void (*SetError)(void *, unsigned, int, const char *);
static Operation originals[2];
static void **slots[2];
static void *root;
static Equal file_equal;
static SetError set_error;
static unsigned error_domain;
static int denied_code;
static char *marker, *launcher;
static _Atomic int enabled = -1;
static _Atomic unsigned removal_attempts;
extern char **environ;

void transit_set_enabled(int value) { atomic_store(&enabled, value); }
unsigned transit_removal_attempts(void) { return atomic_load(&removal_attempts); }

static int prepare_removal(void) {
    atomic_fetch_add(&removal_attempts, 1);
    if (!launcher || access(launcher, F_OK) != 0)
        return 1;
    char *argv[] = {"systemctl", "--user", "stop", "transit.service", NULL};
    pid_t pid;
    if (posix_spawnp(&pid, argv[0], NULL, NULL, argv, environ) != 0)
        return 0;
    int status;
    for (int i = 0; i < 500; i++) {
        pid_t result = waitpid(pid, &status, WNOHANG);
        if (result == pid) {
            if (!WIFEXITED(status) || WEXITSTATUS(status) != 0)
                return 0;
            int fd = open(marker, O_CREAT | O_WRONLY | O_CLOEXEC | O_NOFOLLOW, 0600);
            if (fd < 0)
                return 0;
            close(fd);
            return 1;
        }
        if (result < 0 && errno != EINTR)
            return 0;
        struct timespec delay = {0, 10000000};
        nanosleep(&delay, NULL);
    }
    kill(pid, SIGKILL);
    while (waitpid(pid, &status, 0) < 0 && errno == EINTR) {}
    return 0;
}

static int dispatch(int index, void *file, void *cancellable, void *error) {
    if (!file_equal(file, root))
        return originals[index](file, cancellable, error);
    int state = atomic_load(&enabled);
    const char *message = "Deleting _transit is restricted. Disable the Transit extension first.";
    if (state == 0) {
        if (prepare_removal())
            return originals[index](file, cancellable, error);
        message = "Transit could not stop cleanup before folder removal. Please try again.";
    } else if (state < 0) {
        message = "Transit could not verify that it is disabled. Please try again.";
    }
    set_error(error, error_domain, denied_code, message);
    return 0;
}
static int remove_file(void *f, void *c, void *e) { return dispatch(0, f, c, e); }
static int trash_file(void *f, void *c, void *e) { return dispatch(1, f, c, e); }

int transit_install(void *file, void **delete_slot, void **trash_slot,
                    Equal equal, SetError error, unsigned domain, int code,
                    const char *marker_path, const char *launcher_path) {
    if (root) return 0;
    marker = marker_path ? strdup(marker_path) : NULL;
    launcher = launcher_path ? strdup(launcher_path) : NULL;
    if ((marker_path && !marker) || (launcher_path && !launcher)) {
        free(marker); free(launcher); return 0;
    }
    root = file; file_equal = equal; set_error = error;
    error_domain = domain; denied_code = code;
    slots[0] = delete_slot; slots[1] = trash_slot;
    originals[0] = (Operation)*delete_slot;
    originals[1] = (Operation)*trash_slot;
    atomic_store(&removal_attempts, 0);
    *delete_slot = (void *)remove_file;
    *trash_slot = (void *)trash_file;
    return 1;
}

/* Tests only; production keeps the library and GFile alive until Files exits. */
void transit_uninstall(void) {
    if (!root) return;
    if (*slots[0] == (void *)remove_file) *slots[0] = (void *)originals[0];
    if (*slots[1] == (void *)trash_file) *slots[1] = (void *)originals[1];
    root = NULL;
    free(marker); free(launcher); marker = launcher = NULL;
}
