"""Retired 0.2.2 selector experiment; this is not a latency measurement.

The original experiment remains in Git at commit f3d8912 (0.2.2). Version 0.2.3 uses
a native capture clock and latest-frame mailbox, so its old synthetic selector
checks cannot validate the current pipeline. Refuse to emit a misleading pass.
"""
import sys


if __name__ == '__main__':
    sys.exit('This 0.2.2 experiment is retired. Use check_gpu_pipeline.py for '
             'generated pixel/codec checks, check_stability.py for opt-in host '
             'capture timing, and ffmpeg/build.sh for native clock/mailbox tests. '
             'None of these measures optical end-to-end latency.')
