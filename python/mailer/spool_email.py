#! /usr/bin/python3
# (c) Copyright 2019-2023, James Stevens ... see LICENSE for details
# Alternative license arrangements possible, contact me for more information

import sys
import os
import json
import datetime
import tempfile

from librar.log import log, debug, init as log_init
from librar.policy import this_policy as policy
from librar import mysql as sql
from librar import registry
from librar import misc
from librar import hashstr

SPOOL_BASE = f"{os.environ['BASE']}/storage/perm/spooler"
ERROR_BASE = f"{os.environ['BASE']}/storage/perm/mail_error"
TEMPLATE_DIR = f"{os.environ['BASE']}/emails"

REQUIRE_FORMATTING = ["price_paid", "acct_current_balance"]


def format_currency(number, currency):
    num = number
    pfx = currency["symbol"]
    if num < 0:
        pfx += "-"
        num *= -1
    num = str(num)
    places = currency["decimal"]
    if len(num) < (places+1):
        num = ("000000000000000"+num)[(places+1)*-1:]
    neg_places = -1*places
    start = num[:neg_places]
    use_start = ""
    while len(start) > 3:
        use_start += currency["separator"][0]+start[-3:]
        start = start[:-3]
    if len(start) > 0:
        use_start = start+use_start

    return pfx+use_start+currency["separator"][1]+num[neg_places:]



def load_records(which_message, request_list):
    my_currency = policy.policy("currency")
    return_data = {"email": {"message": which_message}}
    for request in request_list:
        table = request[0]
        if table is None:
            return_data.update(request[1])
            continue

        ok, reply = sql.sql_select_one(table, request[1])

        if not ok or len(reply) <= 0:
            log(f"SPOOLER: Failed to load '{table}' where '{request[1]}'")
            return None

        for fmt in REQUIRE_FORMATTING:
            if fmt in reply:
                reply[fmt + "_fmt"] = format_currency(reply[fmt], my_currency)

        if table == "users":
            if not reply["email_verified"] and which_message != "verify_email":
                return None
            reply["hash_confirm"] = hashstr.make_hash(reply["created_dt"] + ":" + reply["email"])

        tag = request[3] if len(request) == 3 else table.rstrip("s")

        if table == "domains" and sql.has_data(reply, "name"):
            if (idn := misc.puny_to_utf8(reply["name"])) is not None:
                reply["display_name"] = idn
            else:
                reply["display_name"] = reply["name"]
            return_data["registry"] = registry.tld_lib.reg_record_for_domain(reply["name"])

        return_data[tag] = reply

    return return_data


def spool(which_message, request_list):
    pfx = f"{TEMPLATE_DIR}/{which_message}"
    if not os.path.isfile(f"{pfx}.txt") and not os.path.isfile(f"{pfx}.html"):
        log(f"Warning: No email merge file found for type '{which_message}'")
        return False

    if (request_data := load_records(which_message, request_list)) is None:
        return False

    with tempfile.NamedTemporaryFile("w+", encoding="utf-8", dir=SPOOL_BASE, delete=False,
                                     prefix=which_message + "_") as fd:
        fd.write(json.dumps(request_data))

    return True


def debug_formatter():
    def_cur = policy.policy("currency")
    cur = {
        "desc": "Etherium",
        "iso": "ETH",
        "separator": [",", "."],
        "symbol": "\u039E",
        "decimal": 6,
        }

    print(format_currency(int(sys.argv[1]),def_cur))
    print(format_currency(int(sys.argv[1]),cur))
    sys.exit(0)


if __name__ == "__main__":
    log_init(with_debug=True)
    # debug_formatter()
    sql.connect("engine")
    registry.start_up()
    # print("spool_email>>",spool_email("verify_email", [["domains", {"name": "xn--e28h.xn--dp8h"}], ["users", {"email": "dan@jrcs.net"}]]))
    spool("receipt", [[None, {
        "some-data": "value"
    }], ["sales", {
        "sales_item_id": 10535
    }], ["domains", {
        "domain_id": 10460
    }], ["users", {
        "user_id": 10450
    }]])