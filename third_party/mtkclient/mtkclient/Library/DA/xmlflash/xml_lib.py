#!/usr/bin/python3
# -*- coding: utf-8 -*-
# (c) B.Kerler 2018-2025 GPLv3 License
import logging
import os
import sys
from struct import pack
from queue import Queue
from threading import Thread
from typing import Tuple

from mtkclient.Library.DA.xmlflash.xml_param import DataType, FtSystemOSE, LogLevel
from mtkclient.Library.gui_utils import logsetup, LogBase, progress
from mtkclient.Library.error import ErrorHandler
from mtkclient.Library.partition import Partition
from mtkclient.config.payloads import PathConfig
from mtkclient.Library.thread_handling import writedata
from mtkclient.Library.DA.xmlflash.xml_cmd import XMLCmd


class ShutDownModes:
    TEST = 3
    META = 4
    NORMAL = 0
    HOME_SCREEN = 1
    FASTBOOT = 2


def get_field(data, fieldname):
    if isinstance(data, bytes) or isinstance(data, bytearray):
        data = data.decode('utf-8')
    start = data.find(f"<{fieldname}>")
    if start != -1:
        end = data.find(f"</{fieldname}>", start + len(fieldname) + 2)
        if start != -1 and end != -1:
            return data[start + len(fieldname) + 2:end]
    return ""


class FileSysOp:
    key = None
    file_path = None

    def __init__(self, key, file_path):
        self.key = key
        self.file_path = file_path


class UpFile:
    checksum = None
    info = None
    source_file = None
    packet_length = None

    def __init__(self, checksum, info, target_file, packet_length):
        self.checksum = checksum
        self.info = info
        self.target_file = target_file
        self.packet_length = packet_length


class DwnFile:
    checksum = None
    info = None
    source_file = None
    packet_length = None

    def __init__(self, checksum: str, info: str, source_file: str, packet_length: int):
        self.checksum = checksum
        self.info = info
        self.source_file = source_file
        self.packet_length = packet_length


