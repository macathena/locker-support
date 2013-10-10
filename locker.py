"""
A modern re-interpretation of Athena's liblocker, in Python.
"""
from __future__ import division
import math
import errno, re, os, pwd
import logging
import warnings

import afs.fs
import hesiod

logger = logging.getLogger('locker')

_classNameRE = re.compile(r'([A-Z]+)Locker')
_mountpoint = '/mit'

class LockerError(Exception):
    """
    Base class for Exceptions in this module.
    """
    def __init__(self, message):
        self.message = message

    def __str__(self):
        return "Error: %s" % (self.message)

    def __repr__(self):
        return self.__str__()

class NamedLockerError(LockerError):
    """
    Exceptions for which the locker name is known.
    """
    def __init__(self, name, message):
        self.name = name
        LockerError.__init__(self, message)

    def __str__(self):
        return "%s: %s" % (self.name, self.message)

class LockerNotSupportedError(NamedLockerError):
    """
    The locker is not supported, or the operation is not supported
    on lockers of this type.
    """
    def __init__(self, name, lockerType, operation=None):
        msg = "'%s' lockers are not supported." % (lockerType)
        if operation is not None:
            msg = "'%s' operation not supported for '%s' lockers." % \
                  (operation, lockerType)
        NamedLockerError.__init__(self, name, msg)

class LockerNotFoundError(NamedLockerError):
    """
    The locker does not exist.
    """
    def __init__(self, name):
        NamedLockerError.__init__(self, name, "Locker unknown.")

class LockerUnavailableError(NamedLockerError):
    """
    The locker exists, but is not available.
    """
    def __init__(self, name, message="Locker unavailable."):
        NamedLockerError.__init__(self, name, message)

class LockerQuota(dict):
    """
    Object for storing locker quota, in an extensible manner, that
    also deals with KB vs KiB correctly, because pedantry.
    """
    def __init__(self, usage, maximum, units=1024):
        """
        Initialize a quota object, given a usage amount and a maximum.
        Units determines what the typical metric prefixes mean.
        """
        if type(units) is not int or units not in [1000, 1024]:
            raise TypeError("units must be 1000 or 1024")
        dict.__init__(self)
        self['usage'] = usage
        self['max'] = maximum
        self['units'] = units

    def percentage(self):
        # Historically, unlimited quotas in liblocker have been represented by
        # a max value of 0 and a usage of 0%.  We could make this more friendly
        # by returning -1 so as to differentiate between no limit and a usage
        # so small so as to essentially use 0% of your quota after rounding.
        if self['max'] == 0:
            return 0
        else:
            return int((self['usage'] / self['max']) * 100)

    def _sizeStr(num):
        _suffixes = { 0: 'KB',
                      1: 'MB',
                      2: 'GB',
                      3: 'TB',
                      4: 'PB',
                      }
        i = float(num)
        for power in sorted(_suffixes.keys()):
            if i < self['units']:
                break
            i /= self['units']
        return "%.1f %s" % (i, _suffixes[power])

class Locker(object):
    def __init__(self, name, data):
        self.name = name
        self._data = data
        self.mountpoint = None
        self.path = None
        self.auth = None
        self.authSupported = False
        self.authRequired = False
        self.authDesired = False
        self.parseData()

    def parseData(self):
        pass

    def getAuthCommandline(self):
        """
        Return the command line required to authenticate.
        (suitable for passing to subprocess.Popen)
        """
        return None

    def getDeauthCommandline(self):
        """
        Return the command line required to remove authentication.
        (suitable for passing to subprocess.Popen)
        """
        return None

    def getZephyrTriplets(self):
        """
        Return a list of 3-tuples representing Zephyr triplets
        one should subscribe to when attaching this locker.
        """
        return []

    def attach(self, **kwargs):
        """
        Attempt to attach the locker.
        """
        logger.debug("Attempting to attach %s...", self.name)
        if self.mountpoint is None or self.path is None:
            raise LockerNotSupportedError(self.name, self._type(), 'attach')
        if not self.mountpoint.startswith(_mountpoint):
            raise NamedLockerError(self.name, "mountpoint %s is not under %s" % (self.mountpoint, _mountpoint))
        try:
            os.symlink(self.path, self.mountpoint)
        except OSError as e:
            if e.errno == errno.EEXIST:
                if 'force' in kwargs and kwargs['force']:
                    os.remove(self.mountpoint)
                    self.attach()
                # Call it success if we're already attached
                if not os.path.realpath(self.mountpoint) == \
                       os.path.realpath(self.path):
                    raise NamedLockerError(self.name,
                                           "%s already attached on %s" % \
                                           (os.path.realpath(self.mountpoint),
                                            self.mountpoint))
            else:
                raise NamedLockerError(self.name,
                                       e.strerror + " while attaching")

    def detach(self):
        """
        Attempt to detach the locker.
        """
        logger.debug("Attempting to detach %s...", self.name)
        if self.mountpoint is None:
            raise LockerNotSupportedError(self.name, self._type(), 'detach')
        if not self.mountpoint.startswith(_mountpoint):
            raise NamedLockerError(self.name, "mountpoint %s is not under %s" % (self.mountpoint, _mountpoint))
        try:
            os.unlink(self.mountpoint)
        except OSError as e:
            raise NamedLockerError(self.name,
                                   e.strerror + " while detaching")

    def automountable(self):
        """
        Return True if the locker can be auto-mounted.
        """
        return self.mountpoint is not None

    def getQuota(self):
        """
        Return a the quota as a dict-like object
        """
        raise LockerNotSupportedError(self.name, self._type(), "getQuota()")

    def getFileServers(self):
        """
        Return a list of hostnames or IP addresses of file servers
        which serve this locker.
        """
        raise LockerNotSupportedError(self.name, self._type(),
                                      "getFileServers()")

    def _type(self):
        m = _classNameRE.match(self.__class__.__name__)
        return m.group(1) if m is not None else None

    def _serialize(self):
        return "%s:%s:%s" % (self.name, self._type(),
                             self._data)

    def __str__(self):
        return "%s -> %s" % (self.mountpoint, self.path)

    def __repr__(self):
        return "%s: %s (%s)" % (self.__class__.__name__,
                                self.name,
                                self.__str__())

