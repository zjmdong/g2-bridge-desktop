"""Extract and test the actual DDA fresh-acquisition control flow (CPU only).

Two reusable source files are needed: this script and check_fresh_wait.c.
All generated headers, copied mock source, reports and binaries stay in the
explicit output directory. No source checkout or GPU is modified/opened.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess

EXPECTED_TESTS = {
    'immediately_fresh_no_wait', 'timeout_then_fresh',
    'pointer_then_fresh_single_release_per_lease',
    'repeated_pointer_budget_not_reset', 'static_source_finite_budget_no_spin',
    'clean_cached_cursor_fallback_without_lease', 'acquisition_error_no_release',
    'internal_error_already_released', 'release_error_no_double_release',
    'timer_failure_no_lease_leak', 'option_off_preserves_pointer_success',
    'no_duplication_preserves_legacy_acquisition', 'caller_budget_clipped_at_next_slot',
    'final_nonblocking_attempt_accepts_ready_image',
    'late_timer_wake_does_not_restart_budget', 'maximum_budget_bounded_poll_count',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def unique_offset(data, marker, start=0):
    if data.count(marker, start) != 1:
        raise ValueError('Source layout changed; expected one marker: ' + marker.decode())
    return data.index(marker, start)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True,
                        help='Patched source checkout libavfilter/vsrc_ddagrab.c')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--cc', default='gcc')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / 'fresh-wait-mock-report.json'
    # A failed rerun must not leave an earlier passing result looking current.
    report_path.write_text(json.dumps({'status': 'preparing', 'source': source.name,
                                      'compiled': False}) + '\n', encoding='utf-8')
    data = source.read_bytes()
    if b'\r' in data:
        raise ValueError('Use the LF source produced by the pinned source archive/patch recipe')
    start = unique_offset(data, b'static int next_frame_live(')
    end = unique_offset(data, b'static int probe_output_format(', start)
    function = data[start:end]
    request = unique_offset(data, b'static int ddagrab_request_frame(')
    block_start = unique_offset(data, b'    if (dda->fresh_wait_us) {\n', request)
    block_end = unique_offset(data, b'    if (!dda->first_pts)\n', block_start)
    caller = data[block_start:block_end]
    header = (b'/* Generated exact candidate function and caller deadline block. */\n'
              + function + b'\nstatic int64_t regression_caller_deadline(DdagrabContext *dda)\n{\n'
              + b'    int64_t fresh_deadline = 0;\n' + caller
              + b'    return fresh_deadline;\n}\n')
    (output / 'fresh_wait_extracted.h').write_bytes(header)
    mock = Path(__file__).with_name('check_fresh_wait.c').read_bytes()
    # Copying beside the generated header prevents a historical sibling header
    # from taking precedence over the intended build directory's include path.
    (output / 'check_fresh_wait.c').write_bytes(mock)
    report = {
        'scope': 'CPU-only mock API/clock model; exact extracted candidate control flow, no desktop/GPU/USB calls',
        'source': source.name, 'source_sha256': sha(data),
        'function_byte_range': [start, end], 'function_sha256': sha(function),
        'caller_block_byte_range': [block_start, block_end], 'caller_block_sha256': sha(caller),
        'generated_header_sha256': sha(header), 'mock_source_sha256': sha(mock),
        'compiled': False, 'status': 'prepared',
        'limits': [
            'Mock next_frame_internal specifies its lease/texture contract; it is not real DXGI or GPU timing.',
            'Deterministic timer wakes cannot prove Windows scheduling deadlines.',
            'No native source is rewritten; function and caller deadline block are copied byte-for-byte.',
        ],
    }
    report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    if args.run:
        found = shutil.which(args.cc) if not Path(args.cc).is_file() else args.cc
        if not found:
            raise FileNotFoundError('Compiler not found: ' + args.cc)
        compiler = Path(found).resolve(strict=True)
        environment = dict(os.environ)
        environment['PATH'] = str(compiler.parent) + os.pathsep + environment.get('PATH', '')
        executable = output / 'check_fresh_wait.exe'
        command = [str(compiler), '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-UNDEBUG',
                   str(output / 'check_fresh_wait.c'), '-o', str(executable)]
        build = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=30)
        if build.returncode:
            raise RuntimeError(f'Compiler exited {build.returncode}:\n{build.stdout}\n{build.stderr}')
        completed = subprocess.run([str(executable)], env=environment, capture_output=True, text=True, timeout=10)
        if completed.returncode:
            raise RuntimeError(f'Test exited {completed.returncode}:\n{completed.stdout}\n{completed.stderr}')
        tests = [json.loads(line) for line in completed.stdout.splitlines() if line]
        if len(tests) != len(EXPECTED_TESTS) or {row.get('test') for row in tests} != EXPECTED_TESTS:
            raise ValueError('Missing, duplicate, or unexpected test results')
        if any(row.get('status') != 'passed' for row in tests):
            raise ValueError('One or more mock tests did not pass')
        version = subprocess.check_output([str(compiler), '-dumpfullversion'],
                                          env=environment, text=True, timeout=10).strip()
        report.update(compiled=True, status='passed', compiler_version=version, tests=tests,
                      passed=len(tests), executable_sha256=sha(executable.read_bytes()))
    report_path.write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
