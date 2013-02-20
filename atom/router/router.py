import sqlite3

from gevent import spawn
from gevent.server import StreamServer

from atom.http import HTTPSocket, HTTPHeaders, HTTPError
from atom.router.directory import Directory
from atom.router.sessions import SessionManager
from atom.logger import get_logger

log = get_logger(__name__)

class Router(object):
    def __init__(self, ip, port, apps_dir, run_dir, db_filename):
        self.secure = False
        self.database = sqlite3.connect(db_filename)
        self.database.text_factory = str # TODO revisit this in python 3
        self.directory = Directory(self)
        self.sessions = SessionManager(self)
        
        StreamServer((ip, port), self.handle).serve_forever()
    
    def handle(self, sock, addr):
        RouterConnection(self, sock, addr)


class RouterConnection(object):
    def __init__(self, router, sock, addr):
        sock = HTTPSocket(sock, 'server')
        
        try:
            while True:
                headers = sock.read_headers()
                
                connection_close = headers.get('Connection') == 'close'
                
                # Remove port from hostname if necessary
                host = headers.get_single('Host')
                if ':' in host:
                    parts = host.split(':',1)
                    if router.secure and parts[1] == '443': host = parts[0]
                    if not router.secure and parts[1] == '80': host = parts[0]
                    headers.set('Host', host)
                
                # Add remote IP
                headers.set('X-Forwarded-For', addr[0])
                
                # Remove reserved headers
                headers.remove('X-Authenticated-User')
                
                # Indicate non-persistent connection
                headers.set('Connection', 'close')
                
                # Validate session
                session_cookies = headers.get_cookie('atom-session')
                uid = router.sessions.validate_session(host, session_cookies, addr[0])
                
                if uid != False:
                    headers.set('X-Authenticated-User', str(uid))
                
                if headers.path == '/+atom/login':
                    client_sock = router.sessions.get_socket()
                else:
                    if uid == False:
                        client_sock = router.sessions.get_socket()
                    else:
                        if headers.uri.startswith('/+atom'):
                            response = HTTPHeaders.response(404)
                            sock.send_headers(response)
                            sock.close()
                            return
                        else:
                            if router.directory.check_authorization(uid, host):
                                client_sock = router.directory.get_socket(host, headers.uri)
                                if not client_sock:
                                    sock.send_headers(HTTPHeaders.response(404))
                                    sock.close()
                                    return
                                
                                headers.delete_cookie('atom-session')
                            else:
                                raise NotImplementedError()
                
                try:
                    client_sock.send_headers(headers)
                except HTTPError:
                    log.exception()
                    sock.error_close()
                    return
                
                spawn(self._client_thread, sock, client_sock)
                
                for data in sock.read_body(raw = True):
                    try:
                        client_sock.send_body(data, raw = True)
                    except HTTPError:
                        log.exception()
                        sock.error_close()
                        return
                
                if connection_close:
                    break
        except HTTPError as e:
            log.info('Client {} disconnected: {}', addr, e)
    
    def _client_thread(self, sock, client_sock):
        try:
            response = client_sock.read_headers()
        except HTTPError:
            log.exception()
            sock.error_close()
            client_sock.error_close()
            return
        
        response.set('Server','atom/0.0')
        
        try:
            sock.send_headers(response)
        except HTTPError:
            log.exception()
            sock.error_close()
            client_sock.error_close()
            return
        
        try:
            for data in client_sock.read_body(raw = True):
                try:
                    sock.send_body(data, raw = True)
                except HTTPError:
                    return
        except HTTPError:
            return
    


