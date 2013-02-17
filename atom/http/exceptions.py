
class HTTPError(Exception):
    pass

class HTTPTimeoutError(HTTPError):
    pass

class HTTPConnectionClosedError(HTTPError):
    pass

class HTTPSyntaxError(HTTPError):
    pass