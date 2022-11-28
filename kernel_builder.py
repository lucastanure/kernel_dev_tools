#!/usr/bin/env python3
""" Python script to help configure, build, and install modules, device trees and kernel image
    into embedded systems
"""
import sys
import argparse
import configparser
import tempfile
from os import path, walk, getcwd, listdir
from colorama import Fore, Style
import kdt_utils as kdt
from kdt_install import kdt_install
from git_format_patch import remove_change_id


def kernel_builder_configs():
    """ Reads kernel_builder configuration

    Returns:
        kdt_boards: Boards folder containing all boards configuration
        kdt_build: Build output folder
    """
    return_list = []
    kb_section = kdt.kdt_config_section("kernel_builder")
    if kb_section is not None:
        try:
            eclipse = kb_section.getboolean('kdt_eclipse')
        except ValueError:
            eclipse = kb_section['kdt_eclipse'] == "y"
        config_names = ["kdt_boards", "kdt_build"]
        for each in config_names:
            if each not in kb_section:
                sys.exit(f"Error! Configuration file missing \"{each}\"")
            return_list.append(kb_section[each])
        return return_list + [bool(eclipse)]
    kdt.print_blue("It seems you didn't install kdt yet. Let's do it now.")
    kdt_install()
    sys.exit(-1)


def available_configured_boards(boards_config):
    """ Reads configuration file and returns a list of board and their available arch

    Args:
        boards_config: Configuration file read by ConfigParser()

    Returns:
        Dictionary [board] = [archA, archB]
    """
    boards_arch = {}
    for board_section in boards_config.sections():
        board = board_section[:board_section.index('_')]
        arch = board_section[board_section.index('_') + 1:]
        if board in boards_arch:
            boards_arch[board].append(arch)
        else:
            boards_arch[board] = [arch]
    return boards_arch


