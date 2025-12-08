#!/reg/g/pcds/pyps/conda/rhel6/envs/pcds/bin/python

###!/usr/bin/env python
import argparse
import logging
import re
import socket
import sys
import telnetlib
import time
from subprocess import CalledProcessError

import paramiko
from paramiko.ssh_exception import SSHException

from . import utils
from .settings import (
    ARISTA_HOST,
    CISCO_HOST,
    DIGI_HOST_IGNORE,
    HOST_IGNORE,
    LOG_CONF,
    MOXA_HOST_IGNORE,
)

LOG = logging.getLogger(LOG_CONF.get("logger_name", __name__))


class TelnetCommandRunner(object):
    def __init__(self, user, pw, enablepw, port, cmds, timeout=None, priv=False):
        self.user = user
        self.pw = pw
        self.port = port
        self.timeout = timeout
        self.cmds = cmds or []
        self.tn_prompt = "#> "
        self.lo_prompt = "login: "
        self.pw_prompt = "password: "
        self.newline_split = re.compile("\r?\n")
        self.cmd_list = [
            ("login: ", self.user),
            ("password: ", self.pw),
        ]
        for cmd in self.cmds:
            self.cmd_list.append((self.tn_prompt, cmd))
            self.cmd_list.append(("%s\r\n" % cmd, None))
        self.cmd_list.append((self.tn_prompt, "exit"))
        self.tn = telnetlib.Telnet()

    def run(self, host):
        """
        Runs the command on the passed list of hosts
        """
        output = ""

        try:
            self.tn.open(host, self.port, self.timeout)
            # Container for useful telnet output
            keep_next_out = False
            for prompt, reply in self.cmd_list:
                if reply is None:
                    cur_out = self.tn.read_until(prompt, 1)
                    keep_next_out = True
                else:
                    cur_out = self.tn.read_until(prompt)
                    if keep_next_out:
                        if cur_out.endswith(prompt):
                            cur_out = cur_out[: -len(prompt)]
                        # remove trailing \r is present
                        output += cur_out.rstrip("\r")
                        keep_next_out = False
                    self.tn.write("%s\n" % reply)

            return (0, output)

        finally:
            self.tn.close()


