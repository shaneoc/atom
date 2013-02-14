from gevent.event import Event
from gevent import Timeout

from atom.router2.logger import getLogger

log = getLogger(__name__)


MAX_LINE_LENGTH = 8192
MAX_NUM_HEADERS = 100
RECV_BUFFER_SIZE = 4096
RECV_TIMEOUT = 60*60 # TODO 1 hour.. is this a good value?
# TODO do I need a SEND_TIMEOUT?

status_codes = {
    100: 'Continue',
    200: 'OK',
    302: 'Found',
    400: 'Bad Request',
    403: 'Forbidden',
    404: 'Not Found',
    405: 'Method Not Allowed',
    411: 'Length Required',
    500: 'Internal Server Error',
}


def http_socket_pair():
    a, b = FakeSocketPair()
    return HTTPSocket(a), HTTPSocket(b)


class FakeSocketPair(object):
    def __new__(cls):
        a, b = object.__new__(cls), object.__new__(cls)
        a._other = b
        b._other = a
        a._data = ''
        b._data = ''
        a._data_ready = Event()
        b._data_ready = Event()
        a._closed = False
        b._closed = False
        return a, b
    
    def recv(self, _):
        if not self._closed:
            self._data_ready.wait()
            self._data_ready.clear()
        data, self._data = self._data, ''
        return data
    
    def sendall(self, data):
        if not self._closed and len(data) > 0:
            self._other._data += data
            self._other._data_ready.set()
    
    def close(self):
        self._closed = True
        self._other._closed = True
        self._other._data_ready.set()


class HTTPSocket(object):
    def __init__(self, sock):
        self._sock = sock
        self._buf = ''
    
    def _read_line(self):
        while True:
            try:
                line, self._buf = self._buf.split('\r\n',1)
            except ValueError:
                if len(self._buf) > MAX_LINE_LENGTH:
                    raise HTTPSyntaxError('Line too long')
                with Timeout(RECV_TIMEOUT, HTTPTimeoutError()):
                    data = self._sock.recv(RECV_BUFFER_SIZE)
                if len(data) == 0:
                    raise HTTPConnectionClosed()
                self._buf += data
            else:
                return line
    
    def _read_bytes(self, size):
        while True:
            if len(self._buf) > 0:
                piece, self._buf = self._buf[:size], self._buf[size:]
                yield piece
                size -= len(piece)
                if size == 0:
                    return
            with Timeout(RECV_TIMEOUT, HTTPTimeoutError()):
                data = self._sock.recv(RECV_BUFFER_SIZE)
            if len(data) == 0:
                raise HTTPConnectionClosed()
            self._buf += data
    
    def _read_all(self):
        yield self._buf
        while True:
            data = self._sock.recv(RECV_BUFFER_SIZE)
            if len(data) == 0:
                raise HTTPConnectionClosed()
            yield data
    
    def read_headers(self, type_, auto_continue=True):
        line = self._read_line()
        if type_ == 'request':
            while line == '':
                line = self._read_line()
        
        lines = []
        for _ in xrange(MAX_NUM_HEADERS):
            lines.append(line)
            line = self._read_line()
            if line == '':
                break
        else:
            raise HTTPSyntaxError('Too many headers')
        
        headers = HTTPHeaders.parse(type_, lines)
        
        self._expect_continue = False
        if type_ == 'request' and auto_continue and \
                headers.get_single('Expect') == '100-continue':
            self._expect_continue = True
        
        self._has_body = True
        if type_ == 'request':
            if not headers.get_chunked() and not headers.get_content_length():
                self._has_body = False
        else:
            if self._sent_method.upper() == 'HEAD':
                self._has_body = False
            if headers.code >= 100 and headers.code < 200:
                self._has_body = False
            if headers.code == 204 or headers.code == 304:
                self._has_body = False
        
        self._chunked = headers.get_chunked()
        self._content_length = headers.get_content_length()
        return headers
    
    def send_headers(self, headers):
        headers.send(self._sock)
        if headers.type == 'request':
            self._sent_method = headers.method
    
    def read_body(self):
        raise NotImplementedError()
    
    def read_raw_body(self):
        if self._expect_continue:
            # TODO what if they call send_headers first?
            self.send_headers(HTTPHeaders.response(100))
            self._expect_continue = False
        
        if not self._has_body:
            yield ''
            return
        
        if self._chunked:
            for piece in self._read_chunked_body():
                yield piece
        elif self._content_length:
            for data in self._read_bytes(self._content_length):
                yield data
        else:
            for data in self._read_all():
                yield data
    
    def _read_chunked_body(self):
        while True:
            line = self._read_line()
            try:
                chunk_size = int(line.split(';',1)[0],base=16)
            except ValueError:
                raise HTTPSyntaxError('Invalid chunk size')
            yield line + '\r\n'
            
            if chunk_size > 0:
                for data in self._read_bytes(chunk_size):
                    yield data
                line = self._read_line()
                if line != '':
                    raise HTTPSyntaxError('Chunk does not match chunk size')
                yield '\r\n'
            else:
                while True:
                    line = self._read_line()
                    yield line + '\r\n'
                    if line == '':
                        break
                break
    
    def send_body(self, data):
        raise NotImplementedError()
    
    def send_raw_body(self, data):
        if isinstance(data, str):
            self._sock.sendall(data)
        else:
            for d in data:
                self._sock.sendall(d)
    
    def close(self):
        self._sock.close()


