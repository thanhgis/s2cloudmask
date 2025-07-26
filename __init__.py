# -*- coding: utf-8 -*-

# noinspection PyPep8Naming
def classFactory(iface):  # pylint: disable=invalid-name
    """Load s2CloudMask class from file s2CloudMask."""
    from .s2cloudmask import s2CloudMask
    return s2CloudMask(iface)