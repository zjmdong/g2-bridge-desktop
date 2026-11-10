"""Capture actual Qt widgets for visual review. Simulated states are labeled here."""
from pathlib import Path
import os
import sys
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from desktop_app.ui import MainWindow
from desktop_app.system import environment
from desktop_app.compatibility import assess

app = QApplication([])
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
    # Fixture only: known good device and encoder, no physical stream claimed.
    window.on_event(dict(event='environment', os='Windows x64', gpu=[dict(Name='NVIDIA NVENC')],
        encoder_ok=True, supported_os=True, encoder_message='NVIDIA NVENC 编码测试通过',
        driver=dict(status='verified', title='DJI USB 组件已验证', message='连接时检查设备接口与驱动绑定。')))
    window.on_event(dict(event='device', model='DJI Goggles 2', firmware='01.12.0000',
        usb='USB 2.0 High Speed', interface='MI04', compatibility=assess('DJI Goggles 2', '01.12.0000')))
    window.resize(1120, 800)
    window.navigate(1)
    QTest.qWait(150)
    window.grab().save(str(folder/'fixture-firmware-blocked.png'))
    window.close()
print(folder)
