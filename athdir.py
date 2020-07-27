"""
A Python re-implementation of Athena's libathdir
"""
import os
import six
import subprocess
import sys
import logging

logger = logging.getLogger('athdir')

def _machtype(arg=None):
    """
    Convenience function to run _machtype to get the canonical
    values of -C and -S in the event the environment doesn't
    have them.  Returns None or the output.  Per Debian policy,
    it will first attempt to run machtype in PATH, then explicitly.
    """
    rv = None
    for machtype in ['machtype', '/bin/machtype']:
        cmd = [machtype]
        if arg is not None:
            cmd.append(arg)
        try:
            rv = subprocess.Popen(cmd, stdout=subprocess.PIPE).communicate()[0].strip()
            return six.ensure_str(rv)
        except OSError as e:
            logger.info(e)
    return rv

class AthdirError(Exception):
    pass

class AthdirInternalError(AthdirError):
    pass

class Flavors():
    """
    An enum-esque thing representing the various "flavors" of
    directories we can request.
    """
    ARCH = 1
    SYS = 2
    MACH = 3
    PLAIN = 4

    printableFlags = { 'A': ARCH,
                       'M': MACH,
                       'S': SYS,
                       'P': PLAIN
                       }


class AthdirConvention():
    """
    The various types of "conventions" we have for paths, such
    as arch-dependent, old-style sysnames and machnames, etc.
    """
    def __init__(self, template, custom=False):
        self.template = template
        self.atsys = '%s' in template
        self.custom = custom
        self.flavors = { Flavors.ARCH: 'arch' in template,
                         Flavors.MACH: '%m' in template,
                         Flavors.SYS: self.atsys and not 'arch' in template}
        self.flavors[Flavors.PLAIN] = True not in self.flavors.values()

    def dependencyMatch(self, dependent=False):
        """
        Return True if the convention's dependency matches the
        dependency specified.  (e.g. .dependencyMatch(True) would
        return True if the convention is arch dependent.)
        """
        return True if self.custom else (dependent != self.flavors[Flavors.PLAIN])

    def acceptableFor(self, listOfAcceptable):
        """
        Return True if this convention is accepted for one or more of
        the list of flavors provided.
        """
        if self.custom:
            return True
        for a in listOfAcceptable:
            if self.flavors[a]:
                return True
        return False

    def __repr__(self):
        flags = { 'A': Flavors.ARCH,
                  'M': Flavors.MACH,
                  'S': Flavors.SYS,
                  'P': Flavors.PLAIN
                  }
        return "AthdirConvention: %s (%s%s%s)" % (self.template, ''.join([k for k,v in Flavors.printableFlags.items() if self.flavors[v]]), '@' if self.atsys else '', 'C' if self.custom else '')

