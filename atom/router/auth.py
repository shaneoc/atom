from string import Template
from urlparse import urlparse

from atom.router.endpointpair import EndpointPair
from atom.router.module import Module

from twisted.web.resource import Resource
from twisted.web.server import Site

class AuthModule(Module):
    def __init__(self, login_hostname):
        self.login_hostname = login_hostname
        self.hostnames = [login_hostname, 'auth.atom-service']
    
    def checkAuthorization(self, cookie, url):
        url = urlparse(url)
        if url.hostname == self.login_hostname:
            return True, None
        else:
            return False, 'http://' + self.login_hostname + ':8080/?url=' + url.geturl()
        
    def getEndpoint(self):
        endpoint = EndpointPair()
        endpoint.listen(Site(AuthResource()))
        return endpoint

class AuthResource(Resource):
    isLeaf = True
    
    def render_GET(self, request):
        page_vars = {
            'message': '',
            'post_url': request.uri
        }
        
        with open('login.html') as f:
            return Template(f.read()).substitute(page_vars)