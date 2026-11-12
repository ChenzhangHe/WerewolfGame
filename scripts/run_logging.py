"""Best-effort console output; durable game evidence is written separately."""
import json
import os
import sys
import threading

_LOCK = threading.Lock()


def _discard_disconnected_stdout(output):
    # Avoid Python's exit-time flush retry turning a successful run into exit 120.
    if output is sys.stdout:
        try:
            with open(os.devnull, 'wb') as sink:
                os.dup2(sink.fileno(), output.fileno())
        except (OSError, ValueError, AttributeError):
            if getattr(output, 'closed', False):
                sys.stdout = open(os.devnull, 'w', encoding='utf-8')


def emit(value, *, stream=None):
    """A disconnected observer must not abort a game or its result collector."""
    message = json.dumps(value, ensure_ascii=False, sort_keys=True)
    output = sys.stdout if stream is None else stream
    try:
        with _LOCK:
            output.write(message+'\n')
            output.flush()
    except BrokenPipeError:
        _discard_disconnected_stdout(output)
        return False
    except OSError:
        _discard_disconnected_stdout(output)
        return False  # Only this optional console sink; evidence-file errors still propagate.
    except ValueError:
        if getattr(output, 'closed', False):
            _discard_disconnected_stdout(output)
            return False
        raise
    return True
