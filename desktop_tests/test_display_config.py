import ctypes
import unittest
from unittest.mock import Mock, patch

from desktop_app.display_config import PATH, MODE, attach


class DisplayConfigTests(unittest.TestCase):
    def setUp(self):
        self.primary = PATH(flags=1)
        self.primary.sourceInfo.id = 2
        self.primary.sourceInfo.modeInfoIdx = 0
        self.primary.targetInfo.modeInfoIdx = 1
        self.virtual = PATH()
        self.virtual.targetInfo.targetAvailable = True
        self.virtual.sourceInfo.id = 7
        self.virtual.targetInfo.modeInfoIdx = 0xFFFFFFFF
        self.unrelated = PATH()  # Another available inactive display must stay inactive.
        self.unrelated.targetInfo.targetAvailable = True
        self.unrelated.sourceInfo.id = 9
        self.modes = [MODE(infoType=1), MODE(infoType=2)]
        self.modes[0].sourceMode.width = 3440
        self.modes[1].raw[0] = 123456789  # Preserve exact physical signal timings.

    def run_attach(self, configure):
        with patch('desktop_app.display_config.query', return_value=(
                [self.primary, self.virtual, self.unrelated], self.modes)), \
             patch('desktop_app.display_config.source_name', side_effect=lambda p: str(p.sourceInfo.id)), \
             patch('desktop_app.display_config.configure', configure):
            return attach('7', 1920, 1080, 60, 3440, 0)

    def test_exact_primary_paths_and_modes_survive_attachment_and_rollback(self):
        configure = Mock()
        rollback = self.run_attach(configure)
        paths, modes, flags = configure.call_args.args
        self.assertEqual(len(paths), 2)  # Does not enable unrelated display.
        self.assertEqual(bytes(paths[0]), bytes(self.primary))
        self.assertEqual([bytes(m) for m in modes[:2]], [bytes(m) for m in self.modes])
        self.assertEqual(paths[1].sourceInfo.modeInfoIdx, 2)
        self.assertEqual(modes[2].sourceMode.position.x, 3440)
        self.assertEqual(modes[2].sourceMode.width, 1920)
        self.assertEqual(self.virtual.flags, 0)  # Original query snapshot wasn't mutated.
        self.assertFalse(flags & 0x400)  # Never authorize Windows to change supplied modes.
        with patch('desktop_app.display_config.configure', configure):
            rollback()
        self.assertEqual(configure.call_args.args[0], [self.primary])
        self.assertEqual(configure.call_args.args[1], self.modes)

    def test_validation_failure_does_not_apply_or_restore(self):
        configure = Mock(side_effect=RuntimeError('unsupported mode'))
        with self.assertRaises(RuntimeError):
            self.run_attach(configure)
        self.assertEqual(configure.call_count, 1)
        self.assertEqual(configure.call_args.args[2], 0x60)

    def test_apply_failure_restores_previous_active_paths(self):
        configure = Mock(side_effect=[None, RuntimeError('apply failed'), None])
        with self.assertRaisesRegex(RuntimeError, 'apply failed'):
            self.run_attach(configure)
        self.assertEqual(configure.call_count, 3)
        self.assertEqual(configure.call_args.args[0], [self.primary])

    def test_windows_structure_sizes(self):
        self.assertEqual(ctypes.sizeof(PATH), 72)
        self.assertEqual(ctypes.sizeof(MODE), 64)
