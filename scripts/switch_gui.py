import argparse
import logging
import sys
from os import path

from PyQt5.QtWidgets import QApplication

import psnet.ui as switch_ui

"""
Launch Switch GUI
"""
CRED_FILE = "/cds/group/pcds/pyps/config/switchtool.cfg"


def read_creds():
    d = {}
    with open(CRED_FILE) as f:
        for l in f.readlines():
            ll = [x.strip() for x in l.split("=")]
            d[ll[0]] = ll[1]
    return d


def main():
    # Parse arguments
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-s", "--switch", type=str, help="Name of switch", required=True
    )

    parser.add_argument("-u", "--user", type=str, help="Username for switch login")

    parser.add_argument("-p", "--password", type=str, help="Password for switch login")

    parser.add_argument(
        "-t",
        "--timeout",
        type=float,
        help="Timeout for switch refresh (hours, default 1)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase stderr logging verbosity for each v",
    )

    kwargs = vars(parser.parse_args())
    if not kwargs.get("switch"):
        print("Use --switch argument to provide switch name")
        return None

    log = logging.getLogger("psnet.switch")
    stream = logging.StreamHandler()
    stream.setLevel(max(0, logging.WARNING - 10 * kwargs["verbose"]))
    log.addHandler(stream)
    creds = read_creds()

    # Launch GUI
    app = QApplication(sys.argv)
    tout = kwargs.get("timeout")
    if tout is None:
        tout = 1
    user = kwargs.get("user")
    if user is not None:
        creds["username"] = user
    pw = kwargs.get("password")
    if pw is not None:
        creds["password"] = pw

    widget = switch_ui.SwitchWidget(
        kwargs["switch"], user=creds["username"], pw=creds["password"], timeout=tout
    )
    widget.setWindowTitle(kwargs["switch"])
    widget.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
