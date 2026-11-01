#!/usr/bin/env python3
# MTK Flash Client (c) B.Kerler 2018-2026.
# Licensed under GPLv3 License
import os
import sys
import logging
from mtkclient.Library.mtk_class import Mtk
from mtkclient.Library.utils import getint
from mtkclient.Library.gui_utils import LogBase, logsetup
from mtkclient.config.mtk_config import MtkConfig
from mtkclient.Library.error import ErrorHandler
from mtkclient.Library.DA.mtk_da_handler import DaHandler
from mtkclient.Library.Partitions.gpt import GptSettings


class ArgHandler(metaclass=LogBase):
    def __init__(self, args, config):
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger,
                                                                                  config.loglevel, config.gui)
        try:
            config.gpt_file = None
            if args.gpt_file is not None:
                if os.path.exists(args.gpt_file):
                    config.gpt_file = args.gpt_file
        except AttributeError:
            pass
        try:
            if args.vid is not None:
                config.vid = getint(args.vid)
        except AttributeError:
            pass
        try:
            if args.pid is not None:
                config.pid = getint(args.pid)
        except AttributeError:
            pass
        config.stock = False
        try:
            if args.stock is not None:
                config.stock = args.stock
        except AttributeError:
            pass

        config.reconnect = True
        try:
            if args.noreconnect is not None:
                config.reconnect = not args.noreconnect
        except AttributeError:
            pass
        config.uartloglevel = 2
        try:
            if args.uartloglevel is not None:
                config.uartloglevel = args.uartloglevel
        except AttributeError:
            pass
        config.logchannel = "UART"
        try:
            if args.logchannel is not None:
                config.logchannel = args.logchannel
        except AttributeError:
            pass

        try:
            if args.payload is not None:
                config.payloadfile = args.payload
        except Exception:
            pass
        try:
            if args.appid is not None:
                config.appid = bytes.fromhex(args.appid)
        except Exception:
            pass
        try:
            if args.loader is not None:
                config.loader = args.loader
        except AttributeError:
            pass
        try:
            if args.da_address is not None:
                config.chipconfig.da_payload_addr = getint(args.da_address)
                self.info("O:DA offset:\t\t\t" + args.da_address)
        except AttributeError:
            pass
        try:
            if args.brom_address is not None:
                config.chipconfig.brom_payload_addr = getint(args.brom_address)
                self.info("O:Payload offset:\t\t" + args.brom_address)
        except AttributeError:
            pass
        try:
            if args.watchdog_address is not None:
                config.chipconfig.watchdog = getint(args.wdt)
                self.info("O:Watchdog addr:\t\t" + args.wdt)
        except AttributeError:
            pass
        try:
            if args.skipwdt is not None:
                config.skipwdt = args.skipwdt
        except AttributeError:
            pass
        try:
            if args.uart_address is not None:
                config.chipconfig.uart = getint(args.uart_address)
                self.info("O:Uart addr:\t\t" + args.uart_address)
        except AttributeError:
            pass
        try:
            if args.var1 is not None:
                config.chipconfig.var1 = getint(args.var1)
                self.info("O:Var1:\t\t" + hex(config.chipconfig.var1))
        except AttributeError:
            pass
        try:
            if args.preloader is not None:
                if os.path.exists(args.preloader):
                    config.preloader_filename = args.preloader
                    config.preloader = open(config.preloader_filename, "rb").read()
        except AttributeError:
            pass
        try:
            if args.write_preloader_to_file is not None:
                config.write_preloader_to_file = args.write_preloader_to_file
        except AttributeError:
            pass
        try:
            if args.generatekeys is not None:
                config.generatekeys = args.generatekeys
        except AttributeError:
            pass
        try:
            if args.ptype is not None:
                config.ptype = args.ptype
        except AttributeError:
            pass
        try:
            if args.socid is not None:
                config.readsocid = args.socid
        except AttributeError:
            pass
        try:
            if args.crash is not None:
                config.enforcecrash = args.crash
        except AttributeError:
            pass

        gpt_num_part_entries = 0
        try:
            if args.gpt_num_part_entries is not None:
                gpt_num_part_entries = args.gpt_num_part_entries
        except Exception:
            pass

        gpt_part_entry_size = 0
        try:
            if args.gpt_part_entry_size is not None:
                gpt_part_entry_size = args.gpt_part_entry_size
        except Exception:
            pass

        gpt_part_entry_start_lba = 0
        try:
            if args.gpt_part_entry_start_lba is not None:
                gpt_part_entry_start_lba = args.gpt_part_entry_start_lba
        except Exception:
            pass

        config.gpt_settings = GptSettings(gpt_num_part_entries, gpt_part_entry_size,
                                          gpt_part_entry_start_lba)


