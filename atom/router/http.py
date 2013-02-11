from twisted.protocols.basic import LineReceiver
from twisted.protocols.policies import TimeoutMixin
from twisted.python import log


class HTTPHeaders(object):
    def __init__(self, request):
        self._request    = request
        self._headers    = []
    
    def set_first_line(self, first_line):
        self._first_line = first_line
        if self._request:
            parts = first_line.split()
            if len(parts) != 3:
                raise HTTPHeaderError('Invalid HTTP request first line: "{}"'.format(first_line))
            self.method, self.uri, self.version = parts
        else:
            parts = first_line.split()
            if len(parts) != 3:
                raise HTTPHeaderError('Invalid HTTP response first line: "{}"'.format(first_line))
            self.version, self.response_code, self.response_reason = parts
    
    def add_raw(self, header):
        parts = header.split(':',1)
        if len(parts) != 2:
            raise HTTPHeaderError('Invalid HTTP header: "{}"'.format(header))
        
        self.add(parts[0], parts[1])
    
    def add(self, name, value):
        self._headers.append([name, value])
        self._updated()
    
    def remove(self, name):
        self._headers = [h for h in self._headers if h[0].strip().lower() != name.strip().lower()]
        self._updated()
    
    def set(self, name, value):
        self.remove(name)
        self.add(name, value)
    
    def replay(self, f):
        f.write(self._first_line + b'\r\n')
        f.write(b'\r\n'.join(b'{}:{}'.format(h[0], h[1]) for h in self._headers))
        f.write(b'\r\n\r\n')
    
    def extract_session_cookies(self):
        if self._request:
            session_cookies = []
            for h in self._headers:
                if h[0].strip().lower() == b'cookie':
                    cookies = [c.split(b'=') for c in h[1].split(b';')]
                    session_cookies.extend(c[1].strip() for c in cookies if c[0].strip().lower() == b'atom-session')
                    cookies = [c for c in cookies if c[0].strip().lower() != b'atom-session']
                    h[1] = b';'.join(b'='.join(c) for c in cookies)
            self._headers = [h for h in self._headers if not (h[0].strip().lower() == b'cookie' and len(h[1]) == 0)]
            return session_cookies
        else:
            self._headers = [h for h in self._headers if not (h[0].strip().lower() == b'set-cookie' and h[1].split(b'=',1)[0].strip().lower() == b'atom-session')]
    
    def _updated(self):
        # Check if too many headers
        if len(self._headers) > 500:
            raise HTTPHeaderError('Too many headers')
        
        # Determine if message chunked
        te_headers = [h[1] for h in self._headers if h[0].strip().lower() == 'transfer-encoding']
        encodings = [value.strip() for header in te_headers for value in header.split(';')]
        self.chunked = False
        if len(encodings) > 0:
            self.chunked = (encodings[-1] == 'chunked')
            if any(e == 'chunked' for e in encodings[:-1]):
                raise HTTPHeaderError('Invalid Transfer-Encoding')
        
        # Determine if specific content length
        self.content_length = None
        if len(encodings) == 0:
            cl_headers = [h[1] for h in self._headers if h[0].strip().lower() == 'content-length']
            if len(cl_headers) == 1:
                try:
                    self.content_length = int(cl_headers[0].strip())
                except ValueError:
                    raise HTTPHeaderError('Invalid Content-Length')
            elif len(cl_headers) > 1:
                raise HTTPHeaderError('Too many Content-Length headers')
        
        # Determine the hostname
        if self._request:
            host_headers = [h for h in self._headers if h[0].strip().lower() == 'host']
            if len(host_headers) > 1:
                raise HTTPHeaderError('Too many Host headers')
            self.host = host_headers[0][1].strip() if len(host_headers) > 0 else None

class HTTPHeaderError(Exception):
    pass


