""" Python script to help finding embedded systems in the network.
    It finds the ip addresses for the given mac addresses and saves hostnames in /etc/hosts
"""
import sys
import configparser
from os import path, cpu_count, environ
from subprocess import run, CalledProcessError, PIPE, STDOUT, DEVNULL
from colorama import Fore, Style


def print_blue(text):
    """ Print a blue text """
    print(Fore.BLUE + text + Style.RESET_ALL)


def print_red_blue(first, second):
    """ Print a blue text """
    print(Fore.RED + first + Fore.BLUE + second + Style.RESET_ALL)


def print_magenta(text):
    """ Print a blue text """
    print(Fore.MAGENTA + text + Style.RESET_ALL)


def print_green_blue(first, second):
    """ Print a blue text """
    print(Fore.GREEN + first + Fore.BLUE + second + Style.RESET_ALL)


def get_config(section, name, mandatory=True):
    """ Gets the configuration by name

    Args:
        section: A configuration section read from boards file
        name: Name of the particular board configuration
        mandatory: True if mandatory

    Returns:
        Exit if a mandatory config is not found.
        Returns configuration value or an empty string.
    """
    if name in section:
        return section[name]
    if mandatory:
        return sys.exit(f"Error! Missing \"{name}\" in board configuration section")
    return ""


def parse_fdisk(img, bash):
    """ Parses the output on fdisk -l on a disk or image

    Args:
        img: Image or disk path
        bash: Bash class used to execute commands

    Returns:
        Name, start and length in bytes of one or two partitions
    """
    unit, start1, sectors1, start2, sectors2 = 0, 0, 0, 0, 0
    name1, name2 = "", ""
    valid, fdisk, err = bash.kdt_run_str(["fdisk", "-o", "Device,Start,Sectors", "-l", img], check=True)
    if not valid:
        return name1, start1, sectors1, name2, start2, sectors2
    for line in fdisk.split('\n'):
        if "Units:" in line:
            unit = line[line.index("= ") + 2:line.index("bytes") - 1]
        if f"{img}1" in line:
            # Replace all spaces with one space
            name1, start1, sectors1 = ' '.join(line.split()).split(' ')
            start1 = int(start1) * int(unit)
            sectors1 = int(sectors1) * int(unit)
        if f"{img}2" in line:
            # Replace all spaces with one space
            name2, start2, sectors2 = ' '.join(line.split()).split(' ')
            start2 = int(start2) * int(unit)
            sectors2 = int(sectors2) * int(unit)
    if 0 in (unit, start1, sectors1):
        sys.exit(f"Error! Fail to parse fdisk output from image {img}")
    return name1, start1, sectors1, name2, start2, sectors2


def disk_mount(disk, mount_point, bash):
    """ Mounts a disk or an image at mount_point

    Args:
        disk: Image or disk path
        mount_point: The path where the disk or images will be mounted
        bash: Bash class used to execute commands

    Returns:
        Pair boolean values for root mounted and boot mounted
    """
    root_args, boot_args = [], []
    root_src, boot_src = None, None
    root_ret, boot_ret = False, False
    name1, start1, sectors1, name2, start2, sectors2 = parse_fdisk(disk, bash)
    if "/dev/" in disk:
        if start2 > 0:
            root_src, boot_src = name2, name1
        else:
            root_src = name1
    elif path.isfile(disk):
        if start2 > 0:
            root_args = ["-o", f"loop,offset={start2},sizelimit={sectors2}"]
            boot_args = ["-o", f"loop,offset={start1},sizelimit={sectors1}"]
            root_src, boot_src = disk, disk
        else:
            root_args = ["-o", f"loop,offset={start1},sizelimit={sectors1}"]
            root_src = disk
    else:
        return root_ret, boot_ret
    root_ret = bash.mount(root_args + [root_src, mount_point], sudo=True)
    if boot_src is not None:
        boot_ret = bash.mount(boot_args + [boot_src, f"{mount_point}/boot"], sudo=True)
        if not boot_ret:
            bash.umount([root_src], sudo=True)
            root_ret = False
    return root_ret, boot_ret


