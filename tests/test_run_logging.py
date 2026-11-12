"""A lost console is optional; serialization and durable evidence remain strict."""
import errno
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from scripts.run_logging import emit


class RunLoggingTests(unittest.TestCase):
    def test_optional_closed_or_failed_sink_is_ignored(self):
        closed = io.StringIO()
        closed.close()
        self.assertFalse(emit({'status': 'running'}, stream=closed))
        class Failed:
            def write(self, value): raise OSError(errno.EIO, 'Disconnected terminal')
        self.assertFalse(emit({'status': 'running'}, stream=Failed()))

    def test_invalid_event_is_not_hidden_as_a_console_failure(self):
        with self.assertRaises(TypeError):
            emit({'invalid': object()}, stream=io.StringIO())

    def test_closed_stdout_object_does_not_fail_interpreter_shutdown(self):
        child = subprocess.run([sys.executable, '-c',
            "import sys; from scripts.run_logging import emit; sys.stdout.close(); emit({'status':'finished'})"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=10)
        self.assertEqual(0, child.returncode)
        self.assertNotIn(b'ValueError', child.stderr)

    def test_actual_closed_os_pipe_does_not_fail_interpreter_shutdown(self):
        with tempfile.TemporaryDirectory() as directory:
            gate = Path(directory)/'ready'
            done = Path(directory)/'completed'
            code = """
from pathlib import Path
import sys,time
from scripts.run_logging import emit
gate,done=map(Path,sys.argv[1:])
while not gate.exists(): time.sleep(.01)
emit({'status':'running'})
emit({'status':'finished'})
done.write_text('completed after observer disconnected')
"""
            child = subprocess.Popen([sys.executable, '-c', code, str(gate), str(done)],
                cwd=Path(__file__).resolve().parents[1], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                child.stdout.close()
                gate.write_text('go')
                self.assertEqual(0, child.wait(timeout=10))
                self.assertTrue(done.exists())
                self.assertNotIn(b'BrokenPipeError', child.stderr.read())
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
                child.stderr.close()


if __name__ == '__main__':
    unittest.main()
