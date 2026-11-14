"""Windows capture compatibility adapter at the SDK's public process boundary.

USB packet framing remains unchanged. Capture uses DXGI and an
explicit GPU RGB -> limited-range NV12 conversion. NVIDIA NVENC is the only encoder;
failure is reported without a software fallback. The SDK frame-size guard stays.
"""
import subprocess
import re

from .system import run_cancellable
from .scheduling import configure_encoder_process
from .encoding import H264_PROFILE, H264_ENTROPY_CODER, H264_CHROMA_QP_OFFSET

ENCODER_PRIORITY = getattr(subprocess, 'ABOVE_NORMAL_PRIORITY_CLASS', 0)
# One capture clock also supplies the native muxer's absolute release deadline.
# The offset includes capture/encode work; only its remaining budget is waited.
FRESH_WAIT_US = 2000
DELIVERY_DELAY_US = 8000


def frame_selection(fps):
    """Legacy SDK WGC admission rule, retained for the 0.2.2 research checks.

    Current desktop DDA capture uses its own native deadline clock instead.
    Compact timestamps prevent CFR/AVI from replaying old images after a stall.
    A slow source stays slow; inventing frames cannot reduce picture age.
    """
    if fps not in (60, 75, 90, 100):
        raise ValueError('Unsupported stream frame rate')
    return ("select='if(isnan(prev_selected_pts),st(0,pts*TB);1,"
            "if(gte((pts+0.5)*TB,ld(0)),"
            f"st(0,max(ld(0)+1/{fps},pts*TB));1,0))',"
            f'setpts=N/({fps}*TB):strip_fps=1')


