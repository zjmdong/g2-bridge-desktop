/* CPU-only test doubles around the exact extracted next_frame_live function.
 * No Windows/DXGI headers, GPU calls, desktop capture or USB access.
 */
#include <assert.h>
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#define AVERROR(e) (-(e))
#define AVERROR_EXTERNAL (-542398533)
#define AV_LOG_ERROR 16
#define FAILED(hr) ((hr) < 0)
#define FALSE 0
#define INFINITE 0xffffffffu
#define WAIT_OBJECT_0 0
#define FFMAX(a,b) ((a) > (b) ? (a) : (b))
#define FFMIN(a,b) ((a) < (b) ? (a) : (b))
typedef int HRESULT;
typedef struct { int64_t QuadPart; } LARGE_INTEGER;
typedef struct { int refs; int clean; } ID3D11Texture2D;
typedef struct { int owned; int releases; int release_error; } Duplication;
typedef struct {
    int64_t frequency, last_deadline;
    struct { int64_t period; } source_phase;
    void *timer;
} DdaFrameClock;
typedef struct {
    int fresh_wait_us, dup_frames;
    int64_t source_present;
    unsigned source_accumulated;
    ID3D11Texture2D *buffer_texture;
    Duplication *dxgi_outdupl;
    DdaFrameClock frame_clock;
    int cursor_revision;
} DdagrabContext;
typedef struct { DdagrabContext *priv; } AVFilterContext;

enum EventKind { FRESH, POINTER, ACQUIRE_ERROR, ACQUIRED_ERROR };
typedef struct { int64_t at; enum EventKind kind; } Event;
static Event events[128];
static int event_count, event_next;
static int64_t now_us, timer_end, timer_lateness_us;
static int acquires, timer_sets, timer_waits, timer_error, log_errors;
static int timeouts[128], legacy_timeout;
static ID3D11Texture2D clean_buffer, fresh_texture;
static Duplication duplication;
static DdagrabContext context;
static AVFilterContext filter;

static int64_t dda_clock_ticks(void) { return now_us; }
static int64_t dda_clock_rescale(int64_t value, int64_t num, int64_t den)
{ return (value / den) * num + (value % den) * num / den; }
static int ID3D11Texture2D_AddRef(ID3D11Texture2D *texture)
{ assert(texture && texture->refs > 0); return ++texture->refs; }
static void release_resource(ID3D11Texture2D **texture)
{
    if (*texture) { assert((*texture)->refs > 0); --(*texture)->refs; *texture = NULL; }
}
static HRESULT IDXGIOutputDuplication_ReleaseFrame(Duplication *dup)
{
    assert(dup->owned); /* A duplicate release fails this test immediately. */
    dup->owned = 0;
    ++dup->releases;
    return dup->release_error ? -1 : 0;
}
static void av_log(AVFilterContext *ctx, int level, const char *message)
{ (void)ctx; (void)level; (void)message; ++log_errors; }
static int SetWaitableTimer(void *timer, LARGE_INTEGER *due, int period,
                            void *completion, void *argument, int resume)
{
    (void)timer; (void)period; (void)completion; (void)argument; (void)resume;
    assert(due->QuadPart < 0);
    ++timer_sets;
    if (timer_error) return 0;
    timer_end = now_us + (-due->QuadPart) / 10;
    return 1;
}
static int WaitForSingleObject(void *timer, unsigned timeout)
{
    (void)timer; assert(timeout == INFINITE);
    assert(timer_end >= now_us);
    now_us = timer_end + timer_lateness_us;
    ++timer_waits;
    return WAIT_OBJECT_0;
}

/* Test double for the existing helper's contract: success owns one lease and
 * returns one texture ref; errors release any acquired lease themselves.
 * Pointer-only success updates cursor state and returns the clean cache.
 * A 10 us call cost ensures immediate-event loops consume real time.
 */
