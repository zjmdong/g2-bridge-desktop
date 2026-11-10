"""Windows desktop interface. No video work executes on the UI thread."""
from collections import deque
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import re
import zipfile

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QDesktopServices, QIcon, QFont, QPainter, QColor, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QCheckBox, QFrame, QStackedWidget, QGridLayout,
    QFormLayout, QTextBrowser, QProgressBar, QFileDialog, QSystemTrayIcon, QMenu,
    QSizePolicy, QScrollArea)

from . import APP_NAME, VERSION, SDK_REVISION
from .controller import Controller
from .drivers import ASSISTANT_PAGE, InstallerProcess
from .paths import resources, data_dir
from .settings import Settings, bitrates, preset_values


STYLE = '''
QWidget { color: #20363c; font-family: "Microsoft YaHei UI", "Segoe UI"; font-size: 13px; }
QMainWindow, QWidget#workspace, QWidget#page { background: #f6f7f3; }
QFrame#rail { background: #153f46; }
QLabel#brand { color: #ffffff; font-size: 20px; font-weight: 650; }
QLabel#railNote { color: #c4d9d9; font-size: 12px; }
QPushButton#nav { color: #d4e4e3; background: transparent; text-align: left; border: 0;
 padding: 12px 16px; border-radius: 6px; font-size: 14px; }
QPushButton#nav:hover { background: #24515a; }
QPushButton#nav:checked { background: #32646a; color: white; font-weight: 600; }
QLabel#title { font-size: 26px; font-weight: 650; color: #183c43; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#muted { color: #526a70; }
QLabel#small { color: #526a70; font-size: 12px; }
QLabel#status { font-size: 20px; font-weight: 600; }
QLabel#statValue { font-size: 21px; font-weight: 600; color: #174f57; }
QFrame#panel { background: #ffffff; border: 1px solid #d7e1de; border-radius: 10px; }
QFrame#statusPanel { background: #e9f1ed; border: 1px solid #ccded6; border-radius: 10px; }
QFrame#footer { background: #ffffff; border-top: 1px solid #d7e1de; }
QPushButton { background: #ffffff; border: 1px solid #b9cac9; border-radius: 6px;
 min-height: 20px; padding: 8px 14px; }
QPushButton:hover { background: #edf4f1; border-color: #36706f; }
QPushButton:pressed { background: #daeae4; }
QPushButton:focus, QComboBox:focus, QCheckBox:focus { border: 2px solid #257b7b; }
QPushButton:disabled { color: #7c898b; background: #edf0ec; border-color: #d7dfda; }
QPushButton#primary { background: #146b64; color: #ffffff; border: 1px solid #146b64;
 font-weight: 600; padding: 12px 28px; font-size: 15px; }
QPushButton#primary:hover { background: #0e5852; }
QPushButton#primary:disabled { background: #d9e3de; color: #526b66; border-color: #d9e3de; }
QComboBox { background: white; border: 1px solid #b9cac9; border-radius: 6px;
 padding: 9px 12px; min-height: 18px; }
QComboBox:disabled { color: #53666a; background: #f0f3ef; }
QComboBox::drop-down { width: 26px; border: 0; }
QComboBox::down-arrow { image: url(CHEVRON_PATH); width: 14px; height: 10px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #d5eae2; selection-color: #173e43; padding: 5px; }
QCheckBox { spacing: 8px; padding: 5px 0; }
QCheckBox::indicator { width: 17px; height: 17px; }
QTextBrowser { background: #ffffff; border: 1px solid #d7e1de; border-radius: 8px;
 padding: 16px; selection-background-color: #c4e3d6; }
QProgressBar { background: #e6ece7; border: 0; border-radius: 4px; height: 8px; text-align: center; }
QProgressBar::chunk { background: #18786f; border-radius: 4px; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #edf1eb; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #a5bbb4; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QToolTip { background: #173f45; color: white; border: 0; padding: 7px; }
'''


def label(text='', kind=None, wrap=False):
    item = QLabel(text)
    if kind:
        item.setObjectName(kind)
    item.setWordWrap(wrap)
    if wrap:
        item.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    item.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return item


def panel(name='panel'):
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 18, 22, 18)
    layout.setSpacing(12)
    return frame, layout