class BoardConfig:
    """ Stores information for a particular board

    Stores build parameters for a particular board, like, the board name, architecture,
    kernel configuration, etc.
    Those parameters are later used by the kernel builder to configure, build and install the kernel
    into the target device.

    Attributes:
        build_params: Dictionary of build parameters
    """

    def __init__(self, boards_file, bash_env, kdt_boards):
        boards_config = configparser.ConfigParser()
        boards_config.read(boards_file)
        available_boards_arch = available_configured_boards(boards_config)
        self.build_params = {}

        # Check board selection
        if "board" not in bash_env:
            board_options = ' or '.join(available_boards_arch.keys())
            sys.exit(f"Error! Board not selected. Please select: {board_options}\n"
                     f"Example: export board={board_options[0]}")
        board_name = bash_env["board"]

        if board_name not in available_boards_arch:
            sys.exit(f"Error! Board {board_name} not configured")
        self.build_params['board_name'] = board_name

        # Set arch or select a default one
        self.set_arch(available_boards_arch, bash_env)

        # Select config for the kernel according to priority
        self.board_sect = boards_config[self.board_arch()]
        self.select_kernel_config(bash_env, self.board_sect, kdt_boards)

        # get board build params
        def get_board_config(name, mandatory=True):
            b_cfg = kdt.get_config(self.board_sect, name, mandatory)
            b_cfg = b_cfg.replace("~", bash_env["HOME"]).replace("$kdt_boards", kdt_boards)
            self.build_params[name] = b_cfg

        get_board_config('kernel_target')
        get_board_config('kernel_file')
        get_board_config('pkg_folder', False)
        get_board_config('ramfs_file', False)
        if bool(self.ramfs_file):
            get_board_config("update_ramfs")
        get_board_config('dtb_path', False)
        get_board_config('on', False)
        get_board_config('off', False)
        get_board_config('overlay_path', False)
        get_board_config("vendor", False)
        get_board_config('cc', False)
        get_board_config('cc_path', False)

        self.build_params['build_target'] = [self.kernel_target, "modules"]
        if bool(self.dtb_path) or bool(self.vendor) or bool(self.overlay_path):
            self.build_params['build_target'] += ["dtbs"]

    def __getattr__(self, name):
        return self.build_params[name]

    def set_arch(self, available_boards_arch, bash_env):
        """ Sets the arch defined by user or a default one (64 Bits)

        Args:
            available_boards_arch: Dictionary [board] = [archA, archB]
            bash_env: Bash environment variables
        """
        if "arch" in bash_env:
            exported_arch = bash_env["arch"]
            if exported_arch not in available_boards_arch[self.board_name]:
                sys.exit(f"Error! Arch \"{exported_arch}\" not configured for {self.board_name}")
            self.build_params['arch'] = exported_arch
        else:
            if len(available_boards_arch[self.board_name]) == 1:
                self.build_params['arch'] = available_boards_arch[self.board_name][0]
            else:
                if "x86_64" in available_boards_arch[self.board_name] or \
                        "x86" in available_boards_arch[self.board_name]:
                    self.build_params['arch'] = "x86_64"
                else:  # arm or arm64
                    self.build_params['arch'] = "arm64"

    def select_kernel_config(self, bash_env, board_section, kdt_boards):
        """ Selects the correct config based on priority 
            Exported configs takes precedence

        Args:
            bash_env: Bash variables section
            board_section: Board variables read from config file
            kdt_boards: Boards folder
        """
        config_target = kdt.get_config(bash_env, 'config_target', False)
        config_file = kdt.get_config(bash_env, 'config_file', False)
        config_gz = kdt.get_config(bash_env, 'config_gz', False)

        if bool(config_target) or bool(config_file) or bool(config_gz):  # anyone set?
            if not bool(config_target) ^ bool(config_file) ^ bool(config_gz):  # only one set
                sys.exit("Error! More than one kernel config is set")
            if bool(config_target):
                self.build_params["config_to_use"] = 'config_target'
                self.build_params['config_target'] = config_target
            if bool(config_file):
                self.build_params["config_to_use"] = 'config_file'
                if not path.exists(config_file):
                    sys.exit(f"Error! File {config_file} doesn't exist.")
                self.build_params['config_file'] = config_file
            if bool(config_gz):
                self.build_params["config_to_use"] = 'config_gz'
            return

        config_target = kdt.get_config(board_section, 'config_target', False)
        config_file = kdt.get_config(board_section, 'config_file', False)
        config_gz = kdt.get_config(board_section, 'config_gz', False)

        if bool(config_target) or bool(config_file) or bool(config_gz):  # anyone set?
            if not bool(config_target) ^ bool(config_file) ^ bool(config_gz):  # only one set
                sys.exit("Error! More than one kernel config is set")
            if bool(config_target):
                self.build_params["config_to_use"] = 'config_target'
                self.build_params['config_target'] = config_target
            if bool(config_file):
                self.build_params["config_to_use"] = 'config_file'
                config_file = config_file.replace("$kdt_boards", kdt_boards)
                if not path.exists(config_file):
                    sys.exit(f"Error! File {config_file} doesn't exist.")
                self.build_params['config_file'] = f"{config_file}"
            if bool(config_gz):
                self.build_params["config_to_use"] = 'config_gz'
            return
        sys.exit("Error! No config options are set.")

    def board_arch(self):
        """ Returns the expected string used in config file """
        return self.board_name + '_' + self.arch

    def is_x86(self):
        """ Is this an X86 / Intel / AMD build """
        return self.arch in ('x86_64', 'x86')

    def get_cross_compiler(self):
        """ Returns the cross-compiler path and the cross-compiler prefix """
        return self.build_params['cc_path'], self.build_params['cc']


