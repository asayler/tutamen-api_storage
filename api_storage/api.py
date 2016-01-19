#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Andy Sayler
# Copyright 2015


### Imports ###
import functools
import uuid
import datetime

import flask
import flask.ext.httpauth
import flask.ext.cors

from pcollections import drivers
from pcollections import backends

from pytutamen_server import constants
from pytutamen_server import utility
from pytutamen_server import datatypes
from pytutamen_server import storage

from . import exceptions
from . import config


### Constants ###

_KEY_CACERT = "cacert"
_KEY_SIGKEY = "sigkey"

_KEY_COLLECTIONS = "collections"
_KEY_SECRETS = "secrets"

_TOKENS_HEADER = 'tutamen-tokens'
_TOKENS_DELIMINATOR = ':'


### Global Setup ###

app = flask.Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.debug = False
cors = flask.ext.cors.CORS(app, headers=["Content-Type", "Authorization"])
sigkey_manager = utility.SigkeyManager()


### Logging ###

if not app.testing:

    import logging
    import logging.handlers

    loggers = [app.logger, logging.getLogger('pytutamen_server')]

    formatter_line = logging.Formatter('%(levelname)s: %(module)s - %(message)s')
    formatter_line_time = logging.Formatter('%(asctime)s %(levelname)s: %(module)s - %(message)s')

    # Stream Handler
    handler_stream = logging.StreamHandler()
    handler_stream.setFormatter(formatter_line)
    handler_stream.setLevel(logging.DEBUG)

    # File Handler
    # if not os.path.exists(_LOGGING_PATH):
    #     os.makedirs(_LOGGING_PATH)
    # logfile_path = "{:s}/{:s}".format(_LOGGING_PATH, "api.log")
    # handler_file = logging.handlers.WatchedFileHandler(logfile_path)
    # handler_file.setFormatter(formatter_line_time)
    # if app.debug:
    #     handler_file.setLevel(logging.DEBUG)
    # else:
    #     handler_file.setLevel(logging.INFO)

    for logger in loggers:
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler_stream)
    #    logger.addHandler(handler_file)


### Setup/Teardown ###

@app.before_request
def before_request():

    flask.g.pdriver = drivers.RedisDriver(db=config.REDIS_DB)
    flask.g.pbackend = backends.RedisAtomicBackend(flask.g.pdriver)
    flask.g.srv_ss = storage.StorageServer(flask.g.pbackend, create=False)

@app.teardown_request
def teardown_request(exception):
    pass


### Auth Decorators ###

def get_tokens():

    def _decorator(func):

        @functools.wraps(func)
        def _wrapper(*args, **kwargs):

            tokens = flask.request.headers.get(_TOKENS_HEADER, "")

            if not tokens:
                msg = "Client sent blank or missing token header"
                app.logger.warning(msg)
                raise exceptions.TokensError(msg)

            tokens = tokens.split(_TOKENS_DELIMINATOR)
            app.logger.debug("tokens = {}".format(tokens))

            if not tokens:
                msg = "Client sent no parsable tokens"
                app.logger.warning(msg)
                raise exceptions.TokensError(msg)

            flask.g.tokens = tokens

            # Call Function
            return func(*args, **kwargs)

        return _wrapper

    return _decorator

### Endpoints ###

## Root Endpoints ##

@app.route("/", methods=['GET'])
def get_root():

    app.logger.debug("GET ROOT")
    return app.send_static_file('index.html')

## Storage Endpoints ##

@app.route("/{}/".format(_KEY_COLLECTIONS), methods=['POST'])
@get_tokens()
def post_collections():

    app.logger.debug("POST COLLECTIONS")

    # Verify Tokens
    objperm = constants.PERM_SRV_COL_CREATE
    objtype = constants.TYPE_SRV
    remaining = list(config.AC_SERVERS)
    cnt = 0
    for token in flask.g.tokens:
        server = utility.verify_auth_token(token, remaining, objperm, objtype,
                                           manager=sigkey_manager)
        if server:
            msg = "Verifed token '{}' via server '{}'".format(token, server)
            app.logger.debug(msg)
            remaining.remove(server)
            cnt += 1
    if cnt < config.AC_REQUIRED:
        msg = "Failed to verify enough tokens: {} of {}".format(cnt, config.AC_REQUIRED)
        app.logger.warning(msg)
        raise exceptions.TokensError(msg)
    else:
        msg = "Verified {} tokens".format(cnt)
        app.logger.debug(msg)

    # Parse JSON
    json_in = flask.request.get_json(force=True)
    app.logger.debug("json_in = '{}'".format(json_in))
    uid = json_in.get('uid', None)
    app.logger.debug("uid = '{}'".format(uid))
    userdata = json_in.get('userdata', {})
    app.logger.debug("userdata = '{}'".format(userdata))
    ac_servers = json_in.get('ac_servers')
    app.logger.debug("ac_servers = '{}'".format(ac_servers))
    ac_required = json_in.get('ac_required', len(ac_servers))
    app.logger.debug("ac_required = '{}'".format(ac_required))

    # Create Collection
    col = flask.g.srv_ss.collections.create(key=uid, userdata=userdata,
                                            ac_servers=ac_servers, ac_required=ac_required)
    app.logger.debug("col.key = '{}'".format(col.key))

    # Return UUID
    json_out = {_KEY_COLLECTIONS: [col.key]}
    return flask.jsonify(json_out)

