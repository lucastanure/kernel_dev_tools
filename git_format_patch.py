#!/usr/bin/env python3
""" Git format-patch version that removes Change-id: lines created for Gerrit.
    Use in the same git format-patch command.
    Add this script in your $PATH as git-fp, like:
    ~/.local/bin/git-fp

    Add this function to ~/.bashrc to overwrite git format-patch command
    function git {
        if [[ "$1" == "format-patch" && "$@" != *"--help"* ]]; then
        shift 1
            command git fp "$@"
        else
            command git "$@"
        fi
    }
"""
import sys
from os import path
from kdt_utils import BashCommands


def remove_change_id(patch_file):
    """ Removes Change-Id: from a patch file

    Args:
        patch_file: Path to patch file
    """
    change_id = "Change-Id:"
    if not path.exists(patch_file):
        return
    with open(patch_file, "r", encoding="utf-8") as patch:
        patch_lines = patch.readlines()
    with open(patch_file, "w", encoding="utf-8") as patch:
        for line in patch_lines:
            if line[:len(change_id)] != change_id:
                patch.write(line)


if __name__ == "__main__":
    bash = BashCommands()
    _, patches, _ = bash.kdt_run_str(["git", "format-patch"] + sys.argv[1:], check=True)
    for each_patch in patches.split("\n"):
        remove_change_id(each_patch)
    print(patches)