class CommandRunner(object):
    def __init__(
        self,
        user,
        pw,
        enablepw,
        port,
        cmds,
        prompt,
        terminator,
        timeout=None,
        private_key=False,
        priv=False,
    ):
        self.user = user
        self.pw = pw
        self.enablepw = enablepw
        self.port = port
        self.timeout = timeout
        self.private_key = private_key
        self.priv = priv
        self.cmds = cmds or []
        self.page_cont_pattern = re.compile(
            "--More--, next page: Space, next line: Return key, quit: Control-c"
        )
        self.prompt_temp = prompt
        self.prompt_pattern = None
        self.terminator = terminator
        self.recv_buf = 8192
        self.chan = None
        self.mode = ""
        self._config()
        self._rbuffer = None
        self.debug = False

    def _config(self):
        self.ssh = paramiko.SSHClient()
        self.ssh.load_system_host_keys()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def enter(self):
        pass

    def exit(self):
        self.exec_cmd("exit", False)

    """
    OK, we're running afoul of how paramiko does readline here.  It's
    very insistent on getting a newline, which is problematic for getting
    prompt.

    So instead... we use our own readline here.  We count on getting the
    prompt at the end of one of our big gulps of data.

    This has the issue that we get confused with the pagination, which
    tries to erase the line.

    Therefore, we define our own _recv, which does a recv and then gets
    rid of "^H followed by a number of " ^H^H" followed by " ^H".

    Then, we also have our own _readline, which does _recv and breaks
    the results into lines.  If there is nothing to read when we have
    a partial line, we just return the partial, assuming it's a prompt.
    """

    def _recv(self):
        d = self.chan.recv(self.recv_buf)
        if d[0] == 8:
            d = d[1:]
        while d[:3] == b" \b\b":
            d = d[3:]
        if d[:2] == b" \b":
            d = d[2:]
        return d

    def _readline(self):
        # If we don't have any data, try to read some!
        while self._rbuffer is None:
            if self.chan.recv_ready():
                self._rbuffer = self._recv()
            else:
                time.sleep(0.1)

        while True:
            # If there is a newline in our data, return the first chunk.
            try:
                idx = self._rbuffer.index(b"\n")
                r = self._rbuffer[0 : idx + 1].decode("utf-8")
                if idx == len(self._rbuffer):
                    self._rbuffer = None
                else:
                    self._rbuffer = self._rbuffer[idx + 1 :]
                if self.debug:
                    print("<<< %s" % r)
                return r
            except:
                # If there isn't a newline, try to read more.  If there
                # is no more, just return the partial line!
                didread = False
                for i in range(6):
                    if self.chan.recv_ready():
                        d = self._recv()
                        self._rbuffer += d
                        didread = True
                        break
                    else:
                        time.sleep(0.1)
                if not didread:
                    r = self._rbuffer.decode("utf-8")
                    self._rbuffer = None
                    if self.debug:
                        print("<<< %s" % r)
                    return r

    def exec_cmd(self, cmd, keepOutput=True):
        seen_echo = False
        seen_prompt = False
        if self.debug:
            print(">>> %s\\n" % cmd)
        self.chan.send("%s%s" % (cmd, self.terminator))
        output = ""

        while not seen_echo:
            line = self._readline()
            prompt_match = self.prompt_pattern.match(line.rstrip())
            if prompt_match and prompt_match.group("cmd") == cmd:
                self.mode = prompt_match.group("mode")
                seen_echo = True

        while not seen_prompt:
            line = self._readline()
            page_cont = self.page_cont_pattern.match(line)
            if page_cont:
                self.chan.send(" %s" % self.terminator)
                if self.debug:
                    print(">>> \\n")
            else:
                prompt_match = self.prompt_pattern.match(line)
                if self.debug and prompt_match:
                    print("prompt_match!")
                if prompt_match:
                    self.mode = prompt_match.group("mode")
                    seen_prompt = True
                else:
                    output += line
        self.chan.send(" %s" % self.terminator)
        if keepOutput:
            return output

    def run(self, host):
        """
        Runs the command on the passed list of hosts
        """
        # Sigh... now we want to actually see if our prompt is '>' or '#' and enable if needed!
        self.prompt_pattern = re.compile(self.prompt_temp % (host, "(?P<mode>[#>])"))
        output = ""

        # The connect seems to fail a lot.  Let's see if we can catch this at all
        # and retry?
        did_connect = False
        for i in range(5):
            try:
                self.ssh.connect(
                    host,
                    self.port,
                    self.user,
                    self.pw,
                    timeout=self.timeout,
                    look_for_keys=False,
                )
                did_connect = True
                break
            except:
                print("SSH connect failed, retry %d!" % i)
        if not did_connect:
            print("SSH connect failed, aborting!")
            sys.exit(0)

        try:
            self.chan = self.ssh.invoke_shell()

            self.enter()
            for cmd in self.cmds:
                output += self.exec_cmd(cmd)
            self.exit()
            return (self.chan.recv_exit_status(), output)
        finally:
            # If we close without this, we sometimes get SSHExceptions when
            # trying to reconnect. Get the exit status, then read everything from
            # the socket until it's closed or get EOF from switch - at this point
            # the connection should be closed and we should be able to reconnect
            try:
                sock = self.chan.get_transport().sock
                sock.settimeout(self.timeout)
                f = sock.makefile("rb")
                _ = f.read()
            except (OSError, socket.timeout) as e:
                # OSError - connection closed while reading from socket
                # socket.timeout - just timeout if we block for too long
                pass
            self.ssh.close()


class AristaCommandRunner(CommandRunner):
    def __init__(
        self,
        user,
        pw,
        enablepw,
        port,
        cmds,
        timeout=None,
        private_key=False,
        priv=False,
    ):
        super(AristaCommandRunner, self).__init__(
            user,
            pw,
            enablepw,
            port,
            cmds,
            "^%s(?:\.ARISTA)?%s(?P<cmd>.*)",
            "\n",
            timeout,
            private_key,
            priv,
        )
        self.cmds = self._fix_cmds()

    def _fix_cmds(self):
        new_cmds = []
        for cmd in self.cmds:
            new_cmds.append("%s | no-more" % cmd)
        return new_cmds