def compatible_command(command, *, hmonitor=None, output=None, dimensions=(1920, 1080)):
    result = list(command)
    if '-c:v' not in result or result[result.index('-c:v')+1] != 'h264_nvenc':
        raise ValueError('Unsupported desktop encoder')
    # FFmpeg's periodic stderr progress otherwise writes synchronously to disk.
    result[result.index('-loglevel')+1] = 'warning'
    result[1:1] = ['-nostats']
    source_index = result.index('-i')+1
    source = result[source_index]
    width, height = dimensions
    if dimensions not in ((1280, 720), (1920, 1080)):
        raise ValueError('Unsupported stream dimensions')
    if source.startswith('ddagrab='):
        if hmonitor is not None:
            raise ValueError('Desktop Duplication requires a DXGI adapter/output identity')
        if output is not None:
            result[source_index] = re.sub(r'output_idx=\d+', f"output_idx={output['output']}", source)
            result[1:1] = ['-init_hw_device', f"d3d11va=cap:{output['adapter']}", '-filter_hw_device', 'cap']
        source_index = result.index('-i')+1
        result[source_index] += (':output_fmt=bgra:dup_frames=1:precise_clock=1:'
                                 'acquire_timeout=0:clock_spin_us=500:'
                                 'source_clock=1:source_guard_us=3000:'
                                 f'fresh_wait_us={FRESH_WAIT_US}:'
                                 f'delivery_delay_us={DELIVERY_DELAY_US}')
        filter_index = result.index('-vf')+1
        # The pinned FFmpeg patch fixes D3D11 texture views and explicitly
        # converts full-range SDR RGB to limited BT.709, with aspect-fit padding.
        # No per-frame GPU download, CPU scale or upload on the NVIDIA path.
        if output is None or output.get('vendor_id', 0x10de) == 0x10de:
            result[filter_index] = (f'scale_d3d11=width={width}:height={height}:'
                                    'format=nv12:desktop_sdr=1')
            if output and 0 < output.get('width', 0) < width and 0 < output.get('height', 0) < height:
                # This NVIDIA processor colours chroma edges when RGB is
                # enlarged and subsampled in the same blit. Enlarge RGB first;
                # perform NV12 conversion at 1:1. Normal/downscale use one blit.
                result[filter_index] = (f'scale_d3d11=width={width}:height={height}:'
                                       'format=bgra:desktop_sdr=1,' + result[filter_index])
        else:
            # NVENC cannot register another vendor's D3D11 device. A hybrid
            # laptop still uses NVIDIA encoding, with an explicit CPU transfer.
            # With software NV12 input, FFmpeg picks CUDA before D3D11 for
            # NVENC. Supply a separate NVIDIA context so it cannot accidentally
            # reuse the foreign capture device. Filters remain bound to cap.
            result[1:1] = ['-init_hw_device', 'cuda=enc:0']
            filter_index = result.index('-vf')+1
            result[filter_index] = (f'hwdownload,format=bgra,scale={width}:{height}:'
                'force_original_aspect_ratio=decrease:flags=bilinear:in_range=pc:'
                f'out_color_matrix=bt709:out_range=tv,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,format=nv12')
    else:
        raise ValueError('Unsupported desktop capture source')

    # Firmware 01.14 requires the colour-description-free SPS verified in 0.1.
    # Keep conversion explicit without changing that decoder compatibility.
    result[filter_index] += (',setsar=1,setparams=range=limited:'
                             'color_primaries=unknown:color_trc=unknown:colorspace=unknown')
    if source.startswith('ddagrab='):
        # The SDK's GOP is fps * keyframe_seconds; source carries the actual rate.
        fps = re.search(r'framerate=(\d+)', source).group(1)
        # DDA owns the only cadence clock and gently aligns it to genuine source
        # updates when their measured rate matches. The 3 ms source guard and
        # bounded fresh-image retry avoid copying a near-ready previous image.
        # The native muxer uses this same capture deadline plus the delivery
        # offset, waits only the remainder, and sends late packets immediately.
        # Compact PTS prevent CFR from replaying missed capture slots.
        result[filter_index] = f'setpts=N/({fps}*TB):strip_fps=1,' + result[filter_index]
        live = '-frames:v' not in result
        result[-3:-3] = ['-r', fps, '-fps_mode', 'passthrough' if live else 'cfr']
        if live:
            # A single raw-frame mailbox replaces stale unencoded pictures.
            # The encoder compacts admitted PTS; encoded reference frames are
            # never discarded. Native delivery uses the existing single-packet
            # output queue; the SDK sends each released frame immediately.
            result[-3:-3] = ['-latest_frame', '1']
    # Keep the SDK's NVIDIA encoder, P1/P4 preset, ULL tuning and CBR/VBV budget.
    # Quarter-resolution multipass is needed for the SDK's tight frame budget.
    # Keep periodic intra refresh disabled to avoid the observed display pulses.
    for option, value in (('-intra-refresh', '0'),
                          ('-single-slice-intra-refresh', '0')):
        result[result.index(option)+1] = value
    # High/CABAC uses the same 8-bit NV12 input and no frame reordering. The
    # early Baseline workaround needlessly spent the fixed bitrate on less
    # efficient coding, especially during motion. Preserve colour-VUI handling.
    result[result.index('-profile:v')+1] = H264_PROFILE
    # Repeat headers during decoder startup, then avoid periodic full-IDR pulses.
    # USB is ordered/reliable; SDK recovery restarts this bootstrap on link loss.
    result[result.index('-g')+1] = '1000000'
    result[-3:-3] = ['-coder', H264_ENTROPY_CODER,
                     '-qp_cb_offset', str(H264_CHROMA_QP_OFFSET),
                     '-qp_cr_offset', str(H264_CHROMA_QP_OFFSET),
                     '-async_encode', '1', '-force_key_frames', '0,1,2', '-refs', '1',
                     '-rc-lookahead', '0', '-no-scenecut', '1',
                     '-color_range', 'tv', '-color_primaries', 'unknown',
                     '-color_trc', 'unknown', '-colorspace', 'unknown']
    # Pull the capture source directly inside the processing graph. A lavfi
    # demuxer input introduces wrapped-frame packet/decoder queues before the
    # selector; a full queue can retain several old GPU textures under load.
    # These are raw capture frames, not encoded references that can be dropped.
    input_index = result.index('-i')
    if result[input_index-2:input_index] != ['-f', 'lavfi']:
        raise ValueError('Expected an SDK lavfi desktop source')
    capture_source = result[input_index+1]
    del result[input_index-2:input_index+2]
    filter_index = result.index('-vf')
    filters = result[filter_index+1]
    result[filter_index:filter_index+2] = [
        '-filter_complex', capture_source + ',' + filters + '[desktop]',
        '-map', '[desktop]']
    return result


def start_encoder(command, *, hmonitor=None, output=None, dimensions=(1920, 1080), **kwargs):
    kwargs['creationflags'] = kwargs.get('creationflags', 0) | ENCODER_PRIORITY
    process = subprocess.Popen(compatible_command(command, hmonitor=hmonitor, output=output, dimensions=dimensions), **kwargs)
    process.desktop_scheduling = configure_encoder_process(process)
    return process


def check_capture(command, *, stop, hmonitor=None, output=None, dimensions=(1920, 1080), **kwargs):
    return run_cancellable(compatible_command(command, hmonitor=hmonitor, output=output, dimensions=dimensions), stop, **kwargs)
