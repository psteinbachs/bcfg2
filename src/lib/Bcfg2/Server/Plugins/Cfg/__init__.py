"""This module implements a config file repository."""

import re
import os
import sys
import stat
import logging
import lxml.etree
import Bcfg2.Options
import Bcfg2.Server.Plugin
import Bcfg2.Server.Lint
# pylint: disable=W0622
from Bcfg2.Compat import u_str, unicode, b64encode, walk_packages, any
# pylint: enable=W0622

LOGGER = logging.getLogger(__name__)

#: SETUP contains a reference to the
#: :class:`Bcfg2.Options.OptionParser` created by the Bcfg2 core for
#: parsing command-line and config file options.
#: :class:`Bcfg2.Server.Plugins.Cfg.Cfg` stores it in a module global
#: so that the handler objects can access it, because there is no other
#: facility for passing a setup object from a
#: :class:`Bcfg2.Server.Plugin.helpers.GroupSpool` to its
#: :class:`Bcfg2.Server.Plugin.helpers.EntrySet` objects and thence to
#: the EntrySet children.
SETUP = None


class CfgBaseFileMatcher(Bcfg2.Server.Plugin.SpecificData):
    """ CfgBaseFileMatcher is the parent class for all Cfg handler
    objects. """

    #: The set of filenames handled by this handler.  If
    #: ``__basenames__`` is the empty list, then the basename of each
    #: :class:`Bcfg2.Server.Plugins.Cfg.CfgEntrySet` is used -- i.e.,
    #: the name of the directory that contains the file is used for
    #: the basename.
    __basenames__ = []

    #: This handler only handles files with the listed extensions
    #: (which come *after*
    #: :attr:`Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__specific__`
    #: indicators).
    __extensions__ = []

    #: This handler ignores all files with the listed extensions.  A
    #: file that is ignored by a handler will not be handled by any
    #: other handlers; that is, a file is ignored if any handler
    #: ignores it.  Ignoring a file is not simply a means to defer
    #: handling of that file to another handler.
    __ignore__ = []

    #: Whether or not the files handled by this handler are permitted
    #: to have specificity indicators in their filenames -- e.g.,
    #: ``.H_client.example.com`` or ``.G10_foogroup``.
    __specific__ = True

    #: Flag to indicate a deprecated handler.
    deprecated = False

    def __init__(self, name, specific, encoding):
        Bcfg2.Server.Plugin.SpecificData.__init__(self, name, specific,
                                                  encoding)
        self.encoding = encoding
        self.regex = self.__class__.get_regex([name])
    __init__.__doc__ = Bcfg2.Server.Plugin.SpecificData.__init__.__doc__ + \
"""
.. -----
.. autoattribute:: Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__basenames__
.. autoattribute:: Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__extensions__
.. autoattribute:: Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__ignore__
.. autoattribute:: Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__specific__"""

    @classmethod
    def get_regex(cls, basenames):
        """ Get a compiled regular expression to match filenames (not
        full paths) that this handler handles.

        :param basename: The base filename to use if
                         :attr:`Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__basenames__`
                         is not defined (i.e., the name of the
                         directory that contains the files the regex
                         will be applied to)
        :type basename: string
        :returns: compiled regex
        """
        components = ['^(?P<basename>%s)' % '|'.join(basenames)]
        if cls.__specific__:
            components.append('(|\\.H_(?P<hostname>\S+?)|' +
                              '\.G(?P<prio>\d+)_(?P<group>\S+?))')
        if cls.__extensions__:
            components.append('\\.(?P<extension>%s)' %
                              '|'.join(cls.__extensions__))
        components.append('$')
        return re.compile("".join(components))

    @classmethod
    def handles(cls, event, basename=None):
        """ Return True if this handler handles the file described by
        ``event``.  This is faster than just applying
        :func:`Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.get_regex`
        because it tries to do non-regex matching first.

        :param event: The FAM event to check
        :type event: Bcfg2.Server.FileMonitor.Event
        :param basename: The base filename to use if
                         :attr:`Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__basenames__`
                         is not defined (i.e., the name of the
                         directory that contains the files the regex
                         will be applied to)
        :type basename: string
        :returns: bool - True if this handler handles the file listed
                  in the event, False otherwise.
        """
        if cls.__basenames__:
            basenames = cls.__basenames__
        else:
            basenames = [os.path.basename(basename)]

        return bool(cls.get_regex(basenames).match(event.filename))

    @classmethod
    def ignore(cls, event, basename=None):  # pylint: disable=W0613
        """ Return True if this handler ignores the file described by
        ``event``.  See
        :attr:`Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__ignore__`
        for more information on how ignoring files works.

        :param event: The FAM event to check
        :type event: Bcfg2.Server.FileMonitor.Event
        :param basename: The base filename to use if
                         :attr:`Bcfg2.Server.Plugins.Cfg.CfgBaseFileMatcher.__basenames__`
                         is not defined (i.e., the name of the
                         directory that contains the files the regex
                         will be applied to)
        :type basename: string
        :returns: bool - True if this handler handles the file listed
                  in the event, False otherwise.
        """
        return any(event.filename.endswith("." + e) for e in cls.__ignore__)

    def __str__(self):
        return "%s(%s)" % (self.__class__.__name__, self.name)


