"""Disconnect recovery without periodic PnP work in the video process."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from desktop_app.stream_engine import DesktopBridgeEngine
from goggles_bridge.engine import BridgeEngine, BridgeSettings
from goggles_bridge.session import SessionLost
from goggles_bridge.usb_transport import UsbTransportError


class DisconnectRecoveryTests(unittest.TestCase):
    def run_engine(self, presence, session, *, reconnect=True):
        callbacks = []
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'session.jsonl'
            engine = DesktopBridgeEngine(
                BridgeSettings(dll=Path('unused.dll'), ffmpeg=Path('unused.exe')),
                path, on_event=callbacks.append, presence_probe=presence,
                reconnect=reconnect, retry_delay=0)
            with patch.object(BridgeEngine, '_session', autospec=True, side_effect=session) as sdk:
                engine.run()
            rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        return engine, callbacks, rows, sdk

    def test_confirmed_removal_stops_reconnect_after_transport_or_heartbeat_failure(self):
        for error in (UsbTransportError('device removed'), SessionLost('heartbeat expired')):
            for reconnect in (True, False):
                with self.subTest(error=type(error).__name__, reconnect=reconnect):
                    presence = Mock(return_value=False)
                    def session(engine, attempt):
                        self.assertEqual(attempt, 1)
                        # This event normally comes from the SDK's finally block.
                        engine.emit('session_ended', frames=100)
                        raise error
                    engine, callbacks, rows, sdk = self.run_engine(presence, session, reconnect=reconnect)
                    self.assertTrue(engine.stop_event.is_set())
                    self.assertEqual(sdk.call_count, 1)
                    presence.assert_called_once_with()
                    events = [row['event'] for row in callbacks]
                    self.assertEqual(events, ['starting', 'session_ended', 'usb_disconnected', 'stopped'])
                    self.assertEqual(rows, callbacks)
                    self.assertTrue(engine.log_complete)

    def test_connected_interface_keeps_sdk_retry_and_never_queries_successful_session(self):
        presence = Mock(return_value=True)
        def session(engine, attempt):
            if attempt == 1:
                raise UsbTransportError('temporary link failure')
            engine.stop_event.set()
        engine, callbacks, _, sdk = self.run_engine(presence, session)
        self.assertEqual(sdk.call_count, 2)
        presence.assert_called_once_with()
        events = [row['event'] for row in callbacks]
        self.assertIn('waiting', events)
        self.assertNotIn('usb_disconnected', events)

    def test_failed_presence_query_preserves_recovery_instead_of_faking_disconnect(self):
        presence = Mock(side_effect=OSError('PnP temporarily unavailable'))
        def session(engine, attempt):
            if attempt == 1:
                raise SessionLost('original heartbeat failure')
            engine.stop_event.set()
        _, callbacks, _, sdk = self.run_engine(presence, session)
        self.assertEqual(sdk.call_count, 2)
        presence.assert_called_once_with()
        waiting = [row for row in callbacks if row['event'] == 'waiting']
        self.assertEqual(waiting[0]['message'], 'original heartbeat failure')
        self.assertNotIn('usb_disconnected', [row['event'] for row in callbacks])

    def test_user_stop_does_not_add_presence_query_during_cleanup(self):
        for error in (UsbTransportError('cancelled transfer'), SessionLost('cancelled heartbeat')):
            for reconnect in (True, False):
                with self.subTest(error=type(error).__name__, reconnect=reconnect):
                    presence = Mock(side_effect=AssertionError('unexpected PnP enumeration'))
                    def session(engine, attempt):
                        engine.emit('session_ended')
                        engine.stop_event.set()
                        raise error
                    _, callbacks, _, sdk = self.run_engine(presence, session, reconnect=reconnect)
                    presence.assert_not_called()
                    self.assertEqual(sdk.call_count, 1)
                    self.assertEqual([row['event'] for row in callbacks], ['starting', 'session_ended', 'stopped'])

    def test_cancellation_during_presence_query_completes_without_waiting_or_error(self):
        for reconnect in (True, False):
            with self.subTest(reconnect=reconnect):
                active = []
                def session(engine, attempt):
                    active.append(engine)
                    engine.emit('session_ended')
                    raise UsbTransportError('interrupted transfer')
                def presence():
                    active[0].stop_event.set()
                    return True
                _, callbacks, _, sdk = self.run_engine(presence, session, reconnect=reconnect)
                self.assertEqual(sdk.call_count, 1)
                self.assertEqual([row['event'] for row in callbacks], ['starting', 'session_ended', 'stopped'])

    def test_unconfirmed_failure_without_reconnect_preserves_original_error(self):
        for presence in (Mock(return_value=True), Mock(side_effect=OSError('PnP unavailable'))):
            with self.subTest(presence=presence):
                error = UsbTransportError('original transport failure')
                def session(engine, attempt):
                    raise error
                with self.assertRaises(UsbTransportError) as caught:
                    self.run_engine(presence, session, reconnect=False)
                self.assertIs(caught.exception, error)
                presence.assert_called_once_with()

    def test_non_transport_failure_is_not_masked_by_presence_query(self):
        presence = Mock(side_effect=AssertionError('unexpected PnP enumeration'))
        def session(engine, attempt):
            raise RuntimeError('encoder failed')
        with self.assertRaisesRegex(RuntimeError, 'encoder failed'):
            self.run_engine(presence, session)
        presence.assert_not_called()


if __name__ == '__main__':
    unittest.main()
