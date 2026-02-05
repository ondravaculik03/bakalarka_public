import getpass
import platform
import socket


def get_system_info():
    info = {}

    # Základní informace
    info["hostname"] = socket.gethostname()
    info["user"] = getpass.getuser()
    info["os"] = platform.system()
    info["os_version"] = platform.version()
    info["architecture"] = platform.machine()
    info["processor"] = platform.processor()

    return info
