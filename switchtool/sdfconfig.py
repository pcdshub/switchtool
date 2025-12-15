"""
An abbreviated set of utilities for using sdfconfig
for the core features of the switchtool gui.

This does not implement every feature from the older
netconfig module.

The netconfig tool is deprecated and pending removal
at time of writing.
"""

import functools
import subprocess


@functools.lru_cache(maxsize=1000)
def get_host_for_mac(mac_addr: str) -> str:
    """
    Returns the hostname associated with a mac_addr
    
    Returns an empty string if the mac as not found.

    May raise if sdfconfig is not configured for the user.
    """
    try:
        fqdn = subprocess.check_output(
            ["sdfconfig", "search", "--brief", "--type", "mac", mac_addr],
            universal_newlines=True,
        )
        return remove_domain(fqdn)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("sdfconfig is not configured for user") from exc


def get_desc_for_host(hostname: str) -> str:
    """
    Get the contents of the description field for hostname
    
    Returns an empty string if the description field hasn't been added yet,
    or if the host does not exist.

    May raise if sdfconfig is not configured for the user.
    """
    return sdfconfig_view(hostname)["description"]


def get_subnet_for_host(hostname: str) -> str:
    """
    Get the contents of the subnet field for hostname.

    Returns an empty string if the host does not exist.

    May raise if sdfconfig is not configured for the user.
    """
    return sdfconfig_view(hostname)["subnet_name"]


def remove_domain(fqdn: str) -> str:
    """
    Given a host entry expressed as a fully-qualified domain name, return the hostname.

    For example, my_host.pcdsn would become my_host.
    """
    parts = fqdn.split(".")
    return ".".join(parts[:-1])


@functools.lru_cache(maxsize=1000)
def sdfconfig_view(hostname: str) -> dict[str, str]:
    """
    Call sdfconfig view and parse as a dictionary.

    May raise if sdfconfig is not configured for the user.
    """
    try:
        info = subprocess.check_output(
            ["sdfconfig", "view", f"{hostname}.pcdsn"],
            universal_newlines=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("sdfconfig is not configured for user") from exc
    output = {}
    lines = info.split("\n")
    for line in lines:
        parts = line.strip().split(":")
        if len(parts) < 2:
            continue
        key = parts[0].lower().replace(" ", "_").strip()
        value = ":".join(parts[1:]).strip()
        output[key] = value
    return output
