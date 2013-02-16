import sqlite3

from atom.router.directory import Directory

class Router(object):
    def __init__(self, ip, port, apps_dir, run_dir, db_filename):
        self.secure = False
        self.database = sqlite3.connect(db_filename)
        self.directory = Directory(self)
        self.sessions = SessionManager(self)