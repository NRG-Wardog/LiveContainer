/* One benign owned process. No exec, child creation, I/O or privilege changes. */
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <time.h>

int main(void) {
    struct timespec remaining = {30, 0};
    while (nanosleep(&remaining, &remaining) != 0) {
        if (errno != EINTR) return 1;
    }
    return 0;
}
