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
                              firmware_error=reader.error, interface='MI04', usb='USB 2.0 High Speed',
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
    def __init__(self, dll, *, stop, emit, write_size=16384, factory=ControlUsb):
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
        return self.usb.write(data)

    def close(self):
        return self.usb.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
