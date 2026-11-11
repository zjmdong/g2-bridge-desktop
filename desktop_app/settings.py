"""Versioned, atomic settings with SDK validation and no GUI dependencies."""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import os

from goggles_bridge.engine import BridgeSettings, CHOICES
from goggles_bridge.usb_transport import find_dll
from .paths import data_dir, ffmpeg_path
from .encoding import H264_PROFILE


@dataclass
class Settings:
    schema: int = 1
    fps: int = 100
    bitrate_mbps: int = 20
    preset: str = 'p4'
    capture: str = 'ddagrab'
    show_cursor: bool = True
    reconnect: bool = True
    quality: str = 'balanced'
    display_device: str = ''
    source: str = 'primary'
    resolution: str = '1080p'
    auto_start: bool = True

    @property
    def dimensions(self):
        return {'720p': (1280, 720), '1080p': (1920, 1080)}[self.resolution]

    def bridge(self, display_index=0):
        self.validate()
        return BridgeSettings(dll=find_dll(), ffmpeg=ffmpeg_path(), fps=self.fps,
                              bitrate_mbps=self.bitrate_mbps, preset=self.preset,
                              capture=self.capture, display_index=display_index,
                              show_cursor=self.show_cursor, h264_profile=H264_PROFILE, keyframe_seconds=3)

    def validate(self):
        if type(self.schema) is not int or self.schema != 1:
            raise ValueError('Unsupported settings schema')
        if type(self.fps) is not int or self.fps not in CHOICES['fps']:
            raise ValueError('Unsupported frame rate')
        if type(self.bitrate_mbps) is not int or self.bitrate_mbps not in bitrates(self.fps):
            raise ValueError('Bitrate exceeds the SDK frame budget')
        if self.preset not in ('p1', 'p4') or self.capture not in ('gfxcapture', 'ddagrab'):
            raise ValueError('Unsupported Windows encoder settings')
        if type(self.show_cursor) is not bool or type(self.reconnect) is not bool:
            raise ValueError('Invalid boolean setting')
        if self.quality not in ('balanced', 'quality', 'efficient', 'custom'):
            raise ValueError('Unknown quality preset')
        if not isinstance(self.display_device, str) or len(self.display_device) > 256:
            raise ValueError('Invalid desktop identifier')
        if self.source not in ('primary', 'extended'):
            raise ValueError('Unknown desktop source')
        if self.resolution not in ('720p', '1080p') or type(self.auto_start) is not bool:
            raise ValueError('Invalid display or automatic streaming setting')

    def save(self, path=None):
        self.validate()
        target = Path(path) if path else data_dir() / 'settings.json'
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        os.replace(temporary, target)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            raise ValueError('Settings must be an object')
        values = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        # 0.2 uses DXGI output identity for both sources, without WGC's capture border.
        if values.get('capture') == 'gfxcapture':
            values['capture'] = 'ddagrab'
        result = cls(**values)
        result.validate()
        return result

    @classmethod
    def load(cls, path=None):
        target = Path(path) if path else data_dir() / 'settings.json'
        if not target.exists():
            return cls(), None
        try:
            return cls.from_dict(json.loads(target.read_text(encoding='utf-8'))), None
        except (OSError, ValueError, TypeError):
            return cls(), '配置文件无法读取，已使用默认参数。'


def bitrates(fps):
    return [b for b in CHOICES['bitrate_mbps'] if b * 1_000_000 // (8 * fps) <= 50_000]


def preset_values(name, fps):
    desired = {'balanced': (20, 'p4'), 'quality': (40, 'p4'), 'efficient': (8, 'p1')}
    bitrate, preset = desired[name]
    return min(bitrate, max(bitrates(fps))), preset
