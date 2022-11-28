#!/usr/bin/env python3
""" Translates a git diff call to meld call
    USE: git config --global diff.external diff.py
    Put diff.py on $PATH
"""
import sys
import os

os.system(f"meld {sys.argv[2]} {sys.argv[5]}")
