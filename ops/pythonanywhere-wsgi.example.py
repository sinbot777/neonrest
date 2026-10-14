"""Example dispatcher; configure secrets privately, never in this file."""
import os
import sys
sys.path.insert(0, '/home/sinbot')
os.environ['NEONREST_PRODUCTION_MAIL_QUEUE'] = '1'
from neonrest.app import app as production_app
from neonrest_sandbox.app import app as sandbox_app
from werkzeug.middleware.dispatcher import DispatcherMiddleware
application = DispatcherMiddleware(production_app, {'/sandbox': sandbox_app})