def disk_umount(mount_point, boot, bash):
    """ Umount a disk or an image

    Args:
        mount_point: The path where the disk or images has been mounted
        boot: True if a second partition for boot was mounted
        bash: Bash class to be used to issue commands
    """
    if boot:
        bash.umount([f"{mount_point}/boot"], sudo=True)
    bash.umount([f"{mount_point}"], sudo=True)


def kdt_config_section(section_name):
    """ Reads ~/.kdt configuration file and returns a section

    Args:
        section_name: Section name to be returned

    Returns:
        The section
    """
    kdt_config = f"{path.expanduser('~')}/.kdt"
    if not path.exists(kdt_config):
        return None
    configs_file = configparser.ConfigParser()
    configs_file.read(kdt_config)
    if section_name in configs_file:
        return configs_file[section_name]
    return None


def kdt_update_section(section_name, section):
    """ Updates a section in ~/.kdt configuration file

    Args:
        section_name: Section name to be returned
        section: New section to be writen
    """
    kdt_config_path = f"{path.expanduser('~')}/.kdt"
    kdt_config = configparser.ConfigParser()
    if path.exists(kdt_config_path):
        kdt_config.read(kdt_config_path)
    kdt_config[section_name] = section
    with open(kdt_config_path, 'w', encoding="utf-8") as new_kdt_config:
        kdt_config.write(new_kdt_config)