class DAXML(metaclass=LogBase):
    def __init__(self, mtk, daconfig, loglevel=logging.INFO):
        self.__logger, self.info, self.debug, self.warning, self.error = logsetup(self, self.__logger,
                                                                                  loglevel, mtk.config.gui)
        self.cmd = XMLCmd(mtk)
        self.mtk = mtk
        self.loglevel = loglevel
        self.daext = False
        self.chipid = None
        self.randomid = None
        self.__logger = self.__logger
        self.eh = ErrorHandler()
        self.config = self.mtk.config
        self.usbwrite = self.mtk.port.usbwrite
        self.usbread = self.mtk.port.usbread
        self.echo = self.mtk.port.echo
        self.rbyte = self.mtk.port.rbyte
        self.rdword = self.mtk.port.rdword
        self.rword = self.mtk.port.rword
        self.daconfig = daconfig
        self.partition = Partition(self.mtk, self.readflash, self.read_partition_table, loglevel)
        self.pathconfig = PathConfig()

    def xread(self) -> Tuple[int,int]:
        while True:
            hdr = self.usbread()
            if len(hdr) not in [12,16]:
                self.error("xread: Wrong length")
                return -1, -1
            magic = int.from_bytes(hdr[:4],'little')
            if magic != 0xFEEEEEEF:
                self.error("xread: Wrong magic")
                return -1, -1
            datatype = int.from_bytes(hdr[4:8],'little')
            length = int.from_bytes(hdr[8:0xC],'little')
            if datatype == DataType.DT_MESSAGE:
                priority = int.from_bytes(hdr[0xC:0x10],'little')
                length -= 4
                data = self.usbread(length)
                try:
                    msg = data.rstrip(b"\x00").decode('utf-8', errors='replace')
                    self.config.uartlog.append(msg)
                    self.debug(f"[DA] {priority} {msg}")
                except Exception:
                    pass
            elif datatype == DataType.DT_PROTOCOL_FLOW:
                return datatype, length

    def xsend(self, data, datatype=DataType.DT_PROTOCOL_FLOW, is64bit: bool = False):
        if isinstance(data, int):
            if is64bit:
                data = pack("<Q", data)
                length = 8
            else:
                data = pack("<I", data)
                length = 4
        else:
            if type(data) is str:
                length = len(data) + 1
            else:
                length = len(data)
        tmp = pack("<III", self.cmd.MAGIC, datatype, length)
        if self.usbwrite(tmp):
            if type(data) is str:
                return self.usbwrite(bytes(data, 'utf-8') + b"\x00")
            else:
                return self.usbwrite(data)
        return False

    def ack(self):
        return self.xsend("OK\0")

    def ack_value(self, length):
        return self.xsend(f"OK@{hex(length)}\0")

    def ack_text(self, text):
        return self.xsend(f"OK@{text}\0")

    # FM350: настройка DA ровно как у SP Flash Tool. С родной настройкой mtkclient модем готовит каждый
    # блок 2 МБ около 1,8 с вместо 0,18 с (замеры в docs/speed-investigation.md).
    FM350_RUNTIME_PARAMETER = (
        '<?xml version="1.0" encoding="utf-8"?><da><version>1.0</version>'
        '<command>CMD:SET-RUNTIME-PARAMETER</command><arg><checksum_level>NONE</checksum_level>'
        '<battery_exist>YES</battery_exist><da_log_level>INFO</da_log_level>'
        '<log_channel>UART</log_channel><system_os>WINDOWS</system_os></arg></da>\x00')

    def setup_env(self):
        if self.mtk.config.hwcode == 0x992:      # MT6880/MT6890, чип FM350-GL
            return self.send_command(self.FM350_RUNTIME_PARAMETER)
        da_log_level = int(self.daconfig.uartloglevel)
        loglevel = LogLevel().INFO
        if da_log_level == 0:
            loglevel = LogLevel().TRACE
        elif da_log_level == 1:
            loglevel = LogLevel().DEBUG
        elif da_log_level == 2:
            loglevel = LogLevel().INFO
        elif da_log_level == 3:
            loglevel = LogLevel().WARN
        elif da_log_level == 4:
            loglevel = LogLevel().ERROR
        system_os = FtSystemOSE.OS_LINUX
        logchannel = self.daconfig.logchannel
        res = self.send_command(self.cmd.cmd_set_runtime_parameter(da_log_level=loglevel, system_os=system_os,
                                                                   log_channel=logchannel,
                                                                   version="1.1", battery_exist="AUTO-DETECT",
                                                                   initialize_dram=True))
        return res

    def send_command(self, xmldata, noack: bool = False):
        if self.xsend(data=xmldata):
            result = self.get_response()
            if result == "OK":
                if noack:
                    return True
                cmd, result = self.get_command_result()
                if cmd == "CMD:END":
                    if result != "OK":
                        # FM350: как SP Flash Tool, подтверждаем отказ и принимаем CMD:START. Без этого обмен
                        # сбивался, и чтение после загрузки DA ждало ответа около 100 с (xread: Wrong length).
                        self.ack()
                        self.get_command_result()
                        if result != "ERR!UNSUPPORTED":
                            self.error(result)
                        return False
                    self.ack()
                    if result == '2nd DA address is invalid. reset.\r\n':
                        self.error(result)
                        exit(1)
                    scmd, sresult = self.get_command_result()
                    if scmd == "CMD:START":
                        if result == "OK":
                            return True
                        else:
                            self.error(result)
                            return False
                else:
                    return result
            elif result == "ERR!UNSUPPORTED":
                scmd, sresult = self.get_command_result()
                self.ack()
                tcmd, tresult = self.get_command_result()
                if tcmd == "CMD:START":
                    return False
            elif "ERR!" in result:
                return result
        return False

    def get_response(self, raw: bool = False):
        datatype, length = self.xread()
        if datatype == DataType.DT_PROTOCOL_FLOW:
            data = self.usbread(length)
            if raw:
                return data
            try:
                return data.rstrip(b"\x00").decode('utf-8', errors='replace')
            except Exception:
                return ""
        return ""

    def get_response_data(self) -> bytes:
        datatype, length = self.xread()
        if datatype == -1 or datatype != DataType.DT_PROTOCOL_FLOW:
            return b""
        data = bytearray()
        bytestoread = length
        while bytestoread > 0:
            tmp = self.usbread(bytestoread, w_max_packet_size=bytestoread)
            data.extend(tmp)
            bytestoread -= len(tmp)
        if len(data) == length:
            return data
        return b""

    def upload_da1(self):
        if self.daconfig.da_loader is None:
            self.error("No valid da loader found... aborting.")
            return False
        loader = self.daconfig.loader
        self.info(f"Uploading xflash stage 1 from {os.path.basename(loader)}")
        if not os.path.exists(loader):
            self.info(f"Couldn't find {loader}, aborting.")
            return False
        with open(loader, 'rb') as bootldr:
            # stage 1
            da1offset = self.daconfig.da_loader.region[1].m_buf
            bootldr.seek(da1offset)
            # ------------------------------------------------
            da2offset = self.daconfig.da_loader.region[2].m_buf
            bootldr.seek(da2offset)
            da1offset = self.daconfig.da_loader.region[1].m_buf
            da1size = self.daconfig.da_loader.region[1].m_len
            da1address = self.daconfig.da_loader.region[1].m_start_addr
            da1sig_len = self.daconfig.da_loader.region[1].m_sig_len
            bootldr.seek(da1offset)
            da1 = bootldr.read(da1size)
            # ------------------------------------------------
            da2offset = self.daconfig.da_loader.region[2].m_buf
            da2sig_len = self.daconfig.da_loader.region[2].m_sig_len
            bootldr.seek(da2offset)
            da2 = bootldr.read(self.daconfig.da_loader.region[2].m_len)
            self.mtk.daloader.patch = False
            self.daconfig.da2 = da2[:-da2sig_len]
            self.daconfig.da1 = da1
            if self.mtk.preloader.send_da(da1address, da1size, da1sig_len, da1):
                self.info("Successfully uploaded stage 1, jumping ..")
                if self.mtk.preloader.jump_da(da1address):
                    cmd, result = self.get_command_result()
                    if cmd == "CMD:START":
                        self.setup_env()
                        self.setup_hw_init()
                        self.setup_host_info()
                        return True
                    else:
                        return False
                else:
                    self.error("Error on jumping to DA.")
            else:
                self.error("Error on sending DA.")
        return False

    def setup_hw_init(self):
        self.send_command(self.cmd.cmd_host_supported_commands(
            host_capability="CMD:DOWNLOAD-FILE^1@CMD:FILE-SYS-OPERATION^1@CMD:PROGRESS-REPORT^1@CMD:UPLOAD-FILE^1@"))
        self.send_command(self.cmd.cmd_notify_init_hw())
        return True

    def setup_host_info(self, hostinfo: str = ""):
        res = self.send_command(self.cmd.cmd_set_host_info(hostinfo))
        return res

    def read_efuse(self):
        tmp = self.cmd.cmd_read_efuse()
        self.send_command(tmp)
        cmd, result = self.get_command_result()
        # CMD:END
        scmd, sresult = self.get_command_result()
        self.ack()
        if sresult == "OK":
            tcmd, tresult = self.get_command_result()
            if tresult == "START":
                return result
        return None

    def read_register(self, addr):
        tmp = self.cmd.cmd_read_reg(base_address=addr)
        if self.send_command(tmp):
            cmd, data = self.get_command_result()
            if cmd != '':
                return False
            # CMD:END
            scmd, sresult = self.get_command_result()
            self.ack()
            if sresult == "OK":
                tcmd, tresult = self.get_command_result()
                if tresult == "START":
                    return data
            return None

    def get_command_result(self):
        data = self.get_response()
        cmd = get_field(data, "command")
        result = ""
        if cmd == '' and "OK@" in data:
            tmp = data.split("@")[1]
            length = int(tmp[2:], 16)
            self.ack()
            sresp = self.get_response()
            if "OK" in sresp:
                self.ack()
                data = bytearray()
                bytesread = 0
                bytestoread = length
                while bytestoread > 0:
                    tmp = self.get_response_data()
                    bytestoread -= len(tmp)
                    bytesread += len(tmp)
                    data.extend(tmp)
                self.ack()
                return cmd, data
        if cmd == "CMD:PROGRESS-REPORT":
            """
            <?xml version="1.0" encoding="utf-8"?><host><version>1.0</version>
            <command>CMD:PROGRESS-REPORT</command>
            <arg>
                <message>init-hw</message>
            </arg></host>
            """
            self.ack()
            data = ""
            while data != "OK!EOT":
                data = self.get_response()
                self.ack()
            data = self.get_response()
            cmd = get_field(data, "command")
        if cmd == "CMD:START":
            self.ack()
            return cmd, "START"
        if cmd == "CMD:DOWNLOAD-FILE":
            """
            <?xml version="1.0" encoding="utf-8"?><host><version>1.0</version>
            <command>CMD:DOWNLOAD-FILE</command>
            <arg>
                <checksum>CHK_NO</checksum>
                <info>2nd-DA</info>
                <source_file>MEM://0x7fe83c09a04c:0x50c78</source_file>
                <packet_length>0x1000</packet_length>
            </arg></host>
            """
            checksum = get_field(data, "checksum")
            info = get_field(data, "info")
            source_file = get_field(data, "source_file")
            packet_length = int(get_field(data, "packet_length"), 16)
            self.ack()
            return cmd, DwnFile(checksum, info, source_file, packet_length)
        elif cmd == "CMD:UPLOAD-FILE":
            checksum = get_field(data, "checksum")
            info = get_field(data, "info")
            target_file = get_field(data, "target_file")
            packet_length = get_field(data, "packet_length")
            self.ack()
            return cmd, UpFile(checksum, info, target_file, packet_length)
        elif cmd == "CMD:FILE-SYS-OPERATION":
            """
            '<?xml version="1.0" encoding="utf-8"?>
            <host><version>1.0</version>
            <command>CMD:FILE-SYS-OPERATION</command>
            <arg><key>FILE-SIZE</key><file_path>MEM://0x8000000:0x4000000</file_path></arg>
            </host>'
            """
            key = get_field(data, "key")
            file_path = get_field(data, "file_path")
            self.ack()
            return cmd, FileSysOp(key, file_path)
        if cmd == "CMD:END":
            result = get_field(data, "result")
            if "message" in data and result != "OK":
                message = get_field(data, "message")
                return cmd, message
        return cmd, result

    def upload(self, result: DwnFile, data, display=True, raw=False):
        if type(result) is DwnFile:
            # checksum = result.checksum
            # info = result.info
            source_file = result.source_file
            packet_length = result.packet_length
            if ":" in source_file:
                tmp = source_file.split(":")[2]
                length = int(tmp[2:], 16)
            else:
                length = len(data)
            pg = progress(total=length, prefix="Upload:", guiprogress=self.mtk.config.guiprogress)
            self.ack_value(length)
            resp = self.get_response()
            pos = 0
            bytestowrite = length
            if resp == "OK":
                while bytestowrite > 0:
                    self.ack_value(0)
                    resp = self.get_response()
                    if "OK" not in resp:
                        rmsg = get_field(resp, "message")
                        self.error(f"Error on writing stage2 ACK0 at pos {hex(pos)}")
                        self.error(rmsg)
                        return False
                    tmp = data[pos:pos + packet_length]
                    tmplen = len(tmp)
                    self.xsend(data=tmp)
                    resp = self.get_response()
                    if "OK" not in resp:
                        self.error(f"Error on writing stage2 at pos {hex(pos)}")
                        return False
                    pos += tmplen
                    if display:
                        pg.update(tmplen)
                    bytestowrite -= packet_length
                if raw:
                    self.ack()
                cmd, result = self.get_command_result()
                self.ack()
                if display:
                    pg.done()
                if cmd == "CMD:END" and result == "OK":
                    cmd, result = self.get_command_result()
                    if cmd == "CMD:START":
                        return True
                else:
                    self.error(result)
                    sys.stdout.flush()
                    # Do not remove !
                    cmd, result = self.get_command_result()
                    return False
            return False
        else:
            self.error("No upload data received. Aborting.")
            return False

    def download_raw(self, result, filename: str = "", display: bool = False):
        # FM350_QUEUE: очередь ограничена, чтобы не забить память, если флешка или браузер отстают от модема.
        # Писателя ждём всегда: иначе конец последнего раздела пропадал при выходе из программы.
        limit = int(os.environ.get("FM350_QUEUE", "16"))
        rq = Queue(limit)
        if type(result) is UpFile:
            # checksum = result.checksum
            # info = result.info
            # target_file = result.target_file
            # packet_length = int(result.packet_length, 16)
            resp = self.get_response()
            if "OK@" in resp:
                tmp = resp.split("@")[1]
                length = int(tmp[2:], 16)
                pg = progress(total=length, prefix="Read:", guiprogress=self.mtk.config.guiprogress)
                self.ack()
                sresp = self.get_response()
                if "OK" in sresp:
                    self.ack()
                    data = bytearray()
                    bytesread = 0
                    bytestoread = length
                    worker = None
                    if filename != "":
                        worker = Thread(target=writedata, args=(filename, rq), daemon=True)
                        worker.start()
                    while bytestoread > 0:
                        tmp = self.get_response_data()
                        lt = len(tmp)
                        bytestoread -= lt
                        bytesread += lt
                        if filename != "":
                            rq.put(tmp)
                        else:
                            data.extend(tmp)
                        if display:
                            pg.update(lt)
                        self.ack()
                        sresp = self.get_response()
                        if "OK" not in sresp:
                            break
                        else:
                            self.ack()
                    if display:
                        pg.done()
                    if filename != "":
                        rq.put(None)
                        worker.join()
                        return True
                    return data
            self.error("Error on downloading data:" + resp)
            return False
        else:
            self.error("No download data received. Aborting.")
            return False

    def download(self, result):
        if type(result) is UpFile:
            # checksum = result.checksum
            # info = result.info
            # target_file = result.target_file
            # packet_length = int(result.packet_length, 16)
            resp = self.get_response()
            if "OK@" in resp:
                tmp = resp.split("@")[1]
                length = int(tmp[2:], 16)
                self.ack()
                sresp = self.get_response()
                if "OK" in sresp:
                    self.ack()
                    data = bytearray()
                    bytesread = 0
                    bytestoread = length
                    while bytestoread > 0:
                        tmp = self.get_response_data()
                        bytestoread -= len(tmp)
                        bytesread += len(tmp)
                        data.extend(tmp)
                    self.ack()
                    return data
            self.error("Error on downloading data:" + resp)
            return False
        else:
            self.error("No download data received. Aborting.")
            return False

    def boot_to(self, addr, data, display=True, timeout=0.5):
        result = self.send_command(self.cmd.cmd_boot_to(at_addr=addr, jmp_addr=addr, length=len(data)))
        if type(result) is DwnFile:
            self.info("Uploading stage 2...")
            if self.upload(result, data):
                return True
        else:
            self.error("Wrong boot_to response :(")
        return False

    def upload_da(self):
        self.daext = False
        if self.upload_da1():
            self.info("DA Stage 1 successfully loaded.")
            da2 = self.daconfig.da2
            da2offset = self.daconfig.da_loader.region[2].m_start_addr
            loaded = self.boot_to(da2offset, da2)
            if loaded:
                self.info("Successfully booted to stage 2")
                self.setup_hw_init()
                self.change_usb_speed()
                if self.check_sla():
                    # для подписи SLA нужен закрытый ключ производителя: его нет, а обходить защиту программа не должна
                    self.error("FM350: SLA is enabled on this modem, read-only stock DA cannot continue.")
                    return False
                self.info("DA XML SLA is disabled")
            self.reinit(True)
            self.check_lifecycle()
            # FM350: сохранить таблицу разделов, которую отдаёт DA (только чтение), если задан путь
            if os.environ.get("FM350_PARTTBL"):
                try:
                    _raw, _pt = self.read_partition_table()
                    _txt = _raw if isinstance(_raw, str) else bytes(_raw).decode("utf-8", "replace")
                    with open(os.environ["FM350_PARTTBL"], "w") as _f:
                        _f.write(_txt)
                    self.info("PARTTBL saved, entries: " + str(len(_pt or [])))
                except Exception as _e:
                    self.info("read_partition_table: " + repr(_e))
            return True
        return False

    def get_dev_info(self):
        content = {}
        if self.send_command(self.cmd.cmd_get_dev_info(), noack=True):
            cmd, result = self.get_command_result()
            if not isinstance(result, UpFile):
                return False
            data = self.download(result)
            # CMD:END
            scmd, sresult = self.get_command_result()
            self.ack()
            if sresult == "OK":
                if b"rnd" in data:
                    content["rnd"] = bytes.fromhex(get_field(data, "rnd"))
                if b"hrid" in data:
                    content["hrid"] = bytes.fromhex(get_field(data, "hrid"))
                if b"socid" in data:
                    content["socid"] = bytes.fromhex(get_field(data, "socid"))
                tcmd, tresult = self.get_command_result()
                if tresult == "START":
                    return content
        return content

    def get_hw_info(self):
        self.send_command(self.cmd.cmd_get_hw_info(), noack=True)
        cmd, result = self.get_command_result()
        if not isinstance(result, UpFile):
            return False
        data = self.download(result)
        """
        <?xml version="1.0" encoding="utf-8"?>
        <da_hw_info>
        <version>1.2</version>
        <ram_size>0x100000000</ram_size>
        <battery_voltage>3810</battery_voltage>
        <random_id>4340bfebf6ace4e325f71f7d37ab15aa</random_id>
        <storage>UFS</storage>
        <ufs>
            <block_size>0x1000</block_size>
            <lua0_size>0x400000</lua0_size>
            <lua1_size>0x400000</lua1_size>
            <lua2_size>0xee5800000</lua2_size>
            <lua3_size>0</lua3_size>
            <id>4D54303634474153414F32553231202000000000</id>
        </ufs>
        <product_id></product_id>
        </da_hw_info>
        """
        scmd, sresult = self.get_command_result()
        self.ack()
        if sresult == "OK":
            tcmd, tresult = self.get_command_result()
            if tresult == "START":
                self.info("hw_info raw: " + (data.decode("utf-8","replace") if isinstance(data,(bytes,bytearray)) else str(data)))
                storagetype = get_field(data, "storage")
                self.daconfig.storage.storagetype = storagetype
                if storagetype == "UFS":
                    self.config.pagesize = 4096
                    self.daconfig.storage.flashtype = "ufs"
                    self.daconfig.storage.ufs.block_size = int(get_field(data, "block_size"), 16)
                    self.daconfig.storage.ufs.lu0_size = int(get_field(data, "lua0_size"), 16)
                    self.daconfig.storage.ufs.lu1_size = int(get_field(data, "lua1_size"), 16)
                    self.daconfig.storage.ufs.lu2_size = int(get_field(data, "lua2_size"), 16)
                    self.daconfig.storage.ufs.lu3_size = int(get_field(data, "lua3_size"), 16)
                    self.daconfig.storage.ufs.cid = get_field(data, "id")  # this doesn't exists in Xiaomi DA
                    if not self.daconfig.storage.ufs.cid:
                        self.daconfig.storage.ufs.cid = get_field(data, "ufs_cid")
                    self.daconfig.storage.set_flash_size()
                elif storagetype == "EMMC":
                    self.daconfig.storage.flashtype = "emmc"
                    self.daconfig.storage.emmc.block_size = int(get_field(data, "block_size"), 16)
                    self.daconfig.storage.emmc.boot1_size = int(get_field(data, "boot1_size"), 16)
                    self.daconfig.storage.emmc.boot2_size = int(get_field(data, "boot2_size"), 16)
                    self.daconfig.storage.emmc.rpmb_size = int(get_field(data, "rpmb_size"), 16)
                    self.daconfig.storage.emmc.user_size = int(get_field(data, "user_size"), 16)
                    self.daconfig.storage.emmc.gp1_size = int(get_field(data, "gp1_size"), 16)
                    self.daconfig.storage.emmc.gp2_size = int(get_field(data, "gp2_size"), 16)
                    self.daconfig.storage.emmc.gp3_size = int(get_field(data, "gp3_size"), 16)
                    self.daconfig.storage.emmc.gp4_size = int(get_field(data, "gp4_size"), 16)
                    self.cid = get_field(data, "id")  # this doesn't exists in Xiaomi DA
                    self.daconfig.storage.set_flash_size()
                    if not self.cid:
                        self.cid = get_field(data, "emmc_cid")
                elif storagetype == "NAND":
                    self.daconfig.storage.flashtype = "nand"
                    self.daconfig.storage.nand.block_size = int(get_field(data, "block_size") or "0", 16)
                    self.daconfig.storage.nand.page_size = int(get_field(data, "page_size") or "0", 16)
                    self.daconfig.storage.nand.spare_size = int(get_field(data, "spare_size") or "0", 16)
                    self.daconfig.storage.nand.total_size = int(get_field(data, "total_size") or "0", 16)
                    self.daconfig.storage.nand.cid = get_field(data, "id")
                    self.daconfig.storage.nand.page_parity_size = int(get_field(data, "page_parity_size") or "0", 16)
                    self.daconfig.storage.nand.sub_type = get_field(data, "sub_type")
                    self.daconfig.storage.set_flash_size()
                else:
                    self.error(f"Unknown storage type: {storagetype}")
                    return False
        return True

    def check_sla(self):
        """
        int RSA_private_encrypt(int flen, unsigned char *from, unsigned char *to, RSA *rsa, int padding);
                                    0x10,                                                 , 1
        """
        # FM350: SLA выключен (target config 0x5), а ответа на этот запрос модем не даёт: каждый запуск
        # ждал таймаута около 100 с. SP Flash Tool такой запрос не посылает.
        if self.mtk.config.hwcode == 0x992:
            return False
        data = self.get_sys_property(key="DA.SLA", length=0x200000)
        if data is None or data is False:
            return False
        data = data.decode('utf-8')
        if "item key=" in data:
            tmp = data[data.find("item key=") + 8:]
            res = tmp[tmp.find(">") + 1:tmp.find("<")]
            return res != "DISABLED"
        else:
            self.error("Couldn't find item key")
        return data

    def get_sys_property(self, key: str = "DA.SLA", length: int = 0x200000):
        self.send_command(self.cmd.cmd_get_sys_property(key=key, length=length), noack=True)
        cmd, result = self.get_command_result()
        if type(result) is not UpFile:
            return False
        data = self.download(result)
        # CMD:END
        scmd, sresult = self.get_command_result()
        self.ack()
        if sresult == "OK":
            tcmd, tresult = self.get_command_result()
            if tresult == "START":
                return data
        return None

    def change_usb_speed(self):
        resp = self.send_command(self.cmd.cmd_can_higher_usb_speed())
        if not resp:
            return False

    def read_partition_table(self) -> tuple:
        self.send_command(self.cmd.cmd_read_partition_table(), noack=True)
        cmd, result = self.get_command_result()
        if type(result) is not UpFile:
            return b"", None
        data = self.download(result)
        # CMD:END
        scmd, sresult = self.get_command_result()
        self.ack()
        if sresult == "OK":
            tcmd, tresult = self.get_command_result()

            class PartitionTable:
                def __init__(self, name, start, size):
                    self.name = name
                    self.start = start
                    self.size = size

            if tresult == "START":
                parttbl = []
                data = data.decode('utf-8')
                for item in data.split("<pt>"):
                    name = get_field(item, "name")
                    if name != '':
                        start = get_field(item, "start")
                        rsize = get_field(item, "size")
                        if rsize == "" or start == "":
                            continue
                        rsize = int(rsize, 16)
                        start = int(start, 16)
                        parttbl.append(
                            PartitionTable(name, start // self.config.pagesize, rsize // self.config.pagesize))
                return data, parttbl
        return b"", None

    def readflash(self, addr, length, filename, parttype=None, display=True) -> (bytes, bool):
        partinfo = self.daconfig.storage.get_storage(parttype, length)
        if not partinfo:
            return b""
        storage, parttype, length = partinfo

        if self.send_command(self.cmd.cmd_read_flash(parttype, addr, length), noack=True):
            cmd, result = self.get_command_result()
            if type(result) is not UpFile:
                self.error(result)
                return b""
            data = self.download_raw(result=result, filename=filename, display=display)
            scmd, sresult = self.get_command_result()
            if sresult == "START":
                if not filename:
                    return data
                else:
                    return True
            if not filename:
                return b""
            return False
        else:
            self.error("Read flash isn't supported")
            sys.exit(1)

    def check_lifecycle(self):
        self.send_command(self.cmd.cmd_emmc_control(function="LIFE-CYCLE-STATUS"), noack=True)
        cmd, result = self.get_command_result()
        if not isinstance(result, UpFile):
            if cmd == 'CMD:END':
                self.ack()
                scmd, sresult = self.get_command_result()
            return False
        data = self.download(result)
        scmd, sresult = self.get_command_result()
        self.ack()
        if sresult == "OK":
            tcmd, tresult = self.get_command_result()
            if tresult == "START":
                return data == b"OK\x00"
        return False

    def reinit(self, display=False):
        """
        self.config.sram, self.config.dram = self.get_ram_info()
        self.emmc = self.get_emmc_info(display)
        self.nand = self.get_nand_info(display)
        self.nor = self.get_nor_info(display)
        self.ufs = self.get_ufs_info(display)
        """
        if not self.get_hw_info():
            self.error("Error: Cannot Reinit daconfig")
            return
