#!/usr/bin/env python3
""" Python script Install Kernel Development Tools
"""
from os import path
# pylint: disable=unused-import
# readline fixes input function where it accepts arrow keys
import readline
import kdt_utils


def get_ip_add(hostname="", mac_address=""):
    """ Adds hostname MAC address lines to get ip section
    """
    gip_section = kdt_utils.kdt_config_section("get_ip")
    if gip_section is None:
        gip_section = {}

    if bool(hostname) and bool(mac_address):
        gip_section[hostname] = mac_address
        kdt_utils.kdt_update_section("get_ip", gip_section)
        return

    print("Add Host / MAC to get IP list?")
    print("Type \"host_name aa:bb:cc:dd:ee:ff\" to add or empty for no.")
    while True:
        host_mac = input("Host / MAC: ")
        if not host_mac:
            break
        try:
            host, mac = ' '.join(host_mac.split()).split(' ')
        except ValueError:
            print("Nope. Could not understand what you said. Try again.")
        else:
            gip_section[host] = mac
    if len(gip_section) > 0:
        kdt_utils.kdt_update_section("get_ip", gip_section)


def kdt_install():
    """ Install Kernel Development Tools """
    home_dir = path.expanduser('~')
    kdt_folder = path.dirname(__file__)
    kb_section = kdt_utils.kdt_config_section("kernel_builder")
    if kb_section is None:
        kb_section = {}
    kdt_params = {"kdt_boards": ("Enter the folder where kernel configs will be stored.\n"
                                 f"Empty for default [{kdt_folder.replace(home_dir, '~')}/boards]: ",
                                 f"{kdt_folder}/boards", False),
                  "kdt_build": ("Enter kernel build output path."
                                f"Empty for default [~/.kdt_kernel_builds]: ",
                                f"{home_dir}/.kdt_kernel_builds", False),
                  "kdt_eclipse": ("Enable eclipse links? Empty for default [y/N]: ", "no", True)
                  }
    for param, (line, dft, is_bool) in kdt_params.items():
        if param not in kb_section or not bool(kb_section[param]):
            answer = input(line)
            if not bool(answer):
                answer = dft
            if is_bool and answer.lower() in ("y", "yes"):
                answer = "yes"
            if is_bool and answer.lower() in ("n", "no"):
                answer = "no"
            kb_section[param] = answer
    kdt_utils.kdt_update_section("kernel_builder", kb_section)

    def bool_input(string):
        return input(string).lower() in ("y", "yes")

    git_format_patch = bool_input("Enable git format-patch overload? [y/N] ")
    git_diff = bool_input("Enable git diff using meld? [y/N] ")
    get_ip = bool_input("Enable get IP tool? [y/N] ")

    git_function = (
        "\n"
        "function git {\n"
        "    if [[ \"$1\" == \"format-patch\" && \"$@\" != *\"--help\"* ]]; then\n"
        "        shift 1\n"
        "        command git fp \"$@\"\n"
        "    else\n"
        "        command git \"$@\"\n"
        "    fi\n"
        "}\n"
    )

    with open(f"{home_dir}/.bashrc", 'a', encoding="utf-8") as bashrc:
        if git_format_patch:
            bashrc.write(git_function)
            print("Git overload of format-patch enabled.")
        bashrc.write('\nPATH=~/.local/bin:$PATH\n')

    bash = kdt_utils.BashCommands()
    local_bin = f"{home_dir}/.local/bin"
    bash.kdt_run(["mkdir", "-p", local_bin], check=True)
    if git_diff:
        bash.kdt_run(["ln", "-sf", f"{kdt_folder}/git_diff.py",         f"{local_bin}/diff.py"], check=True)
        bash.kdt_run(["git", "config", "--global", "diff.external", "diff.py"], check=True)
        print("Git diff using meld enabled.")
    if git_format_patch:
        bash.kdt_run(["ln", "-sf", f"{kdt_folder}/git_format_patch.py", f"{local_bin}/git-fp"],  check=True)
    if get_ip:
        get_ip_add()
        bash.kdt_run(["ln", "-sf", f"{kdt_folder}/get_ip.py", f"{local_bin}/gip"], check=True)
    bash.kdt_run(["ln", "-sf", f"{kdt_folder}/kernel_builder.py",   f"{local_bin}/kb"],      check=True)
    print("Restart bash or source bashrc to start using kdt tools.")


if __name__ == "__main__":
    kdt_install()