def app_icon():
    image = QPixmap(128, 128)
    image.fill(Qt.GlobalColor.transparent)
    paint = QPainter(image)
    paint.setRenderHint(QPainter.RenderHint.Antialiasing)
    paint.setBrush(QColor('#153f46'))
    paint.setPen(Qt.PenStyle.NoPen)
    paint.drawRoundedRect(2, 2, 124, 124, 25, 25)
    paint.setPen(QPen(QColor('#f1f6ec'), 8))
    paint.setBrush(Qt.BrushStyle.NoBrush)
    paint.drawRoundedRect(21, 42, 36, 35, 10, 10)
    paint.drawRoundedRect(71, 42, 36, 35, 10, 10)
    paint.drawLine(57, 53, 71, 53)
    paint.setPen(QPen(QColor('#80cbb1'), 7))
    paint.drawLine(44, 95, 84, 95)
    paint.end()
    return QIcon(image)


class MainWindow(QMainWindow):
    def __init__(self, *, autostart_checks=True):
        super().__init__()
        QApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
        self.setWindowTitle(f'{APP_NAME} {VERSION}')
        self.setWindowIcon(app_icon())
        self.resize(1120, 800)
        self.setMinimumSize(920, 680)
        self.settings, config_warning = Settings.load()
        self.environment = None
        self.device = None
        self.stream_active = False
        self.closing = False
        self.had_problem = False
        self.installer = None
        self.pending_installer = None
        self.history = deque(maxlen=200)
        self.log_path = None
        self.controller = Controller(self)
        self.controller.event.connect(self.on_event)
        self.controller.ended.connect(self.on_ended)
        self.controller.busy_changed.connect(self.refresh_controls)
        self._build()
        self._load_settings()
        self._tray()
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(8000)
        self.poll_timer.timeout.connect(self.auto_probe)
        self.install_timer = QTimer(self)
        self.install_timer.setInterval(1000)
        self.install_timer.timeout.connect(self.poll_installer)
        self.set_status('正在检查运行环境', '检查内置组件、NVIDIA 编码和 DJI USB 驱动。', 'busy')
        if config_warning:
            self.notice.setText(config_warning)
        if autostart_checks:
            QTimer.singleShot(200, self.check_environment)
            self.poll_timer.start()

    def _build(self):
        self.setStyleSheet(STYLE.replace('CHEVRON_PATH', (resources()/'desktop_app/assets/chevron.svg').as_posix()))
        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        rail = QFrame()
        rail.setObjectName('rail')
        rail.setFixedWidth(200)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(20, 30, 20, 24)
        nav.setSpacing(8)
        logo = QLabel()
        logo.setPixmap(app_icon().pixmap(48, 48))
        nav.addWidget(logo)
        nav.addSpacing(12)
        nav.addWidget(label('DJI Goggles\nStreamer', 'brand'))
        nav.addWidget(label('USB 桌面串流', 'railNote'))
        nav.addSpacing(28)
        self.nav_buttons = []
        for index, text in enumerate(('桌面串流', '设备与驱动', '帮助与诊断')):
            button = QPushButton(text)
            button.setObjectName('nav')
            button.setCheckable(True)
            button.clicked.connect(lambda _, i=index: self.navigate(i))
            nav.addWidget(button)
            self.nav_buttons.append(button)
        nav.addStretch()
        nav.addWidget(label('WINDOWS  ·  0.0.1', 'railNote'))
        nav.addWidget(label('基于开源 G2 Bridge\n独立项目，非 DJI 官方软件', 'railNote', True))
        root.addWidget(rail)

        workspace = QWidget()
        workspace.setObjectName('workspace')
        column = QVBoxLayout(workspace)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        self.pages = QStackedWidget()
        for builder in (self.build_stream, self.build_device, self.build_help):
            body = builder()
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(body)
            self.pages.addWidget(scroll)
        column.addWidget(self.pages, 1)
        footer = QFrame()
        footer.setObjectName('footer')
        actions = QHBoxLayout(footer)
        actions.setContentsMargins(28, 14, 28, 14)
        self.notice = label('画面通过 USB 传输，不上传至网络。', 'small', True)
        actions.addWidget(self.notice, 1)
        self.start_button = QPushButton('开始串流')
        self.start_button.setObjectName('primary')
        self.start_button.setMinimumWidth(150)
        self.start_button.clicked.connect(self.toggle_stream)
        actions.addWidget(self.start_button)
        column.addWidget(footer)
        root.addWidget(workspace, 1)
        self.setCentralWidget(central)
        self.navigate(0)

    def page(self, title, subtitle):
        page = QWidget()
        page.setObjectName('page')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(18)
        layout.addWidget(label(title, 'title'))
        layout.addWidget(label(subtitle, 'muted', True))
        return page, layout

    def build_stream(self):
        page, layout = self.page('把桌面带进眼镜', '连接眼镜，确认状态，然后开始你的模拟飞行。')
        status_panel, status = panel('statusPanel')
        self.status_title = label('', 'status')
        self.status_detail = label('', 'muted', True)
        status.addWidget(self.status_title)
        status.addWidget(self.status_detail)
        checkpoints = QHBoxLayout()
        self.checkpoints = [label('环境待检查', 'small'), label('眼镜未连接', 'small'), label('视频未开始', 'small')]
        for item in self.checkpoints:
            checkpoints.addWidget(item)
        status.addLayout(checkpoints)
        layout.addWidget(status_panel)

        source, source_layout = panel()
        source_layout.addWidget(label('电脑桌面', 'section'))
        source_layout.addWidget(label('串流 SDK 默认显示器（索引 0）的完整画面。', 'muted', True))
        source_layout.addWidget(label('本版仅支持桌面来源；窗口选择与独立扩展桌面将在后续版本提供。', 'small', True))
        layout.addWidget(source)

        settings_panel, settings_layout = panel()
        settings_layout.addWidget(label('串流设置', 'section'))
        form = QGridLayout()
        form.setHorizontalSpacing(20)
        form.setVerticalSpacing(9)
        self.quality = QComboBox()
        for name, key in (('均衡 · 推荐', 'balanced'), ('画质优先', 'quality'), ('节省带宽', 'efficient'), ('自定义', 'custom')):
            self.quality.addItem(name, key)
        self.fps = QComboBox()
        for rate in (60, 75, 90, 100):
            self.fps.addItem(f'{rate} fps', rate)
        self.resolution = QComboBox()
        self.resolution.addItem('1920 × 1080 · SDK 已验证')
        self.resolution.setEnabled(False)
        self.resolution.setToolTip('当前 SDK 固定输出 1080p。本版保持 SDK 不变。')
        self.bitrate = QComboBox()
        for col, (text, control) in enumerate((('画质预设', self.quality), ('目标帧率', self.fps))):
            field_label = label(text, 'small')
            field_label.setBuddy(control)
            control.setAccessibleName(text)
            form.addWidget(field_label, 0, col)
            form.addWidget(control, 1, col)
        for col, (text, control) in enumerate((('发送分辨率', self.resolution), ('视频码率', self.bitrate))):
            field_label = label(text, 'small')
            field_label.setBuddy(control)
            control.setAccessibleName(text)
            form.addWidget(field_label, 2, col)
            form.addWidget(control, 3, col)
        form.setColumnStretch(0, 1)
        form.setColumnStretch(1, 1)
        settings_layout.addLayout(form)
        checks = QHBoxLayout()
        self.cursor = QCheckBox('显示鼠标指针')
        self.reconnect = QCheckBox('USB 断开后自动重连')
        checks.addWidget(self.cursor)
        checks.addWidget(self.reconnect)
        settings_layout.addLayout(checks)
        self.advanced_toggle = QPushButton('高级设置')
        self.advanced_toggle.setCheckable(True)
        settings_layout.addWidget(self.advanced_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.advanced = QWidget()
        advanced_form = QFormLayout(self.advanced)
        advanced_form.setContentsMargins(0, 4, 0, 0)
        self.capture = QComboBox()
        self.capture.addItem('Windows Graphics Capture · 推荐', 'gfxcapture')
        self.capture.addItem('Desktop Duplication · 兼容模式', 'ddagrab')
        self.encoder_preset = QComboBox()
        self.encoder_preset.addItem('P1 · 速度优先', 'p1')
        self.encoder_preset.addItem('P4 · 精细编码', 'p4')
        advanced_form.addRow('采集方式', self.capture)
        advanced_form.addRow('NVIDIA 编码预设', self.encoder_preset)
        self.advanced.setVisible(False)
        self.advanced_toggle.toggled.connect(self.advanced.setVisible)
        settings_layout.addWidget(self.advanced)
        settings_layout.addWidget(label('目标帧率不等于眼镜面板刷新率。码率按 SDK 的单帧预算限制。', 'small', True))
        layout.addWidget(settings_panel)

        statistics, stats_layout = panel()
        stats_layout.addWidget(label('当前串流', 'section'))
        stats = QHBoxLayout()
        self.stat_values = []
        for title, initial in (('发送速率', '— fps'), ('USB 发送 p95', '— ms'), ('队列等待 p95', '— ms')):
            group = QVBoxLayout()
            value = label(initial, 'statValue')
            group.addWidget(value)
            group.addWidget(label(title, 'small'))
            stats.addLayout(group, 1)
            self.stat_values.append(value)
        stats_layout.addLayout(stats)
        stats_layout.addWidget(label('以上为电脑端统计，并非端到端显示延迟。每 5 秒更新。', 'small', True))
        layout.addWidget(statistics)
        layout.addStretch()
        self.inputs = [self.quality, self.fps, self.bitrate, self.cursor, self.reconnect, self.capture, self.encoder_preset]
        self.quality.currentIndexChanged.connect(self.apply_preset)
        self.fps.currentIndexChanged.connect(self.rate_changed)
        self.bitrate.currentIndexChanged.connect(self.custom_changed)
        self.encoder_preset.currentIndexChanged.connect(self.custom_changed)
        self.capture.currentIndexChanged.connect(self.save_settings)
        self.cursor.toggled.connect(self.save_settings)
        self.reconnect.toggled.connect(self.save_settings)
        return page

    def build_device(self):
        page, layout = self.page('设备与驱动', '先确认电脑环境，再检查眼镜型号和固件。')
        info, info_layout = panel()
        self.device_title = label('等待设备', 'section')
        info_layout.addWidget(self.device_title)
        self.device_detail = label('将眼镜开机，通过 USB 数据线连接电脑。', 'muted', True)
        info_layout.addWidget(self.device_detail)
        self.device_fields = {}
        form = QFormLayout()
        form.setVerticalSpacing(12)
        for key, title in (('model', '设备型号'), ('firmware', '固件版本'), ('usb', 'USB 链路'), ('interface', '通讯接口')):
            value = label('尚未读取', wrap=True)
            form.addRow(label(title, 'small'), value)
            self.device_fields[key] = value
        info_layout.addLayout(form)
        self.recheck_button = QPushButton('重新检测设备与环境')
        self.recheck_button.clicked.connect(self.check_environment)
        info_layout.addWidget(self.recheck_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(info)

        setup, setup_layout = panel()
        setup_layout.addWidget(label('Windows 运行环境', 'section'))
        self.env_detail = label('正在检查…', 'muted', True)
        self.driver_detail = label('正在检查 DJI USB 驱动…', wrap=True)
        setup_layout.addWidget(self.env_detail)
        setup_layout.addWidget(self.driver_detail)
        setup_layout.addWidget(label('首次安装会从 DJI 官方下载已验证的安装包，校验后安装所需 USB 驱动。Windows 可能请求管理员授权。', 'small', True))
        buttons = QHBoxLayout()
        self.driver_button = QPushButton('下载并安装驱动')
        self.driver_button.clicked.connect(self.install_driver)
        self.import_button = QPushButton('使用本地安装包')
        self.import_button.clicked.connect(self.import_driver)
        official = QPushButton('DJI 官方页面')
        official.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ASSISTANT_PAGE)))
        buttons.addWidget(self.driver_button)
        buttons.addWidget(self.import_button)
        buttons.addWidget(official)
        setup_layout.addLayout(buttons)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        setup_layout.addWidget(self.progress)
        self.install_detail = label('已安装的兼容驱动会直接复用；不会自动刷写眼镜固件。', 'small', True)
        setup_layout.addWidget(self.install_detail)
        layout.addWidget(setup)
        tutorial = QPushButton('查看固件兼容与恢复教程')
        tutorial.clicked.connect(lambda: self.open_help('firmware'))
        layout.addWidget(tutorial, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        return page

    def build_help(self):
        page, layout = self.page('帮助与诊断', '连接方法、固件说明和故障恢复都在这里。')
        self.help = QTextBrowser()
        self.help.setOpenExternalLinks(True)
        self.help.setMinimumHeight(350)
        self.help.setHtml((resources() / 'desktop_app/assets/help.html').read_text(encoding='utf-8'))
        layout.addWidget(self.help, 1)
        buttons = QHBoxLayout()
        logs = QPushButton('打开本地日志')
        logs.clicked.connect(self.open_logs)
        export = QPushButton('导出诊断包')
        export.clicked.connect(self.export_diagnostics)
        reset = QPushButton('恢复默认设置')
        reset.clicked.connect(self.reset_settings)
        self.reset_button = reset
        buttons.addWidget(logs)
        buttons.addWidget(export)
        buttons.addWidget(reset)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.diagnostic_status = label('日志仅保存在电脑本地；导出后可自行检查和分享。', 'small', True)
        layout.addWidget(self.diagnostic_status)
        return page

    def _tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu(self)
        menu.addAction('显示客户端', self.show_normal)
        self.tray_stop = menu.addAction('停止串流', self.controller.stop)
        menu.addSeparator()
        menu.addAction('退出', self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda reason: self.show_normal() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.tray.show()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def navigate(self, index):
        self.pages.setCurrentIndex(index)
        for i, button in enumerate(self.nav_buttons):
            button.setChecked(i == index)

    def open_help(self, anchor):
        self.navigate(2)
        self.help.scrollToAnchor(anchor)
        self.help.setFocus()

    def next_action(self):
        if not self.environment:
            return 'environment', '检测运行环境'
        if self.environment['driver']['status'] != 'verified':
            return 'driver', '安装 USB 驱动'
        if not self.environment.get('encoder_ok') or not self.environment.get('supported_os'):
            return 'encoder', '查看编码帮助'
        if not self.device:
            return 'probe', '重新检测设备'
        if not self.device['compatibility']['allowed']:
            return 'firmware', '查看固件教程'
        return 'stream', '开始串流'

    def _load_settings(self):
        for widget in self.inputs:
            widget.blockSignals(True)
        self.quality.setCurrentIndex(self.quality.findData(self.settings.quality))
        self.fps.setCurrentIndex(self.fps.findData(self.settings.fps))
        self.bitrate.clear()
        for bitrate in bitrates(self.settings.fps):
            self.bitrate.addItem(f'{bitrate} Mbps', bitrate)
        self.bitrate.setCurrentIndex(self.bitrate.findData(self.settings.bitrate_mbps))
        self.encoder_preset.setCurrentIndex(self.encoder_preset.findData(self.settings.preset))
        self.capture.setCurrentIndex(self.capture.findData(self.settings.capture))
        self.cursor.setChecked(self.settings.show_cursor)
        self.reconnect.setChecked(self.settings.reconnect)
        for widget in self.inputs:
            widget.blockSignals(False)

    def save_settings(self, *_):
        if self.fps.currentData() is None or self.bitrate.currentData() is None:
            return
        self.settings = Settings(fps=self.fps.currentData(), bitrate_mbps=self.bitrate.currentData(),
            preset=self.encoder_preset.currentData(), capture=self.capture.currentData(),
            show_cursor=self.cursor.isChecked(), reconnect=self.reconnect.isChecked(), quality=self.quality.currentData())
        try:
            self.settings.save()
        except (ValueError, OSError) as exc:
            self.notice.setText(f'设置未保存：{exc}')

    def apply_preset(self, *_):
        name = self.quality.currentData()
        if name and name != 'custom' and self.fps.currentData():
            bitrate, preset = preset_values(name, self.fps.currentData())
            self.bitrate.blockSignals(True)
            self.encoder_preset.blockSignals(True)
            self.bitrate.setCurrentIndex(self.bitrate.findData(bitrate))
            self.encoder_preset.setCurrentIndex(self.encoder_preset.findData(preset))
            self.bitrate.blockSignals(False)
            self.encoder_preset.blockSignals(False)
        self.save_settings()

    def rate_changed(self, *_):
        old = self.bitrate.currentData() or 32
        self.bitrate.blockSignals(True)
        self.bitrate.clear()
        allowed = bitrates(self.fps.currentData())
        for bitrate in allowed:
            self.bitrate.addItem(f'{bitrate} Mbps', bitrate)
        self.bitrate.setCurrentIndex(self.bitrate.findData(min(old, max(allowed))))
        self.bitrate.blockSignals(False)
        self.apply_preset()

    def custom_changed(self, *_):
        self.quality.blockSignals(True)
        self.quality.setCurrentIndex(self.quality.findData('custom'))
        self.quality.blockSignals(False)
        self.save_settings()

    def reset_settings(self):
        if self.controller.busy:
            return
        self.settings = Settings()
        self._load_settings()
        self.save_settings()
        self.notice.setText('已恢复推荐设置。')

    def set_status(self, title, detail, kind='idle'):
        self.status_title.setText(title)
        self.status_detail.setText(detail)
        color = {'good': '#126558', 'bad': '#a13c32', 'busy': '#815414', 'idle': '#203e44'}[kind]
        self.status_title.setStyleSheet(f'color: {color};')

    def check_environment(self):
        if self.controller.busy or self.installer:
            return
        self.had_problem = False
        self.set_status('正在检查运行环境', '正在测试硬件编码，并检查 USB 驱动组件。', 'busy')
        self.controller.start('environment')

    def auto_probe(self):
        if not self.closing and not self.controller.busy and not self.installer and self.environment and self.environment['driver']['status'] == 'verified':
            self.controller.start('probe')

    def ready(self):
        return bool(self.environment and self.environment.get('encoder_ok') and self.environment.get('supported_os')
                    and self.environment['driver']['status'] == 'verified' and self.device
                    and self.device['compatibility']['allowed'])

    def refresh_controls(self, *_):
        busy = self.controller.busy
        streaming = self.controller.task == 'stream'
        for control in self.inputs:
            control.setEnabled(not streaming)
        for control in (self.recheck_button, self.driver_button, self.import_button, self.reset_button):
            control.setEnabled(not busy and not self.installer)
        if hasattr(self, 'tray_stop'):
            self.tray_stop.setEnabled(streaming)
        if streaming:
            self.start_button.setText('正在停止…' if self.controller.stopping else '停止串流')
            self.start_button.setEnabled(not self.controller.stopping)
        elif self.controller.task in ('download_driver', 'import_driver'):
            self.start_button.setText('取消准备驱动')
            self.start_button.setEnabled(not self.controller.stopping)
        else:
            self.start_button.setText('正在安装驱动…' if self.installer else self.next_action()[1])
            self.start_button.setEnabled(not busy and not self.installer)

    def toggle_stream(self):
        if self.controller.task in ('stream', 'download_driver', 'import_driver'):
            self.controller.stop()
            self.refresh_controls()
            return
        if not self.ready():
            action, _ = self.next_action()
            if action == 'driver':
                self.navigate(1)
                self.pages.widget(1).ensureWidgetVisible(self.driver_button)
                self.install_driver()
            elif action in ('firmware', 'encoder'):
                self.open_help('firmware' if action == 'firmware' else 'capture')
            else:
                self.navigate(1)
                self.pages.widget(1).verticalScrollBar().setValue(0)
                self.check_environment() if action == 'environment' else self.auto_probe()
            return
        self.save_settings()
        self.had_problem = False
        self.stream_active = False
        self.notice.setText('正在检查桌面采集，随后将再次验证设备与固件。')
        self.controller.start('stream', settings=asdict(self.settings))

    def on_event(self, row):
        event = row['event']
        self.history.append(dict(at=datetime.now().isoformat(timespec='seconds'), **row))
        if event == 'environment':
            self.environment = row
            gpu = ' / '.join(g.get('Name', '') for g in row['gpu']) or '无法读取显卡名称'
            self.env_detail.setText(f"{row['os']}\n{gpu}\n{row['encoder_message']}")
            driver = row['driver']
            self.driver_detail.setText(f"{driver['title']}\n{driver['message']}")
            env_ok = row['encoder_ok'] and driver['status'] == 'verified'
            self.checkpoints[0].setText('环境已就绪' if env_ok else '环境需要设置')
            if driver['status'] != 'verified':
                self.set_status('还需要准备 USB 驱动', '前往「设备与驱动」，安装 SDK 已验证的 DJI USB 驱动。', 'busy')
            elif not row['encoder_ok']:
                self.set_status('硬件编码尚未就绪', row['encoder_message'], 'busy')
            else:
                self.set_status('等待眼镜连接', '连接 USB 数据线，并在眼镜中打开「更多 → DJI Virtual Flight」。')
        elif event == 'device':
            self.device = row
            for key, item in self.device_fields.items():
                item.setText(str(row.get(key) or '无法读取'))
            policy = row['compatibility']
            self.device_title.setText(policy['title'])
            self.device_detail.setText(policy['message'])
            self.checkpoints[1].setText('眼镜已验证' if policy['allowed'] else '固件需要检查')
            if not self.stream_active:
                if policy['allowed'] and self.environment and not self.environment.get('encoder_ok'):
                    self.set_status('硬件编码尚未就绪', self.environment['encoder_message'], 'busy')
                else:
                    self.set_status('可以开始串流' if self.ready() else policy['title'],
                                    policy['message'], 'good' if self.ready() else 'busy')
        elif event == 'checking_capture':
            self.set_status('正在测试桌面采集', '请保持桌面解锁。首次启动通常需要几秒钟。', 'busy')
        elif event == 'ready':
            self.set_status('设备握手完成', '正在启动视频编码。', 'busy')
        elif event == 'streaming':
            self.stream_active = True
            self.set_status('正在串流桌面', '视频已发送，请在眼镜中确认画面。结束时点击「停止串流」。', 'good')
            self.checkpoints[2].setText('视频正在发送')
            self.notice.setText(f'1920 × 1080  ·  目标 {self.settings.fps} fps  ·  {self.settings.bitrate_mbps} Mbps')
        elif event == 'stats':
            self.stat_values[0].setText(f"{row['fps']:.1f} fps")
            self.stat_values[1].setText(f"{row['send_ms_p95']:.2f} ms")
            self.stat_values[2].setText(f"{row['queue_ms_p95']:.2f} ms")
        elif event == 'waiting':
            self.stream_active = False
            self.checkpoints[2].setText('等待恢复视频')
            message = row.get('message', '')
            hint = '请在眼镜中打开「更多 → DJI Virtual Flight」。' if 'simulator mode' in message else '请检查电源、数据线和 Virtual Flight。客户端会重新验证设备后重连。'
            self.set_status('等待设备就绪', hint, 'busy')
        elif event == 'oversize_frame':
            self.notice.setText('SDK 已拦截过大的视频帧；正在恢复编码。若反复出现，请降低码率。')
        elif event == 'log_path':
            self.log_path = row['path']
        elif event in ('problem', 'error'):
            self.had_problem = True
            code = row.get('code')
            if code == 'not_connected':
                self.device = None
                self.checkpoints[1].setText('眼镜未连接')
                self.device_title.setText('等待眼镜连接')
                self.device_detail.setText(row['message'])
                for item in self.device_fields.values():
                    item.setText('尚未读取')
                if self.environment and self.environment['encoder_ok']:
                    self.set_status('等待眼镜连接', row['message'])
            else:
                self.set_status('需要处理一个问题', row.get('message', '后台任务失败'), 'bad')
                self.notice.setText('可在「帮助与诊断」查看教程并导出诊断包。')
                self.diagnostic_status.setText(row.get('details', row.get('message', ''))[-1500:])
        elif event == 'download_progress':
            self.progress.setVisible(True)
            self.progress.setValue(row['percent'])
            self.install_detail.setText(f"正在从 DJI 官方下载：{row['received']/1024/1024:.1f} MB / {row['total']/1024/1024:.1f} MB")
        elif event == 'driver_preparing':
            self.progress.setRange(0, 0)
            self.install_detail.setText('安装包校验通过，正在提取已签名的 USB 驱动…')
        elif event == 'driver_prepared':
            self.pending_installer = row['path']
        self.refresh_controls()

    def on_ended(self, task, code):
        if self.closing:
            self.close()
            return
        if code != 0 and not self.had_problem and not self.controller.stopping:
            self.had_problem = True
            self.set_status('后台任务意外退出', '请重新检测环境；若再次出现，可导出诊断包。', 'bad')
        if task == 'environment' and code == 0:
            QTimer.singleShot(100, self.auto_probe)
        elif task == 'stream':
            self.stream_active = False
            self.checkpoints[2].setText('视频已停止')
            if not self.had_problem:
                self.set_status('串流已停止', '可以调整参数后再次开始。若眼镜提示 d6，请退出并重新打开 Virtual Flight。')
                self.notice.setText('视频编码和 USB 连接已释放。')
        elif task in ('download_driver', 'import_driver'):
            self.progress.setVisible(False)
            if self.pending_installer and code == 0:
                path, self.pending_installer = self.pending_installer, None
                self.launch_installer(path)
            elif not self.had_problem:
                self.install_detail.setText('已取消下载，可稍后重试。')
        self.refresh_controls()

    def install_driver(self):
        if self.controller.busy or self.installer:
            return
        self.had_problem = False
        self.pending_installer = None
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.install_detail.setText('正在获取并验证官方安装包…')
        self.controller.start('download_driver')

    def import_driver(self):
        if self.controller.busy:
            return
        path, _ = QFileDialog.getOpenFileName(self, '选择 DJI Assistant 2 消费机系列 2.1.42 安装包', '', 'Windows 安装程序 (*.exe)')
        if path:
            self.had_problem = False
            self.pending_installer = None
            self.progress.setRange(0, 0)
            self.progress.setVisible(True)
            self.install_detail.setText('正在验证本地安装包…')
            self.controller.start('import_driver', path=path)

    def launch_installer(self, path):
        try:
            self.installer = InstallerProcess(path)
            self.install_detail.setText('正在通过 Windows 安装所需 USB 驱动。完成管理员授权后，客户端将自动重新检测。')
            self.install_timer.start()
        except Exception as exc:
            self.install_detail.setText(str(exc))
        self.refresh_controls()

    def poll_installer(self):
        try:
            code = self.installer.poll()
        except OSError as exc:
            code = -1
            self.install_detail.setText(str(exc))
        if code is not None:
            self.installer = None
            self.install_timer.stop()
            self.install_detail.setText('驱动已提交给 Windows。请连接眼镜，正在重新检测。' if code == 0 else
                'Windows 要求重启后完成驱动安装，请保存工作后重启电脑。' if code == 3010 else
                f'驱动安装已退出（代码 {code}），请重新检测或查看官方教程。')
            self.check_environment()

    def open_logs(self):
        folder = data_dir() / 'logs'
        folder.mkdir(exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def export_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(self, '导出诊断包', f'Goggles-Streamer-{datetime.now():%Y%m%d-%H%M%S}.zip', 'ZIP 文件 (*.zip)')
        if not path:
            return
        payload = dict(app=APP_NAME, version=VERSION, sdk=SDK_REVISION, settings=asdict(self.settings),
                       environment=self.environment, device=self.device, events=list(self.history))
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        text = text.replace(str(Path.home()).replace('\\', '\\\\'), '<USER>')
        text = re.sub(r'(?i)[a-z]:\\\\Users\\\\[^\\\\"\n]+', '<USER>', text)
        try:
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('diagnostics.json', text)
                archive.writestr('README.txt', '包含配置、环境检查与最近状态；不包含桌面图像、USB 原始数据或完整协议日志。分享前请自行检查。')
            self.diagnostic_status.setText('诊断包已导出，未自动上传。')
        except OSError as exc:
            self.diagnostic_status.setText(f'导出失败：{exc}')

    def closeEvent(self, event):
        if self.controller.busy:
            self.closing = True
            self.controller.stop()
            self.notice.setText('正在结束后台任务并释放设备…')
            self.refresh_controls()
            event.ignore()
            return
        self.poll_timer.stop()
        self.tray.hide()
        event.accept()