class CfgGenerator(CfgBaseFileMatcher):
    """ CfgGenerators generate the initial content of a file. Every
    valid :class:`Bcfg2.Server.Plugins.Cfg.CfgEntrySet` must have at
    least one file handled by a CfgGenerator.  Moreover, each
    CfgEntrySet must have one unambiguously best handler for each
    client. See :class:`Bcfg2.Server.Plugin.helpers.EntrySet` for more
    details on how the best handler is chosen."""

    def __init__(self, name, specific, encoding):
        # we define an __init__ that just calls the parent __init__,
        # so that we can set the docstring on __init__ to something
        # different from the parent __init__ -- namely, the parent
        # __init__ docstring, minus everything after ``.. -----``,
        # which we use to delineate the actual docs from the
        # .. autoattribute hacks we have to do to get private
        # attributes included in sphinx 1.0 """
        CfgBaseFileMatcher.__init__(self, name, specific, encoding)
    __init__.__doc__ = CfgBaseFileMatcher.__init__.__doc__.split(".. -----")[0]

    def get_data(self, entry, metadata):  # pylint: disable=W0613
        """ get_data() returns the initial data of a file.

        :param entry: The entry to generate data for. ``entry`` should
                      not be modified in-place.
        :type entry: lxml.etree._Element
        :param metadata: The client metadata to generate data for.
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :returns: string - the contents of the entry
        :raises: any
        """
        return self.data


class CfgFilter(CfgBaseFileMatcher):
    """ CfgFilters modify the initial content of a file after it has
    been generated by a :class:`Bcfg2.Server.Plugins.Cfg.CfgGenerator`. """

    def __init__(self, name, specific, encoding):
        # see comment on CfgGenerator.__init__ above
        CfgBaseFileMatcher.__init__(self, name, specific, encoding)
    __init__.__doc__ = CfgBaseFileMatcher.__init__.__doc__.split(".. -----")[0]

    def modify_data(self, entry, metadata, data):
        """ Return new data for the entry, based on the initial data
        produced by the :class:`Bcfg2.Server.Plugins.Cfg.CfgGenerator`.

        :param entry: The entry to filter data for. ``entry`` should
                      not be modified in-place.
        :type entry: lxml.etree._Element
        :param metadata: The client metadata to filter data for.
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :param data: The initial contents of the entry produced by the
                      CfgGenerator
        :type data: string
        :returns: string - the new contents of the entry
        """
        raise NotImplementedError


class CfgInfo(CfgBaseFileMatcher):
    """ CfgInfo handlers provide metadata (owner, group, paranoid,
    etc.) for a file entry.

    .. private-include: _set_info
    """

    #: Whether or not the files handled by this handler are permitted
    #: to have specificity indicators in their filenames -- e.g.,
    #: ``.H_client.example.com`` or ``.G10_foogroup``.  By default
    #: CfgInfo handlers do not allow specificities
    __specific__ = False

    def __init__(self, fname):
        """
        :param name: The full path to the file
        :type name: string

        .. -----
        .. autoattribute:: Bcfg2.Server.Plugins.Cfg.CfgInfo.__specific__
        """
        CfgBaseFileMatcher.__init__(self, fname, None, None)

    def bind_info_to_entry(self, entry, metadata):
        """ Assign the appropriate attributes to the entry, modifying
        it in place.

        :param entry: The abstract entry to bind the info to
        :type entry: lxml.etree._Element
        :param metadata: The client metadata to get info for
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :returns: None
        """
        raise NotImplementedError

    def _set_info(self, entry, info):
        """ Helper function to assign a dict of info attributes to an
        entry object.  ``entry`` is modified in-place.

        :param entry: The abstract entry to bind the info to
        :type entry: lxml.etree._Element
        :param info: A dict of attribute: value pairs
        :type info: dict
        :returns: None
        """
        for key, value in list(info.items()):
            if not key.startswith("__"):
                entry.attrib[key] = value


