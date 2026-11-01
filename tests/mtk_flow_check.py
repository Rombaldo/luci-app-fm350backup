"""Запускается отдельным процессом из test_mtkclient.py: mtkclient при импорте подменяет sys.stdout."""
import json
import os
import sys
import tempfile
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "third_party", "mtkclient")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "..", "..", "vendor", "pylib"))


class NoCrypto:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("Crypto", "Cryptodome", "capstone", "keystone", "mfusepy", "PySide6"):
            raise ImportError("запрещено в тесте: " + name)
        return None


def multi():
    import mtk
    from mtkclient.Library import mtk_class, mtk_preloader
    from mtkclient.Library.DA import mtk_daloader

    def init(preloader, *a, **k):
        preloader.config.target_config = {"sbc": True, "sla": False, "daa": True}
        preloader.config.is_brom = False
        return True

    reads = []

    def readflash(loader, addr, length, filename, parttype, display=True):
        reads.append([addr, length])
        return True

    with tempfile.TemporaryDirectory() as tmp:
        da = os.path.join(tmp, "DA_test.bin")
        with open(da, "wb") as f:
            f.write(b"MTK_DOWNLOAD_AGENT" + bytes(0x100))
        one = "ro 0x0 0x1000 %s --stock --loader %s" % (os.path.join(tmp, "a.bin"), da)
        two = "ro 0x1000 0x2000 %s --stock --loader %s" % (os.path.join(tmp, "b.bin"), da)
        os.chdir(tmp)
        with mock.patch.object(sys, "argv", ["mtk.py", "--stock", "--loader", da, "multi", one + ";" + two]), \
                mock.patch.object(mtk_class, "Port") as port, \
                mock.patch.object(mtk_preloader.Preloader, "init", init), \
                mock.patch.object(mtk_daloader.DAloader, "upload_da", return_value=True) as up, \
                mock.patch.object(mtk_daloader.DAloader, "writestate"), \
                mock.patch.object(mtk_daloader.DAloader, "readflash", readflash):
            port.return_value.cdc.connected = None
            mtk.main()
        os.chdir("/")
    return {"reads": reads, "uploads": up.call_count}


def sla():
    from mtkclient.Library.DA.xmlflash.xml_lib import DAXML
    da = DAXML.__new__(DAXML)
    for name in ("upload_da1", "boot_to", "setup_hw_init", "change_usb_speed", "reinit", "check_lifecycle",
                 "info", "error"):
        object.__setattr__(da, name, mock.Mock(return_value=True))
    da.check_sla = mock.Mock(return_value=True)
    da.daconfig = mock.MagicMock()
    return {"result": da.upload_da(), "error": da.error.call_args[0][0], "reinit": da.reinit.call_count}


def slow_disk():
    """Флешка медленнее модема: файл полон к моменту возврата, в очереди не больше предела."""
    import threading
    import time
    from mtkclient.Library.DA.xmlflash import xml_lib
    joins = []
    real_join = threading.Thread.join

    def join(thread, timeout=None):
        joins.append(timeout)
        return real_join(thread, timeout)

    real_writedata = xml_lib.writedata
    deepest = [0]

    def slow(filename, rq):
        class SlowQueue:
            def get(self, timeout=None):
                deepest[0] = max(deepest[0], rq.qsize())
                time.sleep(0.005)
                return rq.get(timeout=timeout)

            def task_done(self):
                rq.task_done()
        real_writedata(filename, SlowQueue())

    chunks = [bytes([i]) * 1024 for i in range(60)]
    feed = iter(chunks)
    da = xml_lib.DAXML.__new__(xml_lib.DAXML)
    da.mtk = mock.MagicMock()
    da.mtk.config.guiprogress = None
    answers = iter(["OK@0x%x" % sum(map(len, chunks)), "OK"] + ["OK"] * len(chunks))
    da.get_response = lambda *a, **k: next(answers)
    da.ack = lambda *a, **k: True
    da.get_response_data = lambda: next(feed)
    result = xml_lib.UpFile("", "", "", 0)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.bin")
        with mock.patch.object(xml_lib, "writedata", slow), mock.patch.object(threading.Thread, "join", join):
            ok = da.download_raw(result, filename=path)
        size = os.path.getsize(path)
    return {"ok": ok, "size": size, "want": sum(map(len, chunks)), "joins": joins, "deepest": deepest[0]}


sys.meta_path.insert(0, NoCrypto())
print("RESULT " + json.dumps({"multi": multi, "sla": sla, "slow_disk": slow_disk}[sys.argv.pop(1)]()))
