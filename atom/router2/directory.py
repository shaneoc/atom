
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
    
    def check_login(self, username, password):
        return username == 'shane' and password == 'test'
    
    def check_authentication(self, src_user, src_hostname, dest_hostname):
        pass
    
    def get_module(self, hostname):
        pass

class Module(object):
    def get_endpoint(self, path):
        pass

class User(object):
    pass