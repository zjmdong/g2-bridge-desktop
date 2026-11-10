#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ddagrab_clock.h"

static int cmp_double(const void *a, const void *b)
{
    const double x = *(const double *)a, y = *(const double *)b;
    return (x > y) - (x < y);
}

static void model(void)
{
    const int rates[] = {60, 75, 90, 100};
    for (int r = 0; r < 4; r++) {
        DdaFrameClock c = {0};
        c.frequency = 10000000;
        c.origin = 1234567890123;
        c.fps_num = rates[r];
        c.fps_den = 1;
        c.next_slot = 1;
        for (int64_t n = 1; n <= 600000; n++) {
            int64_t ideal = c.origin + n * c.frequency / c.fps_num;
            assert(dda_clock_deadline(&c, ideal - 1) == ideal);
            assert(c.next_slot == n);
            c.next_slot++;
        }
        c.next_slot = 2;
        int64_t late = c.origin + c.frequency * 3 + c.frequency / 1000;
        int64_t deadline = dda_clock_deadline(&c, late);
        assert(deadline <= late);
        assert(late - deadline < c.frequency / c.fps_num + 1);
        c.next_slot++;
        assert(dda_clock_deadline(&c, late) > late);
        assert(dda_clock_rescale(c.origin, 1000000, c.frequency) == c.origin / 10);
    }
    puts("clock arithmetic: 2,400,000 rational deadlines and stall recovery passed");
}

int main(int argc, char **argv)
{
    model();
    if (argc < 2 || strcmp(argv[1], "--measure"))
        return 0;
    const int n = 1200;
    DdaFrameClock c = {0};
    double intervals[1200];
    int64_t previous = 0, first = 0, now = 0, skipped = 0, previous_slot = 0;
    assert(dda_clock_init(&c, 100, 1));
    if (argc > 2) c.spin_us = atoi(argv[2]);
    for (int i = 0; i <= n; i++) {
        assert(dda_clock_wait(&c, &now));
        if (!i) first = now;
        else intervals[i-1] = (now-previous)/1000.0;
        if (previous_slot) skipped += c.next_slot - previous_slot - 1;
        previous_slot = c.next_slot;
        previous = now;
    }
    dda_clock_close(&c);
    qsort(intervals, n, sizeof(*intervals), cmp_double);
    printf("{\"timer_only\":true,\"spin_us\":%d,\"samples\":%d,\"fps\":%.4f,\"min_ms\":%.4f,\"p50_ms\":%.4f,\"p95_ms\":%.4f,\"p99_ms\":%.4f,\"max_ms\":%.4f,\"skipped_slots\":%lld}\n",
        c.spin_us, n, n*1000000.0/(now-first), intervals[0],intervals[n/2],intervals[n*95/100],intervals[n*99/100],intervals[n-1],(long long)skipped);
    return 0;
}