class CiscoCommandRunner(CommandRunner):
    def __init__(
        self,
        user,
        pw,
        enablepw,
        port,
        cmds,
        timeout=None,
        private_key=False,
        priv=False,
    ):
        super(CiscoCommandRunner, self).__init__(
            user,
            pw,
            enablepw,
            port,
            cmds,
            "^%s%s(?P<cmd>.*)",
            "\n",
            timeout,
            private_key,
            priv,
        )

    def enter(self):
        self.exec_cmd("terminal length 0", False)


class BrocadeCommandRunner(CommandRunner):
    def __init__(
        self,
        user,
        pw,
        enablepw,
        port,
        cmds,
        timeout=None,
        private_key=False,
        priv=False,
    ):
        super(BrocadeCommandRunner, self).__init__(
            user,
            pw,
            enablepw,
            port,
            cmds,
            "^SSH@%s(?:\([\w-]*\))?%s(?P<cmd>.*)",
            "\r\n",
            timeout,
            private_key,
            priv,
        )

    def exit(self):
        self.chan.send("exit%s" % self.terminator)
        # set a timeout incase switch never responds after first exit
        self.chan.settimeout(0.25)
        try:
            if not self.chan.exit_status_ready():
                self.chan.send("exit%s" % self.terminator)
        except socket.timeout:
            # if this timedout then its likely exited
            pass


class RuckusCommandRunner(CommandRunner):
    def __init__(
        self,
        user,
        pw,
        enablepw,
        port,
        cmds,
        timeout=None,
        private_key=False,
        priv=False,
    ):
        super(RuckusCommandRunner, self).__init__(
            user,
            pw,
            enablepw,
            port,
            cmds,
            "^SSH@%s(?:\([-/\w]*\))?%s(?P<cmd>.*)",
            "\n",
            timeout,
            private_key,
            priv,
        )

    def enter(self):
        # This doesn't seem to work.  If we do this, we freeze during the output.
        #     self.exec_cmd('skip', False)
        #
        if self.priv:
            # We do this only to get the mode.
            self.exec_cmd("show clock")
            if self.mode == ">":
                self.exec_cmd("enable %s" % self.enablepw)
                if self.mode != "#":
                    raise IOError("Bad enable password!")

    def exit(self):
        self.chan.send("exit%s" % self.terminator)
        # set a timeout incase switch never responds after first exit
        self.chan.settimeout(0.25)
        try:
            if not self.chan.exit_status_ready():
                self.chan.send("exit%s" % self.terminator)
        except socket.timeout:
            # if this timedout then its likely exited
            pass


