#!/usr/bin/env python3
# MTK Flash Client (c) B.Kerler 2018-2025 (refactored & cleaned 2025/2026)
# Licensed under GPLv3 License
#
# Урезанная версия для FM350 Backup: только чтение памяти штатным DA.
# Что убрано и как вернуть: docs/mtkclient-changes.md

import argparse
import logging
import sys

from mtkclient.Library.mtk_main import Main

INFO = "MTK Flash Client V2.1.4 (c) B.Kerler 2018-2026, read-only cut for FM350 Backup"


def create_base_parser():
    parser = argparse.ArgumentParser(description=INFO, add_help=False)
    g = parser.add_argument_group("Options")
    g.add_argument('--vid', type=str)
    g.add_argument('--pid', type=str)
    g.add_argument('--noreconnect', action='store_true')
    g.add_argument('--stock', action='store_true', help='use stock da')
    g.add_argument('--loglevel', help='Set log level (0=Trace, 2=Normal)')
    g.add_argument('--debugmode', action='store_true', help='Enable verbose mode')
    g.add_argument('--loader', type=str, help='DA loader')
    g.add_argument('--sectorsize', default='0x200', help='Set default sector size')
    g.add_argument('--parttype', help='Partition type (user/boot1/rpmb/lu0 etc.)')
    return parser


def main():
    base = create_base_parser()
    parser = argparse.ArgumentParser(description=INFO, parents=[base],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest='cmd', required=True, metavar='command')
    ro = subparsers.add_parser("ro", help="Read flash starting at offset to filename", parents=[base])
    ro.add_argument("offset", help="Byte offset")
    ro.add_argument("length", help="Length")
    ro.add_argument("filename", help="File")
    subparsers.add_parser("multi", help="Run multiple commands using semicolon-separated list") \
        .add_argument("commands")

    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debugmode else logging.INFO,
                        format="%(levelname)s: %(message)s")
    mtk = Main(args)
    return mtk.run(parser)


if __name__ == '__main__':
    sys.exit(main() or 0)
