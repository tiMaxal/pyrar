#! /usr/bin/python3
# (c) Copyright 2019-2022, James Stevens ... see LICENSE for details
# Alternative license arrangements possible, contact me for more information
import os
import sys
import json
import httpx
import flask

from lib.providers import tld_lib
from lib.log import log, debug, init as log_init
from lib.policy import this_policy as policy
import users
from lib import mysql as sql
import domains

from inspect import currentframe as czz, getframeinfo as gzz

PYRAR_TAG = "X-Pyrar-Sess"
PYRAR_TAG_LOWER = "x-pyrar-sess"

log_init(policy.policy("facility_python_code"),
         with_logging=policy.policy("log_python_code"))

sql.connect("webui")
application = flask.Flask("EPP Registrar")


class WebuiReq:
    """ data unique to each request to keep different users data separate """
    def __init__(self):
        tld_lib.check_for_new_files()
        self.session = None
        self.user_id = 0
        self.headers = {
            item.lower(): val
            for item, val in dict(flask.request.headers).items()
        }
        self.user_agent = self.headers[
            "user-agent"] if "user-agent" in self.headers else "Unknown"

        if PYRAR_TAG_LOWER in self.headers:
            logged_in, user_data = users.check_session(
                self.headers[PYRAR_TAG_LOWER], self.user_agent)
            self.parse_user_data(logged_in, user_data)

        self.base_event = self.set_base_event()

    def parse_user_data(self, logged_in, user_data):
        if not logged_in or "session" not in user_data:
            return

        self.user_data = user_data
        self.session = self.user_data["session"]
        self.user_id = self.user_data['user']['user_id']
        debug(f"Logged in as {self.user_id}", gzz(czz()))

    def set_base_event(self):
        return {
            "from_where": flask.request.remote_addr,
            "user_id": self.user_id,
            "who_did_it": "webui"
        }

    def abort(self, data, err_no=400):
        return self.response({"error": data}, err_no)

    def response(self, data, code=200):
        resp = flask.make_response(data, code)
        if self.session is not None:
            resp.headers[PYRAR_TAG] = self.session
        return resp

    def event(self, data, frameinfo):
        data["program"] = frameinfo.filename.split("/")[-1]
        data["function"] = frameinfo.function
        data["line_num"] = frameinfo.lineno
        data["when_dt"] = None
        data.update(self.base_event)
        sql.sql_insert("events", data)


@application.route('/api/v1.0/config', methods=['GET'])
def get_config():
    req = WebuiReq()
    ret = {
        "providers": tld_lib.zone_send,
        "zones": tld_lib.return_zone_list(),
        "policy": policy.data()
    }
    return req.response(ret)


@application.route('/api/v1.0/zones', methods=['GET'])
def get_supported_zones():
    req = WebuiReq()
    return req.response(tld_lib.return_zone_list())


@application.route('/api/v1.0/hello', methods=['GET'])
def hello():
    req = WebuiReq()
    return req.response("Hello World\n")


@application.route('/api/v1.0/users/details', methods=['GET'])
def users_details():
    req = WebuiReq()
    if req.user_id == 0 or req.session is None:
        return req.abort("Not logged in")

    ret, user_data = sql.sql_select_one("users", {"user_id": req.user_id})
    debug(f"USER>>>> {ret} {user_data}", gzz(czz()))
    if not ret:
        return req.abort("User-Id not found")

    ret, doms = sql.sql_select("domains", {"user_id": req.user_id})
    debug(f"DOMS>>>> {ret} {doms}", gzz(czz()))
    if ret is None:
        return req.abort("Failed to load domains")

    data = {"session": req.session, "user": user_data, "domains": doms}

    return req.response(data)


@application.route('/api/v1.0/users/login', methods=['POST'])
def users_login():
    req = WebuiReq()
    if flask.request.json is None:
        return req.abort("No JSON posted")

    ret, data = users.login(flask.request.json, req.user_agent)
    if not ret or not data:
        return req.abort("Login failed")

    req.parse_user_data(ret, data)

    ret, doms = sql.sql_select("domains", {"user_id": req.user_id})
    if ret:
        data["domains"] = doms

    return req.response(data)


@application.route('/api/v1.0/users/logout', methods=['GET'])
def users_logout():
    req = WebuiReq()
    if not req.session:
        return req.abort("Not logged in")
    users.logout(req.session, req.user_id, req.user_agent)
    req.session = None
    return req.response("logged-out")


@application.route('/api/v1.0/users/register', methods=['POST'])
def users_register():
    req = WebuiReq()
    if flask.request.json is None:
        return req.abort("No JSON posted")

    ret, val = users.register(flask.request.json, req.user_agent)
    if not ret:
        return req.abort(val)

    debug("REGISTER " + str(val), gzz(czz()))

    user_id = val["user"]["user_id"]
    req.user_id = user_id
    req.session = val["session"]
    req.base_event["user_id"] = user_id
    req.event(
        {
            "user_id": user_id,
            "notes": "User registered",
            "event_type": "new_user"
        }, gzz(czz()))

    return req.response(val)


@application.route('/api/v1.0/domain/check', methods=['POST', 'GET'])
def rest_domain_price():
    req = WebuiReq()
    if flask.request.json is not None:
        dom = flask.request.json["domain"]
        if not isinstance(dom, str) and not isinstance(dom, list):
            return req.abort("Unsupported data type for domain")
    else:
        data = None
        if flask.request.method == "POST":
            data = flask.request.form
        if flask.request.method == "GET":
            data = flask.request.args
        if data is None or len(data) <= 0:
            return req.abort("No data sent")
        if (dom := data.get("domain")) is None:
            return req.abort("No domain sent")

    dom_obj = domains.DomainName(dom)

    if dom_obj.names is None:
        if dom_obj.err is not None:
            return req.abort(dom_obj.err)
        return req.abort("Invalid domain name")

    try:
        ret = domains.check_and_parse(dom_obj)
        return req.response(ret)
    except Exception as exc:
        debug(str(exc), gzz(czz()))
        return req.abort("Domain check failed")


if __name__ == "__main__":
    application.run()
    domains.close_epp_sess()
