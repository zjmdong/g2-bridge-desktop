"""Desktop and frozen worker entry points."""
import sys


def main():
    if '--worker' in sys.argv:
        from desktop_app.worker import main as worker_main
        return worker_main()
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('G2Bridge.DJIGogglesStreamer')
    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication, QMessageBox
    from desktop_app.paths import data_dir
    from desktop_app.ui import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName('DJI Goggles Streamer')
    app.setOrganizationName('G2 Bridge Community')
    app.setStyle('Fusion')
    lock = QLockFile(str(data_dir() / 'application.lock'))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None, 'DJI Goggles Streamer', '客户端已在运行，请从任务栏或系统托盘打开。')
        return 0
    window = MainWindow()
    window.show()
    result = app.exec()
    lock.unlock()
    return result


if __name__ == '__main__':
    raise SystemExit(main())
