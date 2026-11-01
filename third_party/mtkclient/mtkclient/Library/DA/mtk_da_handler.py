#!/usr/bin/env python3
# MTK Flash Client (c) B.Kerler 2018-2026.
# Licensed under GPLv3 License
import logging
import os
import sys
from mtkclient.Library.utils import getint
from mtkclient.Library.gui_utils import LogBase, logsetup
from mtkclient.Library.error import ErrorHandler


class DaHandler(metaclass=LogBase):
    def __init__(self, mtk, loglevel=logging.INFO):
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger,
                                                                                  loglevel, mtk.config.gui)
        self.info = self.__logger.info
        self.debug = self.__logger.debug
        self.error = self.__logger.error
        self.warning = self.__logger.warning
        self.config = mtk.config
        self.loader = mtk.config.loader
        self.vid = mtk.config.vid
        self.pid = mtk.config.pid
        self.interface = mtk.config.interface
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger,
                                                                                  loglevel, mtk.config.gui)
        self.eh = ErrorHandler()
        self.mtk = mtk

    @staticmethod
    def close():
        sys.exit(0)

    def connect(self, mtk, directory:str = None):
        if directory is None:
            directory = "."
        # NOTE: single attempt with an exception guard. The actual wait/retry
        # loop lives in mtk.preloader.init() (port.handshake), which must run
        # while the port is still unclaimed so it can catch the plug-in
        # handshake; blocking here would skip it and break fresh sessions.
        mtk.port.wait_for_device(max_attempts=1, wait=False)
        if mtk.port.cdc.connected is None or not mtk.port.cdc.connected or mtk.serialportname is not None:
            mtk.preloader.init(directory=directory)
            if self.config.internal_flash and self.mtk.config.iot:
                offset = self.mtk.offset
                length = self.mtk.length
                step = self.mtk.step
                mtk.preloader.dump_internal_flash(offset=offset,length=length,step=step,filename="internal_flash.bin")
        else:
            if mtk.serialportname is not None:
                mtk.preloader.init()
            if directory:
                self.mtk.config.hwparam_path = directory
            if mtk.port.cdc.connected and os.path.exists(os.path.join(mtk.config.hwparam_path, ".state")):
                mtk.daloader.reinit()
                mtk.reinited = True
                return mtk
        if mtk.config.target_config is None:
            self.warning("Target config is still unset after the initial connection attempt; retrying preloader initialization.")
            try:
                if getattr(mtk, "preloader", None) is not None:
                    mtk.preloader.init(directory=directory)
            except Exception as err:
                self.warning(f"Preloader retry failed: {err}")
            if mtk.config.target_config is None:
                self.info("Please disconnect, start mtkclient and reconnect.")
                return None
        return mtk

    def configure_da(self, mtk):
        if mtk is None:
            return None
        if mtk.reinited:
            return mtk
        self.info("Device is protected." if mtk.config.target_config["sbc"] else "Device is unprotected.")
        # только штатный DA без правок: защита модема не обходится
        mtk.daloader.patch = False
        if not mtk.daloader.upload_da(preloader=mtk.config.preloader):
            self.error("Failed to upload da.")
            sys.exit(1)
        mtk.daloader.writestate()
        return mtk

    def da_ro(self, start: int, length: int, filename: str, parttype: str, display: bool = True):
        return self.mtk.daloader.readflash(addr=start,
                                           length=length,
                                           filename=filename, parttype=parttype, display=display)

    def handle_da_cmds(self, mtk, cmd: str, args):
        if mtk is None or mtk.daloader is None:
            self.error("Error on running da, aborting :(")
            sys.exit(1)
        if cmd == "ro":
            start = getint(args.offset)
            length = getint(args.length)
            filename = args.filename
            self.mtk.config.hwparam_path = os.path.dirname(filename)
            parttype = args.parttype
            if self.da_ro(start=start, length=length, filename=filename, parttype=parttype):
                print(f"Dumped offset {hex(start)} with length {hex(length)} as {filename}.")
            else:
                print(f"Failed to dump offset {hex(start)} with length {hex(length)} as {filename}.")