static int next_frame_internal(AVFilterContext *avctx, ID3D11Texture2D **texture,
                               int need_frame, int timeout_override)
{
    DdagrabContext *dda = avctx->priv;
    int timeout = timeout_override < 0 ? legacy_timeout : timeout_override;
    int64_t end = now_us + timeout * 1000;
    Event event;
    assert(!need_frame);
    assert(!duplication.owned);
    assert(*texture == NULL);
    assert(acquires < 128);
    timeouts[acquires++] = timeout_override;
    dda->source_present = 0;
    dda->source_accumulated = 0;
    if (event_next >= event_count || events[event_next].at > end) {
        now_us = end + 10;
        return AVERROR(EAGAIN);
    }
    event = events[event_next++];
    if (event.at > now_us) now_us = event.at;
    now_us += 10;
    if (event.kind == ACQUIRE_ERROR) return AVERROR_EXTERNAL;
    duplication.owned = 1;
    if (event.kind == ACQUIRED_ERROR) {
        IDXGIOutputDuplication_ReleaseFrame(&duplication);
        return AVERROR_EXTERNAL;
    }
    if (event.kind == POINTER) {
        ++dda->cursor_revision;
        ID3D11Texture2D_AddRef(dda->buffer_texture);
        *texture = dda->buffer_texture;
    } else {
        dda->source_present = now_us - 1;
        dda->source_accumulated = 1;
        ID3D11Texture2D_AddRef(&fresh_texture);
        *texture = &fresh_texture;
    }
    return 0;
}

#include "fresh_wait_extracted.h"

static void reset(void)
{
    event_count = event_next = acquires = timer_sets = timer_waits = 0;
    timer_error = log_errors = 0;
    now_us = 1000000;
    timer_end = timer_lateness_us = 0;
    legacy_timeout = 0;
    memset(timeouts, 0, sizeof(timeouts));
    clean_buffer = (ID3D11Texture2D){1, 1};
    fresh_texture = (ID3D11Texture2D){1, 1};
    duplication = (Duplication){0};
    context = (DdagrabContext){.fresh_wait_us = 2000, .dup_frames = 1,
        .buffer_texture = &clean_buffer, .dxgi_outdupl = &duplication,
        .frame_clock = {.frequency = 1000000, .last_deadline = 1000000,
                        .source_phase = {.period = 10000}, .timer = (void *)1}};
    filter.priv = &context;
}
static void event(int offset, enum EventKind kind)
{ assert(event_count < 128); events[event_count++] = (Event){1000000 + offset, kind}; }
static int call(ID3D11Texture2D **texture, int *owned)
{ return next_frame_live(&filter, texture, regression_caller_deadline(&context), owned); }
static void cleanup(ID3D11Texture2D **texture, int owned)
{
    if (context.fresh_wait_us && context.dup_frames)
        for (int i = 0; i < acquires; ++i) assert(timeouts[i] == 0);
    if (*texture) release_resource(texture);
    if (owned) IDXGIOutputDuplication_ReleaseFrame(&duplication);
    assert(!duplication.owned && clean_buffer.refs == 1 && fresh_texture.refs == 1);
}
static void passed(const char *name)
{ printf("{\"test\":\"%s\",\"status\":\"passed\"}\n", name); }

