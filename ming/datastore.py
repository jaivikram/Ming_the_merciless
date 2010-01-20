from __future__ import with_statement
import time
import logging

from threading import Lock

from pymongo.connection import Connection
from pymongo.master_slave_connection import MasterSlaveConnection
from pymongo import database

from .utils import parse_uri

log = logging.getLogger(__name__)

class DataStore(object):
    """Manages a connections to Mongo, with seprate connections per thread."""

    def __init__(self, master='mongo://localhost:27017/gutenberg', slave=None,
                 connect_retry=3):
        # self._tl_value = ThreadLocal()
        self._conn = None
        self._lock = Lock()
        self._connect_retry = connect_retry
        self.configure(master, slave)

    def __repr__(self):
        return 'DataStore(master=%r, slave=%r)' % (
            self.master_args, self.slave_args)

    def configure(self, master='mongo://localhost:27017/gutenberg', slave=None):
        log.disabled = 0 # @%#$@ logging fileconfig disables our logger
        if isinstance(master, basestring):
            master = [ master ]
        if isinstance(slave, basestring):
            slave = [ slave ]
        if master is None: master = []
        if slave is None: slave = []
        self.master_args = [ parse_uri(s) for s in master if s ]
        self.slave_args = [ parse_uri(s) for s in slave if s ]
        if len(self.master_args) > 2:
            log.warning(
                'Only two masters are supported at present, you specified %r',
                master)
            self.master_args = self.master_args[:2]
        if len(self.master_args) > 1 and self.slave_args:
            log.warning(
                'Master/slave is not supported with replica pairs')
            self.slave_args = []
        self.database = (self.master_args+self.slave_args)[0]['path'][1:]
        for a in self.master_args + self.slave_args:
            assert a['path'] == '/' + self.database, \
                "All connections MUST use the same database"

    @property
    def conn(self):
        for attempt in xrange(self._connect_retry+1):
            if self._conn is not None: break
            with self._lock:
                if self._connect() is None:
                    time.sleep(1)
        return self._conn

    def _connect(self):
        self._conn = None
        try:
            if len(self.master_args) == 2:
                self._conn = Connection.paired(
                    (str(self.master_args[0]['host']), int(self.master_args[0]['port'])),
                    (str(self.master_args[1]['host']), int(self.master_args[1]['port'])),
                    pool_size=int(self.master_args[0]['query'].get('pool_size','16')))
            else:
                if self.master_args:
                    try:
                        network_timeout = self.master_args[0]['query'].get('network_timeout')
                        if network_timeout is not None:
                            network_timeout = float(network_timeout)
                        master = Connection(str(self.master_args[0]['host']), int(self.master_args[0]['port']),
                                            pool_size=int(self.master_args[0]['query'].get('pool_size','16')),
                                            network_timeout=network_timeout)
                        ##authenticating  when the db requires it to be done.
                        if self.master_args[0].get('username') and self.master_args[0].get('password'):
                            db = database.Database(master, self.master_args[0]['path'][1:])
                            db.authenticate(self.master_args[0]['username'], 
                                            self.master_args[0]['password'])
                        ##
                    except:
                        if self.slave_args:
                            log.exception('Cannot connect to master: %s will use slave: %s' % (self.master_args, self.slave_args))
                            # and continue... to use the slave only
                            master = None
                        else:
                            raise
                else:
                    log.info('No master connection specified, using slaves only: %s' % self.slave_args)
                    master = None

                if self.slave_args:
                    slave = []
                    for a in self.slave_args:
                        network_timeout = a['query'].get('network_timeout')
                        if network_timeout is not None:
                            network_timeout = float(network_timeout)
                        slave.append(
                            Connection(str(a['host']), int(a['port']),
                                       pool_size=int(a['query'].get('pool_size','16')),
                                       slave_okay=True,
                                       network_timeout=network_timeout,
                                      )
                        )
                    if master:
                        self._conn = MasterSlaveConnection(master, slave)
                    else:
                        self._conn = slave[0]

                else:
                    self._conn = master
        except:
            log.exception('Cannot connect to %s %s' % (self.master_args, self.slave_args))
        else:
            #log.info('Connected to %s %s' % (self.master_args, self.slave_args))
            pass
        return self._conn

    @property
    def db(self):
        return getattr(self.conn, self.database, None)
