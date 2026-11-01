#!/usr/bin/env python3
import os


class PathConfig:
    def __init__(self):
        curscript = os.path.realpath(__file__)
        self.scriptpath = os.path.dirname(curscript)