int main(void)
{
    ID3D11Texture2D *texture;
    int owned, ret;

    reset(); texture = NULL; event(0, FRESH);
    ret = call(&texture, &owned);
    assert(ret == 0 && owned && texture == &fresh_texture && acquires == 1);
    assert(timeouts[0] == 0 && timer_waits == 0 && duplication.releases == 0);
    cleanup(&texture, owned); passed("immediately_fresh_no_wait");

    reset(); texture = NULL; event(200, FRESH);
    ret = call(&texture, &owned);
    assert(ret == 0 && owned && acquires == 2 && now_us == 1000270);
    assert(timeouts[0] == 0 && timeouts[1] == 0 && timer_waits == 1);
    cleanup(&texture, owned); passed("timeout_then_fresh");

    reset(); texture = NULL; event(0, POINTER); event(300, FRESH);
    ret = call(&texture, &owned);
    assert(ret == 0 && owned && texture == &fresh_texture && context.cursor_revision == 1);
    assert(duplication.releases == 1 && acquires == 3 && clean_buffer.refs == 1);
    cleanup(&texture, owned); assert(duplication.releases == 2);
    passed("pointer_then_fresh_single_release_per_lease");

    reset(); texture = NULL;
    for (int i = 0; i < 50; ++i) event(i * 100, POINTER);
    ret = call(&texture, &owned);
    assert(ret == 0 && !owned && texture == &clean_buffer && context.cursor_revision > 1);
    assert(now_us <= 1002010 && acquires == 9 && timer_waits == 8);
    assert(duplication.releases == event_next && !duplication.owned);
    cleanup(&texture, owned); passed("repeated_pointer_budget_not_reset");

    reset(); texture = NULL;
    ret = call(&texture, &owned);
    assert(ret == AVERROR(EAGAIN) && !owned && !texture);
    assert(now_us == 1002010 && acquires == 9 && timer_waits == 8);
    assert(timeouts[0] == 0 && timeouts[1] == 0 && timeouts[2] == 0);
    cleanup(&texture, owned); passed("static_source_finite_budget_no_spin");

    reset(); texture = NULL; event(0, POINTER);
    ret = call(&texture, &owned);
    assert(ret == 0 && !owned && texture == &clean_buffer && texture->clean);
    assert(context.cursor_revision == 1 && duplication.releases == 1 && !duplication.owned);
    assert(clean_buffer.refs == 2);
    cleanup(&texture, owned); assert(duplication.releases == 1);
    passed("clean_cached_cursor_fallback_without_lease");

    reset(); texture = NULL; event(0, ACQUIRE_ERROR);
    ret = call(&texture, &owned);
    assert(ret == AVERROR_EXTERNAL && !owned && !texture && duplication.releases == 0);
    cleanup(&texture, owned); passed("acquisition_error_no_release");

    reset(); texture = NULL; event(0, ACQUIRED_ERROR);
    ret = call(&texture, &owned);
    assert(ret == AVERROR_EXTERNAL && !owned && !texture && duplication.releases == 1);
    cleanup(&texture, owned); passed("internal_error_already_released");

    reset(); texture = NULL; event(0, POINTER); duplication.release_error = 1;
    ret = call(&texture, &owned);
    assert(ret == AVERROR_EXTERNAL && !owned && !texture && duplication.releases == 1);
    assert(log_errors == 1);
    cleanup(&texture, owned); passed("release_error_no_double_release");

    reset(); texture = NULL; timer_error = 1;
    ret = call(&texture, &owned);
    assert(ret == AVERROR_EXTERNAL && !owned && !texture && timer_sets == 1 && timer_waits == 0);
    cleanup(&texture, owned); passed("timer_failure_no_lease_leak");

    reset(); texture = NULL; context.fresh_wait_us = 0; event(0, POINTER);
    ret = call(&texture, &owned);
    assert(ret == 0 && owned && texture == &clean_buffer && acquires == 1);
    assert(timeouts[0] == -1 && timer_waits == 0 && duplication.releases == 0);
    cleanup(&texture, owned); passed("option_off_preserves_pointer_success");

    reset(); texture = NULL; context.dup_frames = 0; legacy_timeout = 1;
    ret = call(&texture, &owned);
    assert(ret == AVERROR(EAGAIN) && !owned && !texture && acquires == 1);
    assert(timeouts[0] == -1 && now_us == 1001010 && timer_waits == 0);
    cleanup(&texture, owned); passed("no_duplication_preserves_legacy_acquisition");

    reset(); context.fresh_wait_us = 5000;
    context.frame_clock.source_phase.period = 1000;
    assert(regression_caller_deadline(&context) == 1001000);
    texture = NULL; event(1500, FRESH);
    ret = call(&texture, &owned);
    assert(ret == AVERROR(EAGAIN) && !owned && !texture && now_us == 1001010);
    assert(event_next == 0);
    cleanup(&texture, owned); passed("caller_budget_clipped_at_next_slot");

    reset(); texture = NULL; event(2000, FRESH);
    ret = call(&texture, &owned);
    assert(ret == 0 && owned && texture == &fresh_texture && acquires == 9 && timer_waits == 8);
    assert(now_us == 1002010);
    cleanup(&texture, owned); passed("final_nonblocking_attempt_accepts_ready_image");

    reset(); texture = NULL; timer_lateness_us = 8000;
    ret = call(&texture, &owned);
    assert(ret == AVERROR(EAGAIN) && !owned && !texture);
    assert(acquires == 2 && timer_waits == 1 && now_us == 1008270);
    cleanup(&texture, owned); passed("late_timer_wake_does_not_restart_budget");

    reset(); texture = NULL; context.fresh_wait_us = 5000;
    ret = call(&texture, &owned);
    assert(ret == AVERROR(EAGAIN) && !owned && !texture);
    assert(acquires <= 22 && timer_waits < acquires && now_us == 1005010);
    cleanup(&texture, owned); passed("maximum_budget_bounded_poll_count");
    return 0;
}
