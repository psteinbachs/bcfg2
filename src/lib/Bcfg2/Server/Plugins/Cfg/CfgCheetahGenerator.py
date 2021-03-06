""" The CfgCheetahGenerator allows you to use the `Cheetah
<http://www.cheetahtemplate.org/>`_ templating system to generate
:ref:`server-plugins-generators-cfg` files. """

import logging
import Bcfg2.Server.Plugin
from Bcfg2.Server.Plugins.Cfg import CfgGenerator

LOGGER = logging.getLogger(__name__)

try:
    from Cheetah.Template import Template
    HAS_CHEETAH = True
except ImportError:
    HAS_CHEETAH = False


class CfgCheetahGenerator(CfgGenerator):
    """ The CfgCheetahGenerator allows you to use the `Cheetah
    <http://www.cheetahtemplate.org/>`_ templating system to generate
    :ref:`server-plugins-generators-cfg` files. """

    #: Handle .cheetah files
    __extensions__ = ['cheetah']

    #: :class:`Cheetah.Template.Template` compiler settings
    settings = dict(useStackFrames=False)

    def __init__(self, fname, spec, encoding):
        CfgGenerator.__init__(self, fname, spec, encoding)
        if not HAS_CHEETAH:
            msg = "Cfg: Cheetah is not available: %s" % self.name
            LOGGER.error(msg)
            raise Bcfg2.Server.Plugin.PluginExecutionError(msg)
    __init__.__doc__ = CfgGenerator.__init__.__doc__

    def get_data(self, entry, metadata):
        template = Template(self.data.decode(self.encoding),
                            compilerSettings=self.settings)
        template.metadata = metadata
        template.path = entry.get('realname', entry.get('name'))
        template.source_path = self.name
        return template.respond()
    get_data.__doc__ = CfgGenerator.get_data.__doc__
