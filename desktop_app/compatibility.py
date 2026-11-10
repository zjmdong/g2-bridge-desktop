"""Evidence-based firmware policy, separate from SDK session behavior."""
import re

VERIFIED = {'DJI Goggles 2': {'01.11.0000', '01.14.0000'},
            'DJI Goggles Integra': {'01.09.0000'}}


def normalize_firmware(value):
    value = str(value or '').strip().lower().removeprefix('v')
    match = re.fullmatch(r'(\d{2})\.(\d{2})\.(\d{2})\.(\d{2})', value)
    if match:
        return f'{match[1]}.{match[2]}.{match[3]}{match[4]}'
    return value if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', value) else None


def assess(model, firmware):
    version = normalize_firmware(firmware)
    if model not in VERIFIED:
        return dict(status='unsupported', allowed=False, title='暂不支持此型号',
                    message='当前 SDK 仅验证了 Goggles 2 与 Goggles Integra。请勿强制发送视频。')
    if model == 'DJI Goggles 2' and version and version.startswith('01.12.'):
        return dict(status='blocked', allowed=False, title='此固件存在黑屏问题报告',
                    message='上游报告 01.12 可能导致黑屏。请按固件教程改用 01.14.00.00 或 01.11.00.00 后重新检测。')
    if version in VERIFIED[model]:
        return dict(status='verified', allowed=True, title='固件在 SDK 已验证列表内',
                    message='仍需在眼镜中打开「更多 → DJI Virtual Flight」。')
    target = '01.14.00.00 或 01.11.00.00' if model == 'DJI Goggles 2' else '01.09.00.00'
    return dict(status='unknown', allowed=False, title='固件尚未验证' if version else '无法确认固件版本',
                message=f'此型号已验证版本：{target}。请按固件教程更新或恢复后重新检测；不会自动刷机。')
