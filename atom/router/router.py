import os
import shutil

from twisted.python import log
from twisted.internet import reactor
from twisted.internet.endpoints import TCP4ServerEndpoint

from atom.router.proxy import ProxyFactory
from atom.router.database import Database
from atom.router.module import UnixDomainModule, ModuleLoadError
from atom.router.manifest import ModuleManifest, ModuleManifestError
from atom.router.auth import AuthModule

class Router(object):
    def __init__(self, ip, port, apps_dir, run_dir, db_filename):
        self.db = Database(db_filename)
        
        if os.path.exists(run_dir):
            shutil.rmtree(run_dir)
        
        os.mkdir(run_dir)
        os.chmod(run_dir, 0700)
        
        self.modules = [AuthModule('auth.xvc.cc')]
        for db_module in self.db.modules:
            module_path = os.path.join(apps_dir, db_module.name)
            try:
                manifest = ModuleManifest(module_path)
            except ModuleManifestError as e:
                log.err('Error loading module "{}": {}'.format(db_module.name, e))
                continue
            
            try:
                if manifest.type == 'unix':
                    socket_dir = os.path.join(run_dir, 'module-{}'.format(db_module.name))
                    if os.path.exists(socket_dir):
                        shutil.rmtree(socket_dir)
                    os.mkdir(socket_dir)
                    os.chmod(socket_dir, 0700)
                    socket_filename = os.path.join(socket_dir, 'socket')
                    
                    self.modules.append(UnixDomainModule(
                        name            = db_module.name,
                        path            = module_path,
                        hostnames       = db_module.hostnames,
                        command         = manifest.command,
                        socket_filename = socket_filename))
                
                log.msg('Loaded module: ' + db_module.name)
            except ModuleLoadError as e:
                log.err(e, 'unable to load module "{}"'.format(db_module.name))
        
        self.hostnames = {}
        for module in self.modules:
            for hostname in module.hostnames:
                if hostname in self.hostnames:
                    log.err('Multiple modules have registered hostname "{}"'.format(hostname))
                else:
                    self.hostnames[hostname] = module
        
        endpoint = TCP4ServerEndpoint(reactor, interface=ip, port=port)
        endpoint.listen(ProxyFactory(self))
        reactor.run() #@UndefinedVariable
        
        
    
#    def start(self):
#        print('Enumerating apps...')
#        self.enumerate_apps()
#        print('Starting!')
#        for app in self.apps.itervalues():
#            app.start()
#        self.request_proxy.start()
#        print('Entering loop!')
#  
#    def enumerate_apps(self):
#        for filename in os.listdir(self.apps_dir):
#            app_path = os.path.join(self.apps_dir, filename)
#            if not os.path.isdir(app_path):
#                continue
#            
#            try:
#                app = Application(self, app_path)
#                print('Loaded app: ' + app.hostname)
#            except ApplicationError as e:
#                print('Error: unable to load app at path "{}": {}'.format(app_path, e))
#                continue
#            
#            if app.hostname in self.apps:
#                print('Error: unable to load app at path "{}": duplicate hostname'.format(app_path))
#                continue
#            
#            self.apps[app.hostname] = app
    



#class SocketManager(object):
#    def __init__(self, run_dir):
#        self.run_dir = run_dir
#        
#        if os.path.exists(run_dir):
#            shutil.rmtree(run_dir)
#        
#        os.mkdir(run_dir)
#        os.chmod(run_dir, 0700)
#        
#        self.router_socket_filename = os.path.join(run_dir, 'router.socket')
#        if os.path.exists(self.router_socket_filename):
#            os.unlink(self.router_socket_filename)
#        self.router_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
#        self.router_socket.bind(self.router_socket_filename)
#    
#    def create_socket(self, app_hostname):
#        app_dir = os.path.join(self.run_dir, 'app-{}'.format(app_hostname))
#        
#        if os.path.exists(app_dir):
#            shutil.rmtree(app_dir)
#        
#        os.mkdir(app_dir)
#        os.chmod(app_dir, 0700)
#        
#        filename = os.path.join(app_dir, 'socket')
#        if os.path.exists(filename):
#            os.unlink(filename)
#        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
#        s.bind(filename)
#        
#        return filename, s


