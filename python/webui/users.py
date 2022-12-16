#! /usr/bin/python3
# (c) Copyright 2019-2022, James Stevens ... see LICENSE for details
# Alternative license arrangements possible, contact me for more information
import secrets
import base64
import hashlib
import time
import os
import bcrypt

from lib import mysql as sql
from lib import validate
from lib.policy import this_policy as policy
from lib.log import log, debug, init as log_init

USER_REQUIRED = ["email", "password"]


def make_session_code(user_id):
    hsh = hashlib.sha256()
    hsh.update(secrets.token_bytes(500))
    hsh.update(str(user_id).encode("utf-8"))
    hsh.update(str(os.getpid()).encode("utf-8"))
    hsh.update(str(time.time()).encode("utf-8"))
    return base64.b64encode(hsh.digest()).decode("utf-8")


def make_session_key(session_code, user_agent):
    hsh = hashlib.sha256()
    hsh.update(session_code.encode("utf-8"))
    hsh.update(user_agent.encode("utf-8"))
    return base64.b64encode(hsh.digest()).decode("utf-8")


def secure_user_db_rec(data):
    for block in ["password", "payment_data", "two_fa"]:
        del data[block]


def start_session(user_db_rec, user_agent):
    user_id = user_db_rec['user_id']
    sql.sql_delete_one("session_keys", {"user_id": user_id})

    ses_code = make_session_code(user_id)
    sess_data = {"session_key": make_session_key(ses_code, user_agent), "user_id": user_id, "created_dt": None}

    ok, __ = sql.sql_insert("session_keys", sess_data)
    if not ok:
        return False, "Failed to start session"

    secure_user_db_rec(user_db_rec)
    return True, {"user_id": user_id, "user": user_db_rec, "session": ses_code}


def start_user_check(data):
    if data is None:
        return False, "Data missing"

    for item in USER_REQUIRED:
        if item not in data:
            return False, f"Missing data item '{item}'"

    if not validate.is_valid_email(data["email"]):
        return False, "Invalid email address"

    if "name" in data and not validate.is_valid_display_name(data["name"]):
        return False, "Invalid display name"

    return True, None


def register(data, user_agent):
    ok, msg = start_user_check(data)
    if not ok:
        return ok, msg

    if sql.sql_exists("users", {"email": data["email"]}):
        return False, "EMail address already in use"

    if ("name" not in data) or (data["name"] == "") or (data["name"] is None):
        data["name"] = data["email"].split("@")[0]

    all_cols = USER_REQUIRED + ["name", "created_dt"]
    data.update({col: None for col in all_cols if col not in data})

    data["password"] = bcrypt.hashpw(data["password"].encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    ok, user_id = sql.sql_insert("users", {item: data[item] for item in all_cols})
    if not ok:
        return False, "Registration insert failed"

    update_user_login_dt(user_id)
    ok, user_db_rec = sql.sql_select_one("users", {"user_id": user_id})
    if not ok:
        return False, "Registration retrieve failed"

    return start_session(user_db_rec, user_agent)


def check_session(ses_code, user_agent):
    if not validate.is_valid_ses_code(ses_code):
        return False, None

    key = make_session_key(ses_code, user_agent)
    tout = policy.policy('session_timeout')
    ok, data = sql.sql_select_one("session_keys", {"session_key": key},
                                  f"date_add(amended_dt, interval {tout} minute) > now() 'ok',user_id")

    if not ok:
        return False, None

    if "ok" not in data or not data["ok"]:
        sql.sql_delete_one("session_keys", {"session_key": key})
        return False, None

    sql.sql_update_one("session_keys", {}, {"session_key": key})

    return True, {"session": ses_code, "user_id": data["user_id"]}


def logout(ses_code, user_id, user_agent):
    ok = sql.sql_delete_one("session_keys", {
        "session_key": make_session_key(ses_code, user_agent),
        "user_id": user_id
    })
    if not ok:
        return False, "Logout failed"

    return True


def update_user_login_dt(user_id):
    sql.sql_update_one("users", {"last_login_dt": sql.now()}, {"user_id": int(user_id)})


def login(data, user_agent):
    ok, __ = start_user_check(data)
    if not ok:
        return False, None

    ok, user_db_rec = sql.sql_select_one("users", {"account_closed": 0, "email": data["email"]})
    if not ok:
        return False, None

    if not sql.has_data(user_db_rec, "password"):
        return False, None

    if user_db_rec["password"][:7] == "CLOSED:":
        return False, None

    encoded_pass = user_db_rec["password"].encode("utf8")
    enc_pass = bcrypt.hashpw(data["password"].encode("utf8"), encoded_pass)
    if encoded_pass != enc_pass:
        return False, None

    update_user_login_dt(user_db_rec['user_id'])
    log(f"USR-{user_db_rec['user_id']} logged in")
    return start_session(user_db_rec, user_agent)


USER_CAN_CHANGE = {
    "auto_renew_all": validate.validate_binary,
    "email": validate.is_valid_email,
    "name": validate.is_valid_display_name
}


def update_user(user_id, post_json):
    for item in post_json:
        if item not in USER_CAN_CHANGE or not USER_CAN_CHANGE[item](post_json[item]):
            return False, f"Invalid data item - '{item}'"

    ok, user_db_rec = sql.sql_select_one("users", {"user_id": user_id})
    if not ok:
        return False, "Failed to load user"

    if "email" in post_json and user_db_rec["email"] != post_json["email"]:
        post_json["email_verified"] = 0

    ok = sql.sql_update_one("users", post_json, {"user_id": user_id})
    if not ok:
        return False, "Failed to update user"

    ok, user_db_rec = sql.sql_select_one("users", {"user_id": user_id})
    if not ok:
        return False, "Failed to load user"

    return ok, user_db_rec


def check_password(user_id, data):
    if not sql.has_data(data, "password"):
        return False

    ok, user_db_rec = sql.sql_select_one("users", {"user_id": user_id})
    if not ok:
        return False

    encoded_pass = user_db_rec["password"].encode("utf8")
    enc_pass = bcrypt.hashpw(data["password"].encode("utf-8"), encoded_pass)

    return encoded_pass == enc_pass


if __name__ == "__main__":
    sql.connect("webui")
    log_init(with_debug=True)
    login_ok, login_data = login({"email": "flip@flop.com", "password": "aa"}, "curl/7.83.1")
    debug(">>> LOGIN " + str(login_ok) + "/" + str(login_data))
    # print(register({"email":"james@jrcs.net","password":"my_password"}))
    # print(register({"e-mail":"james@jrcs.net","password":"my_password"}))
    # print(make_session_code(100))
    # print(make_session_key("fred", "Windows"))
    debug(
        ">>>>SELECT " +
        str(sql.sql_select("session_keys", "1=1", "date_add(amended_dt, interval 60 minute) > now() 'ok',user_id")))
    debug(">>>> " + str(login_data["session"]))
    debug(">>>>CHECK-SESSION " + str(check_session(login_data["session"], "curl/7.83.1")))