class BashCommands:
    """ Execute bash commands with modified params """

    def __init__(self, debug_enable=False):
        ssh_params = ["-o LogLevel=ERROR", "-o UserKnownHostsFile=/dev/null",
                      "-o StrictHostKeyChecking=no"]
        rsync_params = ["rsync", "-rcptD", "--exclude=.*", "--mkpath", "--no-links"]
        ssh_command = ["ssh"] + ssh_params
        scp_command = ["scp"] + ssh_params
        self.ssh_for_rsync = f"-e {' '.join(ssh_command)}"
        self.ssh_for_rsync_with_qmark = f"-e \"{' '.join(ssh_command)}\""
        self.commands = {
            "ssh": ssh_command,
            "scp": scp_command,
            "net_rsync": rsync_params + [self.ssh_for_rsync],
            "disk_rsync": rsync_params,
            "mount": ["mount"],
            "umount": ["umount"],
        }
        self.make_command = []
        self.debug = debug_enable
        self.environ = environ.copy()
        self.current_command = []

    def set_make(self, arch, kernel_build_path, install_mod_path, cross_compiler=None):
        """ Configure make parameters

        Args:
            arch: The build architecture (x86, x86_64, arm, arm64)
            kernel_build_path: Path where the kernel will be built
            install_mod_path: Path where the kernel modules will be installed
            cross_compiler: Cross-Compiler prefix (aarch64-linux-gnu-)
        """

        self.make_command = ["make", f"-j{str(cpu_count())}", f"ARCH={arch}",
                             f"O={kernel_build_path}", f"INSTALL_MOD_PATH={install_mod_path}"]
        if cross_compiler is not None:
            self.make_command += [f"CROSS_COMPILE={cross_compiler}"]

    def get_make_arguments(self):
        """ Configure make parameters"""
        return self.make_command[1:]

    def add_make_argument(self, argument):
        """ Add argument to the make command

        Args:
            argument: String to be added to make command
        """
        self.make_command += [argument]

    def set_prefix_path(self, prefix):
        """ Add prefix string to the front of PATH in the current bash environment

        Args:
            prefix: String to be added to PATH
        """
        self.environ["PATH"] = f"{prefix}:{self.environ['PATH']}"

    def export(self, name, value):
        """ Saves variable name with value

        Args:
            name: Variable Name
            value: Variable Value
        """
        self.environ[name] = value

    def print_command(self, command, debug_type=(False, True)):
        """ Print the command being executed

        Args:
            command: List of strings, where the first position is the actual command,
            and the rest are parameters
            debug_type: In debug mode (Print , Execute)
        """
        _print, _exec = debug_type
        if self.debug and _print:
            if self.ssh_for_rsync in command:
                command[command.index(self.ssh_for_rsync)] = self.ssh_for_rsync_with_qmark
            print(' '.join(command))
        if self.debug:
            return _exec
        return True

    def kdt_run(self, command, debug_type=(False, True), sudo=False, **kwargs):
        """ Runs a bash command without checking its return

        Args:
            command: List of strings, where the first position is the actual command,
            and the rest are parameters
            debug_type: In debug mode (Print , Execute)
            sudo: True if command must be executed with sudo

        Returns:
            True or False if the process has successfully executed
        """
        command = ["sudo"] + command if sudo else command
        if not self.print_command(command, debug_type):
            return True
        try:
            # pylint: disable=subprocess-run-check
            proc = run(command, **kwargs, env=self.environ, stdout=DEVNULL, stderr=DEVNULL)
        except (CalledProcessError, FileNotFoundError):
            return False
        return proc.returncode == 0

    def kdt_run_str(self, command, debug_type=(False, True), sudo=False, **kwargs):
        """ Executes command and returns it's output

        Args:
            command: List of strings, where the first position is the actual command,
            and the rest are parameters
            debug_type: In debug mode (Print , Execute)
            sudo: True if command must be executed with sudo

        Returns:
            boolean for valid output
            stdout string
            stderr string
        """
        command = ["sudo"] + command if sudo else command
        if not self.print_command(command, debug_type):
            return True, "", ""
        try:
            # pylint: disable=subprocess-run-check
            proc = run(command, **kwargs, capture_output=True, env=self.environ)
        except FileNotFoundError:
            sys.exit("FAIL: " + ' '.join(command))
        except CalledProcessError as exception:
            sys.exit(exception.stderr.decode("utf-8"))
        return proc.returncode == 0, proc.stdout.decode("utf-8")[:-1], proc.stderr.decode("utf-8")[:-1]

    def make_pass(self, args):
        """ Passes the command directly to make

        Args:
            args: List of parameters for make
        """

        if not self.print_command(self.make_command + args, (True, False)):
            return True, "", ""

        if len(self.make_command) == 0:
            sys.exit("FAIL: Make command not set")
        try:
            run(self.make_command + args, env=self.environ, check=False)
        except FileNotFoundError:
            sys.exit("FAIL: " + ' '.join(self.make_command + args))

    def make(self, args):
        """ Executes make command

        Args:
            args: List of parameters for make
        """
        if len(self.make_command) == 0:
            sys.exit("FAIL: Make command not set")
        self.kdt_run(self.make_command + args, debug_type=(True, False), check=True)

    def make_str(self, args, debug_type=(True, True), **kwargs):
        """ Executes make command and returns it's output

        Args:
            args: List of parameters for make
            debug_type: In debug mode (Print , Execute)

        Returns:
            The string output of make
        """
        if len(self.make_command) == 0:
            sys.exit("FAIL: Make command not set")
        return self.kdt_run_str(self.make_command + args, debug_type=debug_type, **kwargs)

    def __run_current_command_check__(self, arguments, sudo=False, **kwargs):
        """ Executes command from folder cwd

        Args:
            arguments: List of string arguments for the current_command set
            sudo: True if this command needs to be executed by sudo

        Returns:
            True or False if the command has executed without issues
        """
        sudo_cmd = ["sudo"] if sudo else []
        command = sudo_cmd + self.current_command + arguments
        if not self.print_command(command, debug_type=(True, False)):
            return True
        try:
            run(command, check=True, stdout=PIPE, stderr=STDOUT, env=self.environ, **kwargs)
        except FileNotFoundError:
            sys.exit("FAIL: " + ' '.join(command))
        except CalledProcessError as exception:
            sys.exit(exception.output.decode("utf-8"))
        return True

    def __getattr__(self, item):
        if item in self.commands:
            self.current_command = self.commands[item]
            return self.__run_current_command_check__
        return None
