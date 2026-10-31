"""In-memory continuation checkpoints, restricted to transient transport failures."""
import socket
from urllib.error import HTTPError, URLError


def transient(error):
    if isinstance(error, HTTPError):
        return error.code in (408, 429, 500, 502, 503, 504)
    return isinstance(error, (URLError, TimeoutError, ConnectionError, socket.timeout))


def bind(state, signature):
    if state.get('signature') is not None and state['signature'] != signature:
        raise ValueError('Continuation requires the original search conditions.')
    state['signature'] = signature
    state['paused'] = False
    state.pop('error', None)


def pause(state, error):
    state.update(paused=True, error=str(error))


def finished(state, stopped=False):
    if state is not None:
        state['paused'] = stopped
        state['stopped'] = stopped
        if not stopped:
            state.pop('batch', None)
