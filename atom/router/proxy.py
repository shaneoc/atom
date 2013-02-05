from twisted.internet import reactor
from twisted.internet.endpoints import UNIXClientEndpoint, TCP4ServerEndpoint
from twisted.internet.protocol import Protocol, Factory, ServerFactory
from twisted.protocols.basic import LineReceiver
from twisted.protocols.policies import TimeoutMixin
from twisted.python import log


#class RequestProxy(object):
#    def __init__(self, router, ip, port):
#        self.router = router
#        self.ip     = ip
#        self.port   = port
#    
#    def start(self):
#        self.endpoint = TCP4ServerEndpoint(reactor, interface=self.ip, port=self.port)
#        self.endpoint.listen(ServerFactory(self.router))


class ClientFactory(Factory):
    def __init__(self, server):
        self.server = server
    
    def buildProtocol(self, addr):
        return ClientConnection(self.server)

class ClientConnection(Protocol):
    def __init__(self, server):
        self.server = server
        self.finished = False
    
    def connectionMade(self):
        log.msg('ClientConnection: connection opened')
    
    def dataReceived(self, data):
        log.msg('ClientConnection: {} bytes of data received'.format(len(data)))
        self.server.transport.write(data)
    
    def finish(self):
        self.finished = True
        self.transport.loseConnection()
    
    def connectionLost(self, reason):
        log.msg('ClientConnection: connection closed')
        if not self.finished:
            self.server.transport.loseConnection()


class ProxyFactory(ServerFactory):
    def __init__(self, router):
        self.router = router
    
    def buildProtocol(self, addr):
        return ServerConnection(self.router)

