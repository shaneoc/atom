#!/usr/bin/python

import os
#import sys

#from atom.router import Router
from atom.router.proxy import ProxyServer

#Router(ip          = '127.0.0.1',
#       port        = 8080,
#       apps_dir    = os.path.abspath('../../'),
#       run_dir     = os.path.abspath('socket_dir'),
#       db_filename = os.path.abspath('config.db'))

ProxyServer(None, '127.0.0.1', 8080).start()
