"""Public HTTPS model transport for a shared cloud host.

Connect to the validated IP, retaining the original hostname for TLS/SNI. A
separate DNS preflight alone would permit a second lookup to rebind to an intranet.
"""
import http.client
import ipaddress
import json
import socket
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from cra_engine.common import EngineError, require
from cra_engine.literature import RedirectPolicy


def addresses(host, port=443):
    require(port == 443, "云端模型仅支持公网HTTPS的443端口")
    try:
        rows = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise EngineError("模型域名解析失败，未发送请求") from exc
    require(rows and all(ipaddress.ip_address(row[4][0]).is_global for row in rows), "云端禁止内网、回环及元数据地址")
    return rows


class PublicHTTPSConnection(http.client.HTTPSConnection):
    def connect(self):
        require(not self._tunnel_host, "云端模型不使用代理隧道")
        rows = addresses(self.host, self.port)
        # No second hostname lookup after validation. Certificate verification
        # still uses the original host, never the numeric address.
        sock = socket.create_connection((rows[0][4][0], self.port), self.timeout, self.source_address)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class PublicHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(PublicHTTPSConnection, req, context=self._context)


def public_fetch_json(url, hosts, timeout=30, payload=None, headers=None, retries=0):
    target = urlsplit(url)
    require(target.scheme == "https" and target.hostname in hosts and target.port in (None, 443)
            and not target.username and not target.password and not target.fragment, "云端模型地址未授权")
    require(retries == 0, "付费模型请求不自动重试")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicHTTPSHandler(), RedirectPolicy([target.hostname]))
    try:
        request = urllib.request.Request(url, data=payload, headers=headers or {})
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(4_000_001)
            require(len(raw) <= 4_000_000, "模型响应超过允许大小")
            return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise EngineError("模型请求结果不可确认；未回显厂商原文，需核对费用") from exc
