#!/usr/bin/python

import os
#import sys

#from twisted.python import log

#from atom.router import Router
from atom.router2.proxy import ProxyServer

#log.startLogging(sys.stdout)

#Router(ip          = '127.0.0.1',
#       port        = 8080,
#       apps_dir    = os.path.abspath('../../'),
#       run_dir     = os.path.abspath('socket_dir'),
#       db_filename = os.path.abspath('config.db'))

ProxyServer(None, '127.0.0.1', 8080).start()