class LOCLocker(Locker):
    """
    A class representing LOC lockers, which are just
    symlinks.  The mode bit is ignored.
    e.g. LOC /u1/lockers/sipb w /mit/sipb
    """
    def __init__(self, name, data):
        Locker.__init__(self, name, data)

    def parseData(self):
        parts = self._data.split(" ")
        if len(parts) != 3:
            raise NamedLockerError(self.name,
                                   "Invalid LOC locker data (%s)" % \
                                   (self._data,))
        self.path = parts[0]
        self.mountpoint = parts[2]
        # The auth bit is unused, but present
        self.auth = parts[1]

class AFSLocker(Locker):
    """
    A class representing AFS lockers.
    """
    def __init__(self, name, data):
        Locker.__init__(self, name, data)

    def parseData(self):
        parts = self._data.split(" ")
        if len(parts) != 3:
            raise NamedLockerError(self.name,
                                   "Invalid AFS locker data (%s)" % \
                                   (self._data,))
        self.path = parts[0]
        self.mountpoint = parts[2]
        self.auth = parts[1]
        self.authSupported = True
        self.authRequired = self.auth == 'w'
        self.authDesired = self.authRequired or (self.auth == 'r')

    def getAuthCommandline(self):
        return ['aklog', '-path', self.path]

    def getZephyrTriplets(self):
        rv = []
        try:
            cell = afs.fs.whichcell(self.path)
            rv.append(('filsrv', cell+':root.cell', '*'))
            rv.append(('filsrv', cell, '*'))
            try:
                volume = afs.fs.examine(self.path)[0].name
                rv.append(('filsrv', cell+':'+volume, '*'))
                # Because dirname is stupid if it ends in a trailing slash
                parent_dir = os.path.dirname(os.path.normpath(self.path))
                parent_vol = afs.fs.examine(parent_dir)[0].name
                # TODO: This is a hack until afs.vos exists.  Once it
                #       does, we should check if ParentId != Vid in
                #       the VolumeStatus, and get the ParentId's name
                if parent_vol.endswith('.readonly'):
                    parent_vol = parent_vol[0:len(parent_vol)-9]
                rv.append(('filsrv', cell+':'+parent_vol, '*'))
            except:
                pass
        except:
            pass
        for f in self.getFileServers():
            rv.append(('filsrv', f.lower(), '*'))
        return rv

    def getQuota(self):
        try:
            volstat = afs.fs.examine(self.path)[0]
            return LockerQuota(volstat.BlocksInUse, volstat.MaxQuota)
        except OSError as e:
            raise LockerError("Error getting AFS quota: %s: %s" % (self.path,
                              e.strerror))

    def getFileServers(self):
        try:
            return afs.fs.whereis(self.path)
        except:
            return []

class NFSLocker(Locker):
    """
    Stub support for NFS lockers.
    """
    def __init__(self, name, data):
        Locker.__init__(self, name, data)

    def parseData(self):
        parts = self._data.split(" ")
        if len(parts) != 4:
            raise NamedLockerError(self.name,
                                   "Invalid NFS locker data (%s)" % \
                                   (self._data,))
        self.path = parts[0]
        self.mountpoint = parts[3]
        self.auth = parts[2]
        self.server = parts[1]

    def getFileServers(self):
        return [self.server]

    def __str__(self):
        return "%s -> %s:%s" % (self.mountpoint, self.server, self.path)


