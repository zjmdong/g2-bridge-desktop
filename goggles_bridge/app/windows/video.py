"""Adapt the SDK command to native DDA capture without changing USB framing."""
import re
import subprocess

from ...engine import WIDTH, HEIGHT
from .scheduling import configure_encoder_process
from .system import run_cancellable


def compatible_command(command, *, output):
    result = list(command)
    input_index = result.index('-i')
    source = result[input_index+1]
    if (not source.startswith('ddagrab=') or result[input_index-2:input_index] != ['-f', 'lavfi']
            or result[result.index('-c:v')+1] != 'h264_nvenc'):
        raise ValueError('Native capture requires Desktop Duplication and NVIDIA NVENC')
    fps = re.search(r'framerate=(\d+)', source).group(1)
    source = re.sub(r'output_idx=\d+', f"output_idx={output['output']}", source)
    source += (':output_fmt=bgra:dup_frames=1:precise_clock=1:acquire_timeout=0:'
               'clock_spin_us=500:source_clock=1:source_guard_us=3000:'
               'fresh_wait_us=2000:delivery_delay_us=8000')
    devices = ['-init_hw_device', f"d3d11va=cap:{output['adapter']}", '-filter_hw_device', 'cap']
    if output['vendor_id'] == 0x10de:
        filters = f'scale_d3d11=width={WIDTH}:height={HEIGHT}:format=nv12:desktop_sdr=1'
        # Enlarge RGB before chroma subsampling to avoid coloured edges.
        if output['width'] < WIDTH and output['height'] < HEIGHT:
            filters = f'scale_d3d11=width={WIDTH}:height={HEIGHT}:format=bgra:desktop_sdr=1,' + filters
    else:
        # NVENC cannot register another vendor's D3D11 device.
        devices[:0] = ['-init_hw_device', 'cuda=enc:0']
        filters = (f'hwdownload,format=bgra,scale={WIDTH}:{HEIGHT}:'
                   'force_original_aspect_ratio=decrease:flags=bilinear:in_range=pc:'
                   f'out_color_matrix=bt709:out_range=tv,pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=nv12')
    filters = (f'setpts=N/({fps}*TB):strip_fps=1,' + filters +
               ',setsar=1,setparams=range=limited:color_primaries=unknown:color_trc=unknown:colorspace=unknown')
    del result[input_index-2:input_index+2]
    index = result.index('-vf')
    # A direct source avoids the lavfi demuxer/decoder queues of old GPU textures.
    result[index:index+2] = ['-filter_complex', source+','+filters+'[desktop]', '-map', '[desktop]']
    result[1:1] = ['-nostats', *devices]
    result[result.index('-loglevel')+1] = 'warning'
    result[result.index('-intra-refresh')+1] = '0'
    live = '-frames:v' not in result
    result[-3:-3] = ['-r', fps, '-fps_mode', 'passthrough' if live else 'cfr']
    if live:
        result[-3:-3] = ['-latest_frame', '1']  # Replace only unencoded frames.
    profile = result[result.index('-profile:v')+1]
    result[-3:-3] = ['-coder', 'cabac' if profile == 'high' else 'cavlc',
                     '-qp_cb_offset', '-4', '-qp_cr_offset', '-4',
                     '-async_encode', '1', '-refs', '1', '-rc-lookahead', '0', '-no-scenecut', '1',
                     '-color_range', 'tv', '-color_primaries', 'unknown',
                     '-color_trc', 'unknown', '-colorspace', 'unknown']
    return result


def start_encoder(command, *, output, **kwargs):
    kwargs['creationflags'] = kwargs.get('creationflags', 0) | subprocess.ABOVE_NORMAL_PRIORITY_CLASS
    process = subprocess.Popen(compatible_command(command, output=output), **kwargs)
    configure_encoder_process(process)
    return process


def check_capture(command, *, stop, output, **kwargs):
    return run_cancellable(compatible_command(command, output=output), stop, **kwargs)
