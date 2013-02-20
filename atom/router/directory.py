
class Directory(object):
    def __init__(self, router):
        self.router = router
    
    def start(self):
        db = self.router.database
        db.execute(
            'CREATE TABLE IF NOT EXISTS users (' +
            'id INTEGER PRIMARY KEY, name TEXT, password TEXT)')
        db.execute(
            'INSERT OR REPLACE INTO users VALUES (0, ?, ?)', ('system', None))
        
        db.execute(
            'CREATE TABLE IF NOT EXISTS modules (' +
            'id INTEGER PRIMARY KEY, name TEXT)')
        
        db.execute(
            'CREATE TABLE IF NOT EXISTS hostnames (' +
            'id INTEGER PRIMARY KEY, hostname TEXT UNIQUE, module_id INTEGER)')
        
    
    def get_users(self):
        pass
    
    def get_modules(self):
        pass
    
    def get_system_hostname(self):
        return 'sys.xvc.cc:8080'
    
    def get_shell_hostname(self, uid):
        return 'home.xvc.cc:8080'
    
    def check_login(self, username, password):
        if username == 'shane' and password == 'test':
            return 1
        else:
            return None
    
    def check_authorization(self, uid, hostname):
        return True
    
    def get_socket(self, hostname, uri):
        return False

class Module(object):
    def get_endpoint(self, path):
        pass

class User(object):
    pass