"""Load local credentials without shell evaluation or exposing their values."""

from pathlib import Path
import os
import re


ENV_FILE = Path(__file__).resolve().parent.parent / ".env"
ALLOWED_KEYS = frozenset({"DEEPSEEK_API_KEY"})


def load_local_credentials(path=None, environ=None):
    """Load a literal DeepSeek key from .env; existing process values take priority.

    Supports KEY=value, export KEY=value, and single/double quoted literal values.
    No interpolation, command substitution, escapes, or arbitrary environment
    configuration is evaluated. Returns loaded variable names, never values.
    """
    destination = os.environ if environ is None else environ
    source = ENV_FILE if path is None else Path(path)
    if not source.is_file():
        return []
    values = {}
    for number, raw in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)", line)
        if not match:
            raise ValueError(f"Invalid .env entry on line {number}; use KEY=value.")
        name, value = match.groups()
        if name not in ALLOWED_KEYS:
            continue
        if value.startswith(("'", '"')):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].lstrip().startswith("#")):
                raise ValueError(f"Invalid .env quoting on line {number}.")
            value = value[1:end]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()
        if value and (any(char.isspace() for char in value) or "\x00" in value):
            raise ValueError(f"Invalid credential format on .env line {number}.")
        if value:
            values[name] = value
    loaded = []
    for name, value in values.items():
        if not destination.get(name, "").strip():
            destination[name] = value
            loaded.append(name)
    return loaded
