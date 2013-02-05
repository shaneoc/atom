#!/usr/bin/python

import os
import sys

from twisted.python import log

from atom.router import Router

log.startLogging(sys.stdout)

Router(ip          = '127.0.0.1',
       port        = 8080,
       apps_dir    = os.path.abspath('../../'),
       run_dir     = os.path.abspath('socket_dir'),
       db_filename = os.path.abspath('config.db'))
