#! /usr/bin/python3
# (c) Copyright 2019-2022, James Stevens ... see LICENSE for details
# Alternative license arrangements possible, contact me for more information

import os
import json
import subprocess
import tempfile
import argparse

DAYS = 3565
CA_BITS = 4096
KEY_BITS = 2048

REQUIRED_FILES = ["host.crt", "my_ca.pem", "host.key", "my_ca.key"]


def make_tlsa_json(injs):
    return make_tlsa(injs["fqdn"], injs["l"], injs["o"], injs["ou"], injs["st"], injs["c"])


def make_tlsa(fqdn, location, organization, organizational_unit, state, country):
    with tempfile.TemporaryDirectory() as tmpdir:

        host_conf = os.path.join(tmpdir, "host.conf")

        MAKE_CA_PRIV = ["openssl", "genrsa", "-out", os.path.join(tmpdir, "my_ca.key"), str(CA_BITS)]
        MAKE_CA_PUB = [
            "openssl", "req", "-x509", "-new", "-nodes", "-key",
            os.path.join(tmpdir, "my_ca.key"), "-sha256", "-days",
            str(DAYS), "-out",
            os.path.join(tmpdir, "my_ca.pem"), "-config", host_conf
        ]

        MAKE_HOST_KEY = ["openssl", "genrsa", "-out", os.path.join(tmpdir, "host.key"), str(KEY_BITS)]

        MAKE_HOST_CSR = [
            "openssl", "req", "-new", "-key",
            os.path.join(tmpdir, "host.key"), "-sha256", "-nodes", "-config", host_conf, "-out",
            os.path.join(tmpdir, "host.csr"), "-extensions", "v3_req"
        ]

        SIGN_HOST_KEY = [
            "openssl", "x509", "-req", "-in",
            os.path.join(tmpdir, "host.csr"), "-CA",
            os.path.join(tmpdir, "my_ca.pem"), "-CAkey",
            os.path.join(tmpdir, "my_ca.key"), "-CAcreateserial", "-out",
            os.path.join(tmpdir, "host.crt"), "-days",
            str(DAYS), "-sha256", "-extensions", "v3_req", "-extfile",
            os.path.join(tmpdir, "host.v3")
        ]

        lines = ["[ v3_req ]", "subjectAltName = @alt_names", "", "[alt_names]", f"DNS.1 = {fqdn}"]

        with open(os.path.join(tmpdir, "host.v3"), "w", encoding="utf-8") as fd:
            fd.write("\n".join(lines))

        lines = [
            "[req]", "req_extensions = v3_req", "distinguished_name = req_distinguished_name", "prompt = no", "",
            "[req_distinguished_name]", f"C = {country}", f"ST = {state}", f"L = {location}", f"O = {organization}",
            f"OU = {organizational_unit}", f"CN = {fqdn}", "", "[ v3_req ]", "", "basicConstraints = CA:FALSE",
            "keyUsage = nonRepudiation, digitalSignature, keyEncipherment", "subjectAltName = @alt_names", "",
            "[alt_names]", f"DNS.1 = {fqdn}"
        ]

        with open(host_conf, "w", encoding="utf-8") as fd:
            fd.write("\n".join(lines))

        for cmd in [MAKE_CA_PRIV, MAKE_CA_PUB, MAKE_HOST_KEY, MAKE_HOST_CSR, SIGN_HOST_KEY]:
            subprocess.run(cmd, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

        for file in REQUIRED_FILES:
            if not os.path.isfile(os.path.join(tmpdir, file)):
                print(f"ERROR: File '{os.path.join(tmpdir,file)}' did not get created")
                return False, None

        pem = []
        for file in ["host.crt", "host.key"]:
            with open(os.path.join(tmpdir, file), "r", encoding="utf-8") as fd:
                pem.extend([line.strip() for line in fd.readlines()])

        tlsa_dns = subprocess.run([
            "ldns-dane", "-c",
            os.path.join(tmpdir, "host.crt"), "-f",
            os.path.join(tmpdir, "my_ca.pem"), "create", fqdn, "443", "3", "1", "2"
        ],
                                  capture_output=True)
        ret_tlsa = {"pem": pem, "tlsa": tlsa_dns.stdout.decode('utf-8').strip().split()}

        return True, ret_tlsa


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='EPP Jobs Runner')
    parser.add_argument("-f", '--fqdn', required=True)
    parser.add_argument("-c", '--country', required=True)
    parser.add_argument("-l", '--location', required=True)
    parser.add_argument("-o", '--organization', required=True)
    parser.add_argument("-u", '--organizational-unit', required=True)
    parser.add_argument("-s", '--state', required=True)
    args = parser.parse_args()

    ok, reply = make_tlsa(args.fqdn, args.location, args.organization, args.organizational_unit, args.state,
                          args.country)
    print(json.dumps(reply, indent=3))
