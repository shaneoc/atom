from string import Template
import re
import time
import hashlib
import random

from base64 import urlsafe_b64encode as b64encode
from base64 import urlsafe_b64decode as b64decode

from gevent import spawn

from atom.http import HTTPHeaders, http_socket_pair
from atom.logger import get_logger

log = get_logger(__name__)

class SessionManager(object):
    def __init__(self, router):
        self.router = router
        
        self.router.database.execute(
            'CREATE TABLE IF NOT EXISTS sessions (' +
            'id        INTEGER PRIMARY KEY,' +
            'user_id   INTEGER NOT NULL,' +
            'hostname  TEXT NOT NULL,' +
            'key       TEXT UNIQUE NOT NULL,' +
            'remote_ip TEXT NOT NULL,' +
            'created   INTEGER NOT NULL,' +
            'last_seen INTEGER NOT NULL)')
    
    def validate_session(self, hostname, session_cookies, remote_ip):
        if len(session_cookies) == 0:
            return False
        
        uid_key_pairs = []
        for cookie in session_cookies:
            parts = cookie.split('-')
            if len(parts) != 2:
                continue
            try:
                pair = (int(parts[0]), parts[1])
            except ValueError:
                continue
            uid_key_pairs.append(pair)
        
        now = int(time.time())
        cutoff = now - 60*60*24;
        db = self.router.database.cursor()
        db.execute('DELETE FROM sessions WHERE last_seen < ?', (cutoff,))
        
        for uid, key in uid_key_pairs:
            db.execute('SELECT user_id, hostname, remote_ip FROM sessions WHERE key = ?', (key,))
            row = db.fetchone()
            if not row or row[0] != uid or row[1] != hostname or row[2] != remote_ip:
                continue
            db.execute('UPDATE sessions SET last_seen = ? WHERE key = ?', (now, key))
            return uid
        
        return False
    
    def _generate_nonce(self):
        random_bytes = ''.join(chr(random.getrandbits(8)) for _ in xrange(64))
        return hashlib.sha512(random_bytes+str(time.time())).hexdigest()
    
    def create_session(self, uid, hostname, remote_ip):
        key = self._generate_nonce()
        now = int(time.time())
        self.router.database.execute(
            'INSERT INTO sessions VALUES (NULL, ?, ?, ?, ?, ?, ?)',
            (uid, hostname, key, remote_ip, now, now))
        
        return str(uid) + '-' + key
    
    def delete_sessions(self, keys):
        pass
    
    def get_sessions(self):
        pass
    
    def get_socket(self):
        client, server = http_socket_pair()
        spawn(SessionManagerHTTPConnection, self.router, server)
        return client


class SessionManagerHTTPConnection(object):
    def __init__(self, router, sock):
        self.router = router
        self.sock = sock
        self.headers = sock.read_headers()
        
        self.host = self.headers.get_single('Host')
        self.remote_ip = self.headers.get_single('X-Forwarded-For')
        existing_keys = self.headers.get_cookie('atom-session')
        system_host = self.router.directory.get_system_hostname()
        
        try:
            uid = int(self.headers.get_single('X-Authenticated-User'))
        except (ValueError, TypeError):
            uid = None
        
        log.debug('SessionManager received "{}" request for "{}{}"', self.headers.method, self.host, self.headers.uri)
        
        if self.headers.path != '/+atom/login':
            # The router should only send us these requests if not logged in
            assert not uid
            ret = b64encode(self.host + self.headers.uri)
            self.redirect(system_host + '/+atom/login?return=' + ret)
        else:
            if self.host == system_host:
                if self.headers.method == 'GET':
                    if uid:
                        self.return_redirect(uid)
                    else:
                        self.show_login('')
                elif self.headers.method == 'POST':
                    uid = self.check_login()
                    if not uid:
                        self.show_login('Invalid username or password')
                    else:
                        key = self.router.sessions.create_session(uid, self.host, self.remote_ip)
                        self.return_redirect(uid, key)
                else:
                    response = HTTPHeaders.response(405)
                    response.set('Allow', 'GET, HEAD, POST')
                    sock.send_headers(response)
                    sock.close()
            else:
                if self.headers.method == 'GET':
                    if 'key' in self.headers.args:
                        key = self.headers.args['key'][0]
                        uid = self.router.sessions.validate_session(self.host, [key], self.remote_ip)
                        if uid:
                            self.router.sessions.delete_sessions(existing_keys)
                            if 'return' in self.headers.args:
                                host_and_path = b64decode(self.headers.args['return'][0])
                            else:
                                host_and_path = self.host + '/'
                            self.redirect(host_and_path, key = key)
                        else:
                            self.redirect(system_host + '/+atom/login')
                    else:
                        self.redirect(system_host + '/+atom/login')
                else:
                    response = HTTPHeaders.response(405)
                    response.set('Allow', 'GET, HEAD')
                    sock.send_headers(response)
                    sock.close()
    
    def return_redirect(self, uid, key = None):
        if 'return' in self.headers.args:
            host_and_path = b64decode(self.headers.args['return'][0])
            # TODO check this URL to make sure it's sane
            #      maybe I should cryptographically sign the URL?
        else:
            host_and_path = self.router.directory.get_shell_hostname(uid) + '/'
        return_host = host_and_path.split('/',1)[0]
        if return_host != self.host:
            return_key = self.router.sessions.create_session(uid, return_host, self.remote_ip)
            host_and_path = return_host + '/+atom/login?key={}&return={}'.format(return_key, b64encode(host_and_path))
        self.redirect(host_and_path, key = key)
    
    def redirect(self, host_and_path, key = None):
        scheme = 'https://' if self.router.secure else 'http://'
        response = HTTPHeaders.response(302)
        response.set('Location', scheme + host_and_path)
        if key:
            response.set_cookie('atom-session', key, expires=False, secure=self.router.secure, httponly=True)
        self.sock.send_headers(response)
        self.sock.close()
    
    def show_login(self, message):
        args = self.headers.args
        if 'return' in args and re.match(r'^[a-zA-Z0-9=_-]+$', args['return'][0]):
            post_url = '/+atom/login?return={}'.format(args['return'][0])
        else:
            post_url = '/+atom/login'
        
        response = HTTPHeaders.response(200)
        response.set('Content-Type', 'text/html')
        self.sock.send_headers(response)
        
        with open('login.html') as f:
            self.sock.send_body(Template(f.read()).substitute({
                'message': message,
                'post_url': post_url
            }))
            self.sock.close()
    
    def check_login(self):
        args = self.sock.read_form_body()
        if 'username' not in args or 'password' not in args:
            return None
        
        username = args['username'][0]
        password = args['password'][0]
        return self.router.directory.check_login(username, password)
