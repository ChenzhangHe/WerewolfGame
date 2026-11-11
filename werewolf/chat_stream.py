"""Bounded DeepSeek SSE assembly and safe transport diagnostics, no text logging."""
import json
import time
from http.client import IncompleteRead
from urllib import error

MAX_BYTES = 16_000_000
MAX_ATTEMPTS = 3
IDLE_SECONDS = 90
REQUEST_SECONDS = 900


class StreamError(ValueError):
    pass


def read_chat_stream(response, deadline, *, clock=time.monotonic):
    began = clock()
    size = chunks = 0
    first = None
    model = None
    finish = None
    usage = {}
    content, reasoning, calls = [], [], {}
    while True:
        if clock() >= deadline:
            raise TimeoutError('stream_deadline')
        line = response.readline(MAX_BYTES+1)
        size += len(line)
        if size > MAX_BYTES:
            raise StreamError('stream_size')
        if not line:
            raise StreamError('stream_incomplete')
        if not line.startswith(b'data:'):
            continue  # SSE heartbeat/comment; never model text.
        payload = line[5:].strip()
        if payload == b'[DONE]':
            if finish not in ('tool_calls', 'stop', 'length', 'content_filter'):
                raise StreamError('stream_missing_finish')
            break
        try:
            chunk = json.loads(payload)
            if not isinstance(chunk, dict) or 'error' in chunk:
                raise StreamError('stream_provider_error')
            chunks += 1
            if first is None:
                first = max(0., clock()-began)
            if chunk.get('model'):
                if model is not None and chunk['model'] != model:
                    raise StreamError('stream_model_changed')
                model = chunk['model']
            if isinstance(chunk.get('usage'), dict):
                usage = chunk['usage']
            choices = chunk.get('choices', [])
            if not choices:
                continue  # Also accept the compatibility usage-only final chunk.
            if len(choices) != 1 or choices[0].get('index', 0) != 0:
                raise StreamError('stream_choices')
            choice = choices[0]
            delta = choice.get('delta', {})
            if finish is not None and any(delta.get(k) for k in ('content', 'reasoning_content', 'tool_calls')):
                raise StreamError('stream_after_finish')
            for name, parts in (('content', content), ('reasoning_content', reasoning)):
                value = delta.get(name)
                if value is not None:
                    if not isinstance(value, str):
                        raise StreamError('stream_text_shape')
                    parts.append(value)
            for tool in delta.get('tool_calls') or []:
                index = tool['index']
                if type(index) is not int or not 0 <= index < 16:
                    raise StreamError('stream_tool_index')
                call = calls.setdefault(index, {'id': '', 'type': 'function', 'function': {'name': '', 'arguments': ''}})
                if tool.get('type', 'function') != 'function':
                    raise StreamError('stream_tool_type')
                for field, target in (('id', call), ('name', call['function']), ('arguments', call['function'])):
                    value = tool.get(field) if field == 'id' else (tool.get('function') or {}).get(field)
                    if value is not None:
                        if not isinstance(value, str):
                            raise StreamError('stream_tool_shape')
                        target[field] += value
            if choice.get('finish_reason') is not None:
                if finish is not None and choice['finish_reason'] != finish:
                    raise StreamError('stream_finish_changed')
                finish = choice['finish_reason']
        except (KeyError, TypeError, AttributeError, json.JSONDecodeError):
            raise StreamError('stream_malformed') from None
    if sorted(calls) != list(range(len(calls))):
        raise StreamError('stream_tool_gap')
    return {'model': model, 'usage': usage, 'choices': [{'finish_reason': finish, 'message': {
        'role': 'assistant', 'content': ''.join(content) or None, 'reasoning_content': ''.join(reasoning),
        'tool_calls': [calls[i] for i in sorted(calls)]}}],
        '_transport': {'stream_bytes': size, 'chunks': chunks, 'first_chunk_seconds': round(first or 0., 3),
                       'stream_seconds': round(max(0., clock()-began), 3)}}


def send(config, body, *, attempts):
    # Lazy import avoids provider/transport cycles and reuses testable HTTP seams.
    import os
    from . import providers as p
    token = os.environ.get('DEEPSEEK_API_KEY', '').strip()
    if not token:
        raise p.ProviderError('Missing DEEPSEEK_API_KEY; configure this provider before continuing.')
    if not 1 <= attempts <= MAX_ATTEMPTS:
        raise ValueError('Invalid transport retry budget.')
    began = time.monotonic()
    deadline = began+REQUEST_SECONDS
    history = []
    for attempt in range(attempts):
        request = p.http.Request('https://api.deepseek.com/beta/chat/completions',
            data=json.dumps(body, ensure_ascii=False).encode(), method='POST', headers={
                'Authorization': 'Bearer '+token, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
        started = time.monotonic()
        retry_after = None
        try:
            with p.http.urlopen(request, timeout=min(IDLE_SECONDS, max(.1, deadline-started))) as response:
                result = read_chat_stream(response, deadline)
            history.append({'attempt': attempt+1, 'status': 'completed', 'seconds': round(time.monotonic()-started, 3)})
            result['_transport'].update(attempts=history, total_seconds=round(time.monotonic()-began, 3))
            return result
        except error.HTTPError as cause:
            status = cause.code
            retry = status == 429 or 500 <= status <= 599
            try:
                retry_after = float(cause.headers.get('Retry-After', '0')) if cause.headers else None
            except ValueError:
                pass
            cause.close()
            info = {'attempt': attempt+1, 'status': 'http_error', 'http_status': status}
        except (error.URLError, TimeoutError, OSError, IncompleteRead, StreamError) as cause:
            reason = getattr(cause, 'reason', cause)
            info = {'attempt': attempt+1, 'status': 'transport_error', 'failure_type': type(reason).__name__}
            if isinstance(cause, StreamError):
                info['stream_error'] = str(cause)  # Fixed internal code, never response content.
            retry = not isinstance(cause, StreamError) or str(cause) == 'stream_incomplete'
        info['seconds'] = round(time.monotonic()-started, 3)
        history.append(info)
        if not retry or attempt+1 == attempts or time.monotonic() >= deadline:
            break
        delay = min(30., max(2.**attempt, retry_after or 0.))
        time.sleep(min(delay, max(0., deadline-time.monotonic())))
    status = history[-1].get('http_status') if history else None
    category = ('authentication' if status == 401 else 'balance' if status == 402 else 'rate limit' if status == 429 else 'transport')
    failure = p.ProviderError('DeepSeek '+category+' failed'+(' (HTTP '+str(status)+')' if status else '')+'; attempts are recorded and no action was committed.')
    failure.validation_details = {'category': 'provider_transport_error', 'transport': {
        'attempts': history, 'idle_timeout_seconds': IDLE_SECONDS, 'request_deadline_seconds': REQUEST_SECONDS}}
    raise failure from None
