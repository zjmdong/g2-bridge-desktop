"""Windows capture compatibility adapter at the SDK's public process boundary.

The SDK and its USB packet framing remain unchanged. Capture uses DXGI and an
explicit RGB -> limited-range NV12 conversion. Software H.264 avoids the observed
NVENC/Goggles 2 grey-block corruption, while retaining the SDK frame-size guard.
"""
import subprocess
import re

from .system import run_cancellable


def compatible_command(command, *, hmonitor=None, output=None, dimensions=(1920, 1080)):
    result = list(command)
    if '-c:v' not in result or result[result.index('-c:v')+1] != 'h264_nvenc':
        raise ValueError('Unsupported desktop encoder')
    source_index = result.index('-i')+1
    source = result[source_index]
    width, height = dimensions
    if dimensions not in ((1280, 720), (1920, 1080)):
        raise ValueError('Unsupported stream dimensions')
    if source.startswith('gfxcapture='):
        if hmonitor is not None:
            # Use the actual monitor handle; enumeration order can change on hotplug.
            source = source.replace(source.split(':', 1)[0], f'gfxcapture=hmonitor={int(hmonitor)}', 1)
            result[source_index] = source
        result[source_index] = result[source_index].replace('width=1920:height=1080', f'width={width}:height={height}') + ':display_border=0:output_fmt=bgra'
        filter_index = result.index('-vf')+1
        result[filter_index] += (',hwdownload,format=bgra,'
                                'scale=iw:ih:in_range=pc:out_color_matrix=bt709:out_range=tv,format=nv12')
    elif source.startswith('ddagrab='):
        if hmonitor is not None:
            raise ValueError('Desktop Duplication requires a DXGI adapter/output identity')
        if output is not None:
            result[source_index] = re.sub(r'output_idx=\d+', f"output_idx={output['output']}", source)
            result[1:1] = ['-init_hw_device', f"d3d11va=cap:{output['adapter']}", '-filter_hw_device', 'cap']
        source_index = result.index('-i')+1
        result[source_index] = re.sub(r'framerate=\d+', 'framerate=240', result[source_index])
        result[source_index] += ':output_fmt=bgra:dup_frames=1'
        filter_index = result.index('-vf')+1
        result[filter_index] = result[filter_index].replace(
            'flags=fast_bilinear', 'flags=bilinear:in_range=pc:out_color_matrix=bt709:out_range=tv')
        result[filter_index] = result[filter_index].replace('1920:1080', f'{width}:{height}')
    else:
        raise ValueError('Unsupported desktop capture source')

    # Firmware 01.14 requires the colour-description-free SPS verified in 0.1.
    # Keep conversion explicit without changing that decoder compatibility.
    result[filter_index] += (',setsar=1,setparams=range=limited:'
                             'color_primaries=unknown:color_trc=unknown:colorspace=unknown')
    if source.startswith('ddagrab='):
        # The SDK's GOP is fps * keyframe_seconds; source carries the actual rate.
        fps = re.search(r'framerate=(\d+)', source).group(1)
        # Sample DXGI frequently, then select pictures by their wall-clock PTS.
        # Compacting capture timestamps made 100 fps run at ~72 fps on this host.
        result[filter_index] = f'fps={fps}:round=near,' + result[filter_index]
        result[-3:-3] = ['-r', fps, '-fps_mode', 'cfr']
    preset = result[result.index('-preset')+1]
    for option in ('-rc', '-zerolatency', '-delay', '-multipass', '-intra-refresh',
                   '-single-slice-intra-refresh'):
        index = result.index(option)
        del result[index:index+2]
    result[result.index('-c:v')+1] = 'libx264'
    result[result.index('-profile:v')+1] = 'baseline'
    result[result.index('-preset')+1] = 'ultrafast' if preset == 'p1' else 'veryfast'
    result[result.index('-tune')+1] = 'zerolatency'
    # Repeat headers during decoder startup, then avoid periodic full-IDR pulses.
    # USB is ordered/reliable; SDK recovery restarts this bootstrap on link loss.
    result[result.index('-g')+1] = '1000000'
    result[-3:-3] = ['-force_key_frames', '0,1,2', '-refs', '1',
                     '-x264-params', 'scenecut=0:repeat-headers=1:force-cfr=1',
                     '-color_range', 'tv', '-color_primaries', 'unknown',
                     '-color_trc', 'unknown', '-colorspace', 'unknown']
    return result


def start_encoder(command, *, hmonitor=None, output=None, dimensions=(1920, 1080), **kwargs):
    return subprocess.Popen(compatible_command(command, hmonitor=hmonitor, output=output, dimensions=dimensions), **kwargs)


def check_capture(command, *, stop, hmonitor=None, output=None, dimensions=(1920, 1080), **kwargs):
    return run_cancellable(compatible_command(command, hmonitor=hmonitor, output=output, dimensions=dimensions), stop, **kwargs)
