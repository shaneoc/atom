import gevent

_format = '{greenlet:016X} - {name}({level}): {msg}'
_loggers = {}

def getLogger(name):
    if not name in _loggers:
        _loggers[name] = Logger(name)
    return _loggers[name]

class Logger(object):
    def __init__(self, name):
        self.name = name
    
    def error(self, msg_, *args, **kwargs):
        self.log('ERROR', msg_, *args, **kwargs)
    
    def info(self, msg_, *args, **kwargs):
        self.log('INFO', msg_, *args, **kwargs)
    
    def debug(self, msg_, *args, **kwargs):
        self.log('DEBUG', msg_, *args, **kwargs)
    
    def log(self, level_, msg_, *args, **kwargs):
        msg = msg_.format(*args, **kwargs)
        
        print _format.format(
            greenlet=id(gevent.getcurrent()),
            name=self.name,
            level=level_,
            msg=msg)
        
        