def parse_cli():
    # Create the parser
    parser = argparse.ArgumentParser(
        description="A cli tool for running commands on Brocade, Cisco, and Arista switches or Digi PortServers/ConnectPorts."
    )

    subparsers = parser.add_subparsers(help="Available device types to run commands on")

    cisco_parser = subparsers.add_parser(
        "cisco", help="Runs commands on Cisco switches found in netconfig"
    )
    cisco_parser.set_defaults(
        dev="switches",
        func=utils.get_switch_list,
        cmd_run=CiscoCommandRunner,
        ignore=HOST_IGNORE,
        subset=CISCO_HOST,
    )

    cisco_parser.add_argument(
        "cmds", metavar="CMD", nargs="+", help="The commands to run on the switches"
    )

    brocade_parser = subparsers.add_parser(
        "brocade", help="Runs commands on Brocade switches found in netconfig"
    )
    brocade_parser.set_defaults(
        dev="switches",
        func=utils.get_switch_list,
        cmd_run=BrocadeCommandRunner,
        ignore=HOST_IGNORE,
        subset=None,
    )

    brocade_parser.add_argument(
        "cmds", metavar="CMD", nargs="+", help="The commands to run on the switches"
    )

    arista_parser = subparsers.add_parser(
        "arista", help="Runs commands on Arista switches found in netconfig"
    )
    arista_parser.set_defaults(
        dev="switches",
        func=utils.get_switch_list,
        cmd_run=AristaCommandRunner,
        ignore=HOST_IGNORE,
        subset=ARISTA_HOST,
    )

    arista_parser.add_argument(
        "cmds", metavar="CMD", nargs="+", help="The commands to run on the switches"
    )

    digi_parser = subparsers.add_parser(
        "digi",
        help="Runs commands on digi portservers or connectports found in netconfig",
    )
    digi_parser.set_defaults(
        dev="digi portservers",
        func=utils.get_digi_list,
        cmd_run=TelnetCommandRunner,
        ignore=DIGI_HOST_IGNORE,
        subset=None,
    )

    digi_parser.add_argument(
        "cmds", metavar="CMD", nargs="+", help="The commands to run on the digis"
    )

    # Add the default telnet options
    utils.add_telnet_opts(digi_parser)

    # Add the default ssh options
    utils.add_ssh_opts(cisco_parser)
    utils.add_ssh_opts(brocade_parser)
    utils.add_ssh_opts(arista_parser)

    # Add the default logger options
    utils.add_log_opts(parser)

    return parser.parse_args()


def main():
    # grab the command line opts
    args = parse_cli()
    passwd = args.pswd or utils.passwd_prompt(args.user)

    # set levels for loggers that we care about
    LOG.setLevel(utils.log_level_parse(args.log))

    # create the command runner
    LOG.debug(
        "Creating command runner with user: %s, pswd: %s, port: %s, cmds: %s",
        args.user,
        args.pswd,
        args.port,
        ", ".join(args.cmds),
    )

    if hasattr(args, "private_key"):
        cmd_run = args.cmd_run(
            args.user,
            passwd,
            args.port,
            args.cmds,
            timeout=args.timeout,
            private_key=args.private_key,
        )
    else:
        cmd_run = args.cmd_run(
            args.user, passwd, args.port, args.cmds, timeout=args.timeout
        )

    # if no hosts are specified try to get a list from netconfig
    if args.hosts is None:
        try:
            LOG.info("Attempting to retrieve a list of %s from netconfig:", args.dev)
            devices = args.func()
        except (OSError, CalledProcessError) as err:
            LOG.critical("Problem running netconfig: %s", err)
            return 1
        good_devices = [sw for sw in devices if sw not in args.ignore]
        num_sw = len(devices)
        num_sw_good = len(good_devices)
        LOG.info(
            "Found %d %s via netconfig, %d of which are in the ignore list",
            num_sw,
            args.dev,
            num_sw - num_sw_good,
        )
    else:
        good_devices = args.hosts
        num_sw_good = len(good_devices)

    fails = 0
    failed_hosts = []

    for host in good_devices:
        try:
            if args.subset is None or host in args.subset:
                LOG.info("Running command(s) %s on %s", ", ".join(args.cmds), host)
                status_code, output = cmd_run.run(host)
                if status_code == 0:
                    sys.stdout.write(output)
                    sys.stdout.flush()
                else:
                    LOG.warn("Commands returned non-zero status code")
                    sys.stderr.write(output)
                    sys.stderr.flush()
            else:
                LOG.warning(
                    "Not running command(s) %s on %s since device type does not match",
                    ", ".join(args.cmds),
                    host,
                )
        except (SSHException, socket.error) as err:
            fails += 1
            failed_hosts.append(host)
            LOG.error("Failure connecting to %s: %s", host, err)
            LOG.error("Skipping running command on %s", host)

    if fails != 0:
        LOG.error(
            "Running of the commands failed on %d of %d %s",
            fails,
            num_sw_good,
            args.dev,
        )
        LOG.error("%s with failures: %s", args.dev.capitalize(), failed_hosts)
        return 1


if __name__ == "__main__":
    try:
        # set the root logger since this is an entry point
        utils.log_init("%(levelname)s:%(message)s")
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