@app.route("/{}/<col_uid>/{}/".format(_KEY_COLLECTIONS, _KEY_SECRETS), methods=['POST'])
@get_tokens()
def post_collections_secrets(col_uid):

    app.logger.debug("POST COLLECTIONS SECRETS")
    app.logger.debug("col_uid = '{}'".format(col_uid))
    col = ss.collections_get(key=col_uid)

    json_in = flask.request.get_json(force=True)
    app.logger.debug("json_in = '{}'".format(json_in))

    sec_uid = json_in.get('uid', None)
    app.logger.debug("sec_uid = '{}'".format(sec_uid))
    userdata = json_in.get('userdata', {})
    app.logger.debug("userdata = '{}'".format(userdata))
    data = json_in.get('data')
    app.logger.debug("data = '{}'".format(data))

    sec = col.secrets.create(key=sec_uid, data=data, userdata=userdata)
    app.logger.debug("sec.key = '{}'".format(sec.key))
    json_out = {_KEY_SECRETS: [sec.key]}
    return flask.jsonify(json_out)

@app.route("/{}/<col_uid>/{}/<sec_uid>/versions/latest/".format(_KEY_COLLECTIONS, _KEY_SECRETS),
           methods=['GET'])
@get_tokens()
def get_collections_secret_versions_latest(col_uid, sec_uid):

    app.logger.debug("GET COLLECTIONS SECRET VERSIONS LATEST")
    col = ss.collections.get(key=col_uid)
    app.logger.debug("col.key = '{}'".format(col.key))
    sec = col.secrets.get(key=sec_uid)
    app.logger.debug("sec.key = '{}'".format(sec.key))

    json_out = {'data': sec.data, 'userdata': sec.userdata}
    return flask.jsonify(json_out)


### Error Handling ###

# @app.errorhandler(KeyError)
# def bad_key(error):
#     err = { 'status': 400,
#             'message': "{}".format(error) }
#     app.logger.info("Client Error: KeyError: {}".format(err))
#     res = flask.jsonify(err)
#     res.status_code = err['status']
#     return res

# @app.errorhandler(ValueError)
# def bad_value(error):
#     err = { 'status': 400,
#             'message': "{}".format(error) }
#     app.logger.info("Client Error: ValueError: {}".format(err))
#     res = flask.jsonify(err)
#     res.status_code = err['status']
#     return res

# @app.errorhandler(TypeError)
# def bad_type(error):
#     err = { 'status': 400,
#             'message': "{}".format(error) }
#     app.logger.info("Client Error: TypeError: {}".format(err))
#     res = flask.jsonify(err)
#     res.status_code = err['status']
#     return res

@app.errorhandler(datatypes.ObjectExists)
def object_exists(error):
    err = { 'status': 409,
            'message': "{}".format(error) }
    app.logger.info("Client Error: ObjectExists: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res

@app.errorhandler(datatypes.ObjectDNE)
def object_exists(error):
    err = { 'status': 404,
            'message': "{}".format(error) }
    app.logger.info("Client Error: Object Does Not Exist: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res

@app.errorhandler(exceptions.TokensError)
def bad_tokens(error):
    err = { 'status': 401,
            'message': "{}".format(error) }
    app.logger.info("Client Error: TokensError: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res

@app.errorhandler(400)
def bad_request(error=False):
    err = { 'status': 400,
            'message': "Malformed request" }
    app.logger.info("Client Error: 400: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res

@app.errorhandler(401)
def not_authorized(error=False):
    err = { 'status': 401,
            'message': "Not Authorized" }
    app.logger.info("Client Error: 401: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res

@app.errorhandler(404)
def not_found(error=False):
    err = { 'status': 404,
            'message': "Not Found: {}".format(flask.request.url) }
    app.logger.info("Client Error: 404: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res

@app.errorhandler(405)
def bad_method(error=False):
    err = { 'status': 405,
            'message': "Bad Method: {} {}".format(flask.request.method, flask.request.url) }
    app.logger.info("Client Error: 405: {}".format(err))
    res = flask.jsonify(err)
    res.status_code = err['status']
    return res


### Run Test Server ###

if __name__ == "__main__":
    app.run(debug=True)
