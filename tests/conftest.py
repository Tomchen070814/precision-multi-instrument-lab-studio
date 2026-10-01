import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session", autouse=True)
def qt_application(tmp_path_factory):
    # A QCoreApplication created by worker tests cannot later host widgets.
    # Keep one QApplication alive for any ordering of worker and UI tests.
    from PySide6 import QtWidgets

    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LOCALAPPDATA", str(tmp_path_factory.mktemp("application-data")))
        yield application
        application.processEvents()
