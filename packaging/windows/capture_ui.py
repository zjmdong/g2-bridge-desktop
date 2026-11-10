"""Capture actual Qt widgets for visual review. Simulated states are labeled here."""
from pathlib import Path
import os
import sys
import tempfile
import threading

# Development rendering uses an isolated offscreen Qt platform, never desktop input.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFontDatabase
from PySide6.QtTest import QTest
from desktop_app.ui import MainWindow
from desktop_app.system import environment
from desktop_app.compatibility import assess

app = QApplication([])
if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
    for name in ('msyh.ttc', 'segoeui.ttf'):
        QFontDatabase.addApplicationFont(str(Path(os.environ['SystemRoot'])/'Fonts'/name))
app.setStyle('Fusion')
folder = ROOT/'.impeccable/review'
folder.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as data:
    os.environ['GOGGLES_STREAMER_DATA_DIR'] = data
    window = MainWindow(autostart_checks=False)
    window.on_event(dict(event='environment', **environment(threading.Event())))
    window.show()
    for width, height, prefix in ((1120, 800, 'desktop'), (920, 680, 'compact')):
        window.resize(width, height)
        for index, name in enumerate(('stream', 'device', 'help')):
            window.navigate(index)
            QTest.qWait(150)
            window.grab().save(str(folder/f'{prefix}-{name}.png'))
    # Fixtures only: no USB claim or physical stream is made by this renderer.
    window.on_event(dict(event='environment', os='Windows x64', gpu=[dict(Name='Display adapter fixture')],
        encoder_ok=True, supported_os=True, encoder_message='NVIDIA NVENC 硬件编码测试通过',
        driver=dict(status='verified', title='DJI USB 组件已验证', message='连接时检查设备接口与驱动绑定。')))
    window.source.setCurrentIndex(window.source.findData('extended'))
    window.fps.setCurrentIndex(window.fps.findData(100))
    window.virtual_state = dict(owned=True, installed=True, config_current=True,
        displays=[dict(active=True,primary=False,width=1920,height=1080,hz=100)])
    window.on_event(dict(event='device', model='DJI Goggles 2', firmware='01.14.0000',
        usb='USB 2.0 High Speed · 512 B Bulk', interface='MI04', compatibility=assess('DJI Goggles 2', '01.14.0000')))
    window.controller.task = 'stream'
    window.on_event(dict(event='streaming'))
    window.on_event(dict(event='live_stats', fps=99.9, send_ms=.28, bandwidth_mbps=31.5))
    for width, height, prefix in ((1120,800,'desktop'),(920,680,'compact')):
        window.resize(width,height)
        window.navigate(0)
        scroll = window.pages.widget(0).verticalScrollBar()
        for position in ('top','bottom'):
            scroll.setValue(0 if position == 'top' else scroll.maximum())
            QTest.qWait(100)
            window.grab().save(str(folder/f'{prefix}-fixture-stream-{position}.png'))
    window.controller.task = None
    window.on_event(dict(event='device', model='DJI Goggles 2', firmware='01.12.0000',
        usb='USB 2.0 High Speed', interface='MI04', compatibility=assess('DJI Goggles 2', '01.12.0000')))
    window.resize(1120, 800)
    window.navigate(1)
    QTest.qWait(150)
    window.grab().save(str(folder/'fixture-firmware-blocked.png'))
    window.close()
print(folder)
