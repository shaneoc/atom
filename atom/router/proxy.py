from twisted.internet import reactor
from twisted.internet.endpoints import UNIXClientEndpoint, TCP4ServerEndpoint
from twisted.internet.protocol import Protocol, Factory, ServerFactory
from twisted.protocols.basic import LineReceiver
from twisted.protocols.policies import TimeoutMixin
from twisted.python import log

from atom.router.http import HTTPProtocol


class ClientFactory(Factory):
    def __init__(self, server):
        self.server = server
    
    def buildProtocol(self, addr):
        return ClientConnection(self.server)

class ClientConnection(HTTPProtocol):
    def __init__(self, server):
        HTTPProtocol.__init__(self, client = True)
        self.server = server
        self.finished = False
    
    def allHeadersReceived(self):
        self.headers.extract_session_cookies()
        self.headers.replay(self.server)
    
    def bodyDataReceived(self, data):
        self.server.write(data)
    
    def bodyDataFinished(self):
        self.finished = True
        self.disconnect()
        self.server.resumeProducing()
    
    def connectionLost(self, reason):
        HTTPProtocol.connectionLost(self, reason)
        if not self.finished:
            self.server.disconnect()


class ProxyFactory(ServerFactory):
    def __init__(self, router):
        self.router = router
    
    def buildProtocol(self, addr):
        return ServerConnection(self.router)


class ServerConnection(HTTPProtocol):
    def __init__(self, router):
        HTTPProtocol.__init__(self, client = False)
        self.router = router
        self.client = None

    def connectionLost(self, reason):
        HTTPProtocol.connectionLost(self, reason)
        if self.client:
            self.client.disconnect()
    
    def allHeadersReceived(self):
        self.pauseProducing()
        
        # Check authentication
        # TODO encrypt the URL and base64 before redirecting to /+atom/login
        #       - encrypting prevents others from putting arbitrary URLs there
        #      prevent URLs after /+atom from working in order to preserve that for me
        
        # Remove port from hostname if necessary
        if ':' in self.headers.host:
            parts = self.headers.host.split(':',1)
            if self.router.secure and parts[1] == '443':
                self.headers.set('Host', parts[0])
            if not self.router.secure and parts[1] == '80':
                self.headers.set('Host', parts[0])
        
        # Add remote IP
        remote_ip = self.transport.getPeer().host
        self.headers.set('X-Forwarded-For', remote_ip)
        
        # Remove reserved headers
        self.headers.remove('X-Authenticated-User')
        
        # Validate session
        session_cookies = self.headers.extract_session_cookies()
        (self.router.sessions.validate_session(self.headers.host, session_cookies, remote_ip)
            .addCallback(self._session_validated)
            .addErrback(self.errback))
    
    def _session_validated(self, uid):
        if uid != False:
            self.headers.set('X-Authenticated-User', str(uid))
        
        if self.headers.uri.startswith('/+atom/login'):
            self._endpoint_ready(self.router.sessions.get_endpoint())
        else:
            if uid == False:
                scheme = 'https://' if self.router.secure else 'http://'
                return_url = scheme + self.headers.host + self.headers.uri
                redirect_url = self.router.sessions.get_login_url(return_url)
                self.redirect(redirect_url)
                self.transport.loseConnection()
            else:
                if self.headers.uri.startswith('/+atom'):
                    self.notfound()
                    self.transport.close()
                else:
                    (self.directory.check_authorization(uid, self.headers.host)
                        .addCallback(self._authorization_checked)
                        .addErrback(self.errback))
    
    def _authorization_checked(self, authorized):
        if authorized:
            (self.directory.get_endpoint(self.headers.host, self.headers.uri)
                .addCallback(self._endpoint_ready)
                .addErrback(self.errback))
        else:
            raise NotImplementedError()
    
    def _endpoint_ready(self, endpoint):
        (endpoint.connect(ClientFactory(self))
            .addCallback(self._client_connected)
            .addErrback(self.errback))
    
    def _client_connected(self, client):
        self.client = client
        self.headers.replay(self.client)
        self.resumeProducing()
    
    def bodyDataReceived(self, data):
        self.client.write(data)
    
    def bodyDataFinished(self):
        self.pauseProducing()