class ServerConnection(LineReceiver, TimeoutMixin):
    def __init__(self, router):
        self.router = router
        self.client = None
        self.setState('INIT')
    
    def connectionMade(self):
        log.msg('ServerConnection: connection opened')
        self.setTimeout(60*60*12)
    
    def connectionLost(self, reason):
        log.msg('ServerConnection: connection closed')
        self.setTimeout(None)
        if self.client:
            self.client.transport.loseConnection()
    
    def timeoutConnection(self):
        log.msg('ServerConnection: timed out')
        self.transport.write(RequestTimeoutError().response())
        self.transport.loseConnection()
    
    def setState(self, state):
        if hasattr(self, 'before_' + state):
            getattr(self, 'before_' + state)()
        self.state = state
  
    def lineReceived(self, line):
        log.msg('ServerConnection({}): line received: "{}"'.format(self.state, line))
        self.resetTimeout()
        try:
            getattr(self, 'handle_' + self.state)(line)
        except HTTPError as e:
            log.err('ServerConnection({}): sent response: "{}"'.format(self.state, e.response()))
            self.transport.write(e.response())
            self.transport.loseConnection()
    
    def rawDataReceived(self, data):
        log.msg('ServerConnection({}): {} bytes of data received'.format(self.state, len(data)))
        self.resetTimeout()
        try:
            getattr(self, 'handle_' + self.state)(data)
        except HTTPError as e:
            log.err('ServerConnection({}): sent response: "{}"'.format(self.state, e.response()))
            self.transport.write(e.response())
            self.transport.loseConnection()
    
    def before_INIT(self):
        if self.client:
            self.client.finish()
            self.client = None
    
    def handle_INIT(self, line):
        # skip empty CRLF's at start
        if not line:
            return
        
        self.first_line = line
        parts = line.split()
        if len(parts) != 3:
            raise BadRequestError()
        self.method, self.uri, self.version = parts
        
        self.setState('HEADERS')
    
    def before_HEADERS(self):
        self.headers = []
        self.cur_header = None
    
    def handle_HEADERS(self, line):
        if len(line) > 0 and line[0] in b' \t':
            if self.cur_header == None:
                raise BadRequestError()
            self.cur_header += b'\r\n' + line
        else:
            if self.cur_header != None:
                if len(self.headers) > 500:
                    raise BadRequestError()
                
                parts = self.cur_header.split(':',1)
                if len(parts) != 2:
                    raise BadRequestError()
              
                self.headers.append(parts)
                
            if line == b'':
                self.allHeadersReceived()
            else:
                self.cur_header = line
    
    def allHeadersReceived(self):
        # Determine if message chunked
        te_headers = [h[1] for h in self.headers if h[0].lower() == 'transfer-encoding']
        encodings = [value.strip(' \t\r\n') for header in te_headers for value in header.split(';')]
        self.chunked = False
        if len(encodings) > 0:
            self.chunked = (encodings[-1] == 'chunked')
            if any(e == 'chunked' for e in encodings[:-1]):
                raise BadRequestError()
        
        # Determine if specific content length
        self.content_length = None
        if len(encodings) == 0:
            cl_headers = [h[1] for h in self.headers if h[0].lower() == 'content-length']
            if len(cl_headers) == 1:
                try:
                    self.content_length = int(cl_headers[0].strip(' \t\r\n'))
                except ValueError:
                    raise BadRequestError()
            elif len(cl_headers) > 1:
                raise BadRequestError()
        
        # Determine app to send request to and open socket
        host_headers = [h[1] for h in self.headers if h[0].lower() == 'host']
        if len(host_headers) != 1:
            raise BadRequestError()
        parts = host_headers[0].strip(' \t\r\n').split(':',1)
        host = parts[0]
        
        if host not in self.router.hostnames:
            raise NotFoundError()
        
        endpoint = self.router.hostnames[host].getEndpoint()
        endpoint.connect(ClientFactory(self)) \
            .addCallback(self.clientConnected) \
            .addErrback(self.clientConnectFailed)
        self.pauseProducing()
        
        if self.chunked:
            self.setState('CHUNKED_HEADER')
        elif self.content_length:
            self.setState('RAW_BODY')
        else:
            self.setState('INIT')
    
    def clientConnected(self, client):
        self.client = client
        self.client.transport.write(self.first_line + b'\r\n')
        for header in self.headers:
            self.client.transport.write('{}: {}\r\n'.format(header[0], header[1]))
        self.client.transport.write('\r\n')
        self.resumeProducing()
    
    def clientConnectFailed(self, failure):
        log.err(failure)
        self.transport.write(InternalServerError().response())
        self.transport.loseConnection()
    
    def before_RAW_BODY(self):
        self.bytes_received = 0
        self.setRawMode()
    
    def handle_RAW_BODY(self, data):
        if self.content_length != None:
            bytes_left = self.content_length - self.bytes_received
            if len(data) >= bytes_left:
                self.client.transport.write(data[:bytes_left])
                self.setLineMode(data[bytes_left:])
                self.setState('INIT')
            else:
                self.client.transport.write(data)
                self.bytes_received += len(data)
        else:
            self.client.transport.write(data)
    
    def handle_CHUNKED_HEADER(self, line):
        self.client.transport.write(line + b'\r\n')
        try:
            self.chunk_size = int(line.split(';',1)[0],base=16)
        except ValueError:
            raise BadRequestError()
        
        if self.chunk_size > 0:
            self.setState('CHUNKED_BODY')
        else:
            self.setState('CHUNKED_TRAILER')
    
    def before_CHUNKED_BODY(self):
        self.bytes_received = 0
        self.setRawMode()
    
    def handle_CHUNKED_BODY(self, data):
        bytes_left = self.chunk_size - self.bytes_received
        if len(data) >= bytes_left:
            self.client.transport.write(data[:bytes_left])
            self.setLineMode(data[bytes_left:])
            self.setState('CHUNKED_BODY_END')
        else:
            self.client.transport.write(data)
            self.bytes_received += len(data)
    
    def handle_CHUNKED_BODY_END(self, line):
        self.client.transport.write(line + b'\r\n')
        if line != b'':
            raise BadRequestError()
        self.setState('CHUNKED_HEADER')
    
    def handle_CHUNKED_TRAILER(self, line):
        self.client.transport.write(line + b'\r\n')
        
        if line == b'':
            self.setState('INIT')


class HTTPError(Exception):
    def __init__(self, code, reason):
        self.code   = code
        self.reason = reason
    def response(self):
        return b'HTTP/1.1 {} {}\r\n\r\n'.format(self.code, self.reason)

class BadRequestError(HTTPError):
    def __init__(self):
        HTTPError.__init__(self, 400, 'Bad Request')

class NotFoundError(HTTPError):
    def __init__(self):
        HTTPError.__init__(self, 404, 'Not Found')

class RequestTimeoutError(HTTPError):
    def __init__(self):
        HTTPError.__init__(self, 408, 'Request Timeout')

class InternalServerError(HTTPError):
    def __init__(self):
        HTTPError.__init__(self, 500, 'Internal Server Error')