class CfgVerifier(CfgBaseFileMatcher):
    """ CfgVerifier handlers validate entry data once it has been
    generated, filtered, and info applied.  Validation can be enabled
    or disabled in the configuration.  Validation can apply to the
    contents of an entry, the attributes on it (e.g., owner, group,
    etc.), or both.
    """

    def __init__(self, name, specific, encoding):
        # see comment on CfgGenerator.__init__ above
        CfgBaseFileMatcher.__init__(self, name, specific, encoding)
    __init__.__doc__ = CfgBaseFileMatcher.__init__.__doc__.split(".. -----")[0]

    def verify_entry(self, entry, metadata, data):
        """ Perform entry contents. validation.

        :param entry: The entry to validate data for. ``entry`` should
                      not be modified in-place.  Info attributes have
                      been bound to the entry, but the text data has
                      not been set.
        :type entry: lxml.etree._Element
        :param metadata: The client metadata to validate data for.
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :param data: The contents of the entry
        :type data: string
        :returns: None
        :raises: Bcfg2.Server.Plugins.Cfg.CfgVerificationError
        """
        raise NotImplementedError


class CfgVerificationError(Exception):
    """ Raised by
    :func:`Bcfg2.Server.Plugins.Cfg.CfgVerifier.verify_entry` when an
    entry fails verification """
    pass


class CfgDefaultInfo(CfgInfo):
    """ :class:`Bcfg2.Server.Plugins.Cfg.Cfg` handler that supplies a
    default set of file metadata """

    def __init__(self, defaults):
        CfgInfo.__init__(self, '')
        self.defaults = defaults
    __init__.__doc__ = CfgInfo.__init__.__doc__.split(".. -----")[0]

    def bind_info_to_entry(self, entry, metadata):
        self._set_info(entry, self.defaults)
    bind_info_to_entry.__doc__ = CfgInfo.bind_info_to_entry.__doc__

#: A :class:`CfgDefaultInfo` object instantiated with
#: :attr:`Bcfg2.Server.Plugin.helper.DEFAULT_FILE_METADATA` as its
#: default metadata.  This is used to set a default file metadata set
#: on an entry before a "real" :class:`CfgInfo` handler applies its
#: metadata to the entry.
DEFAULT_INFO = CfgDefaultInfo(Bcfg2.Server.Plugin.DEFAULT_FILE_METADATA)


