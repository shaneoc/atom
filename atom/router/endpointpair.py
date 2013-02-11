from zope.interface import implements

from twisted.internet.interfaces import IStreamClientEndpoint
from twisted.internet.interfaces import IStreamServerEndpoint
from twisted.internet.interfaces import ITransport
from twisted.internet.error import ConnectionDone
from twisted.python.failure import Failure
from twisted.internet import defer

class EndpointPair(object):
    implements(IStreamClientEndpoint, IStreamServerEndpoint)
    
    def __init__(self):
        self._serverFactory = None
    
    def connect(self, protocolFactory):
        clientProtocol = protocolFactory.buildProtocol(None)
        serverProtocol = self._serverFactory.buildProtocol(None)
        
        serverProtocol.makeConnection(EndpointPairTransport(clientProtocol))
        clientProtocol.makeConnection(EndpointPairTransport(serverProtocol))
        
        return defer.succeed(clientProtocol)
    
    def listen(self, protocolFactory):
        self._serverFactory = protocolFactory
        


class EndpointPairTransport(object):
    implements(ITransport)
    
    def __init__(self, destProtocol):
        self.destProtocol = destProtocol
        self.disconnecting = 0
    
    def write(self, data):
        self.destProtocol.dataReceived(data)
    
    def writeSequence(self, data):
        for s in data:
            self.write(s)
    
    def loseConnection(self):
        #import traceback
        #traceback.print_stack()
        self.destProtocol.connectionLost(Failure(ConnectionDone))
    
    def getPeer(self):
        None
    
    def getHost(self):
        None