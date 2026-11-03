"""HTTPS connections for custom providers, pinned to validated public DNS addresses."""
from http.client import HTTPSConnection
import ipaddress
import socket
from urllib.request import HTTPSHandler


class PublicHTTPSConnection(HTTPSConnection):
    def connect(self):
        if self._tunnel_host:
            raise OSError('Proxy tunnels are not supported for custom AI endpoints.')
        addresses = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
            raise OSError('Custom AI endpoint must resolve exclusively to public addresses.')
        # Use the checked socket address directly; TLS still verifies the configured hostname.
        last_error = None
        for family, kind, protocol, _, address in addresses:
            sock = socket.socket(family, kind, protocol)
            try:
                sock.settimeout(self.timeout)
                sock.connect(address)
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as error:
                sock.close()
                last_error = error
        raise last_error or OSError('Unable to connect to AI endpoint.')


class PublicHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(PublicHTTPSConnection, request, context=self._context)
