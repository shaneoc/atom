import sqlite3

from gevent import spawn
from gevent.server import StreamServer

from atom.http import HTTPSocket, HTTPHeaders, HTTPError
from atom.router.directory import Directory
from atom.router.sessions import SessionManager
from atom.logger import getLogger

log = getLogger(__name__)

class Router(object):
    def __init__(self, ip, port, apps_dir, run_dir, db_filename):
        self.secure = False
        self.database = sqlite3.connect(db_filename)
        self.directory = Directory(self)
        self.sessions = SessionManager(self)
        
        StreamServer((ip, port), self.handle).serve_forever()
    
    def handle(self, sock, addr):
        RouterConnection(self, HTTPSocket(sock), addr)


class RouterConnection(object):
    def __init__(self, router, sock, addr):
        headers = sock.read_headers('request')
        
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
        session_cookies = headers.extract_cookie('atom-session')
        uid = router.sessions.validate_session(host, session_cookies, addr[0])
        
        if uid != False:
            headers.set('X-Authenticated-User', str(uid))
        
        if headers.path == '/+atom/login':
            client_sock = router.sessions.get_socket()
        else:
            if uid == False:
                scheme = 'https://' if router.secure else 'http://'
                return_url = scheme + host + headers.uri
                redirect_url = router.sessions.get_login_url(return_url)
                response = HTTPHeaders.response(302)
                response.set('Location', redirect_url)
                sock.send_headers(response)
                sock.close()
                return
            else:
                if headers.uri.starswith('/+atom'):
                    response = HTTPHeaders.response(404)
                    sock.send_headers(response)
                    sock.close()
                    return
                else:
                    if router.directory.check_authorization(uid, host):
                        client_sock = router.directory.get_socket(host, headers.uri)
                    else:
                        raise NotImplementedError()
        
        spawn(self._client_thread, sock, headers, client_sock)
        
        try:
            for data in sock.read_body(raw = True):
                try:
                    client_sock.send_body(data, raw = True)
                except HTTPError:
                    return
        except HTTPError:
            return
    
    def _client_thread(self, sock, headers, client_sock):
        client_sock.send_headers(headers)
        
        try:
            response = client_sock.read_headers('response')
        except HTTPError:
            log.exception()
            response = HTTPHeaders.response(500)
            response.set('Connection','close')
            sock.send_headers(response)
            sock.close()
            client_sock.close()
            return
        
        response.set('Server','atom/0.0')
        
        try:
            sock.send_headers(response)
        except HTTPError:
            log.exception()
            sock.close()
            client_sock.close()
            return
        
        try:
            for data in client_sock.read_body(raw = True):
                try:
                    sock.send_body(data, raw = True)
                except HTTPError:
                    return
        except HTTPError:
            return
    