class CfgEntrySet(Bcfg2.Server.Plugin.EntrySet):
    """ Handle a collection of host- and group-specific Cfg files with
    multiple different Cfg handlers in a single directory. """

    def __init__(self, basename, path, entry_type, encoding):
        Bcfg2.Server.Plugin.EntrySet.__init__(self, basename, path,
                                              entry_type, encoding)
        self.specific = None
        self._handlers = None
    __init__.__doc__ = Bcfg2.Server.Plugin.EntrySet.__doc__

    @property
    def handlers(self):
        """ A list of Cfg handler classes. Loading the handlers must
        be done at run-time, not at compile-time, or it causes a
        circular import and Bad Things Happen."""
        if self._handlers is None:
            self._handlers = []
            for submodule in walk_packages(path=__path__,
                                           prefix=__name__ + "."):
                mname = submodule[1].rsplit('.', 1)[-1]
                module = getattr(__import__(submodule[1]).Server.Plugins.Cfg,
                                 mname)
                hdlr = getattr(module, mname)
                if set(hdlr.__mro__).intersection([CfgInfo, CfgFilter,
                                                   CfgGenerator, CfgVerifier]):
                    self._handlers.append(hdlr)
        return self._handlers

    def handle_event(self, event):
        """ Dispatch a FAM event to :func:`entry_init` or the
        appropriate child handler object.

        :param event: An event that applies to a file handled by this
                      CfgEntrySet
        :type event: Bcfg2.Server.FileMonitor.Event
        :returns: None
        """
        action = event.code2str()

        if event.filename not in self.entries:
            if action not in ['exists', 'created', 'changed']:
                # process a bogus changed event like a created
                return

            for hdlr in self.handlers:
                if hdlr.handles(event, basename=self.path):
                    if action == 'changed':
                        # warn about a bogus 'changed' event, but
                        # handle it like a 'created'
                        LOGGER.warning("Got %s event for unknown file %s" %
                                       (action, event.filename))
                    self.debug_log("%s handling %s event on %s" %
                                   (hdlr.__name__, action, event.filename))
                    self.entry_init(event, hdlr)
                    return
                elif hdlr.ignore(event, basename=self.path):
                    return
        elif action == 'changed':
            self.entries[event.filename].handle_event(event)
            return
        elif action == 'deleted':
            del self.entries[event.filename]
            return

        LOGGER.error("Could not process event %s for %s; ignoring" %
                     (action, event.filename))

    def get_matching(self, metadata):
        return self.get_handlers(metadata, CfgGenerator)
    get_matching.__doc__ = Bcfg2.Server.Plugin.EntrySet.get_matching.__doc__

    def entry_init(self, event, hdlr):  # pylint: disable=W0221
        """ Handle the creation of a file on the filesystem and the
        creation of a Cfg handler object in this CfgEntrySet to track
        it.

        :param event: An event that applies to a file handled by this
                      CfgEntrySet
        :type event: Bcfg2.Server.FileMonitor.Event
        :param hdlr: The Cfg handler class to be used to create an
                     object for the file described by ``event``
        :type hdlr: class
        :returns: None
        :raises: :class:`Bcfg2.Server.Plugin.exceptions.SpecificityError`
        """
        if hdlr.__specific__:
            Bcfg2.Server.Plugin.EntrySet.entry_init(
                self, event, entry_type=hdlr,
                specific=hdlr.get_regex([os.path.basename(self.path)]))
        else:
            if event.filename in self.entries:
                LOGGER.warn("Got duplicate add for %s" % event.filename)
            else:
                fpath = os.path.join(self.path, event.filename)
                self.entries[event.filename] = hdlr(fpath)
            self.entries[event.filename].handle_event(event)

    def bind_entry(self, entry, metadata):
        self.bind_info_to_entry(entry, metadata)
        data = self._generate_data(entry, metadata)

        for fltr in self.get_handlers(metadata, CfgFilter):
            data = fltr.modify_data(entry, metadata, data)

        if SETUP['validate']:
            try:
                self._validate_data(entry, metadata, data)
            except CfgVerificationError:
                msg = "Data for %s for %s failed to verify: %s" % \
                    (entry.get('name'), metadata.hostname,
                     sys.exc_info()[1])
                LOGGER.error(msg)
                raise Bcfg2.Server.Plugin.PluginExecutionError(msg)

        if entry.get('encoding') == 'base64':
            data = b64encode(data)
        else:
            try:
                if not isinstance(data, unicode):
                    data = u_str(data, self.encoding)
            except UnicodeDecodeError:
                msg = "Failed to decode %s: %s" % (entry.get('name'),
                                                   sys.exc_info()[1])
                LOGGER.error(msg)
                LOGGER.error("Please verify you are using the proper encoding")
                raise Bcfg2.Server.Plugin.PluginExecutionError(msg)
            except ValueError:
                msg = "Error in specification for %s: %s" % (entry.get('name'),
                                                             sys.exc_info()[1])
                LOGGER.error(msg)
                LOGGER.error("You need to specify base64 encoding for %s" %
                             entry.get('name'))
                raise Bcfg2.Server.Plugin.PluginExecutionError(msg)
            except TypeError:
                # data is already unicode; newer versions of Cheetah
                # seem to return unicode
                pass

        if data:
            entry.text = data
        else:
            entry.set('empty', 'true')
        return entry
    bind_entry.__doc__ = Bcfg2.Server.Plugin.EntrySet.bind_entry.__doc__

    def get_handlers(self, metadata, handler_type):
        """ Get all handlers of the given type for the given metadata.

        :param metadata: The metadata to get all handlers for.
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :param handler_type: The type of Cfg handler to get
        :type handler_type: type
        :returns: list of Cfg handler classes
        """
        rv = []
        for ent in self.entries.values():
            if (isinstance(ent, handler_type) and
                (not ent.__specific__ or ent.specific.matches(metadata))):
                rv.append(ent)
                if ent.deprecated:
                    if ent.__basenames__:
                        fdesc = "/".join(ent.__basenames__)
                    elif ent.__extensions__:
                        fdesc = "." + "/.".join(ent.__extensions__)
                    LOGGER.warning("Cfg: %s: Use of %s files is deprecated" %
                                   (ent.name, fdesc))
        return rv

    def bind_info_to_entry(self, entry, metadata):
        """ Bind entry metadata to the entry with the best CfgInfo
        handler

        :param entry: The abstract entry to bind the info to. This
                      will be modified in place
        :type entry: lxml.etree._Element
        :param metadata: The client metadata to get info for
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :returns: None
        """
        info_handlers = self.get_handlers(metadata, CfgInfo)
        DEFAULT_INFO.bind_info_to_entry(entry, metadata)
        if len(info_handlers) > 1:
            LOGGER.error("More than one info supplier found for %s: %s" %
                         (entry.get("name"), info_handlers))
        if len(info_handlers):
            info_handlers[0].bind_info_to_entry(entry, metadata)
        if entry.tag == 'Path':
            entry.set('type', 'file')

    def _generate_data(self, entry, metadata):
        """ Generate data for the given entry on the given client

        :param entry: The abstract entry to generate data for.  This
                      will not be modified
        :type entry: lxml.etree._Element
        :param metadata: The client metadata generate data for
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :returns: string - the data for the entry
        """
        generator = self.best_matching(metadata,
                                       self.get_handlers(metadata,
                                                         CfgGenerator))
        if entry.get('perms').lower() == 'inherit':
            # use on-disk permissions
            LOGGER.warning("Cfg: %s: Use of perms='inherit' is deprecated" %
                           entry.get("name"))
            fname = os.path.join(self.path, generator.name)
            entry.set('perms',
                      str(oct(stat.S_IMODE(os.stat(fname).st_mode))))
        try:
            return generator.get_data(entry, metadata)
        except:
            msg = "Cfg: exception rendering %s with %s: %s" % \
                (entry.get("name"), generator, sys.exc_info()[1])
            LOGGER.error(msg)
            raise Bcfg2.Server.Plugin.PluginExecutionError(msg)

    def _validate_data(self, entry, metadata, data):
        """ Validate data for the given entry on the given client

        :param entry: The abstract entry to validate data for
        :type entry: lxml.etree._Element
        :param metadata: The client metadata validate data for
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :returns: None
        :raises: :exc:`Bcfg2.Server.Plugins.Cfg.CfgVerificationError`
        """
        verifiers = self.get_handlers(metadata, CfgVerifier)
        # we can have multiple verifiers, but we only want to use the
        # best matching verifier of each class
        verifiers_by_class = dict()
        for verifier in verifiers:
            cls = verifier.__class__.__name__
            if cls not in verifiers_by_class:
                verifiers_by_class[cls] = [verifier]
            else:
                verifiers_by_class[cls].append(verifier)
        for verifiers in verifiers_by_class.values():
            verifier = self.best_matching(metadata, verifiers)
            verifier.verify_entry(entry, metadata, data)

    def list_accept_choices(self, entry, metadata):
        '''return a list of candidate pull locations'''
        generators = [ent for ent in list(self.entries.values())
                      if (isinstance(ent, CfgGenerator) and
                          ent.specific.matches(metadata))]
        if not generators:
            msg = "No base file found for %s" % entry.get('name')
            LOGGER.error(msg)
            raise Bcfg2.Server.Plugin.PluginExecutionError(msg)

        rv = []
        try:
            best = self.best_matching(metadata, generators)
            rv.append(best.specific)
        except:  # pylint: disable=W0702
            pass

        if not rv or not rv[0].hostname:
            rv.append(Bcfg2.Server.Plugin.Specificity(
                    hostname=metadata.hostname))
        return rv

    def build_filename(self, specific):
        """ Create a filename for pulled file data """
        bfname = self.path + '/' + self.path.split('/')[-1]
        if specific.all:
            return bfname
        elif specific.group:
            return "%s.G%02d_%s" % (bfname, specific.prio, specific.group)
        elif specific.hostname:
            return "%s.H_%s" % (bfname, specific.hostname)

    def write_update(self, specific, new_entry, log):
        """ Write pulled data to the filesystem """
        if 'text' in new_entry:
            name = self.build_filename(specific)
            if os.path.exists("%s.genshi" % name):
                msg = "Cfg: Unable to pull data for genshi types"
                LOGGER.error(msg)
                raise Bcfg2.Server.Plugin.PluginExecutionError(msg)
            elif os.path.exists("%s.cheetah" % name):
                msg = "Cfg: Unable to pull data for cheetah types"
                LOGGER.error(msg)
                raise Bcfg2.Server.Plugin.PluginExecutionError(msg)
            try:
                etext = new_entry['text'].encode(self.encoding)
            except:
                msg = "Cfg: Cannot encode content of %s as %s" % \
                    (name, self.encoding)
                LOGGER.error(msg)
                raise Bcfg2.Server.Plugin.PluginExecutionError(msg)
            open(name, 'w').write(etext)
            self.debug_log("Wrote file %s" % name, flag=log)
        badattr = [attr for attr in ['owner', 'group', 'perms']
                   if attr in new_entry]
        if badattr:
            # check for info files and inform user of their removal
            for ifile in ['info', ':info']:
                info = os.path.join(self.path, ifile)
                if os.path.exists(info):
                    LOGGER.info("Removing %s and replacing with info.xml" %
                                info)
                    os.remove(info)
            metadata_updates = {}
            metadata_updates.update(self.metadata)
            for attr in badattr:
                metadata_updates[attr] = new_entry.get(attr)
            infoxml = lxml.etree.Element('FileInfo')
            infotag = lxml.etree.SubElement(infoxml, 'Info')
            for attr in metadata_updates:
                infotag.attrib.__setitem__(attr, metadata_updates[attr])
            ofile = open(self.path + "/info.xml", "w")
            ofile.write(lxml.etree.tostring(infoxml, xml_declaration=False,
                                            pretty_print=True).decode('UTF-8'))
            ofile.close()
            self.debug_log("Wrote file %s" % os.path.join(self.path,
                                                          "info.xml"),
                           flag=log)