class Athdir():
    _indepTypes = ("man", "include")
    # We are NOT adding any new ones below
    _sysFlavors = ("bin", "lib", "etc")
    _machFlavors = ("bin", "lib", "etc")

    _conventions = (AthdirConvention("%p/arch/%s/%t"),
                    AthdirConvention("%p/%s/%t"),
                    AthdirConvention("%p/%m%t"),
                    AthdirConvention("%p/%t"))

    def __init__(self, basePath='%p', dirType='%t', customTemplate=None,
                 sysName=None, hostType=None):
        self.path = basePath
        self.dirType = dirType
        self.compatlist = [sysName if sysName is not None else self.sysname()] + self.syscompatlist()
        self.hostType = hostType if hostType is not None else self.hosttype()
        # for unknown types, assume arch dependent
        self.archDependent = not dirType in self._indepTypes
        # We always try the arch flavors
        self.flavorsAcceptable = [ Flavors.ARCH ]
        if dirType in self._sysFlavors:
            logger.debug("Adding 'SYS' flavor")
            self.flavorsAcceptable.append(Flavors.SYS)
        if dirType in self._machFlavors:
            logger.debug("Adding 'MACH' flavor")
            self.flavorsAcceptable.append(Flavors.MACH)
        if ((Flavors.SYS not in self.flavorsAcceptable) and
            (Flavors.MACH not in self.flavorsAcceptable)):
            logger.debug("Adding 'PLAIN' flavor")
            self.flavorsAcceptable.append(Flavors.PLAIN)
        self.conventions = list(self._conventions)
        if customTemplate is not None:
            logger.debug("Adding custom template: %s", customTemplate)
            self.conventions.insert(0, AthdirConvention(customTemplate,
                                                        custom=True))

    def __repr__(self):
        return "Athdir: %s (%s, %s)" % (self.path, self.dirType,
                                        ''.join([k for k,v in Flavors.printableFlags.items() if v in self.flavorsAcceptable]))

    def __str__(self):
        return "Athdir: path=%s, type=%s, flags=%s, host=%s\n        compat=%s" % (self.path, self.dirType, ''.join([k for k,v in Flavors.printableFlags.items() if v in self.flavorsAcceptable]), self.hostType, self.compatlist)

    def _expand(self, template, sys):
        """
        Expand a template by filling in substitutions.
        """
        rv = template
        replacements = { '%s': sys,
                         '%m': self.hostType,
                         '%p': self.path,
                         '%t': self.dirType }
        for k,v in replacements.items():
            rv = rv.replace(k, v)
        return rv

    def get_paths(self, suppressEditorials=False, suppressSearch=False,
                  forceDependent=False, forceIndependent=False,
                  listAll=False):
        """
        Get a list of acceptable paths for an athdir specification.

        Parameters:
        - suppressEditorals: If True, consider all possible conventions,
          not just the "correct" ones.
        - suppressSearch: If True, return the first appropriate path,
          even if it doesn't exist.
        - forceDependent: Used with suppressSearch.  If True, force an
          arch-dependent path, even for things that are usually
          arch-independent.
        - forceIndependent: Used with suppressSearch.  If True, force an
          arch-independent path, even for things that are usually
          arch-dependent.
        - listAll: If True, list all possible paths, expanding as
          appropriate.
        """
        if forceDependent and forceIndependent:
            raise AthdirError("forceDependent and forceIndependent are mutually exclusive.")
        if (forceDependent or forceIndependent) and not suppressSearch:
            raise AthdirError("forceDependent and forceIndependent are meaningless without suppressSearch.")
        rv = []
        if forceDependent:
            logger.debug("Forcing architecture-dependent")
            self.archDependent = True
        if forceIndependent:
            logger.debug("Forcing architecture-independent")
            self.archDependent = False
        for c in self.conventions:
            logger.debug("** Considering %s", c)
            if (c.acceptableFor(self.flavorsAcceptable) or
                suppressEditorials or
                ((forceDependent or forceIndependent) and suppressSearch)):
                if suppressSearch and not c.dependencyMatch(self.archDependent):
                    logger.debug("discarding %s", c)
                    continue
                for compat in self.compatlist:
                    logger.debug("Considering sysname %s", compat)
                    path = self._expand(c.template, compat)
                    logger.debug("Expanding to %s", path)
                    if listAll or suppressSearch:
                        rv.append(path)
                        logger.debug("Storing %s", path)
                        if suppressSearch:
                            logger.debug("Returning...")
                            return rv
                    elif os.path.exists(path):
                        logger.debug("Path %s exists, returning...", path)
                        rv.append(path)
                        return rv
                    if not c.atsys:
                        logger.debug("Skipping sysname iteration")
                        break
        return rv

    @staticmethod
    def sysname():
        """
        Attempt to determine the sysname
        """
        sysname = os.getenv("ATHENA_SYS")
        if sysname is not None:
            return sysname
        logger.info("ATHENA_SYS is unset")
        sysname = _machtype('-S')
        if sysname is not None:
            return sysname
        else:
            raise AthdirInternalError("Unable to determine sysname.")

    @staticmethod
    def syscompatlist():
        """
        Attempt to determine the sysname compat list
        """
        compat = os.getenv("ATHENA_SYS_COMPAT")
        if compat is not None:
            return compat.split(':')
        logger.info("ATHENA_SYS_COMPAT is unset")
        compat = _machtype('-C')
        if compat is not None:
            return compat.split(':')
        else:
            raise AthdirInternalError("Unable to determine sysname compatibility list.")

    @staticmethod
    def hosttype():
        """
        Attempt to determine the machname (host type)
        """
        hosttype = os.getenv("HOSTTYPE")
        if hosttype is not None:
            return hosttype
        logger.info("HOSTTYPE is unset")
        hosttype = _machtype()
        if hosttype is not None:
            return hosttype
        else:
            raise AthdirInternalError("Unable to determine host type.")

    @classmethod
    def is_native(cls, somePath, sysn=None):
        """
        Determine if somePath is the native (i.e. not using
        compatibility) sysname for the specified sysname (or current
        platform)
        """
        if sysn is None:
            sysn = cls.sysname()
        return sysn in somePath
