from urlparse import urlparse, parse_qs

from atom.http.exceptions import HTTPSyntaxError

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
        
        first_line = lines[0].split(None, 2)
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
        return urlparse(self.uri).path
    
    @property
    def args(self):
        return parse_qs(urlparse(self.uri).query)
