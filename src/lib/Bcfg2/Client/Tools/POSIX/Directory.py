""" Handle <Path type='directory' ...> entries """

import os
import sys
import stat
import shutil
import Bcfg2.Client.XML
from Bcfg2.Client.Tools.POSIX.base import POSIXTool


class POSIXDirectory(POSIXTool):
    """ Handle <Path type='directory' ...> entries """
    __req__ = ['name', 'perms', 'owner', 'group']

    def verify(self, entry, modlist):
        ondisk = self._exists(entry)
        if not ondisk:
            return False

        if not stat.S_ISDIR(ondisk[stat.ST_MODE]):
            self.logger.info("POSIX: %s is not a directory" %
                             entry.get('name'))
            return False

        prune = True
        if entry.get('prune', 'false').lower() == 'true':
            # check for any extra entries when prune='true' attribute is set
            try:
                extras = [os.path.join(entry.get('name'), ent)
                          for ent in os.listdir(entry.get('name'))
                          if os.path.join(entry.get('name'),
                                          ent) not in modlist]
                if extras:
                    prune = False
                    msg = "Directory %s contains extra entries: %s" % \
                        (entry.get('name'), "; ".join(extras))
                    self.logger.info("POSIX: " + msg)
                    entry.set('qtext', entry.get('qtext', '') + '\n' + msg)
                    for extra in extras:
                        Bcfg2.Client.XML.SubElement(entry, 'Prune', path=extra)
            except OSError:
                prune = True

        return POSIXTool.verify(self, entry, modlist) and prune

    def install(self, entry):
        """Install device entries."""
        fmode = self._exists(entry)

        if fmode and not stat.S_ISDIR(fmode[stat.ST_MODE]):
            self.logger.info("POSIX: Found a non-directory entry at %s, "
                             "removing" % entry.get('name'))
            try:
                os.unlink(entry.get('name'))
                fmode = False
            except OSError:
                err = sys.exc_info()[1]
                self.logger.error("POSIX: Failed to unlink %s: %s" %
                                  (entry.get('name'), err))
                return False
        elif fmode:
            self.logger.debug("POSIX: Found a pre-existing directory at %s" %
                              entry.get('name'))

        rv = True
        if not fmode:
            rv &= self._makedirs(entry)

        if entry.get('prune', 'false') == 'true':
            ulfailed = False
            for pent in entry.findall('Prune'):
                pname = pent.get('path')
                ulfailed = False
                if os.path.isdir(pname):
                    remove = shutil.rmtree
                else:
                    remove = os.unlink
                try:
                    self.logger.debug("POSIX: Removing %s" % pname)
                    remove(pname)
                except OSError:
                    err = sys.exc_info()[1]
                    self.logger.error("POSIX: Failed to unlink %s: %s" %
                                      (pname, err))
                    ulfailed = True
            if ulfailed:
                # even if prune failed, we still want to install the
                # entry to make sure that we get permissions and
                # whatnot set
                rv = False
        return POSIXTool.install(self, entry) and rv
