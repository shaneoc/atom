from gevent.server import StreamServer
from gevent import spawn

from atom.router2.http import HTTPSocket, HTTPHeaders, http_socket_pair
from atom.router2.logger import getLogger

log = getLogger(__name__)

class ProxyServer(object):
    def __init__(self, router, ip, port):
        self.router = router
        self.server = StreamServer((ip, port), self.handle2)
    
    def start(self):
        self.server.serve_forever()
    
    def handle(self, sock, address):
        sock = HTTPSocket(sock)
        
        while True:
            headers = sock.read_headers('request')
            
            # Remove port from hostname if necessary
            #if ':' in headers.host:
            #    parts = headers.host.split(':',1)
            #    if self.router.secure and parts[1] == '443':
            #        headers.set('Host', parts[0])
            #    if not self.router.secure and parts[1] == '80':
            #        headers.set('Host', parts[0])
            
            # Add remote IP
            remote_ip = address[0]
            headers.set('X-Forwarded-For', remote_ip)
            
            # Remove reserved headers
            headers.remove('X-Authenticated-User')
            
            for _ in sock.read_raw_body():
                pass
            
            headers = HTTPHeaders.response(200)
            headers.set('Content-Type', 'text/plain')
            sock.send_headers(headers)
            
            sock.send_raw_body('test!!!!\r\n')
            sock.close()
    
    def handle2(self, sock, address):
        sock = HTTPSocket(sock)
        
        while True:
            a, b = http_socket_pair()
            spawn(self.client, b, None)
            
            
            headers = sock.read_headers('request')
            a.send_headers(headers)
            a.send_raw_body(sock.read_raw_body())
            
            sock.send_headers(a.read_headers('response'))
            sock.send_raw_body(a.read_raw_body())
            
            a.close()
            #sock.close()
        
    
    def client(self, sock, address):
        headers = sock.read_headers('request')
        
        for _ in sock.read_raw_body():
            pass
        
        headers = HTTPHeaders.response(200)
        headers.set('Content-Type', 'text/plain')
        sock.send_headers(headers)
        
        sock.send_raw_body('test!!!!\r\n')
        sock.close()