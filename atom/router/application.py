import os
import json
import subprocess
import shlex
import shutil

class ApplicationManager(object):
    def __init__(self, apps_dir):
        for filename in os.listdir(self.apps_dir):
            app_path = os.path.join(self.apps_dir, filename)
            if not os.path.isdir(app_path):
                continue
            
            try:
                app = Application(self, app_path)
                print('Loaded app: ' + app.hostname)
            except ApplicationError as e:
                print('Error: unable to load app at path "{}": {}'.format(app_path, e))
                continue
            
            if app.hostname in self.apps:
                print('Error: unable to load app at path "{}": duplicate hostname'.format(app_path))
                continue
            
            self.apps[app.hostname] = app

class Application(object):
    def __init__(self, router, path):
        self.router         = router
        self.path           = path
        
        filename = os.path.join(self.path, 'app.manifest')
        if not os.path.isfile(filename):
            raise ApplicationError('missing app manifest')
        
        try:
            with open(filename, 'r') as f:
                manifest = json.load(f)
        except StandardError as e:
            raise ApplicationError('unable to read manifest file: {}'.format(e))
        
        for key in 'hostname','command':
            if key not in manifest:
                raise ApplicationError('manifest missing "{}" key'.format(key))
        
        self.hostname = manifest['hostname']
        self.command  = manifest['command']
    
    
    def start(self):
        app_socket_dir = os.path.join(self.router.run_dir, 'app-{}'.format(self.hostname))
        if os.path.exists(app_socket_dir):
            shutil.rmtree(app_socket_dir)
        os.mkdir(app_socket_dir)
        os.chmod(app_socket_dir, 0700)
        
        self.socket_filename = os.path.join(app_socket_dir, 'socket')
        
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
    
  


class ApplicationError(Exception):
    pass