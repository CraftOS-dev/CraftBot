"""The installer's per-thread stdout routing.

Two things have to hold at once, and they pull in opposite directions:

  * a worker thread's output goes to the wizard's log panel and nowhere else
    (the whole point of routing per thread rather than swapping the process
    streams, which would capture every other thread too);
  * nothing crashes when the process has no streams at all. The installer is
    frozen with console=False, so under pythonw sys.stdout and sys.stderr are
    None. print() is a documented no-op in that case, and a wrapper that does
    not preserve it turns a harmless library print into AttributeError.
"""

import io
import sys
import threading

import pytest

from installer.api import _install_routed_streams, _NullStream, _ThreadRoutedStream


@pytest.fixture
def restore_streams():
    saved = sys.stdout, sys.stderr
    yield
    sys.stdout, sys.stderr = saved


def test_wrapping_absent_streams_keeps_print_a_no_op(restore_streams):
    """The frozen, windowed installer: sys.stdout is None."""
    sys.stdout = None
    sys.stderr = None

    out, err = _install_routed_streams()

    print("a library logging from a non-routed thread")  # must not raise
    print("and on stderr", file=sys.stderr)
    sys.stdout.flush()
    assert sys.stdout.encoding == "utf-8"
    assert sys.stdout.isatty() is False
    assert isinstance(out, _ThreadRoutedStream)


def test_absent_streams_still_route_to_a_worker_sink(restore_streams):
    sys.stdout = None
    sys.stderr = None
    _install_routed_streams()

    sink = io.StringIO()
    sys.stdout.route_current_thread(sink)
    print("worker line")
    sys.stdout.route_current_thread(None)

    assert sink.getvalue() == "worker line\n"


def test_only_the_routed_thread_is_captured(restore_streams):
    """A per-action swap of sys.stdout is process-wide: the bridge thread
    polling get_state, and every other thread, would be captured with it."""
    console = io.StringIO()
    sink = io.StringIO()
    sys.stdout = _ThreadRoutedStream(console)

    def worker():
        sys.stdout.route_current_thread(sink)
        print("from the worker")
        sys.stdout.route_current_thread(None)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    print("from the main thread")

    assert sink.getvalue() == "from the worker\n"
    assert console.getvalue() == "from the main thread\n"


def test_routing_is_cleared_even_though_the_stream_persists(restore_streams):
    console = io.StringIO()
    sink = io.StringIO()
    sys.stdout = _ThreadRoutedStream(console)

    sys.stdout.route_current_thread(sink)
    sys.stdout.route_current_thread(None)
    print("after the worker finished")

    assert sink.getvalue() == ""
    assert console.getvalue() == "after the worker finished\n"


def test_install_is_idempotent(restore_streams):
    """Called once per action; it must not wrap a wrapper each time."""
    console = io.StringIO()
    sys.stdout = console
    sys.stderr = console

    first_out, _ = _install_routed_streams()
    second_out, _ = _install_routed_streams()

    assert first_out is second_out
    assert first_out._fallback is console


def test_null_stream_reports_no_descriptor():
    """Callers that probe fileno() (subprocess wiring, isatty shims) get the
    same OSError a detached stream raises, not a wrong file descriptor."""
    with pytest.raises(OSError):
        _NullStream().fileno()
