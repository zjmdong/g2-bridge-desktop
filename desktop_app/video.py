"""Windows capture compatibility adapter at the SDK's public process boundary.

The SDK and its USB packet framing remain unchanged. Desktop RGB textures need an
explicit RGB -> limited-range NV12 conversion: letting NVENC convert them carries
sRGB transfer metadata into the H.264 stream on some multi-GPU systems.
"""
import subprocess

from .system import run_cancellable


def compatible_command(command, *, hmonitor=None):
    result = list(command)
    if '-c:v' not in result or result[result.index('-c:v')+1] != 'h264_nvenc':
        raise ValueError('Unsupported desktop encoder')
    source_index = result.index('-i')+1
    source = result[source_index]
    if source.startswith('gfxcapture='):
        if hmonitor is not None:
            # Use the actual monitor handle; enumeration order can change on hotplug.
            source = source.replace(source.split(':', 1)[0], f'gfxcapture=hmonitor={int(hmonitor)}', 1)
            result[source_index] = source
        filter_index = result.index('-vf')+1
        result[filter_index] += (',hwdownload,format=bgra,'
                                'scale=iw:ih:out_color_matrix=bt709:out_range=tv,format=nv12')
    elif source.startswith('ddagrab='):
        if hmonitor is not None:
            raise ValueError('扩展屏请使用 Windows Graphics Capture。')
        filter_index = result.index('-vf')+1
        result[filter_index] = result[filter_index].replace(
            'flags=fast_bilinear', 'flags=fast_bilinear:out_color_matrix=bt709:out_range=tv')
    else:
        raise ValueError('Unsupported desktop capture source')

    # Match the colour-description-free SPS of the clip displayed on Goggles 2
    # 01.14.0000. Conversion above still uses an explicit HD colour matrix.
    result[filter_index] += (',setsar=1,setparams=range=limited:'
                             'color_primaries=unknown:color_trc=unknown:colorspace=unknown')
    for option, value in (('-profile:v', 'baseline'), ('-intra-refresh', '0'),
                          ('-single-slice-intra-refresh', '0')):
        result[result.index(option)+1] = value
    # Force recurring IDRs; setting intra-refresh=0 alone did not produce them
    # with the SDK's other NVENC flags on the tested driver.
    result[-3:-3] = ['-force_key_frames', 'expr:gte(t,n_forced)',
                     '-color_range', 'tv', '-color_primaries', 'unknown',
                     '-color_trc', 'unknown', '-colorspace', 'unknown']
    return result


def start_encoder(command, *, hmonitor=None, **kwargs):
    return subprocess.Popen(compatible_command(command, hmonitor=hmonitor), **kwargs)


def check_capture(command, *, stop, hmonitor=None, **kwargs):
    return run_cancellable(compatible_command(command, hmonitor=hmonitor), stop, **kwargs)