class Main(metaclass=LogBase):
    def __init__(self, args):
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger,
                                                                                  args.loglevel, None)
        self.eh = None
        self.args = args
        if args.loglevel == logging.DEBUG:
            if not os.path.exists("logs"):
                os.mkdir("logs")

    @staticmethod
    def close():
        sys.exit(0)

    def run(self, parser):
        try:
            if self.args.debugmode:
                loglevel = logging.DEBUG
                self.__logger.setLevel(logging.DEBUG)
            else:
                loglevel = logging.INFO
                self.__logger.setLevel(logging.INFO)
        except Exception:
            loglevel = logging.INFO
            self.__logger.setLevel(logging.INFO)
            pass
        try:
            if self.args.loader is not None:
                if not os.path.exists(self.args.loader):
                    print(f"Couldn't find loader {self.args.loader} :(")
                    sys.exit(1)
        except Exception:
            pass
        config = MtkConfig(loglevel=loglevel, gui=None, guiprogress=None)
        ArgHandler(self.args, config)
        self.eh = ErrorHandler()
        serialport = None
        try:
            serialport = self.args.serialport
        except Exception:
            pass
        try:
            disable_internal_flash = self.args.disable_internal_flash
            config.internal_flash = not disable_internal_flash
        except Exception:
            pass
        try:
            auth = self.args.auth
            config.auth = auth
        except Exception:
            pass
        try:
            cert = self.args.cert
            config.cert = cert
        except Exception:
            pass
        mtk = Mtk(config=config, loglevel=loglevel, serialportname=serialport)
        if mtk.config.debugmode:
            logfilename = os.path.join("logs", "log.txt")
            if os.path.exists(logfilename):
                os.remove(logfilename)
            fh = logging.FileHandler(logfilename, encoding='utf-8')
            self.__logger.addHandler(fh)

        self.debug(" ".join(sys.argv))
        # DA / Flash commands start here
        try:
            mtk.config.preloader_filename = self.args.preloader
        except Exception:
            mtk.config.preloader_filename = None
        try:
            directory = self.args.directory
        except Exception:
            directory = "."
        cmd = self.args.cmd
        if cmd == "multi":
            # Split the commands in the multi argument
            commands = self.args.commands.split(';')
            da_handler = DaHandler(mtk, loglevel)
            mtk = da_handler.connect(mtk, directory)
            if mtk is None:
                self.close()
                return
            mtk = da_handler.configure_da(mtk)
            if mtk is not None:
                for rcmd in commands:
                    self.args = parser.parse_args(rcmd.split(" "))
                    ArgHandler(self.args, config)
                    cmd = self.args.cmd
                    da_handler.handle_da_cmds(mtk, cmd, self.args)
                    sys.stdout.flush()
                    sys.stderr.flush()
            else:
                self.close()
        else:
            # DA / FLash commands start here
            da_handler = DaHandler(mtk, loglevel)
            mtk.offset = 0
            try:
                if self.args.offset is not None:
                    mtk.offset = int(self.args.offset, 16)
            except Exception:
                pass
            mtk.length = 0x400000
            try:
                if self.args.length is not None:
                    mtk.length = int(self.args.length, 16)
            except Exception:
                pass
            mtk.step = 0x1000
            try:
                if self.args.step is not None:
                    mtk.step = int(self.args.step, 16)
            except Exception:
                pass
            try:
                if self.args.iot is not None:
                    mtk.config.iot = self.args.iot
            except Exception:
                pass
            mtk = da_handler.connect(mtk, directory)
            if mtk is not None:
                mtk = da_handler.configure_da(mtk)
                if mtk is not None:
                    self.info("Handling da commands ...")
                    da_handler.handle_da_cmds(mtk, cmd, self.args)
                    if len(mtk.config.uartlog)>0:
                        with open("uartlog.txt","w") as wf:
                            for line in mtk.config.uartlog:
                                wf.write(line)
                        print("Uart Log written to uartlog.txt")
                    mtk.port.close()
            self.close()
