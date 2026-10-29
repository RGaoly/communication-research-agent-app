import socket

import pytest

from cra_engine.common import EngineError
from cra_workspace.network import PublicHTTPSConnection, addresses, public_fetch_json


@pytest.mark.parametrize("address", ["127.0.0.1", "169.254.169.254", "10.1.2.3", "::1", "fc00::1", "198.18.0.1"])
def test_cloud_dns_private_addresses_refused(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))])
    with pytest.raises(EngineError): addresses("fixture.invalid")


def test_connect_pins_validated_ip_and_preserves_tls_hostname(monkeypatch):
    calls = []
    class Context:
        def wrap_socket(self, sock, server_hostname):
            calls.append(("tls", server_hostname))
            return sock
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(socket, "create_connection", lambda destination, *a, **k: calls.append(("connect", destination)) or object())
    connection = PublicHTTPSConnection("provider.example")
    connection._context = Context()
    connection.connect()
    assert calls == [("connect", ("93.184.216.34", 443)), ("tls", "provider.example")]


def test_cloud_cannot_use_authorized_loopback_http_or_retry():
    with pytest.raises(EngineError): public_fetch_json("http://127.0.0.1/", ["127.0.0.1"])
    with pytest.raises(EngineError): public_fetch_json("https://provider.example/", ["provider.example"], retries=1)
