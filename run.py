#!/usr/bin/python

import os

from atom.router import Router

Router(ip          = '127.0.0.1',
       port        = 8080,
       apps_dir    = os.path.abspath('../../'),
       run_dir     = os.path.abspath('socket_dir'),
       db_filename = os.path.abspath('config.db'))
