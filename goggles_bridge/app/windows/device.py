"""Optional sender counters around the upstream USB transport.

Device identification, supported models, link speed and simulator negotiation
remain in the SDK. Opening this wrapper never starts a second probe session or
imposes an application firmware whitelist.
"""
from goggles_bridge.usb_transport import ControlUsb


class MeasuredTransport:
    """A BridgeEngine transport_factory with no pacing or extra USB traffic.

    Pass telemetry=None to remove sampling entirely. With a SenderTelemetry,
    successful writes only update a tuple; its separate thread publishes stats.
    """
    def __init__(self, dll, *, write_size=16384, factory=ControlUsb, telemetry=None):
        self.telemetry = telemetry
        self.usb = factory(dll, write_size=write_size)

    def read(self, **kwargs):
        return self.usb.read(**kwargs)

    def write(self, data):
        if self.telemetry is None:
            return self.usb.write(data)
        video = len(data) >= 11 and data[9:11] == b'\x0b\x53'
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
