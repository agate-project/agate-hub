"""Small process helpers shared by preview.py and providers."""
import os
import signal
import time


def alive(pid):
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    try:  # a zombie child still answers kill(0); treat it as dead
        with open("/proc/%d/status" % int(pid)) as f:
            for line in f:
                if line.startswith("State:") and "Z" in line.split()[1]:
                    return False
    except OSError:
        pass
    return True


def kill(pid, wait=3.0):
    if not alive(pid):
        return True
    try:
        os.kill(int(pid), signal.SIGTERM)
    except OSError:
        return True
    end = time.time() + wait
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    try:
        os.kill(int(pid), signal.SIGKILL)
    except OSError:
        pass
    return not alive(pid)
