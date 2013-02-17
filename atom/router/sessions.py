from string import Template
import base64
import re
import time
import hashlib
import random

from gevent import spawn

from atom.http import HTTPHeaders, http_socket_pair
from atom.logger import getLogger

log = getLogger(__name__)

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
    
    def get_login_url(self, return_url):
        scheme = 'https://' if self.router.secure else 'http://'
        return (scheme + self.router.directory.get_system_hostname() +
            '/+atom/login?return=' + base64.urlsafe_b64encode(return_url))
    
    def validate_session(self, hostname, session_cookies, remote_ip):
        if len(session_cookies) == 0:
            return False
        
        uid_key_pairs = []
        for cookie in session_cookies:
            parts = cookie.split('-')
            if len(parts) != 2:
                continue
            uid_key_pairs.append(tuple(parts))
        
        now = int(time.time())
        cutoff = now - 60*60*24;
        db = self.router.database
        db.execute('DELETE FROM sessions WHERE last_seen < ?', (cutoff,))
        
        for uid, key in uid_key_pairs:
            db.execute('SELECT user_id, hostname, remote_ip FROM sessions WHERE key = ?', (key,))
            row = db.fetchone()
            if row[0] != uid or row[1] != hostname or row[2] != remote_ip:
                continue
            db.execute('UPDATE sessions SET last_seen = ? WHERE key = ?', (now, key))
            return uid
        
        return False
    
    def _generate_nonce(self):
        random_str = str(random.getrandbits(8) for _ in xrange(64))
        return hashlib.sha512(random_str+str(time.time())).hexdigest()
    
    def create_session(self, uid, hostname, remote_ip):
        key = self._generate_nonce()
        now = int(time.time())
        
        self.router.database.execute(
            'INSERT INTO sessions VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)',
            (uid, hostname, key, remote_ip, now, now))
        
        return key
    
    def get_sessions(self):
        pass
    
    def get_socket(self):
        a, b = http_socket_pair()
        spawn(SessionManagerHTTPConnection, self.router, b)
        return a


class SessionManagerHTTPConnection(object):
    def __init__(self, router, sock):
        self.router = router
        self.sock = sock
        self.headers = sock.read_headers('request')
        
        if self.headers.path != '/+atom/login':
            sock.send_headers(HTTPHeaders.response(500))
            sock.close()
            log.error("SessionManager: received a path that wasn't /+atom/login")
            return
        
        system_host = (self.headers.get_single('Host') == self.router.directory.get_system_hostname())
        if system_host:
            if self.headers.method == 'GET':
                self._show_login('')
            elif self.headers.method == 'POST':
                self.process_sys_post()
            else:
                response = HTTPHeaders.response(405)
                response.set('Allow', 'GET, HEAD, POST')
                sock.send_headers(response)
        else:
            print('{}: {}'.format(self.headers.method, self.headers.path))
            response = HTTPHeaders.response(200)
            response.set('Content-Type', 'text/plain')
            sock.send_headers(response)
            
            sock.send_raw_body('path: ' + self.path)
            #if self.method == 'PUT':
            #  with open(self.path[1:], 'wb') as f:
            #    f.write(self.content.read())
            #self.write('test!')
            log.msg('process 1 finished')
            sock.close()
    
    def _show_login(self, message):
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
    
    def process_sys_post(self):
        uid = self._check_login()
        
        if uid == False:
            self._show_login('Invalid username or password')
        else:
            remote_ip = self.headers.get_single('X-Forwarded-For')
            host = self.headers.get_single('Host')
            key = self.router.sessions.create_session(uid, host, remote_ip)
            
            args = self.headers.args
            response = HTTPHeaders.response(302)
            response.set('Location', args['return'][0])
            response.add('Set-Cookie',
                'atom-session={}-{}; Expires=Mon, 31 Dec 2035 23:59:59 GMT; Path=/; {}HttpOnly'.format(
                uid, key, 'Secure; ' if self.router.secure else ''))
        
    
    def _check_login(self):
        args = self.sock.read_form_body()
        if 'username' not in self.args or 'password' not in self.args:
            return False
        
        username = args['username'][0]
        password = args['password'][0]
        return self.router.directory.check_login(username, password)