class MULLocker(Locker):
    """
    Stub support for "MUL" lockers, which are pointers to
    a list of lockers.
    """

    def __init__(self, name, data):
        Locker.__init__(self, name, data)

    def parseData(self):
        self.sublockers = []
        for l in self._data.split(" "):
            self.sublockers.append(*lookup(l))

    def __str__(self):
        return ', '.join([x.__repr__() for x in self.sublockers])

# A mapping of filesystem type as specified in the Hesiod record
# to classes in this module.
_lockerTypes = {
    'AFS': AFSLocker,
    'NFS': NFSLocker,
    'MUL': MULLocker,
    'LOC': LOCLocker,
}

def fromSymlink(src, dst, mountpoint):
    path = os.path.join(mountpoint, dst)
    return LOCLocker(dst, "%s n %s" % (src, path))

def lookup(name):
    """
    Lookup a locker in Hesiod and return a list locker objects.  For
    FSGROUPs, the list will be sorted based on the priority of each
    record.

    Raises: LockerUnavailableError, LockerNotFoundError, LockerError
    """
    filesystems = resolve(name)
    lockers = []
    for f in filesystems:
        if f['type'] == 'ERR':
            raise LockerUnavailableError(name, f['data'])
        if f['type'] not in _lockerTypes:
            raise LockerNotSupportedError(name, f['type'])
        lockers.append(_lockerTypes[f['type']](name, f['data']))
    return lockers

def resolve(name):
    """
    Lookup a locker in Hesiod and return a list of dictionaries, with
    keys 'priority', 'data', and 'type'.   If the lookup found an FSGROUP,
    the list will be sorted based on key the key 'priority'.

    Raises: LockerNotFoundError, LockerError
    """
    filesystems = []
    # Avoid generating a confusing "message too long" error from
    # Hesiod.
    if name.startswith('.'):
        raise LockerError("Invalid locker name: " + name)
    try:
        filesystems = hesiod.FilsysLookup(name, parseFilsysTypes=False).filsys
    except IOError as e:
        if e.errno == errno.ENOENT:
            raise LockerNotFoundError(name)
        else:
            raise LockerError("Hesiod Error: %s while resolving %s" % \
                              (e.strerror if e.strerror else e.message, name))
    return filesystems

def ellipsize(text, maxlen):
    if len(text) <= maxlen:
        return text
    cutoff = (maxlen - 5) / 2
    return text[:int(math.ceil(cutoff))] + '[...]' + text[-int(math.floor(cutoff)):]

class attachtab(dict):
    """
    A magic dictionary with magic versions of __getitem__ and __contains__
    which allows the caller to access lockers by name or mountpoint.
    (This may or may not be a good idea.)
    """
    def __init__(self):
        dict.__init__(self)

    def __getitem__(self, key):
        if '/' in key:
            return dict.__getitem__(self, key)
        else:
            for k,v in self.items():
                if v.name == key:
                    return v
            raise KeyError(key)

    def __contains__(self, key):
        if '/' in key:
            return dict.__contains__(self, key)
        else:
            for k,v in self.items():
                if v.name == key:
                    return True
            return False

    def _legacyFormat(self):
        fmt = "%-30s %-26s %-9s %s\n"
        rv = fmt % ("filesystem", "mountpoint", "user", "mode")
        rv += fmt % ("----------", "----------", "----", "----")
        uid = os.getuid()
        try:
            username = pwd.getpwuid(uid).pw_name
        except Exception as e:
            username = "uid %d" % (uid,)
        for k,v in self.items():
            fs = v.name if v._type() != 'LOC' else v.path
            mode = v.auth if v.auth is not None else 'n'
            mode += ',nosuid'
            rv += fmt % (ellipsize(fs, 30), k, username, mode)
        return rv

def read_attachtab(mountpoint=_mountpoint):
    """
    Read the attachtab and return a dict() of
    mountpoint:Locker
    """
    rv = attachtab()
    try:
        with open(os.path.join(mountpoint, '.attachtab'), 'r') as f:
            for line in f:
                line = line.strip()
                if len(line) == 0:
                    continue
                parts = line.strip().split(':', 2)
                assert len(parts) == 3
                assert parts[0] not in rv
                assert parts[1] in _lockerTypes
                locker_mtpt = os.path.join(mountpoint,parts[0])
                rv[locker_mtpt] = _lockerTypes[parts[1]](parts[0],
                                                         parts[2])
                if locker_mtpt != rv[locker_mtpt].mountpoint:
                    warnings.warn("Mountpoint mismatch for locker %s" % \
                                      (parts[0]))
    except IOError as e:
        raise LockerError("Failed to read attachtab: %s" % (e,))
    return rv
