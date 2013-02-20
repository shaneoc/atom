from gevent.event import Event

from atom.http.socket import HTTPSocket

FAKESOCKET_BUFFER_SIZE = 8192

def http_socket_pair():
    client, server = FakeSocketPair()
    return HTTPSocket(client, 'client'), HTTPSocket(server, 'server')


class LoggingSocket(object):
    def __init__(self, sock, file_obj):
        self._sock = sock
        self._file = file_obj
    
    def recv(self, size):
        data = self._sock.recv(size)
        self._file.write('recv:\n|{}|\n'.format(data))
        self._file.flush()
        return data
    
    def sendall(self, data):
        self._file.write('send:\n|{}|\n'.format(data))
        self._file.flush()
        return self._sock.sendall(data)
    
    def close(self):
        self._sock.close()


class FakeSocketPair(object):
    def __new__(cls):
        a, b = object.__new__(cls), object.__new__(cls)
        a._other = b
        b._other = a
        a._buf = ''
        b._buf = ''
        a._read = Event()
        b._read = Event()
        a._wrote = Event()
        b._wrote = Event()
        a._closed = False
        b._closed = False
        return a, b
    
    def recv(self, size):
        while not self._closed and len(self._buf) == 0:
            self._wrote.wait()
            self._wrote.clear()
        data, self._buf = self._buf[:size], self._buf[size:]
        self._read.set()
        return data
    
    def sendall(self, data):
        while len(data) > 0:
            while not self._closed and len(self._other._buf) >= FAKESOCKET_BUFFER_SIZE:
                self._other._read.wait()
                self._other._read.clear()
            if self._closed:
                return
            size = min(len(data), FAKESOCKET_BUFFER_SIZE-len(self._other._buf))
            piece, data = data[:size], data[size:]
            self._other._buf += piece
            self._other._wrote.set()
    
    def close(self):
        self._closed = True
        self._read.set()
        self._wrote.set()
        self._other._closed = True
        self._other._read.set()
        self._other._wrote.set()
