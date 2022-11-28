#!/usr/bin/env python3
""" Python script to help finding embedded systems in the network.
    It finds the ip addresses for the given mac addresses and saves hostnames in /etc/hosts
"""
import os
import sys
import tempfile
import argparse
from kdt_utils import BashCommands, kdt_config_section
from kdt_install import get_ip_add

bash = BashCommands()


def get_ip_ranges():
    """ Find the current network connections and returns a list of ip ranges to be scanned

    Returns:
        List of available network ip ranges
    """
    command = ["ip", "-f", "inet", "addr", "show", "scope", "global"]
    _, interfaces, _ = bash.kdt_run_str(command, check=True)
    ip_ranges = []
    get_next_line = False
    for iface_ln in interfaces.split("\n"):
        if get_next_line:
            ip_range = iface_ln[iface_ln.index("inet ") + len("inet "): iface_ln.index(" brd")]
            addr, mask = ip_range.split("/")
            addr = addr[:addr.rindex(".")] + ".0"  # replace last part of ip with zero
            ip_ranges.append(f"{addr}/{mask}")
            get_next_line = False
        if "state UP" in iface_ln:
            get_next_line = True

    return ip_ranges


def list_net_devices():
    """ Scans the current network for devices IPs and MAC addresses

    Returns:
        Dictionary of mac addresses to ip address
    """
    net_devs = {}
    for ip_range in get_ip_ranges():
        _, net_ips, _ = bash.kdt_run_str(["sudo", "arp-scan", "-qxr", "4", ip_range], check=True)
        for net_ip in net_ips.split("\n"):
            ip_addr, mac = net_ip.split("\t")
            net_devs[mac] = ip_addr
    return net_devs


def match_host_ip():
    """ Matches hostnames to IP addresses using MAC addresses defines in the configuration file

    Returns:
        Dictionary of hostnames and IP addresses
    """
    host_mac_list = kdt_config_section("get_ip")
    if host_mac_list is None:
        sys.exit("Error! Host / MAC list empty.")
    net_devices = list_net_devices()

    host_ip = {}
    for dev_name in host_mac_list:
        host_mac = host_mac_list[dev_name]
        if host_mac in net_devices:
            host_ip[dev_name] = net_devices[host_mac]
    return host_ip


def read_etc_hosts():
    """ Returns the contents of /etc/hosts, but remove lines with #gip added

    Returns:
        Clean /etc/hosts content as string
    """
    temp_etc_hosts = ""
    with open("/etc/hosts", 'r', encoding="utf-8") as _etc_hosts_file:
        for host_line in _etc_hosts_file.readlines():
            if "#gip added" not in host_line:
                temp_etc_hosts += host_line
    return temp_etc_hosts


def get_ips(debug=False):
    """ Scans the network for know mac address and add entries to /etc/hosts
    """
    etc_hosts = read_etc_hosts()
    if etc_hosts[-2:] != "\n\n":  # an extra line between added hosts
        etc_hosts += "\n"
    for hostname, host_ip_addr in match_host_ip().items():
        if debug:
            print(f"Found: {hostname} {host_ip_addr}")
        etc_hosts += f"{host_ip_addr} {hostname} #gip added\n"
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(bytearray(etc_hosts, encoding="utf-8"))
        tmp.close()
        bash.kdt_run_str(["sudo", "cp", tmp.name, "/etc/hosts"], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scans the local network to find known mac "
                                                 "addresses and add entries to /etc/hosts")
    parser.add_argument("-d", "--debug", action="store_true", default=False,
                        help="Print all commands being executed")
    subparsers = parser.add_subparsers(dest='command', required=False)

    DESCRIPTION = "Add host / mac mapping to be latter used in the scan."
    add = subparsers.add_parser('add', help=DESCRIPTION, description=DESCRIPTION)
    add.add_argument("host", nargs='?', default="", type=str, help="Hostname to add")
    add.add_argument("mac", nargs='?', default="", type=str, help="MAC address to add")

    DESCRIPTION = "Lists current hostnames found."
    lists = subparsers.add_parser('list', help=DESCRIPTION, description=DESCRIPTION)

    args = parser.parse_args()

    match args.command:
        case "add":
            if bool(args.host) ^ bool(args.mac):
                parser.error('hostname and mac must be given together')
            get_ip_add(args.host, args.mac)
        case "list":
            with open("/etc/hosts", 'r', encoding="utf-8") as _etc_hosts_file:
                for line in _etc_hosts_file:
                    if "#gip added" in line:
                        print(line.replace("#gip added", ''), end='')
        case _:
            if args.debug:
                get_ips(args.debug)
            else:
                pid = os.fork()
                # fork a child process for the actual job, so the parent can return faster
                if pid == 0:
                    get_ips(args.debug)
