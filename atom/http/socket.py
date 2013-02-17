from urlparse import parse_qs

from gevent import Timeout

from atom.http.exceptions import HTTPConnectionClosedError, HTTPSyntaxError, HTTPTimeoutError
from atom.http.headers import HTTPHeaders

MAX_LINE_LENGTH = 8192
MAX_NUM_HEADERS = 100
RECV_BUFFER_SIZE = 4096
RECV_TIMEOUT = 60*60 # TODO 1 hour.. is this a good value?
# TODO do I need a SEND_TIMEOUT?

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
                    raise HTTPConnectionClosedError()
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
                raise HTTPConnectionClosedError()
            self._buf += data
    
    def _read_all(self):
        yield self._buf
        while True:
            data = self._sock.recv(RECV_BUFFER_SIZE)
            if len(data) == 0:
                return
            yield data
    
    def read_headers(self, type_):
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
        
        #self._expect_continue = False
        #if type_ == 'request' and auto_continue and \
        #        headers.get_single('Expect') == '100-continue':
        #    self._expect_continue = True
        
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
        self._content_type = headers.get_single('Content-Type')
        return headers
    
    def send_headers(self, headers):
        headers.send(self._sock)
        
        self._sent_chunked = headers.get_chunked()
        
        if headers.type == 'request':
            self._sent_method = headers.method
    
    def read_body(self, raw=False):
        #if self._expect_continue:
        #    # TODO what if they call send_headers first?
        #    self.send_headers(HTTPHeaders.response(100))
        #    self._expect_continue = False
        
        if not self._has_body:
            yield ''
            return
        
        if self._chunked:
            for piece in self._read_chunked_body(raw):
                yield piece
        elif self._content_length != None:
            for data in self._read_bytes(self._content_length):
                yield data
        else:
            for data in self._read_all():
                yield data
    
    def read_form_body(self):
        if self._content_type == 'application/x-www-form-urlencoded':
            return parse_qs(''.join(self.read_body()))
        else:
            raise NotImplementedError()
    
    def _read_chunked_body(self, raw):
        while True:
            line = self._read_line()
            try:
                chunk_size = int(line.split(';',1)[0],base=16)
            except ValueError:
                raise HTTPSyntaxError('Invalid chunk size')
            if raw:
                yield line + '\r\n'
            
            if chunk_size > 0:
                for data in self._read_bytes(chunk_size):
                    yield data
                line = self._read_line()
                if line != '':
                    raise HTTPSyntaxError('Chunk does not match chunk size')
                if raw:
                    yield '\r\n'
            else:
                while True:
                    line = self._read_line()
                    if raw:
                        yield line + '\r\n'
                    if line == '':
                        break
                break
    
    def send_body(self, data, raw=False):
        if not raw and self._sent_chunked:
            raise NotImplementedError()
        
        if isinstance(data, str):
            self._sock.sendall(data)
        else:
            for d in data:
                self._sock.sendall(d)
    
    def close(self):
        self._sock.close()



