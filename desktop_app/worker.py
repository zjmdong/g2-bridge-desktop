"""JSON-lines worker process. Video bytes never enter the GUI process."""
from datetime import datetime
from functools import partial
import json
import sys
import threading
import traceback
import uuid

from goggles_bridge.engine import check_encoder
from goggles_bridge.usb_transport import DeviceNotFoundError, LinkSpeedError
from .device import probe, VerifiedTransport, CompatibilityError
from .paths import data_dir
from .settings import Settings
from .system import Cancelled, driver_status, environment, run_cancellable
from .video import start_encoder, check_capture
from .stream_engine import DesktopBridgeEngine


def stream(settings, stop, emit):
    from .display_session import capture_target
    from .dxgi import select_output
    from .telemetry import SenderTelemetry
    # Confirm the device exists before creating a desktop. VerifiedTransport also
    # checks the very handle the SDK will use, including after reconnects.
    found = probe(stop, emit)
    if not found['compatibility']['allowed']:
        raise CompatibilityError(found['compatibility']['message'])
    if stop.is_set():
        raise Cancelled()
    with capture_target(settings, emit) as target:
        output = select_output(target['device'])
        bridge = settings.bridge(display_index=output['output'])
        options = dict(output=output, dimensions=settings.dimensions)
        emit('capture_source', **target, source=settings.source,
             color='8-bit limited NV12 / BT.709', profile='baseline', encoder='h264_nvenc',
             capture='Desktop Duplication', output_resolution=f'{settings.dimensions[0]}x{settings.dimensions[1]}',
             bootstrap_idr_seconds=[0,1,2], periodic_idr=False, reference_frames=1,
             capture_sampling_fps=settings.fps, frame_selection='native deadline / latest desktop',
             capture_clock='QPC / high-resolution timer', clock_spin_us=500,
             raw_frame_policy='latest waiting frame', nvenc_completion='Windows async event',
             color_pipeline='D3D11 GPU' if output['vendor_id'] == 0x10de else 'CPU transfer to NVIDIA',
             sender_pacing=False, capture_gpu=output.get('gpu_name'),
             capture_adapter_luid=output.get('adapter_luid'))
        emit('checking_capture')
        problem = check_encoder(bridge, run=partial(check_capture, stop=stop, **options))
        if problem:
            emit('problem', code='capture', message='无边框桌面采集失败，请保持桌面解锁并检查显示驱动。', details=problem)
            return 2
        if stop.is_set():
            raise Cancelled()
        log = data_dir() / 'logs' / f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'
        emit('log_path', path=str(log))

        def on_event(row):
            if row['event'] not in ('control_send', 'control_receive', 'stats'):
                if row['event'] == 'starting':
                    # DesktopBridgeEngine journals this same row after callback.
                    # Persist the adapter policy, not the SDK's unchanged defaults.
                    row.update(intra_refresh=False, multipass='qres', encoder='h264_nvenc',
                               adapter='desktop-native-latest-v4',
                               nvenc_async=True, raw_frame_queue='latest single slot',
                               sender_pacing=False, input_graph='direct',
                               resolution=f'{settings.dimensions[0]}x{settings.dimensions[1]}')
                emit(**row)

        telemetry = SenderTelemetry(emit)
        def encoder_factory(command, **kwargs):
            process = start_encoder(command, **options, **kwargs)
            emit('encoder_scheduling', encoder_pid=process.pid,
                 cpu_priority='above_normal', **process.desktop_scheduling)
            return process
        # The GUI has a separate presence worker. A failed SDK session also
        # checks presence once, so streaming does not enumerate PnP every 250 ms.
        telemetry.start()
        try:
            engine = DesktopBridgeEngine(bridge, log, stop_event=stop, on_event=on_event,
                reconnect=settings.reconnect, retry_delay=2,
                process_factory=encoder_factory,
                transport_factory=partial(VerifiedTransport, stop=stop, emit=emit,
                                          write_size=bridge.usb_write_size, telemetry=telemetry))
            engine.run()
        finally:
            telemetry.close()
    return 0


def main():
    if '--install-display-driver' in sys.argv or '--remove-display-driver' in sys.argv:
        from .virtual_driver import elevated_main
        return elevated_main('--remove-display-driver' in sys.argv)
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stdin.reconfigure(encoding='utf-8')
    stop = threading.Event()
    from .events import EventWriter
    writer = EventWriter(sys.stdout)
    emit = writer.emit

    def commands():
        for line in sys.stdin:
            try:
                if json.loads(line).get('command') == 'stop':
                    stop.set()
            except (ValueError, AttributeError):
                pass
        stop.set()  # Parent gone: release the transport and encoder.

    try:
        request = json.loads(sys.stdin.readline())
        task = request.get('command')
        threading.Thread(target=commands, daemon=True).start()
        if task == 'environment':
            from .virtual_driver import status
            emit('environment', **environment(stop), virtual_display=status())
        elif task == 'watch_usb':
            from .usb_presence import watch
            watch(stop, emit)
        elif task in ('display_status', 'enable_display', 'disable_display'):
            from .displays import enable_extended, disable_extended
            from .virtual_driver import status, owned_instance
            if task != 'display_status' and not owned_instance():
                raise ValueError('未找到由本客户端安装的扩展屏驱动。已有其他 VDD 时请在 Windows 中配置。')
            if task == 'enable_display':
                settings = Settings.from_dict(request.get('settings', {}))
                enable_extended(*settings.dimensions, settings.fps)
            elif task == 'disable_display':
                disable_extended()
            emit('display_status', **status())
        elif task in ('probe', 'stream'):
            if driver_status()['status'] != 'verified':
                emit('problem', code='driver', message=driver_status()['message'])
                return 2
            if task == 'probe':
                from .virtual_driver import status
                emit('display_status', **status())
                probe(stop, emit)
            else:
                settings = Settings.from_dict(request.get('settings', {}))
                return stream(settings, stop, emit)
        elif task in ('download_driver', 'import_driver'):
            from .drivers import download_assistant, prepare_driver
            installer = download_assistant(stop, emit) if task == 'download_driver' else request['path']
            path = prepare_driver(installer, stop, emit)
            emit('driver_prepared', path=str(path))
        else:
            raise ValueError('Unknown worker command')
    except Cancelled:
        emit('cancelled')
    except DeviceNotFoundError:
        emit('problem', code='not_connected', message='等待眼镜连接。请开机并使用支持数据传输的 USB 线。')
        return 3
    except LinkSpeedError:
        emit('problem', code='usb_speed', message='USB 当前速度不足。请更换数据线或 USB 接口后重试。')
        return 3
    except CompatibilityError as exc:
        emit('problem', code='firmware', message=str(exc))
        return 3
    except Exception as exc:
        emit('problem', code='worker', message=str(exc), details=traceback.format_exc()[-4000:])
        return 1
    finally:
        emit('finished')
        writer.close()
    return 0