class HTTPHeaders(object):
    def __init__(self, type_):
        assert type_ in ('request', 'response')
        self.type = type_
        self._headers = []
        self._chunked = None
        self._content_length = None
    
    @classmethod
    def parse(cls, type_, lines):
        self = cls(type_)
        
        first_line = lines[0].split(None, 3)
        if len(first_line) < 3:
            raise HTTPSyntaxError('Invalid first line: "{}"'.format(lines[0]))
        
        if type_ == 'request':
            self.method, self.uri, self.http_version = first_line
        else:
            self.http_version, self.code, self.message = first_line
            try:
                self.code = int(self.code)
            except ValueError:
                raise HTTPSyntaxError('Invalid first line: "{}"'.format(lines[0]))
        
        # TODO make this work with HTTP/1.0 and >HTTP/1.1 too
        if self.http_version != 'HTTP/1.1':
            raise HTTPSyntaxError('Unknown HTTP version: "{}"'.format(self.http_version))
        
        cur_header = None
        for line in lines[1:]:
            if line[0] in ' \t':
                if cur_header == None:
                    raise HTTPSyntaxError('Invalid header: "{}"'.format(line))
                cur_header += '\r\n' + line
            else:
                if cur_header != None:
                    self._add_raw(cur_header)
                cur_header = line
        if cur_header != None:
            self._add_raw(cur_header)
        
        self.check_syntax()
        return self
    
    def _add_raw(self, header):
        parts = header.split(':',1)
        if len(parts) != 2:
            raise HTTPSyntaxError('Invalid header: "{}"'.format(header))
        self.add(parts[0], parts[1])
    
    @classmethod
    def response(cls, code, message = None):
        self = cls('response')
        self.http_version = 'HTTP/1.1'
        self.code = int(code)
        self.message = message or status_codes[code]
        return self
    
    @classmethod
    def request(cls, method, uri):
        self = cls('request')
        self.method = method
        self.uri = uri
        self.http_version = 'HTTP/1.1'
        return self
    
    def send(self, sock):
        if self.type == 'request':
            sock.sendall('{} {} {}\r\n'.format(self.method, self.uri, self.http_version))
        else:
            sock.sendall('{} {} {}\r\n'.format(self.http_version, self.code, self.message))
        sock.sendall('\r\n'.join('{}:{}'.format(h[1], h[2]) for h in self._headers))
        sock.sendall('\r\n\r\n')
    
    def add(self, name, value):
        self._headers.append([name.lower().strip(), name, ' ' + value])
        self._updated()
    
    def remove(self, name):
        self._headers = [h for h in self._headers if h[0] != name.lower()]
        self._updated()
    
    def set(self, name, value):
        self.remove(name)
        self.add(name, value)
    
    def get(self, name):
        return [h[2].strip() for h in self._headers if h[0] == name.lower()]
    
    def get_single(self, name):
        vals = self.get(name)
        if len(vals) > 1:
            raise HTTPSyntaxError('Header "{}" present multiple times'.format(name))
        return vals[0] if len(vals) != 0 else None
    
    def check_syntax(self):
        self.get_chunked()
        self.get_content_length()
        return True
    
    def _updated(self):
        self._chunked = None
        self._content_length = None
    
    def get_chunked(self):
        if self._chunked == None:
            te_headers = [h[2] for h in self._headers if h[0] == 'transfer-encoding']
            encodings = [value.lower().strip() for header in te_headers for value in header.split(';')]
            self._chunked = False
            if len(encodings) > 0:
                self._chunked = (encodings[-1] == 'chunked')
                if any(e == 'chunked' for e in encodings[:-1]):
                    raise HTTPSyntaxError('Invalid Transfer-Encoding')
        return self._chunked
    
    def get_content_length(self):
        if self._content_length == None:
            if any(h[0] == 'transfer-encoding' for h in self._headers):
                return None
            cl_headers = [h[2] for h in self._headers if h[0] == 'content-length']
            if len(cl_headers) == 1:
                try:
                    self._content_length = int(cl_headers[0].strip())
                except ValueError:
                    raise HTTPSyntaxError('Invalid Content-Length')
            elif len(cl_headers) > 1:
                raise HTTPSyntaxError('Too many Content-Length headers')
        return self._content_length
    
    def extract_cookie(self, name):
        if self.type == 'request':
            cookie_values = []
            for h in self._headers:
                if h[0] == 'cookie':
                    cookies = [c.split(b'=') for c in h[2].split(b';')]
                    cookie_values.extend(c[1].strip() for c in cookies if c[0].strip().lower() == name.lower())
                    cookies = [c for c in cookies if c[0].strip().lower() != name.lower()]
                    h[2] = ';'.join('='.join(c) for c in cookies)
            self._headers = [h for h in self._headers if not (h[0] == 'cookie' and len(h[2]) == 0)]
            return cookie_values
        else:
            self._headers = [h for h in self._headers if not (h[0] == 'set-cookie' and h[2].split('=',1)[0].strip().lower() == name.lower())]
    
    @property
    def path(self):
        return self.uri.split('?',1)[0]

class HTTPTimeoutError(Exception):
    pass

class HTTPConnectionClosed(Exception):
    pass

class HTTPSyntaxError(Exception):
    pass