class KernelBuilder:
    """ Stores information for Kernel Builder

    Stores build environment, tools, and configurations used to configure, build and install
    the kernel.

    Attributes:
        env: Dictionary of configuration for the builder
        board_config: Configuration for a particular board
    """

    def __init__(self, debug_enable=False):
        """ Init path and environment for the build """
        self.bash = kdt.BashCommands(debug_enable)
        self.env = {}
        self.env['kdt_boards'], build_path, self.env['eclipse_links'] = kernel_builder_configs()
        boards_file = f"{self.env['kdt_boards']}/boards_config"
        self.board_config = BoardConfig(boards_file, self.bash.environ, self.env['kdt_boards'])

        board_path = f"{build_path}/{self.board_config.board_name}"
        self.env['kernel_build_path'] = f"{board_path}/kernel"
        self.env['package_path'] = f"{board_path}/package"
        self.env['install_modules_path'] = f"{board_path}/install_modules"
        self.env['eclipse_include'] = f"{build_path}/eclipse_include"

        if not path.exists(self.kdt_boards):
            sys.exit("Error! Boards folder doesn't exist: " + self.kdt_boards)

        if debug_enable:
            print(f"export ARCH={self.board_config.arch}")

        if self.board_config.is_x86():
            self.bash.set_make(self.board_config.arch, self.kernel_build_path,
                               self.install_modules_path)
            cross_compiler_path, cross_compiler = "", ""
        else:
            cross_compiler_path, cross_compiler = self.board_config.get_cross_compiler()
            if debug_enable:
                print(f"export CROSS_COMPILE={cross_compiler}")
            self.bash.set_make(self.board_config.arch, self.kernel_build_path,
                               self.install_modules_path, cross_compiler)
        self.env['cc'] = cross_compiler

        new_path = self.__compiler_path(cross_compiler_path, cross_compiler)
        if new_path != "":
            self.bash.set_prefix_path(new_path)
            if debug_enable:
                print(f"export PATH={new_path}:$PATH\n")

        self.__check_build_paths()

    def __getattr__(self, name):
        return self.env[name]

    def __check_build_paths(self):
        """ Check if the necessary paths for building the kernel exists """
        if not path.exists(self.kernel_build_path):
            self.bash.kdt_run(["mkdir", "-p", self.kernel_build_path])
        if not path.exists(self.package_path):
            self.bash.kdt_run(["mkdir", "-p", self.package_path])
        if not path.exists(self.install_modules_path):
            self.bash.kdt_run(["mkdir", "-p", self.install_modules_path])

    def __compiler_path(self, cc_path, cc_prefix):
        """ Returns the cross-compiler path with ccache if exists

        Args:
            cc_path: Cross-Compiler Path
            cc_prefix: Cross-Compiler prefix
        """
        if cc_path != "":
            cc_path = f"{cc_path}/"

        gcc = [f"{cc_path}{cc_prefix}gcc", "--version"]
        if not self.bash.kdt_run(gcc):
            sys.exit(Fore.RED + "Error! Compiler not found" + Style.RESET_ALL)

        if not self.bash.kdt_run(["ccache", "--version"]):
            if self.board_config.is_x86():
                return ""
            return cc_path

        if self.board_config.is_x86():
            return "/usr/lib/ccache/bin/"

        ccache_dir = f"{cc_path}ccache"
        if not path.exists(ccache_dir):
            ccache = self.bash.kdt_run(["which", "ccache"], debug_type=(False, True))
            self.bash.kdt_run(["mkdir", ccache_dir])
            cc_link = ["ln", "-sf", ccache]
            self.bash.kdt_run(cc_link + [f"{cc_prefix}gcc"], cwd=ccache_dir)
            self.bash.kdt_run(cc_link + [f"{cc_prefix}g++"], cwd=ccache_dir)
            self.bash.kdt_run(cc_link + [f"{cc_prefix}cpp"], cwd=ccache_dir)
            self.bash.kdt_run(cc_link + [f"{cc_prefix}c++"], cwd=ccache_dir)
        return f"{ccache_dir}:{cc_path}"

    def __kernel_release(self):
        """ Returns the output of make kernelrelease from a kernel source """
        if not path.exists(f"{self.kernel_build_path}/include/config/auto.conf"):
            sys.exit("Configure the Kernel first")
        valid, version, _ = self.bash.make_str(["--no-print-directory", "kernelrelease"],
                                               debug_type=(False, True))
        kdt.print_blue(f"# Kernel Version: {Fore.MAGENTA}{version}")
        if valid:
            return version
        sys.exit("Fail to make kernelrelease")

    def __read_config(self):
        """ Outputs the contents of .config file """
        valid, text, _ = self.bash.kdt_run_str(["cat", f"{self.kernel_build_path}/.config"])
        if valid:
            return print(text)
        sys.exit("Fail to read .config")

    def __environment(self):
        """ Print the current board setup """
        padding = 18
        match self.board_config.config_to_use:
            case "config_file":
                config_type, config_name = "Config File:", f"{self.board_config.config_file}"
            case "config_target":
                config_type, config_name = "Config Target:", f"{self.board_config.config_target}"
            case "config_gz":
                config_type, config_name = "Config File:", "/proc/config.gz"
            case _:
                sys.exit("Error! No config set")

        print("Board:".ljust(padding), self.board_config.board_name)
        print("ARCH:".ljust(padding), self.board_config.arch)
        if self.cc:
            print("CROSS_COMPILE:".ljust(padding), self.cc)
        print("Build Path:".ljust(padding), self.kernel_build_path)
        print(config_type.ljust(padding), config_name)
        if bool(self.board_config.pkg_folder):
            print("Source PKGBUILD:".ljust(padding), self.board_config.pkg_folder)
            print("Build PKGBUILD:".ljust(padding), self.package_path)
        if self.board_config.is_x86():
            return
        # Only prints the first 2 paths on PATH and replace home by ~
        _path = ':'.join(self.bash.environ["PATH"].split(':')[:2])
        print("PATH:".ljust(padding), _path.replace(path.expanduser('~'), '~') + ":$PATH")

    def __eclipse_links(self, create):
        """ Create or Remove the header folder links used in Eclipse indexing

        Args:
            create: Create or remove the include links
        """
        if not self.eclipse_links:
            return

        slink = ["ln", "-sf"]
        mkdir = ["mkdir", "-p"]
        build_include = f"{self.kernel_build_path}/include"
        if self.board_config.arch == "x86_64":
            arch_include = "arch/x86/include"
        else:
            arch_include = f"arch/{self.board_config.arch}/include"
        build_arch_include = f"{self.kernel_build_path}/{arch_include}"

        if create:
            if not path.exists(f"{build_include}/generated/uapi"):
                self.bash.make(["modules_prepare"])

            # include/generated
            dest = f"{self.eclipse_include}/include"
            self.bash.kdt_run(mkdir + [dest])
            self.bash.kdt_run(slink + [f"{build_include}", f"{dest}/generated"])

            # arch/$ARCH/include/generated
            dest = f"{self.eclipse_include}/{arch_include}"
            self.bash.kdt_run(mkdir + [dest])
            self.bash.kdt_run(slink + [f"{build_arch_include}/generated", f"{dest}/generated"])
        else:
            remove = ["rm", "-rf"]
            self.bash.kdt_run(remove + [f"{self.eclipse_include}/include"])
            self.bash.kdt_run(remove + [f"{self.eclipse_include}/{arch_include}"])

    def __kernel_config_target(self, silent):
        """ Configure the kernel using a make target """
        cfg = self.board_config.config_target
        if not silent:
            kdt.print_blue(f"# Kernel config using {Fore.CYAN}{cfg}")
        self.bash.make([cfg])

    def __kernel_config_file(self, silent):
        """ Configure the kernel using a config file """
        if not silent:
            kdt.print_blue(f"# Kernel config using{Fore.CYAN} {self.board_config.config_file}")
        command = ["cp", self.board_config.config_file, f"{self.kernel_build_path}/.config"]
        self.bash.kdt_run(command, debug_type=(True, False))
        self.bash.make(["olddefconfig"])

    def __kernel_config_gz(self, silent):
        """ Configure the kernel using /proc/config.gz """
        proc_config_gz = "/proc/config.gz"
        if not silent:
            kdt.print_blue(f"# Kernel config using{Fore.CYAN} {proc_config_gz}")
        if not path.exists(proc_config_gz):
            sys.exit(f"Error!! {proc_config_gz} does not exist!")
        config_file = f"{self.kernel_build_path}/.config"
        with open(config_file, 'w', encoding="utf-8") as build_config:
            valid, text, _ = self.bash.kdt_run_str(["zcat", proc_config_gz])
            if not valid:
                return
            build_config.write(text)
            build_config.close()
            if self.bash.debug:
                print(f"zcat {proc_config_gz} > {config_file}")
            self.bash.make(["olddefconfig"])

    def __kernel_config(self, silent=False):
        """ Configure the kernel """
        config_options = {"config_file": self.__kernel_config_file,
                          "config_target": self.__kernel_config_target,
                          "config_gz": self.__kernel_config_gz}
        config_options[self.board_config.config_to_use](silent)
        self.__eclipse_links(True)

    def __kernel_make_build(self, warn=0, check=True):
        if warn:
            self.bash.add_make_argument(f"W={warn}")
        ret, _, stderr = self.bash.make_str(self.board_config.build_target,
                                            debug_type=(True, False), check=check)
        return ret, stderr

    def __kernel_build(self, package=False):
        """ Builds linux kernel as an Arch Linux Package or separated files

        Args:
            package: True to build the Arch Linux Package
        """
        if package:
            src_pack_dir = f"{self.board_config.pkg_folder}"
            kdt.print_blue(f"# Building Arch Linux package {Fore.MAGENTA}{src_pack_dir}/PKGBUILD")
            pkgbuild = f"{src_pack_dir}/PKGBUILD"
            if not path.exists(pkgbuild):
                sys.exit(f"Error! {pkgbuild} does not exist!")
            self.bash.disk_rsync([f"{src_pack_dir}/", self.package_path])

            make_arguments = self.bash.get_make_arguments()
            for item in make_arguments.copy():
                if "INSTALL_MOD_PATH" in item or "INSTALL_DTBS_PATH" in item:
                    make_arguments.remove(item)
            self.bash.export("KDT_MAKE_FLAGS", ' '.join(make_arguments))

            self.bash.export("KDT_KERNEL_BUILD", self.kernel_build_path)
            self.bash.export("KDT_KERNEL_SOURCE", getcwd())
            self.bash.export("ARCH", self.board_config.arch)
            self.bash.export("KDT_KERNEL_TARGET", self.board_config.kernel_target)
            self.bash.export("KDT_KERNEL_FILE", self.board_config.kernel_file)
            self.bash.export("KDT_DTB_PATH", self.board_config.dtb_path)
            self.bash.export("KDT_KERNEL_VERSION", self.__kernel_release())
            arch_makepkg = ["makepkg", "--skipchecksums", "--skippgpcheck", "-f"]
            self.bash.kdt_run_str(arch_makepkg, cwd=self.package_path, check=True,
                                  debug_type=(True, False))
            for zst_file in listdir(self.package_path):
                if zst_file.endswith(".zst"):
                    print("Package:", path.join(self.package_path, zst_file))
        else:
            kdt.print_blue("# Building the kernel")
            self.__kernel_make_build()
            kdt.print_blue("# Doing modules_install")
            self.bash.make(["modules_install"])

    def __network_copy_package(self, ip_addr):
        """ Copy linux package to the target and install it

        Args:
            ip_addr: Board IP address
        """
        target = f"root@{ip_addr}"
        arch_package = "linux-devel-1-0-any.pkg.tar.zst"
        self.bash.scp([f"{self.package_path}/{arch_package}", f"{target}:/root/"])
        self.bash.ssh([target, "pacman", "-U", "--noconfirm", arch_package])

    def __transfer_device_trees(self, func, target, sudo=False):
        """ Copy device trees and overlays to the target

        Args:
            func: Bash command used (scp, rsync)
            target: Files destination
            sudo: Executes sudo func
        """
        if not bool(self.board_config.dtb_path):
            return
        build_dts = f"{self.kernel_build_path}/arch/{self.board_config.arch}/boot/dts"
        if not path.exists(build_dts):
            sys.exit("Build the kernel first")

        kdt.print_blue("# Copying Device Trees")
        dtb_path = f"{target}/boot/{self.board_config.dtb_path}"
        if len(self.board_config.vendor) != 0:
            # raspberry pi requirement: copy the contents of the vendor to the target's boot folder
            func([f"{build_dts}/{self.board_config.vendor}/", dtb_path], sudo=sudo)
        else:
            _, folders, _ = next(walk(build_dts))
            for each in folders:
                if each != "overlays":
                    source = f"{build_dts}/{each}/"
                    destiny = f"{dtb_path}/{each}"
                    func([source, destiny], sudo=sudo)

        if bool(self.board_config.overlay_path):
            func([f"{build_dts}/overlays/", f"{target}/boot/{self.board_config.overlay_path}"],
                 sudo=sudo)

    def __transfer_modules(self, func, version, target, sudo=False):
        """ Copy Modules to the target

        Args:
            func: Bash command used (scp, rsync)
            version: Kernel version. The output of make kernel release
            target: Files destination
            sudo: Executes sudo func
        """
        kdt.print_blue("# Copying Modules")
        return func([f"{self.install_modules_path}/lib/modules/{version}",
                     f"{target}/lib/modules"], sudo=sudo)

    def __update_ramfs(self, target, version, output_file):
        """ Creates the initial Ram Disk

        Args:
            target: root@IP
            version: Linux Kernel Version
            output_file: Output file for initramfs
        """
        kdt.print_blue("# Update initramfs")
        # mkinitcpio -k ${_version} -g /boot/initramfs-${_version}.img
        #  -k /boot/vmlinuz-linux -c /etc/mkinitcpio.conf -g /boot/initramfs-linux.img

        ramfs_command = self.board_config.update_ramfs
        if not bool(ramfs_command):
            sys.exit("Error! No ramfs update command configured.")
        ramfs_command = ramfs_command.replace("$version", version)
        ramfs_command = ramfs_command.replace("$ramfs_file", f"/boot/{output_file}")
        return self.bash.ssh([target] + ramfs_command.split(" "))

    def __transfer_kernel(self, func, target, sudo=False):
        """ Copy Modules to the target

        Args:
            func: Bash command used (scp, rsync)
            target: Files destination
            sudo: Executes sudo func
        """
        kdt.print_blue("# Copying kernel")
        kernel_img = self.board_config.kernel_target
        source = f"{self.kernel_build_path}/arch/{self.board_config.arch}/boot/{kernel_img}"
        return func([source, f"{target}/boot/{self.board_config.kernel_file}"], sudo=sudo)

    def __network_copy(self, ip_addr, package=False, ramfs=False):
        """ Copy Kernel Image, Device Trees and Modules to the device
            OR
            Copy the linux package and install it

        Args:
            ip_addr: Board IP address
            package: True to copy the Arch Linux package instead of separated binaries'
            ramfs: Update ramfs. Only needed for big changes in kernel or version jumps
        """
        self.bash.kdt_run(["rsync", "--version"], check=True)
        self.bash.kdt_run(["ping", "-c", "1", ip_addr], check=True)

        target = f"root@{ip_addr}"
        if package:
            self.__network_copy_package(ip_addr)
        else:
            version = self.__kernel_release()
            self.__transfer_modules(self.bash.net_rsync, version, f"{target}:")
            self.__transfer_kernel(self.bash.scp, f"{target}:")
            self.__transfer_device_trees(self.bash.net_rsync, f"{target}:")
            if ramfs:
                if self.board_config.ramfs_file != "":
                    self.__update_ramfs(target, version, self.board_config.ramfs_file)
                else:
                    sys.exit("Error! No ramfs file defined.")

    def __local_copy(self, folder, version, sudo):
        """ Copy Kernel Image, Device Trees and Modules to a folder

            Args:
                folder: Destination folder
                version: kernel version
                sudo: True if it requires sudo
        """
        self.__transfer_modules(self.bash.disk_rsync, version, f"{folder}", sudo=sudo)
        self.__transfer_kernel(self.bash.disk_rsync, f"{folder}", sudo=sudo)
        self.__transfer_device_trees(self.bash.disk_rsync, f"{folder}", sudo=sudo)
        self.bash.kdt_run(["sync"], check=True)

    def __disk_copy(self, dest):
        """ Copy Kernel Image, Device Trees and Modules to a disk or folder

        Args:
            dest: Device's, Folder or Image destination path
        """
        version = self.__kernel_release()
        if "/dev/" in dest or path.isfile(dest):
            with tempfile.TemporaryDirectory() as mount_point:
                root, boot = kdt.disk_mount(dest, mount_point, self.bash)
                if not root:
                    sys.exit(f"Fail to mount root partition of {dest}")
                self.__local_copy(mount_point, version, True)
                kdt.disk_umount(mount_point, boot, self.bash)
        else:
            self.__local_copy(dest, version, False)

    def __power(self, power_on):
        """ Power On/Off board """
        if power_on:
            power_cmd = self.board_config.on
        else:
            power_cmd = self.board_config.off
        power_cmd = ' '.join(power_cmd.split()).split(' ')
        self.bash.kdt_run(power_cmd, check=True)

    def __print_board_section(self):
        """ Prints the entire board section inside boards config file """
        for param, value in self.board_config.board_sect.items():
            print(f"{param.ljust(15)} = {value}")

    def __build_check_files(self, patches_folder):
        """ Build the Kernel with W=1 and checks patch files inside patches_folder

        Args:
            patches_folder: Destination folder for patches files
        """
        print(f"check_files {patches_folder}")

    def __build_check_commits(self, patches):
        """ Build the Kernel with W=1 and checks the previous N patches or a folder containing
            patches

        Args:
            patches: A number of patches or destination folder for patches files
        """

        def kdt_run_str(_cmd, check):
            return self.bash.kdt_run_str(_cmd, check=check, debug_type=(False, False))

        _, stdout, _ = kdt_run_str(["git", "branch"], True)
        stdout = stdout.split('\n')
        branch_name = ""
        for branch in stdout:
            if '*' in branch:
                branch_name = branch[2:]

        has_warnings = 0
        patches += 1
        _, stdout, _ = kdt_run_str(["git", "log", "--oneline", f"-{patches}"], True)
        patches = stdout.split('\n')
        patches.reverse()  # Start by the oldest patch

        # Checkout the base patch and build with W=1
        # A Warning here is not relevant
        cmd = ["git", "checkout", f"{patches[0][:12]}"]
        kdt_run_str(cmd, True)
        self.__kernel_config(silent=True)
        build_ret, build_stderr = self.__kernel_make_build(warn=1)
        if not build_ret:
            print(build_stderr)
            sys.exit(f"Can't build patch {patches[0]}")

        # Check all the remaining patches
        for patch in patches[1:]:
            kdt_run_str(["git", "checkout", f"{patch[:12]}"], True)
            self.__kernel_config(silent=True)
            build_ret, build_stderr = self.__kernel_make_build(warn=1, check=False)
            if not build_ret:
                print(build_stderr)
                print(f"{Fore.RED}Error! Can't build patch {Fore.MAGENTA}{patch}{Style.RESET_ALL}")
                break
            _, patch_name, _ = kdt_run_str(["git", "format-patch", "-1", "-o", "/tmp/"], True)
            remove_change_id(patch_name)
            ret, check_output, _ = kdt_run_str(["./scripts/checkpatch.pl", patch_name], False)
            if not ret or "warning:" in build_stderr:
                kdt.print_red_blue("# Bad ", patch)
                if "warning:" in build_stderr:
                    kdt.print_magenta("## Build Output ##\n")
                    print(build_stderr)
                if not ret:
                    kdt.print_magenta("## Checkpatch Output ##\n")
                    end = check_output.index("\n", check_output.index("total:"))
                    print(check_output[:end], end='')
                print("\n")
                has_warnings = 1
            else:
                kdt.print_green_blue("# Good ", patch)

        if bool(branch_name):
            kdt_run_str(["git", "checkout", branch_name], True)
        sys.exit(has_warnings)

    def __build_check(self, patches):
        """ Build the Kernel with W=1 and checks the previous N patches or a folder containing
            patches

        Args:
            patches: A number of patches or destination folder for patches files
        """
        try:
            patches = int(patches)
        except ValueError:
            if not path.exists(patches):
                sys.exit(f"Error! Can't check {patches}")
            self.__build_check_files(patches)
        else:
            self.__build_check_commits(patches)

    def builder_command(self, namespace):
        """ Execute a kernel builder internal command

        Args:
            namespace: Argparse namespace
        """
        match namespace.cmd:
            case "cfg":
                self.__read_config()
            case "env":
                self.__environment()
            case "build":
                self.__kernel_build(namespace.pack)
            case "scp":
                self.__network_copy(namespace.ip, namespace.pack, namespace.ramfs)
            case "cp":
                self.__disk_copy(namespace.path)
            case "config":
                self.__kernel_config()
            case "off":
                self.__power(False)
            case "on":
                self.__power(True)
            case "section":
                self.__print_board_section()
            case "check":
                self.__build_check(namespace.patches)
            case _:
                sys.exit(f"Error! Invalid command: {namespace.cmd}")

    def make_command(self, command):
        """ Pass the command directly to make using the correct environment and print """
        if len(command) == 0:
            return
        self.__eclipse_links(False)
        if not self.bash.make_pass(command):
            sys.exit(-1)
        self.__eclipse_links(True)