class Cfg(Bcfg2.Server.Plugin.GroupSpool,
          Bcfg2.Server.Plugin.PullTarget):
    """ The Cfg plugin provides a repository to describe configuration
    file contents for clients. In its simplest form, the Cfg repository is
    just a directory tree modeled off of the directory tree on your client
    machines.
    """
    __author__ = 'bcfg-dev@mcs.anl.gov'
    es_cls = CfgEntrySet
    es_child_cls = Bcfg2.Server.Plugin.SpecificData

    def __init__(self, core, datastore):
        global SETUP  # pylint: disable=W0603
        Bcfg2.Server.Plugin.GroupSpool.__init__(self, core, datastore)
        Bcfg2.Server.Plugin.PullTarget.__init__(self)

        SETUP = core.setup
        if 'validate' not in SETUP:
            SETUP.add_option('validate', Bcfg2.Options.CFG_VALIDATION)
            SETUP.reparse()
    __init__.__doc__ = Bcfg2.Server.Plugin.GroupSpool.__init__.__doc__

    def has_generator(self, entry, metadata):
        """ Return True if the given entry can be generated for the
        given metadata; False otherwise

        :param entry: Determine if a
                      :class:`Bcfg2.Server.Plugins.Cfg.CfgGenerator`
                      object exists that handles this (abstract) entry
        :type entry: lxml.etree._Element
        :param metadata: Determine if a CfgGenerator has data that
                         applies to this client metadata
        :type metadata: Bcfg2.Server.Plugins.Metadata.ClientMetadata
        :returns: bool
        """
        if entry.get('name') not in self.entries:
            return False

        return bool(self.entries[entry.get('name')].get_handlers(metadata,
                                                                 CfgGenerator))

    def AcceptChoices(self, entry, metadata):
        return self.entries[entry.get('name')].list_accept_choices(entry,
                                                                   metadata)
    AcceptChoices.__doc__ = \
        Bcfg2.Server.Plugin.PullTarget.AcceptChoices.__doc__

    def AcceptPullData(self, specific, new_entry, log):
        return self.entries[new_entry.get('name')].write_update(specific,
                                                                new_entry,
                                                                log)
    AcceptPullData.__doc__ = \
        Bcfg2.Server.Plugin.PullTarget.AcceptPullData.__doc__


class CfgLint(Bcfg2.Server.Lint.ServerPlugin):
    """ warn about usage of .cat and .diff files """

    def Run(self):
        for basename, entry in list(self.core.plugins['Cfg'].entries.items()):
            self.check_entry(basename, entry)

    @classmethod
    def Errors(cls):
        return {"cat-file-used": "warning",
                "diff-file-used": "warning"}

    def check_entry(self, basename, entry):
        """ check that no .cat or .diff files are in use """
        cfg = self.core.plugins['Cfg']
        for basename, entry in list(cfg.entries.items()):
            for fname, handler in entry.entries.items():
                if self.HandlesFile(fname) and isinstance(handler, CfgFilter):
                    extension = fname.split(".")[-1]
                    self.LintError("%s-file-used" % extension,
                                   "%s file used on %s: %s" %
                                   (extension, basename, fname))
