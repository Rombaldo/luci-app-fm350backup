#!/usr/bin/python3
# -*- coding: utf-8 -*-
# (c) B.Kerler 2018-2025 GPLv3 License
import json
import logging
import os
from binascii import hexlify

from mtkclient.Library.DA.xmlflash.xml_lib import DAXML
from mtkclient.Library.gui_utils import LogBase, logsetup
from mtkclient.Library.error import ErrorHandler
from mtkclient.Library.DA.daconfig import DAconfig
from mtkclient.config.brom_config import DAmodes
from mtkclient.Library.settings import HwParam


class DAloader(metaclass=LogBase):
    def __init__(self, mtk, loglevel=logging.INFO):
        self.patch = False
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger,
                                                                                  loglevel, mtk.config.gui)
        self.mtk = mtk
        self.config = mtk.config
        self.loglevel = loglevel
        self.eh = ErrorHandler()
        self.config = self.mtk.config
        self.usbwrite = self.mtk.port.usbwrite
        self.usbread = self.mtk.port.usbread
        self.echo = self.mtk.port.echo
        self.rbyte = self.mtk.port.rbyte
        self.rdword = self.mtk.port.rdword
        self.rword = self.mtk.port.rword
        self.daconfig = DAconfig(mtk=self.mtk, loader=self.mtk.config.loader,
                                 preloader=self.mtk.config.preloader, loglevel=loglevel)
        self.da = None
        self.flashmode = None

    def writestate(self):
        config = {}
        config["flashmode"] = "XML"
        config["patched"] = self.mtk.daloader.patch
        config["hwcode"] = self.config.hwcode
        if self.config.meid is not None:
            config["meid"] = hexlify(self.config.meid).decode('utf-8')
        if self.config.socid is not None:
            config["socid"] = hexlify(self.config.socid).decode('utf-8')
        config["flashtype"] = self.daconfig.storage.flashtype
        config["flashsize"] = self.daconfig.storage.flashsize
        config["target_config"] = self.config.target_config
        if not os.path.exists(self.mtk.config.hwparam_path):
            os.mkdir(self.mtk.config.hwparam_path)
        open(os.path.join(self.mtk.config.hwparam_path, ".state"), "w").write(json.dumps(config))

    def reinit(self):
        if os.path.exists(os.path.join(self.mtk.config.hwparam_path, ".state")):
            config = json.loads(open(os.path.join(self.mtk.config.hwparam_path, ".state"), "r").read())
            self.config.hwcode = config["hwcode"]
            meid_val = None
            if hasattr(config, 'meid') and config.meid is not None:
                self.config.meid = bytes.fromhex(config["meid"])
                meid_val = self.config.meid.hex()
            if "socid" in config:
                self.config.socid = bytes.fromhex(config["socid"])
            self.config.hwparam = HwParam(self.mtk.config, meid_val, self.mtk.config.hwparam_path)
            self.mtk.config.chipconfig.damode = DAmodes.XML
            self.flashmode = DAmodes.XML
            self.config.init_hwcode(self.config.hwcode)
            self.da = DAXML(self.mtk, self.daconfig, self.loglevel)
            self.da.config.target_config = config["target_config"]
            self.daconfig.storage.flashtype = config["flashtype"]
            self.daconfig.storage.flashsize = config["flashsize"]
            self.da.reinit()
            return True
        return False

    def set_da(self):
        # все правки других форматов DA убраны: FM350 и родственные чипы работают только с XML DA
        if self.mtk.config.chipconfig.damode == DAmodes.XML or (
                self.daconfig.da_loader is not None and self.daconfig.da_loader.v6):
            self.flashmode = DAmodes.XML
            self.da = DAXML(self.mtk, self.daconfig, self.loglevel)
            self.da.patch = self.patch
            return True
        self.error("This chip does not use XML DA, it is not supported.")
        return False

    def upload_da(self, preloader=None):
        self.daconfig.setup()
        self.daconfig.extract_emi(preloader)
        if not self.set_da():
            return False
        return self.da.upload_da()

    def boot_to(self, addr, data, display=True, timeout=0.5):
        if self.da.boot_to(addr, data, display=display):
            return True
        return False

    def readflash(self, addr, length, filename, parttype, display=True):
        return self.da.readflash(addr=addr, length=length, filename=filename, parttype=parttype, display=display)

    def get_packet_length(self):
        if self.flashmode == DAmodes.XFLASH:
            pt = self.da.get_packet_length()
            return pt.read_packet_length
        else:
            return 512