def command_line():
    """ Argparse command line configuration """
    cmd_parser = argparse.ArgumentParser(description="Linux Kernel builder tool.")
    _desc = "One of the following commands or a make target that will be passed directly " \
            "to make using the internal parameters for the build"
    subparsers = cmd_parser.add_subparsers(dest='cmd', required=True, description=_desc)

    _desc = "Configure the kernel\n\n" + \
            "export config_file=CONFIG            To use CONFIG file to configure the kernel. " \
            "CONFIG will be copied to .config and olddefconfig will be executed.\n" + \
            "export config_target=CONFIG          Uses make CONFIG to configure the kernel.\n" + \
            "export config_gz                     Uses /proc/config.gz to configure the kernel." \
            "The /proc/config.gz will be copied to .config and olddefconfig will be executed."
    subparsers.add_parser('config', help="Configure the kernel", description=_desc,
                          formatter_class=argparse.RawTextHelpFormatter)

    _desc = "Copy Kernel, DTS and Modules to target and reboot"
    scp = subparsers.add_parser('scp', help=_desc, description=_desc)
    scp.add_argument("ip", type=str, help="Device's IP address")
    scp.add_argument("-p", "--pack", action="store_true", default=False,
                     help="Install a Arch Linux package instead")
    scp.add_argument("-r", "--ramfs", action="store_true", default=False,
                     help="Update initramfs")

    _desc = "Copy Kernel, DTS and Modules to a SD Card, disk image or a folder"
    _cp = subparsers.add_parser('cp', help=_desc, description=_desc)
    _cp.add_argument("path", type=str, help="Device's path (/dev/sdX), an disk image or a folder")

    _desc = "Output the Kernel config being used"
    subparsers.add_parser('cfg', help=_desc, description=_desc)

    _desc = "Power Off the board"
    subparsers.add_parser('off', help=_desc, description=_desc)

    _desc = "Power On the board"
    subparsers.add_parser('on', help=_desc, description=_desc)

    _desc = "Build the kernel"
    build = subparsers.add_parser('build', help=_desc, description=_desc)
    build.add_argument("-p", "--pack", action="store_true", default=False,
                       help="Build a Arch Linux package instead")

    _desc = "Check Kernel Build warnings"
    check = subparsers.add_parser('check', help=_desc, description=_desc)
    check.add_argument("patches", type=str, help="Number of patches or a folder containing patches")

    _desc = "Print build environment"
    subparsers.add_parser('env', help=_desc, description=_desc)

    _desc = "Print board configuration section"
    subparsers.add_parser('section', help=_desc, description=_desc)

    for choice in subparsers.choices.values():
        choice.add_argument("-d", "--debug", action="store_true", default=False,
                            help="Print all commands being executed")

    return list(subparsers.choices.keys()) + ["-h", "--help"], cmd_parser


def main():
    """ Main function """
    # If the make command is not in choices pass it directly to make
    cmd_choices, parser = command_line()
    if len(sys.argv) == 1:
        return parser.parse_args()
    if sys.argv[1] in cmd_choices:
        args = parser.parse_args()
        kernel_builder = KernelBuilder(args.debug)
        kernel_builder.builder_command(args)
    else:
        cmd_debug = False
        cmd_start = 1
        if sys.argv[1] == "-d":
            cmd_debug = True
            cmd_start += 1
        kernel_builder = KernelBuilder(cmd_debug)
        kernel_builder.make_command(sys.argv[cmd_start:])


if __name__ == "__main__":
    main()
