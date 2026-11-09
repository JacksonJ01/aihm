"""Optional, grouped terminal report for the pipeline's synthetic test data."""

from itertools import groupby
from shutil import get_terminal_size
from textwrap import fill

import pytest


@pytest.fixture(scope="session")
def qt_app():
    """Keep one offscreen QApplication alive for the desktop and alignment tests."""
    from PyQt6.QtCore import QCoreApplication, QEvent
    from PyQt6.QtWidgets import QApplication

    with pytest.MonkeyPatch.context() as environment:
        environment.setenv("QT_QPA_PLATFORM", "offscreen")
        app = QApplication.instance() or QApplication([])
        app.setQuitOnLastWindowClosed(False)
        yield app
        app.closeAllWindows()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()


def pytest_addoption(parser):
    parser.addoption(
        "--pipeline-details",
        action="store_true",
        help="Show grouped test inputs, expectations, and observed values after the run.",
    )


@pytest.fixture
def detail(request):
    """Record values from the actual test execution for the terminal report."""
    def record(**fields):
        if request.config.getoption("--pipeline-details"):
            for name, value in fields.items():
                request.node.user_properties.append((f"pipeline.{name}", str(value)))

    return record


def pytest_terminal_summary(terminalreporter, config):
    if not config.getoption("--pipeline-details"):
        return

    results = [
        (report, status)
        for status in ("passed", "failed", "skipped", "xfailed", "xpassed", "error")
        for report in terminalreporter.stats.get(status, [])
        if isinstance(report, pytest.TestReport)
    ]
    if not results:
        return

    terminalreporter.write_sep("=", "AIHuMo pipeline test details")
    terminalreporter.write_line("Inputs are synthetic fixtures. Observed values come from this run.")
    width = max(40, get_terminal_size().columns)
    results.sort(key=lambda item: (item[0].nodeid, item[0].start))
    for path, group in groupby(results, key=lambda item: item[0].nodeid.split("::", 1)[0]):
        terminalreporter.write_sep("-", path)
        for report, status in group:
            name = report.nodeid.split("::", 1)[-1].removeprefix("test_").replace("_", " ")
            phase = f" ({report.when})" if report.when != "call" else ""
            heading = f"[{status.upper()}] {name}{phase} ({report.duration * 1000:.1f} ms)"
            terminalreporter.write_line(fill(heading, width, subsequent_indent="  "))
            for key, value in report.user_properties:
                if key.startswith("pipeline."):
                    label = key.removeprefix("pipeline.").capitalize()
                    prefix = f"  {label:<9} "
                    terminalreporter.write_line(fill(
                        value, width, initial_indent=prefix, subsequent_indent=" " * len(prefix),
                        break_long_words=False, break_on_hyphens=False,
                    ))
