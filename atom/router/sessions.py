from string import Template
import base64
import re
import time
import hashlib
import random

from twisted.web import http
from twisted.python import log
from twisted.internet import defer

from atom.router.endpointpair import EndpointPair

class SessionManager(object):
    def __init__(self, router):
        self.router = router
        self._endpoint = EndpointPair()
        self._endpoint.listen(_SessionManagerHttpFactory(router))
    
    def start(self):
        return self.router.database.runOperation(
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
            return defer.succeed(False)
        
        uid_key_pairs = []
        for cookie in session_cookies:
            parts = cookie.split('-')
            if len(parts) != 2:
                continue
            uid_key_pairs.append(tuple(parts))
        
        return self.router.database.runInteraction(self._validate_db,
            hostname, uid_key_pairs, remote_ip)
        
    def _validate_db(self, txn, hostname, uid_key_pairs, remote_ip):
        now = int(time.time())
        cutoff = now - 60*60*24;
        txn.execute('DELETE FROM sessions WHERE last_seen < ?', (cutoff,))
        
        for uid, key in uid_key_pairs:
            txn.execute('SELECT user_id, hostname, remote_ip FROM sessions WHERE key = ?', (key,))
            row = txn.fetchone()
            if row[0] != uid or row[1] != hostname or row[2] != remote_ip:
                continue
            txn.execute('UPDATE sessions SET last_seen = ? WHERE key = ?', (now, key))
            return uid
        
        return False
    
    def _generate_nonce(self):
        random_str = str(random.getrandbits(8) for _ in xrange(64))
        return hashlib.sha512(random_str+str(time.time())).hexdigest()
    
    def create_session(self, uid, hostname, remote_ip):
        key = self._generate_nonce()
        now = int(time.time())
        
        d = self.router.database.runOperation(
            'INSERT INTO sessions VALUES (NULL, ?, ?, ?, ?, ?, ?, ?)',
            (uid, hostname, key, remote_ip, now, now))
        
        def ret_val(v): return v
        return d.addCallback(ret_val, key)
    
    def get_sessions(self):
        pass
    
    def get_endpoint(self):
        return self._endpoint

class _SessionManagerHttpRequest(http.Request):
    def __init__(self, channel, queued):
        http.Request.__init__(self, channel, queued)
        self.router = self.channel.factory.router
        self.notifyFinish().addErrback(log.err)
    
    #def _finish_error(self, reason):
    #    log.err(reason)
    
    def process(self):
        if self.path != '/+atom/login':
            self.setResponseCode(500)
            
            log.msg('process 0 finished')
            self.finish()
            log.err("SessionManager: received a path that wasn't /+atom/login")
            return
        
        system_host = (self.getHeader('Host') == self.router.directory.get_system_hostname())
        if system_host:
            if self.method == 'GET':
                self._show_login('')
            elif self.method == 'POST':
                self.process_sys_post()
            else:
                self.setHeader('Allow', 'GET, HEAD, POST')
                self.setResponseCode(405)
        else:
            print('{}: {}'.format(self.method, self.path))
            self.setHeader('Content-Type', 'text/plain')
            self.write('path: ' + self.path)
            #if self.method == 'PUT':
            #  with open(self.path[1:], 'wb') as f:
            #    f.write(self.content.read())
            #self.write('test!')
            log.msg('process 1 finished')
            self.finish()
    
    def _errback(self, failure):
        log.msg('errback finished')
        log.err(failure)
        if not self.finished:
            self.setResponseCode(500)
            self.finish()
    
    def _show_login(self, message):
        if 'return' in self.args and re.match(r'^[a-zA-Z0-9=_-]+$', self.args['return'][0]):
            post_url = '/+atom/login?return={}'.format(self.args['return'][0])
        else:
            post_url = '/+atom/login'
        
        with open('login.html') as f:
            self.write(Template(f.read()).substitute({
                'message': message,
                'post_url': post_url
            }))
            log.msg('_show_login finished')
            self.finish()
    
    def process_sys_post(self):
        def done(uid):
            if uid == False:
                self._show_login('Invalid username or password')
            else:
                def add_cookie(key, uid):
                    self.cookies.append(
                        'atom-session={}-{}; Expires=Mon, 31 Dec 2035 23:59:59 GMT; Path=/; {}HttpOnly'.format(
                        uid, key, 'Secure; ' if self.router.secure else ''))
                remote_ip = self.getHeader('X-Forwarded-For')
                (self.router.sessions.create_session(uid, self.host, remote_ip)
                    .addCallback(add_cookie, uid)
                    .addErrback(self._errback))
        
        (self._check_login()
            .addCallback(done)
            .addErrback(self._errback))
    
    def _check_login(self):
        if 'username' not in self.args or 'password' not in self.args:
            return defer.succeed(False)
        
        username = self.args['username'][0]
        password = self.args['password'][0]
        return self.router.directory.check_login(username, password)
    

class _SessionManagerHttpConnection(http.HTTPChannel):
    requestFactory = _SessionManagerHttpRequest

class _SessionManagerHttpFactory(http.HTTPFactory):
    protocol = _SessionManagerHttpConnection
    
    def __init__(self, router):
        http.HTTPFactory.__init__(self)
        self.router = router