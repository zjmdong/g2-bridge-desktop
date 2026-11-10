"""Own the virtual desktop for exactly the duration of a stream."""
from contextlib import contextmanager
from . import displays, virtual_driver


@contextmanager
def capture_target(settings, emit):
    owned = False
    try:
        if settings.source == 'extended':
            state = virtual_driver.status()
            if not state['owned']:
                raise RuntimeError('请先安装本客户端的扩展屏驱动，以便自动管理串流桌面。')
            if state.get('needs_update'):
                raise RuntimeError('请先更新扩展屏驱动配置，以启用 720p/1080p 和四档刷新率。')
            emit('preparing_display')
            displays.enable_extended(*settings.dimensions, settings.fps)
            owned = True
            emit('display_status', **virtual_driver.status())
        yield displays.select_source(settings.source, *settings.dimensions, settings.fps)
    finally:
        if owned:
            emit('releasing_display')
            displays.disable_extended()
            emit('display_status', **virtual_driver.status())
