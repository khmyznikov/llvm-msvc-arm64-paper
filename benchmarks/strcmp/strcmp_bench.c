/*
 * Custom strcmp benchmark — placeholder implementation.
 *
 * Byte-by-byte string comparison with trailing-space stripping,
 * matching the description from the MSVC vs LLVM benchmark paper.
 *
 * Build (MSVC):
 *   cl /O2 /GL /fp:fast /GS- strcmp_bench.c /Fe:strcmp_msvc.exe /link /LTCG
 *
 * Build (LLVM/clang-cl):
 *   clang-cl -O3 -flto /clang:-ffast-math /GS- strcmp_bench.c -o strcmp_llvm.exe -fuse-ld=lld
 *
 * Noinline variant: add /DNOINLINE (MSVC) or -DNOINLINE (clang-cl)
 *
 * TODO: Replace this placeholder with the actual benchmark source.
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#ifdef _WIN32
#include <windows.h>
#else
#include <sys/time.h>
#endif

/* --------------------------------------------------------------------------
 * Buffer type
 * -------------------------------------------------------------------------- */

typedef struct {
    const char *data;
    size_t      len;
} Buffer;

/* --------------------------------------------------------------------------
 * Buffer_strcmp: byte-by-byte comparison with trailing-space stripping.
 *
 * Compares two buffers character by character.  Trailing spaces (0x20) are
 * ignored: "abc   " == "abc".  Returns <0, 0, >0 like memcmp/strcmp.
 * -------------------------------------------------------------------------- */

#ifdef NOINLINE
__declspec(noinline)
#endif
static int Buffer_strcmp(const Buffer *a, const Buffer *b) {
    size_t i = 0;
    size_t alen = a->len;
    size_t blen = b->len;

    /* Strip trailing spaces from effective length */
    while (alen > 0 && a->data[alen - 1] == ' ') alen--;
    while (blen > 0 && b->data[blen - 1] == ' ') blen--;

    /* Byte-by-byte comparison */
    while (i < alen && i < blen) {
        unsigned char ca = (unsigned char)a->data[i];
        unsigned char cb = (unsigned char)b->data[i];
        if (ca != cb)
            return (int)ca - (int)cb;
        i++;
    }

    /* Shorter (after trimming) is "less" */
    if (alen < blen) return -1;
    if (alen > blen) return  1;
    return 0;
}

/* --------------------------------------------------------------------------
 * High-resolution timer
 * -------------------------------------------------------------------------- */

static double get_time_sec(void) {
#ifdef _WIN32
    LARGE_INTEGER freq, cnt;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&cnt);
    return (double)cnt.QuadPart / (double)freq.QuadPart;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec * 1e-9;
#endif
}

/* --------------------------------------------------------------------------
 * Test data generation
 * -------------------------------------------------------------------------- */

#define NUM_STRINGS   200000
#define STRING_LEN    64
#define TRAIL_SPACES  8

static char g_pool[NUM_STRINGS][STRING_LEN + TRAIL_SPACES + 1];
static Buffer g_bufs[NUM_STRINGS];

static void init_data(void) {
    srand(12345);
    for (int i = 0; i < NUM_STRINGS; i++) {
        /* Fill with pseudo-random printable ASCII */
        for (int j = 0; j < STRING_LEN; j++) {
            g_pool[i][j] = (char)(33 + (rand() % 94)); /* '!' .. '~' */
        }
        /* Append trailing spaces */
        for (int j = STRING_LEN; j < STRING_LEN + TRAIL_SPACES; j++) {
            g_pool[i][j] = ' ';
        }
        g_pool[i][STRING_LEN + TRAIL_SPACES] = '\0';

        g_bufs[i].data = g_pool[i];
        g_bufs[i].len  = STRING_LEN + TRAIL_SPACES;
    }
}

/* --------------------------------------------------------------------------
 * Main benchmark loop
 * -------------------------------------------------------------------------- */

#ifndef BENCH_DURATION_SEC
#define BENCH_DURATION_SEC 72  /* ~1.2 min per run */
#endif

#ifndef BENCH_RUNS
#define BENCH_RUNS 3
#endif

int main(void) {
    init_data();

    printf("strcmp benchmark: %d strings x %d+%d chars, %d runs\n",
           NUM_STRINGS, STRING_LEN, TRAIL_SPACES, BENCH_RUNS);
#ifdef NOINLINE
    printf("Mode: noinline\n");
#else
    printf("Mode: inline (default)\n");
#endif

    for (int run = 0; run < BENCH_RUNS; run++) {
        volatile long long total_cmp = 0;
        long long iterations = 0;
        double start = get_time_sec();
        double elapsed;

        do {
            /* Compare all pairs in a sliding window */
            for (int i = 0; i < NUM_STRINGS - 1; i++) {
                total_cmp += Buffer_strcmp(&g_bufs[i], &g_bufs[i + 1]);
            }
            iterations++;
            elapsed = get_time_sec() - start;
        } while (elapsed < (double)BENCH_DURATION_SEC);

        double ops = (double)iterations * (NUM_STRINGS - 1);
        printf("  Run %d: %.3f sec, %lld iterations, %.0f cmp/sec (total=%lld)\n",
               run + 1, elapsed, iterations, ops / elapsed, total_cmp);
    }

    return 0;
}
