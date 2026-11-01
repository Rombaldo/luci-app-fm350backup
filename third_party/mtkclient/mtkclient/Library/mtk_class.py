#!/usr/bin/env python3
# MTK Flash Client (c) B.Kerler 2018-2026
# Licensed under GPLv3 License
import logging
from mtkclient.config.usb_ids import default_ids
from mtkclient.Library.mtk_preloader import Preloader
from mtkclient.Library.DA.mtk_daloader import DAloader
from mtkclient.Library.Port import Port
from mtkclient.Library.gui_utils import LogBase, logsetup
from mtkclient.Library.error import ErrorHandler


class Mtk(metaclass=LogBase):
    def __init__(self, config, loglevel=logging.INFO, serialportname: str = None, preinit=True):
        self.config = config
        self.loader = config.loader
        self.vid = config.vid
        self.pid = config.pid
        self.interface = config.interface
        self.reinited = False
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger, loglevel,
                                                                                  config.gui)
        self.eh = ErrorHandler()
        self.serialportname = serialportname
        if preinit:
            self.setup(self.vid, self.pid, self.interface, serialportname)

    def setup(self, vid=None, pid=None, interface=None, serialportname: str = None):
        if vid is None:
            vid = self.vid
        if pid is None:
            pid = self.pid
        if interface is None:
            interface = self.interface
        if vid != -1 and pid != -1:
            if interface == -1:
                for dev in default_ids:
                    if dev[0] == vid and dev[1] == pid:
                        interface = dev[2]
                        break
            portconfig = [[vid, pid, interface]]
        else:
            portconfig = default_ids
        self.port = Port(mtk=self, portconfig=portconfig, serialportname=serialportname, loglevel=self.__logger.level)
        self.preloader = Preloader(self, self.__logger.level)
        self.daloader = DAloader(self, self.__logger.level)
