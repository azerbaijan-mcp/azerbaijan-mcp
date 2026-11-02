import socket

import pytest

LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _host(address) -> str:
    return address[0] if isinstance(address, tuple) else str(address)


@pytest.fixture(autouse=True, scope="module")
def no_network():
    """These tools are offline, so every test runs with outside network access blocked.

    Loopback stays open because asyncio itself connects a pair of local sockets on Windows.
    """
    real_connect, real_getaddrinfo = socket.socket.connect, socket.getaddrinfo

    def connect(self, address):
        if _host(address) not in LOCAL_HOSTS:
            raise RuntimeError(f"network access is blocked in these tests: {_host(address)}")
        return real_connect(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host not in LOCAL_HOSTS and host is not None:
            raise RuntimeError(f"network access is blocked in these tests: {host}")
        return real_getaddrinfo(host, *args, **kwargs)

    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", connect)
    patch.setattr(socket, "getaddrinfo", getaddrinfo)
    yield
    patch.undo()


@pytest.fixture
def anyio_backend():
    return "asyncio"
