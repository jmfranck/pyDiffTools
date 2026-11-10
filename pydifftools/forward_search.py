"""Acknowledged loopback transport for browser forward-search requests."""

import errno
import json
import os
import queue
import socket


FORWARD_SEARCH_HOST = "127.0.0.1"
CPB_FORWARD_SEARCH_PORT = 51235
QMDB_FORWARD_SEARCH_PORT = 51236
# Concurrent qmdb sessions take the next free port above each base port.
QMDB_PORT_ATTEMPTS = 20
FORWARD_SEARCH_ACK = b"pydifft-forward-search-ok\n"
FORWARD_SEARCH_CONNECTION_TIMEOUT = 1.0
FORWARD_SEARCH_ACCEPT_TIMEOUT = 0.25


class ForwardSearchUnavailable(ConnectionError):
    """Raised when no process is listening at a forward-search address."""


class ForwardSearchProtocolError(RuntimeError):
    """Raised when a port accepts TCP but is not a healthy pydifft listener."""


# also used by: continuous.py and notebook/fast_build.py
def bind_forward_search_server(address, service_name):
    """Bind a listening socket or fail before the service opens a browser."""

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind(address)
        server.listen(5)
        server.settimeout(FORWARD_SEARCH_ACCEPT_TIMEOUT)
    except OSError as exc:
        server.close()
        raise RuntimeError(
            f"Could not bind the {service_name} forward-search endpoint at "
            f"{address[0]}:{address[1]}. Another process may already own it."
        ) from exc
    return server


def serve_forward_search(server, stop_event, search_queue, directory=None):
    """Accept clients, queue valid UTF-8 payloads, and acknowledge receipt."""

    registrations = {}
    if directory is not None:
        registrations[os.path.realpath(directory)] = server.getsockname()[1]

    while not stop_event.is_set():
        try:
            connection, _ = server.accept()
        except socket.timeout:
            continue
        except OSError:
            if stop_event.is_set():
                break
            raise

        with connection:
            connection.settimeout(FORWARD_SEARCH_CONNECTION_TIMEOUT)
            payload = bytearray()
            try:
                while True:
                    chunk = connection.recv(4096)
                    if not chunk:
                        break
                    payload.extend(chunk)
            except (OSError, socket.timeout):
                continue
            if not payload:
                continue
            try:
                search_text = payload.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if search_text.startswith("pydifft-directory\n"):
                try:
                    request = json.loads(search_text.split("\n", 1)[1])
                    directory_key = os.path.realpath(request["directory"])
                    if "port" in request:
                        port = request["port"]
                        if port is None:
                            registrations.pop(directory_key, None)
                        elif isinstance(port, int) and 0 < port < 65536:
                            registrations[directory_key] = port
                    response = json.dumps({
                        "port": registrations.get(directory_key),
                        "registry": directory is not None,
                    }).encode()
                    connection.sendall(response)
                except (ValueError, KeyError, TypeError, OSError):
                    pass
                continue
            search_queue.put(search_text)
            try:
                connection.sendall(FORWARD_SEARCH_ACK)
            except OSError:
                # Receipt already succeeded; one reset client must not kill
                # discovery for every later mfs invocation.
                continue


# also used by: command_line.py (mfs) and tests/test_forward_search.py
def send_forward_search(address, search_text, timeout=1.0):
    """Deliver text and require an acknowledgment from a pydifft listener."""

    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        try:
            client.connect(address)
        except OSError as exc:
            raise ForwardSearchUnavailable(address) from exc

        try:
            client.sendall(search_text.encode("utf-8"))
            client.shutdown(socket.SHUT_WR)
            acknowledgment = bytearray()
            while len(acknowledgment) < len(FORWARD_SEARCH_ACK):
                chunk = client.recv(
                    len(FORWARD_SEARCH_ACK) - len(acknowledgment)
                )
                if not chunk:
                    break
                acknowledgment.extend(chunk)
        except (OSError, socket.timeout) as exc:
            raise ForwardSearchProtocolError(
                f"The service at {address[0]}:{address[1]} accepted a "
                "connection but did not acknowledge forward search."
            ) from exc
        if bytes(acknowledgment) != FORWARD_SEARCH_ACK:
            raise ForwardSearchProtocolError(
                f"The service at {address[0]}:{address[1]} did not return "
                "the pydifft forward-search acknowledgment."
            )
    finally:
        client.close()


# also used by: continuous.py and notebook/fast_build.py
def drain_forward_search_queue(search_queue):
    """Return all currently queued searches without relying on Queue.empty."""

    searches = []
    while True:
        try:
            searches.append(search_queue.get_nowait())
        except queue.Empty:
            return searches


# also used by: continuous.py and command_line.py
def directory_port(address, directory, **registration):
    """Query or update the first cpb process's directory registry."""
    request = {"directory": os.path.realpath(directory), **registration}
    try:
        with socket.create_connection(address, timeout=1) as client:
            client.settimeout(1)
            client.sendall(("pydifft-directory\n" + json.dumps(request)).encode())
            client.shutdown(socket.SHUT_WR)
            response = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response.extend(chunk)
                if len(response) > 4096:
                    raise ValueError("oversized registry response")
    except OSError as exc:
        raise ForwardSearchUnavailable(address) from exc
    try:
        result = json.loads(response)
        if not isinstance(result, dict) or not isinstance(
            result.get("registry"), bool
        ):
            raise ValueError("invalid registry response")
        port = result.get("port")
        if port is not None and (type(port) is not int or not 0 < port < 65536):
            raise ValueError("invalid port")
        return result
    except (ValueError, TypeError) as exc:
        raise ForwardSearchProtocolError(
            f"Invalid directory registry response from {address}"
        ) from exc


# also used by: continuous.py and tests/test_forward_search.py
def bind_cpb_server(address):
    """Take the first available port, reporting every occupied port."""
    for port in range(address[1], 65536):
        try:
            return bind_forward_search_server((address[0], port), "cpb")
        except RuntimeError as exc:
            if not isinstance(exc.__cause__, OSError) or (
                exc.__cause__.errno != errno.EADDRINUSE
            ):
                raise
            print(f"cpb: port {port} is taken; trying port {port + 1}.")
    raise RuntimeError("No free cpb forward-search port remains")
