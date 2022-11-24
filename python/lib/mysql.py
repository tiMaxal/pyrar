#! /usr/bin/python3
# (c) Copyright 2019-2022, James Stevens ... see LICENSE for details
# Alternative license arrangements possible, contact me for more information
import sys
import os
import json

import lib.fileloader
from lib.log import log, init as log_init

from inspect import currentframe as czz, getframeinfo as gzz

from MySQLdb import _mysql
from MySQLdb.constants import FIELD_TYPE
import MySQLdb.converters

LOGINS_JSON = os.environ["BASE"] + "/etc/logins.json"
DATE_FIELDS = ["when_dt", "amended_dt", "created_dt", "deleted_dt"]

cnx = None
my_login = None

HEXLIB = "0123456789ABCDEF"


def ashex(line):
    ret = ""
    for item in line:
        asc = ord(item)
        ret = ret + HEXLIB[asc >> 4] + HEXLIB[asc & 0xf]
    return ret


def format_data(item, data):
    """ convert {data} to SQL string """
    if item in DATE_FIELDS:
        return "now()"

    if data is None:
        return "NULL"

    if isinstance(data, int):
        return str(int(data))

    if not isinstance(data, str):
        data = str(data)

    return "unhex('" + ashex(data) + "')"


def data_set(data, joiner):
    """ create list of `col=val` from dict {data}, joined by {joiner} """
    return joiner.join([item + "=" + format_data(item,data[item]) for item in data])


def sql_exec(sql):
    if cnx is None:
        log("MySQL not connected", gzz(czz()))
        return None, None

    try:
        cnx.query(sql)
        lastrowid = cnx.insert_id()
        affected_rows = cnx.affected_rows()
        cnx.store_result()
        cnx.commit()
        return affected_rows, lastrowid
    except Exception as exc:
        log(exc, gzz(czz()))
        return None, None


def sql_insert(table, data):
    return sql_exec(f"insert into {table} set " + data_set(data,","))


def sql_exists(table, data):
    sql = f"select 1 from {table} where " + data_set(data, " and ") + " limit 1"
    ret, __ = run_query(sql)
    return (ret is not None) and (cnx.affected_rows() > 0)


def sql_get_one(table, data):
    sql = f"select * from {table} where " + data_set(data, " and ") + " limit 1"
    ret, data = run_query(sql)
    return ret and (cnx.affected_rows() > 0), data[0]


def convert_string(data):
    if isinstance(data, bytes):
        return data.decode("utf8")
    return data


def convert_datetime(data):
    return data


my_conv = MySQLdb.converters.conversions.copy()
my_conv[FIELD_TYPE.VARCHAR] = convert_string
my_conv[FIELD_TYPE.CHAR] = convert_string
my_conv[FIELD_TYPE.STRING] = convert_string
my_conv[FIELD_TYPE.VAR_STRING] = convert_string
my_conv[FIELD_TYPE.DATETIME] = convert_datetime


def connect(login):
    """ Connect to MySQL based on ENV vars """

    global cnx
    global my_login

    my_login = login
    logins = lib.fileloader.FileLoader(LOGINS_JSON)
    mysql_json = logins.data()["pyrar"]

    conn = mysql_json["connect"]

    host = None
    port = None
    sock = ""

    if conn.find("/") >= 0:
        sock = conn
    else:
        host = conn
        port = 3306
        if conn.find(":") >= 0:
            svr = conn.split(":")
            host = svr[0]
            port = int(svr[1])

    cnx = _mysql.connect(user=login,
                         password=mysql_json[login],
                         unix_socket=sock,
                         host=host,
                         port=port,
                         database=mysql_json["database"],
                         conv=my_conv,
                         charset='utf8mb4',
                         init_command='set names utf8mb4')


def qry_worked(cnx):
    res = cnx.store_result()
    data = res.fetch_row(maxrows=0, how=1)
    return data


def run_query(sql):
    """ run the {sql}, reconnecting to MySQL, if necessary """
    global cnx
    try:
        cnx.query(sql)
        return True, qry_worked(cnx)

    except MySQLdb.OperationalError as exc:
        cnx.close()
        connect(my_login)
        try:
            cnx.query(sql)
            return True, qry_worked(cnx)

        except MySQLdb.OperationalError as exc:
            log(exc, gzz(czz()))
            cnx.close()
            cnx = None
            return False, None
        except MySQLdb.Error as exc:
            log(exc, gzz(czz()))
            return False, None

    except MySQLdb.Error as exc:
        log(exc, gzz(czz()))
        return False, None


def other_tests():
    print(
        data_set({
            "one": 1,
            "two": "22",
            "three": True,
            "four": "this is four",
            "five": None
        }))


if __name__ == "__main__":
    log_init(debug=True)

    connect("webui")

    ret, data = run_query("select * from events limit 3")
    if ret:
        print("ROWS:", cnx.affected_rows())
        print("ROWID:", cnx.insert_id())
        for r in data:
            print(">>>>", json.dumps(r, indent=4))

    print(f">>>> sql exists -> 10452 ->",
          sql_exists("events", {"event_id": 10452}))
    for e in ["james@jrcs.net", "aaa@bbb.com"]:
        print(f">>>> sql exists -> {e} ->",
              sql_exists("users", {"email": e} ))

    ret, data = sql_get_one("events", {"event_id": 10452})
    print(">>>>>", ret, json.dumps(data, indent=4))

    cnx.close()
