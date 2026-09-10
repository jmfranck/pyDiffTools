"""Acknowledged loopback transport for browser forward-search requests."""

import queue
import socket


FORWARD_SEARCH_HOST = "127.0.0.1"
CPB_FORWARD_SEARCH_PORT = 51235
QMDB_FORWARD_SEARCH_PORT = 51236
FORWARD_SEARCH_ACK = b"pydifft-forward-search-ok\n"
FORWARD_SEARCH_CONNECTION_TIMEOUT = 1.0
FORWARD_SEARCH_ACCEPT_TIMEOUT = 0.25


class ForwardSearchUnavailable(ConnectionError):
    """Raised when no process is listening at a forward-search address."""


class ForwardSearchProtocolError(RuntimeError):
    """Raised when a port accepts TCP but is not a healthy pydifft listener."""


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


def serve_forward_search(server, stop_event, search_queue):
    """Accept clients, queue valid UTF-8 payloads, and acknowledge receipt."""

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
            search_queue.put(search_text)
            try:
                connection.sendall(FORWARD_SEARCH_ACK)
            except OSError:
                # Receipt already succeeded; one reset client must not kill
                # discovery for every later mfs invocation.
                continue


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


def drain_forward_search_queue(search_queue):
    """Return all currently queued searches without relying on Queue.empty."""

    searches = []
    while True:
        try:
            searches.append(search_queue.get_nowait())
        except queue.Empty:
            return searches
