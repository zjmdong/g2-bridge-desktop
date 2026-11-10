"""JSON-lines worker process. Video bytes never enter the GUI process."""
from datetime import datetime
from functools import partial
import json
import sys
import threading
import traceback
import uuid

from goggles_bridge.engine import BridgeEngine, check_encoder
from goggles_bridge.usb_transport import DeviceNotFoundError, LinkSpeedError
from .device import probe, VerifiedTransport, CompatibilityError
from .paths import data_dir
from .settings import Settings
from .system import Cancelled, driver_status, environment, run_cancellable
from .video import start_encoder, check_capture


def main():
    if '--install-display-driver' in sys.argv or '--remove-display-driver' in sys.argv:
        from .virtual_driver import elevated_main
        return elevated_main('--remove-display-driver' in sys.argv)
    sys.stdout.reconfigure(encoding='utf-8', line_buffering=True)
    sys.stdin.reconfigure(encoding='utf-8')
    lock = threading.Lock()
    stop = threading.Event()

    def emit(event, **fields):
        with lock:
            print(json.dumps(dict(event=event, **fields), ensure_ascii=False), flush=True)

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
        elif task in ('display_status', 'enable_display', 'disable_display'):
            from .displays import enable_extended, disable_extended
            from .virtual_driver import status, owned_instance
            if task != 'display_status' and not owned_instance():
                raise ValueError('未找到由本客户端安装的扩展屏驱动。已有其他 VDD 时请在 Windows 中配置。')
            if task == 'enable_display':
                enable_extended()
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
                from .displays import select_source
                target = select_source(settings.source)
                bridge = settings.bridge(display_index=0)
                hmonitor = target['hmonitor'] if settings.capture == 'gfxcapture' else None
                if settings.capture == 'ddagrab' and settings.source != 'primary':
                    raise ValueError('兼容采集仅支持主显示器。')
                emit('capture_source', **target, source=settings.source,
                     color='limited NV12, unspecified H.264 VUI', profile='baseline', idr_seconds=1)
                emit('checking_capture')
                problem = check_encoder(bridge, run=partial(check_capture, stop=stop, hmonitor=hmonitor))
                if problem:
                    emit('problem', code='capture', message='桌面采集测试失败，请检查 NVIDIA 驱动或尝试兼容采集。', details=problem)
                    return 2
                if stop.is_set():
                    raise Cancelled()
                log = data_dir() / 'logs' / f'{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.jsonl'
                emit('log_path', path=str(log))

                def on_event(row):
                    # Binary protocol telemetry stays in the local log, not the UI pipe.
                    if row['event'] not in ('control_send', 'control_receive'):
                        if row['event'] == 'starting':
                            row = dict(row, intra_refresh=False, adapter='desktop-compatibility-v1')
                        emit(**row)

                engine = BridgeEngine(bridge, log, stop_event=stop, on_event=on_event,
                    reconnect=settings.reconnect, retry_delay=2,
                    process_factory=partial(start_encoder, hmonitor=hmonitor),
                    transport_factory=partial(VerifiedTransport, stop=stop, emit=emit,
                                              write_size=bridge.usb_write_size))
                engine.run()
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
    return 0
