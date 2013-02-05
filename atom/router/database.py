import sqlite3

class Database(object):
    def __init__(self, filename):
        self._db = sqlite3.connect(filename)
        
        self._db.execute(
            'CREATE TABLE IF NOT EXISTS users (' +
            'id INTEGER PRIMARY KEY, name TEXT, password TEXT)')
        self._db.execute(
            'INSERT OR REPLACE INTO users VALUES (0, ?, ?)', ('system', None))
        
        self._db.execute(
            'CREATE TABLE IF NOT EXISTS modules (' +
            'id INTEGER PRIMARY KEY, name TEXT)')
        
        self._db.execute(
            'CREATE TABLE IF NOT EXISTS hostnames (' +
            'id INTEGER PRIMARY KEY, hostname TEXT UNIQUE, module_id INTEGER)')
        
        self.load()
        
    def load(self):
        rows = self._db.execute(
            'SELECT id, name FROM users ORDER BY name')
        self.users = [User(id=r[0],name=r[1]) for r in rows]
        
        self.modules = []
        rows = self._db.execute('SELECT id, name FROM modules')
        for row in rows:
            hostname_rows = self._db.execute(
                'SELECT hostname FROM hostnames WHERE module_id=?', (row[0],))
            self.modules.append(Module(
                id        = row[0],
                name      = row[1],
                hostnames = [r[0] for r in hostname_rows]))
    
    def add_user(self, name):
        with self._db:
            self._db.execute(
                'INSERT INTO users VALUES (NULL,?)', (name,))
        
        self.load()
    


class User(object):
    def __init__(self, id, name): #@ReservedAssignment
        self.id   = id
        self.name = name

class Module(object):
    def __init__(self, id, name, hostnames): #@ReservedAssignment
        self.id        = id
        self.name      = name
        self.hostnames = hostnames