class HTTPProtocol(LineReceiver, TimeoutMixin):
    def __init__(self, client):
        self.__client = client
        self.setState('INIT')
    
    def allHeadersReceived(self):
        pass
    
    def bodyDataReceived(self, data):
        pass
    
    def bodyDataFinished(self):
        pass
    
    def write(self, data):
        self.resetTimeout()
        self.transport.write(data)
    
    def disconnect(self):
        self.transport.loseConnection()
    
    def connectionMade(self):
        self.setTimeout(60*60*12)
    
    def connectionLost(self, reason):
        self.setTimeout(None)
    
    def timeoutConnection(self):
        if not self.__client:
            self.write(RequestTimeoutError().response())
        self.disconnect()
    
    def setState(self, state):
        if hasattr(self, 'before_' + state):
            getattr(self, 'before_' + state)()
        self.state = state
    
    def lineReceived(self, line):
        self.resetTimeout()
        try:
            getattr(self, 'handle_' + self.state)(line)
        except HTTPError as e:
            if not self.__client:
                self.write(e.response())
            self.disconnect()
    
    def rawDataReceived(self, data):
        self.resetTimeout()
        try:
            getattr(self, 'handle_' + self.state)(data)
        except HTTPError as e:
            if not self.__client:
                self.write(e.response())
            self.disconnect()
    
    def errback(self, failure):
        log.err(failure)
        if not self.__client:
            self.write(InternalServerError().response())
        self.disconnect()
    
    def handle_INIT(self, line):
        # skip empty CRLF's at start
        if not line:
            return
        
        self.headers = HTTPHeaders(request = not self.__client)
        
        try:
            self.headers.set_first_line(line)
        except HTTPHeaderError as e:
            log.err(e)
            raise BadRequestError()
        
        self.setState('HEADERS')
    
    def before_HEADERS(self):
        self.cur_header = None
    
    def handle_HEADERS(self, line):
        if len(line) > 0 and line[0] in b' \t':
            if self.cur_header == None:
                raise BadRequestError()
            self.cur_header += b'\r\n' + line
        else:
            if self.cur_header != None:
                try:
                    self.headers.add_raw(self.cur_header)
                except HTTPHeaderError as e:
                    log.err(e)
                    raise BadRequestError()
            
            if line == b'':
                self.allHeadersReceived()
                
                if self.headers.chunked:
                    self.setState('CHUNKED_HEADER')
                elif self.headers.content_length:
                    self.setState('RAW_BODY')
                else:
                    self.setState('INIT')
            else:
                self.cur_header = line
    
    def before_RAW_BODY(self):
        self.bytes_received = 0
        self.setRawMode()
    
    def handle_RAW_BODY(self, data):
        if self.headers.content_length != None:
            bytes_left = self.headers.content_length - self.bytes_received
            if len(data) >= bytes_left:
                self.bodyDataReceived(data[:bytes_left])
                self.bodyDataFinished()
                self.setLineMode(data[bytes_left:])
                self.setState('INIT')
            else:
                self.bodyDataReceived(data)
                self.bytes_received += len(data)
        else:
            self.bodyDataReceived(data)
    
    def handle_CHUNKED_HEADER(self, line):
        self.bodyDataReceived(line + b'\r\n')
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
            self.bodyDataReceived(data[:bytes_left])
            self.setLineMode(data[bytes_left:])
            self.setState('CHUNKED_BODY_END')
        else:
            self.bodyDataReceived(data)
            self.bytes_received += len(data)
    
    def handle_CHUNKED_BODY_END(self, line):
        self.bodyDataReceived(line + b'\r\n')
        if line != b'':
            raise BadRequestError()
        self.setState('CHUNKED_HEADER')
    
    def handle_CHUNKED_TRAILER(self, line):
        self.bodyDataReceived(line + b'\r\n')
        self.bodyDataFinished()
        
        if line == b'':
            self.setState('INIT')
    
    def redirect(self, url):
        assert not self.__client
        self.write(RedirectError(url).response())
    
    def notfound(self):
        assert not self.__client
        self.write(NotFoundError().response())



class HTTPError(Exception):
    def __init__(self, code, reason, headers = None):
        self.code    = code
        self.reason  = reason
        self.headers = headers or []
    def response(self):
        return b'HTTP/1.1 {} {}\r\n{}\r\n'.format(
            self.code,
            self.reason,
            '\r\n'.join(self.headers))

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

class RedirectError(HTTPError):
    def __init__(self, url):
        HTTPError.__init__(self, 302, 'Found', ['Location: {}'.format(url)])