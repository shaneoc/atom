import os
import shutil
import shlex
import subprocess

from twisted.internet import reactor
from twisted.python import log
from twisted.internet.endpoints import UNIXClientEndpoint

from zope.interface import implements, Interface

from atom.router.database import Database
from atom.router.manifest import ModuleManifest, ModuleManifestError

# * each module has an owner, which is either a regular user or the "system user"
# * when a module makes an API call to another, it does so using the owner's permissions
# * things that work under the authorization layer, like an smb app, can run
#    as the system user, since it takes user/passwords and translates that to access
#    to their stuff
#    - apps could possibly though be optionally written to be system user or regular user
#      perhaps, depending on configuration, and in regular user mode they're only able to
#      run as that one user?


#class ModuleManager(object):
#    def __init__(self, db_filename, modules_dir, runtime_dir):
#        self.db = Database(db_filename)
#        self.modules_dir = modules_dir
#        self.runtime_dir = runtime_dir
#        
#        self.modules = []
#        for db_module in self.db.modules:
#            try:
#                self.modules.append(Module(self, db_module))
#                log.msg('Loaded module: ' + db_module.name)
#            except ModuleLoadError as e:
#                log.err(e, 'unable to load module "{}"'.format(db_module.name))
#        
#        

class Module(object):
    def getEndpoint(self):
        raise NotImplementedError()


class UnixDomainModule(Module):
    def __init__(self, name, path, hostnames, command, socket_filename):
        self.name            = name
        self.path            = path
        self.hostnames       = hostnames
        self.command         = command
        self.socket_filename = socket_filename
        
        env = {n:v for n,v in os.environ.iteritems()}
        env['ATOM_SOCKET'] = self.socket_filename
        subprocess.Popen(shlex.split(self.command), cwd=self.path, env=env)
        
        #pid = os.fork()
        #if pid != 0:
        #    self.pid = pid
        #else:
        #    os.environ['LISTEN_PID'] = str(os.getpid())
        #    os.environ['LISTEN_FDS'] = '1'
        #    os.dup2(s.fileno(), 3)
        #    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        #    os.closerange(4, hard-1)
        #    os.chdir(self.path)
        #    args = shlex.split(self.command)
        #    os.execvp(args[0], args)
    
    def getEndpoint(self):
        return UNIXClientEndpoint(reactor, self.socket_filename)



class ModuleError(Exception):
    pass

class ModuleLoadError(ModuleError):
    pass