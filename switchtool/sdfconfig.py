"""
An abbreviated set of utilities for using sdfconfig
for the core features of the switchtool gui.

This does not implement every feature from the older
netconfig module.

The netconfig tool is deprecated and pending removal
at time of writing.
"""

import subprocess


def get_host_for_mac(mac_addr: str) -> str:
    """
    Returns the hostname associated with a mac_addr
    
    Returns an empty string if the mac as not found.

    May raise if sdfconfig is not configured for the user.
    """
    try:
        return subprocess.check_output(
            ["sdfconfig", "search", "--brief", "--type", "mac", mac_addr],
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("sdfconfig is not configured for user") from exc


def get_desc_for_host(hostname: str) -> str:
    """
    Get the contents of the description field for hostname
    
    Returns an empty string if the description field hasn't been added yet,
    or if the host does not exist.

    May raise if sdfconfig is configured for the user.
    """
    try:
        info = subprocess.check_output(
            ["sdfconfig", "view", f"{hostname}.pcdsn"],
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("sdfconfig is not configured for user") from exc
    lines = info.split("\n")
    for line in lines:
        parts = line.split(":")
        if parts[0] == "Description":
            return ":".join(parts[1:]).strip()
    return ""


def get_subnet_for_host(hostname: str) -> str:
    """
    Get the contents of the subnet field for hostname.

    Returns an empty string if the host does not exist.

    May raise if sdfconfig is configured for the user.
    """
    try:
        info = subprocess.check_output(
            ["sdfconfig", "view", f"{hostname}.pcdsn"],
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("sdfconfig is not configured for user") from exc
    lines = info.split("\n")
    for line in lines:
        parts = line.split(":")
        if parts[0] == "Subnet Name":
            return ":".join(parts[1:]).strip()
    return ""