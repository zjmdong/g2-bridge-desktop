"""Read-only preflight around the existing USB/session/manifest SDK code."""
import time

from goggles_bridge.control import V1Stream
from goggles_bridge.session import ControlSession
from goggles_bridge.usb_transport import ControlUsb
from tools.research.firmware import ManifestReader
from .compatibility import assess
from .system import Cancelled


class CompatibilityError(RuntimeError):
    pass


def usb_description(usb):
    """Report descriptors already exposed by the claimed SDK transport."""
    device = getattr(usb, 'device', None)
    if device is None:
        return '无法读取 USB 描述符'
    packet_sizes = {ep.wMaxPacketSize for config in device for interface in config
                    if interface.bInterfaceNumber == 4 for ep in interface}
    if packet_sizes == {512}:
        return 'USB 2.0 High Speed · 512 B Bulk'
    return 'USB Bulk · ' + '/'.join(str(s) for s in sorted(packet_sizes)) + ' B'


def inspect_transport(usb, stop, emit, timeout=15):
    session = ControlSession(enter_simulator=False)
    decoder = V1Stream()
    reader = ManifestReader()
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        if stop.is_set():
            raise Cancelled()
        now = time.monotonic()
        for packet in session.poll(now):
            usb.write(packet.serialize())
        for packet in decoder.feed(usb.read(timeout_ms=50)):
            # The research parser validates sequence/command. Add route checks
            # at the application boundary without modifying that implementation.
            if reader.pending:
                request = reader.pending[0]
                if (packet.sender_type, packet.sender_id, packet.receiver_type, packet.receiver_id) == (
                        request.receiver_type, request.receiver_id, request.sender_type, request.sender_id):
                    reader.receive(packet)
            for outgoing in session.receive(packet, time.monotonic()):
                usb.write(outgoing.serialize())
        if session.state == 'identified':
            for request in reader.poll(time.monotonic(), session.reserve_sequence):
                usb.write(request.serialize())
            if reader.done:
                firmware = reader.manifest.firmware if reader.manifest else None
                result = dict(model=session.model, identity=session.identity, firmware=firmware,
                              modules=reader.manifest.modules if reader.manifest else [],
                              firmware_error=reader.error, interface='MI04', usb=usb_description(usb),
                              compatibility=assess(session.model, firmware))
                emit('device', **result)
                return result
    raise TimeoutError('设备信息读取超时，请重新连接 USB 后重试。')


def probe(stop, emit, transport_factory=ControlUsb):
    with transport_factory() as usb:
        return inspect_transport(usb, stop, emit)


class VerifiedTransport:
    """SDK transport_factory: verify firmware on the same handle before streaming.

    Every reconnect passes this gate again. There is no detection/streaming
    race where a different physical device is opened after compatibility checks.
    """
    def __init__(self, dll, *, stop, emit, write_size=16384, factory=ControlUsb, telemetry=None, fps=None):
        self.telemetry = telemetry
        from .pacing import FramePacer
        self.pacer = FramePacer(fps) if fps else None
        self.usb = factory(dll, write_size=write_size)
        try:
            result = inspect_transport(self.usb, stop, emit)
            if not result['compatibility']['allowed']:
                raise CompatibilityError(result['compatibility']['message'])
        except BaseException:
            self.usb.close()
            raise

    def read(self, **kwargs):
        return self.usb.read(**kwargs)

    def write(self, data):
        video = len(data) >= 11 and data[9:11] == b'\x0b\x53'
        if self.pacer and video:
            self.pacer.wait()
        if self.telemetry is None:
            return self.usb.write(data)
        started = self.telemetry.clock()
        result = self.usb.write(data)
        ended = self.telemetry.clock()
        self.telemetry.record(len(data), video, started, ended)
        return result

    def close(self):
        return self.usb.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
