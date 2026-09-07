#!/usr/bin/env python3
"""
pass_persist backend for net-snmp (snmpd).

Serves a DCIM-style MIB under .1.3.6.1.4.1.99999 :

  .99999.1.1.1.i  index          (integer)   i = 1..8   TH table
  .99999.1.1.2.i  temperature    (integer, deci-C)
  .99999.1.1.3.i  humidity       (integer, %)

  .99999.2.1.1.i  index          (integer)   i = 1..12  contact table
  .99999.2.1.2.i  state          (integer, 1 = open, 2 = closed)

Install:
    sudo cp dcim_pass_persist.py /usr/local/bin/
    sudo chmod +x /usr/local/bin/dcim_pass_persist.py

Then in /etc/snmp/snmpd.conf:
    pass_persist .1.3.6.1.4.1.99999 /usr/local/bin/dcim_pass_persist.py

Replace read_values() with real data (file, socket, serial, /sys/class/hwmon...).
"""

import bisect
import random
import sys

BASE = ".1.3.6.1.4.1.99999"
N_TH = 8
N_CONTACT = 12


def oid_key(oid):
    """Numeric sort key so .10 sorts after .9, not after .1"""
    return tuple(int(x) for x in oid.strip(".").split("."))


def norm(oid):
    oid = oid.strip()
    return oid if oid.startswith(".") else "." + oid


def read_values():
    """Build the whole MIB snapshot. Swap the random values for real ones."""
    table = {}

    for i in range(1, N_TH + 1):
        temp_deci = int(round((22.0 + random.uniform(-2, 2)) * 10))
        hum = int(round(45 + random.uniform(-5, 5)))
        table[f"{BASE}.1.1.1.{i}"] = ("integer", i)
        table[f"{BASE}.1.1.2.{i}"] = ("integer", temp_deci)
        table[f"{BASE}.1.1.3.{i}"] = ("integer", hum)

    for i in range(1, N_CONTACT + 1):
        table[f"{BASE}.2.1.1.{i}"] = ("integer", i)
        table[f"{BASE}.2.1.2.{i}"] = ("integer", random.choice([1, 2]))

    return table


def respond(oid, typ, value):
    sys.stdout.write(f"{oid}\n{typ}\n{value}\n")
    sys.stdout.flush()


def respond_none():
    sys.stdout.write("NONE\n")
    sys.stdout.flush()


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        cmd = line.strip()

        if cmd == "PING":
            sys.stdout.write("PONG\n")
            sys.stdout.flush()
            continue

        if cmd in ("get", "getnext"):
            oid = norm(sys.stdin.readline())
            table = read_values()
            keys = sorted(table, key=oid_key)

            if cmd == "get":
                hit = oid if oid in table else None
            else:
                sorted_keys = [oid_key(k) for k in keys]
                idx = bisect.bisect_right(sorted_keys, oid_key(oid))
                hit = keys[idx] if idx < len(keys) else None

            if hit is None:
                respond_none()
            else:
                typ, val = table[hit]
                respond(hit, typ, val)
            continue

        if cmd == "set":
            sys.stdin.readline()  # oid
            sys.stdin.readline()  # type + value
            sys.stdout.write("not-writable\n")
            sys.stdout.flush()
            continue

        # unknown command -> ignore


if __name__ == "__main__":
    main()
