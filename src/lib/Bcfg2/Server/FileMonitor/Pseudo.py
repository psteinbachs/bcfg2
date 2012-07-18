""" Pseudo provides static monitor support for file alteration events """

import os
import logging
from Bcfg2.Server.FileMonitor import FileMonitor, Event

logger = logging.getLogger(__name__)

class Pseudo(FileMonitor):
    __priority__ = 99

    def AddMonitor(self, path, obj, handleID=None):
        """add a monitor to path, installing a callback to obj.HandleEvent"""
        if handleID is None:
            handleID = len(list(self.handles.keys()))
        self.events.append(Event(handleID, path, 'exists'))
        if os.path.isdir(path):
            dirList = os.listdir(path)
            for includedFile in dirList:
                self.events.append(Event(handleID, includedFile, 'exists'))
            self.events.append(Event(handleID, path, 'endExist'))

        if obj != None:
            self.handles[handleID] = obj
        return handleID
