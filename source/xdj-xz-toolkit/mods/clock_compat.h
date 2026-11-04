#ifndef XZ_CLOCK_COMPAT_H
#define XZ_CLOCK_COMPAT_H
#include <errno.h>
#ifdef __linux__
#include <sys/syscall.h>
#include <unistd.h>
#endif
#include <time.h>

/* SYS_clock_gettime writes kernel long fields. A 32-bit libc may instead use
 * 64-bit time_t/timespec fields. Convert explicitly without a clock_gettime
 * libc symbol, preserving the older ARM GLIBC dependency boundary. */
static inline int xz_clock_gettime_compat(clockid_t clock,struct timespec *out) {
    if(!out){errno=EFAULT;return -1;}
#ifdef __linux__
    struct { long seconds,nanoseconds; } kernel;
    if(syscall(SYS_clock_gettime,clock,&kernel))return -1;
    if(kernel.nanoseconds<0||kernel.nanoseconds>=1000000000L){errno=EIO;return -1;}
    out->tv_sec=(time_t)kernel.seconds;
    out->tv_nsec=kernel.nanoseconds;
#else
    /* Host verification on macOS uses its supported clock interface. Keep the
     * Linux kernel-long conversion above for the ARM32/glibc 2.13 runtime. */
    struct timespec value;
    if(clock_gettime(clock,&value))return -1;
    if(value.tv_nsec<0||value.tv_nsec>=1000000000L){errno=EIO;return -1;}
    *out=value;
#endif
    return 0;
}
#endif
