"""
Web-server framework.

Mantra:
1. Why bother about HTTP methods, codes and data type headers?
2. Standardize how endpoints should look like. No more REST mess.
3. Every endpoint accept bytes, and return bytes. User must know how to interpret bytes coming for the requested endpoint, without any additional HTTP payload.
4. Integrate Role-Based Access Control.


## Endpoint
Destination of the request.


## RBAC


## Auth
Server also manages authentication and authorization.

The auth process is simple: each connection must provide an auth token. For standard HTTP - it is provided inside a request's header `auth`. For websocket connection, token will *probably* be specified in headers too (@todo websocket work in progress) - and will be active for the whole time of connection - or until it expires.

This module also powers RBAC system. Each user id is associated with number of roles. Each role is associated with number of permissions. A permission is a regex-string, which is compared to the registered endpoints' routes.

"""

import struct as c_struct
import argparse
import asyncio
import contextvars
from functools import wraps
import json
import re
import typing
from enum import Enum
from typing import Any, Awaitable, Callable, Literal, Self, Sequence

import aiohttp
import aiohttp_cors as engine_cors
import colorama
import httpx
from aiohttp import WSCloseCode, WSMessage
from aiohttp import web as engine
import jwt
from pydantic import BaseModel, ValidationError

import byteop
from codes import ROLE_NOT_FOUND, STRUCT_VALIDATION_ERROR, UNKNOWN_UPDATE_ACTION
import config
from postgres import transaction
import xrandom
import xtime
import log

# from utils import makeid, error
# from byteop import structs_to_bytes, bytes_to_struct
# from codes import CONNECTION_ERROR, EMPTY_COLLECTION, ERROR, OK, PERMISSION_NOT_FOUND, ROLE_NOT_FOUND, STRUCT_VALIDATION_ERROR, UNKNOWN_UPDATE_ACTION
# from orm import Table, CharField, TextField, BooleanField, transaction
# import postgres, utils
# from utils import ENCODING, INDENTATION, Result, T_Model, config_get, debug, info, err, panic, Struct, timestamp, timestamp_float, log_context

indentation = " " * 4
encoding = "utf-8"
Handler = Callable[[bytes], Awaitable[bytes]]
request_context = contextvars.ContextVar("request_context")
response_context = contextvars.ContextVar("response_context")
connect_token = "9d18680c857b4e3e864b59f4a5193864".encode(encoding)
disconnect_token = "dc9472cab41f41ce8715f05a2808b4a5".encode(encoding)

mode_permission = 1
mode_authorized = 2
mode_all = 3

Endpoint_Type = Literal["module", "module_variable", "function", "function_variable"]

class Endpoint(BaseModel):
    type: Endpoint_Type

    module: str
    function: str

    route: str = ""

    handler: Handler | None = None

    # How connected clients are treated:
    #   - 1, "permission": Only clients with required permission are allowed.
    #   - 2, "authorized": All authorized users are allowed.
    #   - 3, "all":        All users are allowed.
    auth_mode: int

    protocol: str

    def get_permission() -> str:
        match type:
            case "module":
                return module
            case "module_variable":
                return f"{module}.@"
            case "function":
                return f"{module}.{function}"
            case "function_variable":
                return f"{module}.{function}.@"

    def display(self) -> str:
        if self.type == "module":
            return f"{self.module}"
        elif self.type == "module_variable":
            return f"{self.module}.@"
        elif self.type == "function":
            return f"{self.module}.{self.function}"
        elif self.type == "function_variable":
            return f"{self.module}.{self.function}.@"
        else:
            raise NotImplementedError

Extension_Request = engine.Request
Extension_Stream_Response = engine.StreamResponse
Extension_Response = engine.Response
Extension_File_Response = engine.FileResponse
Extension_Websocket = engine.WebSocketResponse
Extension_Websocket_Message = WSMessage
Extension_Websocket_Message_type = engine.WSMsgType
Extension = Callable[[Extension_Request], Awaitable[Extension_Stream_Response]]

app: engine.Application | None = None
cors: engine_cors.CorsConfig | None = None
endpoints: dict[str, Endpoint] = {}

def request_remote_address() -> str:
    return request_context.get().get("remote_addr")

def request_endpoint() -> Endpoint:
    return request_context.get().get("endpoint")

def request_path() -> str:
    return request_context.get().get("path")

def request_auth_user_id() -> int | None:
    return request_context.get().get("auth_user_id")

def request_auth_created() -> int | None:
    return request_context.get().get("auth_created")

def request_route_variable() -> str | None:
    return request_context.get().get("route_parameter")("variable", None)

def request_query_parameter(key: str, default: str) -> str:
    return request_context.get().get("query_parameter")(key, default)

def response_code(code: int):
    d = response_context.get({})
    d["code"] = code
    response_context.set(d)

class Websocket:
    def __init__(self, native: engine.WebSocketResponse, endpoint: Endpoint, remote_addr: str, request_path: str) -> None:
        self.id = xrandom.makeid()
        self.native = native
        self.endpoint = endpoint
        self.remote_addr = remote_addr
        self.request_path = request_path

    def __hash__(self) -> int:
        return hash(self.id)

    # NOTE: Empty returned data with OK code won't be sent. Empty returned data with non-OK code will be sent.
    async def send(self, code: int, data: bytes):
        await internal_ws_send(self.native, self.endpoint, self.remote_addr, self.request_path, code, data)

    async def close(self, ws_code: int = WSCloseCode.OK, message: bytes = b""):
        await self.native.close(code=ws_code, message=message)

def request_websocket() -> Websocket:
    ws: Websocket = request_context.get().get("ws", None)
    if ws is None:
        raise Exception(f"Attempted to retrieve websocket in non-websocket connection.")
    return ws

async def internal_ws_send(ws: engine.WebSocketResponse, endpoint: Endpoint, remote_addr: str, request_path: str, code: int, data: bytes):
    if not (0 <= code <= 65535):
        raise Exception(f"Handler '{endpoint.display}' produced an error code out of bounds: {code}.")
    code_bytes = c_struct.pack("<H", code)
    final_data = code_bytes + data
    #log.info(f"({endpoint.protocol.upper()})<<< '{request_path}', code {code}, address '{remote_addr}'")
    try:
        await ws.send_bytes(final_data)
    except ConnectionResetError:
        raise ConnectionError

def ws_handler(
    endpoint: Endpoint,
) -> Callable[[engine.Request], Awaitable[engine.StreamResponse]]:
    handler = endpoint.handler
    if handler is None:
        raise Exception(f"Endpoint '{endpoint.display()}' handler is somehow not defined.")
    async def inner(request: engine.Request) -> engine.StreamResponse:
        remote_addr = request.remote if request.remote else "*unknown address*"
        request_path = request.path.removeprefix("/")

        # Process auth. For websocket, we fetch it from the query parameters.
        auth = request.query.get("auth", None)
        auth_mode = endpoint.auth_mode
        auth_model: Auth | None = None
        if auth is not None:
            auth_model = decode_auth(auth)

        ws = Extension_Websocket()
        await ws.prepare(request)
        #log.info(f"Endpoint '{endpoint.display()}' websocket connection for address '{remote_addr}' is {colorama.Fore.GREEN}opened{colorama.Fore.RESET}.")

        request_context.set({
            "endpoint": endpoint,
            "request_path": request_path,
            "ws": Websocket(ws, endpoint, remote_addr, request_path),
            "route_parameter": request.match_info.get,
            "query_parameter": request.query.get,
            "remote_addr": remote_addr,
            "auth_user_id": auth_model.user_id if auth_model else None,
            "auth_created": auth_model.created if auth_model else None,
        })
        log.context.set({
            "module": "web",
            "remote_addr": remote_addr,
            "auth_user_id": auth_model.user_id if auth_model else None,
            "auth_created": auth_model.created if auth_model else None,
        })

        def forbidden(reason: str) -> engine.Response:
            log.info(f"Forbid access to route '{endpoint.display()}' with auth mode '{display_auth_mode(auth_mode)}' for remote address '{remote_addr}', with a reason '{reason}'.")
            return engine.Response(status=403, text=reason)

        # If auth mode is ALL, we do not perform auth checks.
        if auth_mode != mode_all:
            # At this point having missing or invalid auth token is unacceptable.
            if auth is None or auth_model is None:
                return forbidden("No auth token.")

            user = await get_user(auth_model.user_id)
            if user is None:
                # Token is correct, but it's user id is missing.
                return forbidden("Auth token with unexistent user id.")
            if user.auth != auth:
                # We invalidate any auth tokens that are not matching with user's existing token.
                return forbidden("Auth token does not match with the user's current auth token. Only one token can be authorized for an user simultaneously.")

            # AUTHORIZED endpoints have passed all the required checks by this point.
            if auth_mode != mode_authorized:
                if auth_mode == mode_permission:
                    for p in user.permissions:
                        # If any permission matches the route, we allow the further connection.
                        if match_permission(p, endpoint):
                            break
                    else:
                        return forbidden("Unsufficient permissions.")
                else:
                    log.error(f"Unrecognized auth mode '{auth_mode}'.")
                    return engine.Response(status=500)


        #############################
        # Issue initial connection. #
        #############################
        # Once we're connected, we send an initial connect message with value CONNECT to our handler, to allow it setup everything it needs.
        # So, all websocket handlers must treat the first arrived message, as the connection message, issued by the server itself.
        #
        # Also, to avoid clients confusing handlers, we disallow sending them contents equal to `CONNECT`. `CONNECT`, is a hardcoded UUID4, so the scheme should avoid random hits.
        #
        # The same applies to DISCONNECT. We issue DISCONNECT in any case of a websocket close (finally block).
        try:
            response_data = await handler(connect_token)
        except Exception as e:
            log.error(
                f"Upon websocket connection, during calling a handler '{endpoint.display()}' for the first time, an error occurred: {e}",
                e,
            )
            await ws.close(code=WSCloseCode.OK)
            return ws


        ########################
        # Message Read Routine #
        ########################
        async for message in ws:
            if message.type != aiohttp.WSMsgType.BINARY:
                # We only support binary payloads.
                await ws.close(code=WSCloseCode.UNSUPPORTED_DATA)
                break

            request_data: bytes = message.data
            if request_data == connect_token:
                log.error(f"CONNECT message received at endpoint '{endpoint.display()}' from client '{remote_addr}'. Is this some sort of hacking?")
                await ws.close(code=WSCloseCode.UNSUPPORTED_DATA)
                break

            #log.info(f"({endpoint.protocol.upper()})>>> '{request_path}', address '{remote_addr}'")

            try:
                response_data = await handler(request_data)
            except Exception as e:
                # There is no official concept of errors for websocket connection: you use `response_code()` function to set a code for the outgoing websocket response. Unhandled exceptions will be considered as internal errors.
                log.error(
                    f"During calling a handler '{endpoint.display()}', an error occurred: {e}",
                    trace=e
                )
                await ws.close(code=WSCloseCode.INTERNAL_ERROR)
                break

            response_code = response_context.get({}).get("code", 0)

            # The websocket might be closed by the handler. In such case, trying to process handler response data is meaningless, so we proceed to the closing procedures.
            if ws.closed:
                break

            # Websocket handler can send the data in two ways:
            # 1. In response to client's message, by returning data directly from the handler. Empty returned data with OK code won't be sent.
            # 2. By obtaining request websocket `ws = server.request_websocket()`, and calling `ws.send(code, data)`.
            #
            # These 2 usage cases cover most methods of working with websockets.
            await ws.send_bytes(response_data)
            await internal_ws_send(ws, endpoint, remote_addr, request_path, response_code, response_data)


        #--------------------------------------------
        # Disconnect Routine
        #--------------------------------------------
        try:
            response_data = await handler(disconnect_token)
        except Exception as e:
            log.error(
                f"Upon websocket disconnect, during calling a handler '{endpoint.display()}' for the last time of a connection, an error occurred: {e}",
                trace=e
            )
            await ws.close(code=WSCloseCode.INTERNAL_ERROR)
            return ws

        response_code = response_context.get({}).get("code", 0)
        if response_code != 0:
            log.error(f"Upon websocket disconnect, for endpoint '{endpoint.display()}', a code {response_code} returned.")

        log.info(f"Endpoint '{endpoint.display()}' websocket connection for address '{remote_addr}' is {colorama.Fore.RED}closed{colorama.Fore.RESET}.")
        return ws

    return inner


def match_permission(permission: str, endpoint: Endpoint) -> bool:
    """
    Matches a permissions for an endpoint.

    ## Permission Match Rules
    1. Permission is compared with the full request path.
    2. Permission must be in format `{module}[.function_or_variable][.path_variable]`.
    3. `@` sign will represent a variable, a.k.a. route parameter. Same as for endpoint, a permission can have only one variable: either at the function place (a.k.a. "module variator") or at the function's variable placement.
    4. Permission with the exact text `%` will be treated as super-permission, allowing everything requiring permissions. This type of permissions are usually owned by the admins.
    5. Regarding naming, same as for endpoint, permission's module and function must be alnum, lowercase, kebab-notation, starting with a letter.

    If any of the abovementioned requirement is not fullfilled, this matching function returns false.
    """
    if permission == "%":
        return True

    # @question am i wrong commenting this? -ryzhovalex
    #
    # permission_regex = r"([a-z0-9-]+)\.([a-z0-9-@]+)?(\.@)?"
    # match = re.match(permission_regex, permission)
    # if not match:
    #     return False
    #
    # g1 = match.group(1)
    # check_endpoint_naming(g1)
    # g2 = match.group(2) if len(match.groups()) > 2 else ""
    # if g2 != "@":
    #     check_endpoint_naming(g2)
    # g3 = match.group(3) if len(match.groups()) > 3 else ""
    # if g3 != "@":
    #     check_endpoint_naming(g3)
    #
    # if g2 == "@" and g3 == "@":
    #     raise Exception(f"incorrect permission '{permission}'")

    return permission == endpoint.get_permission()

def check_endpoint_naming(name: str):
    if not re.match(r"^[a-z][a-z0-9-]+$", name):
        raise Exception(f"Name '{name}' is not suitable for an endpoint module or function name.")

# Adaptation of handler for aiohttp.
def http_handler(
    endpoint: Endpoint,
) -> Callable[[engine.Request], Awaitable[engine.StreamResponse]]:
    handler = endpoint.handler
    if handler is None:
        raise Exception(f"Endpoint '{endpoint.display()}' handler is somehow not defined.")
    async def inner(request: engine.Request) -> engine.StreamResponse:
        remote_addr = request.remote if request.remote else "*unknown address*"
        request_path = request.path.removeprefix("/")

        # Process auth.
        auth = request.headers.get("auth", None)
        auth_mode = endpoint.auth_mode
        auth_model: Auth | None = None
        if auth is not None:
            auth_model = decode_auth(auth)

        request_context.set({
            "endpoint": endpoint,
            "request_path": request_path,
            "route_parameter": request.match_info.get,
            "query_parameter": request.query.get,
            "remote_addr": remote_addr,
            "auth_user_id": auth_model.user_id if auth_model else None,
            "auth_created": auth_model.created if auth_model else None,
        })

        log.extra("remote_addr", remote_addr)
        log.extra("auth_user_id", auth_model.user_id if auth_model else None)
        log.extra("auth_created", auth_model.created if auth_model else None)

        def forbidden(reason: str) -> engine.Response:
            log.info(f"Forbid access to route '{endpoint.display()}' with auth mode '{display_auth_mode(auth_mode)}' for remote address '{remote_addr}', with a reason '{reason}'.")
            return engine.Response(status=403, text=reason)

        # If auth mode is ALL, we do not perform auth checks.
        if auth_mode != mode_all:
            # At this point having missing or invalid auth token is unacceptable.
            if auth is None or auth_model is None:
                return forbidden("No auth token.")

            user = await get_user(auth_model.user_id)
            if user is None:
                # Token is correct, but it's user id is missing.
                return forbidden("Auth token with unexistent user id.")
            if user.auth != auth:
                # We invalidate any auth tokens that are not matching with user's existing token.
                return forbidden("Auth token does not match with the user's current auth token. Only one token can be authorized for an user simultaneously.")

            # AUTHORIZED endpoints have passed all the required checks by this point.
            if auth_mode != mode_authorized:
                if auth_mode == mode_permission:
                    for p in user.permissions:
                        # If any permission matches the route, we allow the further connection.
                        if match_permission(p, endpoint):
                            break
                    else:
                        return forbidden("Unsufficient permissions.")
                else:
                    log.error(f"Unrecognized auth mode '{auth_mode}'.")
                    return engine.Response(status=500)

        request_data = await request.read()
        #log.info(f"({endpoint.protocol.upper()})>>> '{request_path}', address '{remote_addr}'")

        try:
            response_data = await handler(request_data)
        except Exception as e:
            # Any unhandled error treated as internal server error. Use `response_code()` to provide a result code for the response.
            log.error(
                f"During calling a handler '{endpoint.display()}', an error occurred: {e}",
                trace=e
            )
            # Do not attach error information to the response: it might leak crucial data.
            return engine.Response(status=500)

        response_code = response_context.get({}).get("code", 0)

        if not (0 <= response_code <= 65535):
            log.error(f"Handler '{endpoint.display()}' produced an error code out of bounds: {response_code}.")
            return engine.Response(status=500)

        code_bytes = c_struct.pack("<H", response_code)
        response_data = code_bytes + response_data

        #log.info(f"({endpoint.protocol.upper()})<<< '{request_path}', code {response_code}, address '{remote_addr}'")

        return engine.Response(
            body=response_data,
            # If the message is processed, we always consider this is OK HTTP
            # status, despite having positive error code in the response.
            # This way, we can utilize other error codes for special cases.
            status=200,
        )

    return inner

# Extension is a GET-only route that serves typical web-browser interactions.
# @legacy
def ext(
    method: str,
    route: str,
    extension: Extension,
):
    if app is None or cors is None:
        log.error("In sky, cannot add handler: uninitialized module")
        return
    if route.startswith("/rpc"):
        log.error("Cannot register rpc route as extension")
        return
    if not route.startswith("/"):
        route = "/" + route

    resource = typing.cast(
        engine.Resource,
        app.router.get(
            route,
            cors.add(app.router.add_resource(route)),
        )
    )
    cors.add(
        resource.add_route(
            method,
            extension,
        ),
        {
            "*": engine_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*"
            )
        }
    )

class EndpointKwargs:
    auth_mode: int = mode_all
    protocol: str = "http"

def endpoint_module(
    module: str,
    function: str,
    **kwargs,
):
    kw = EndpointKwargs.model_validate(kwargs)
    endpoint = Endpoint(type="module", module=module, function="", auth_mode=kw.auth_mode, protocol=kw.protocol)

def endpoint_module_variable(
    module: str,
    **kwargs,
):
    kw = EndpointKwargs.model_validate(kwargs)
    endpoint = Endpoint(type="module_variable", module=module, function="@", auth_mode=kw.auth_mode, protocol=kw.protocol)
    return _endpoint(endpoint)

def endpoint_function(
    module: str,
    function: str,
    auth_mode: int,
    **kwargs,
):
    kw = EndpointKwargs.model_validate(kwargs)
    endpoint = Endpoint(type="function", module=module, function=function, auth_mode=kw.auth_mode, protocol=kw.protocol)
    return _endpoint(endpoint)

def endpoint_function_variable(
    module: str,
    function: str,
    auth_mode: int,
    **kwargs,
):
    kw = EndpointKwargs.model_validate(kwargs)
    endpoint = Endpoint(type="function_variable", module=module, function=function, auth_mode=kw.auth_mode, protocol=kw.protocol)
    return _endpoint(endpoint)

# @todo Also add type `root` for module-only routes `/{module}`.
def _endpoint(endpoint: Endpoint):
    def wrapper(handler: Handler):

        @wraps(handler)
        async def inner(*args, **kwargs):
            return await handler(*args, **kwargs)

        # Variables in route is always prefixed with `@` - to avoid confusion between module variators and functions.
        if endpoint.type == "module":
            route = f"/{endpoint.module}"
        elif endpoint.type == "module_variable":
            route = f"/{endpoint.module}/" + "@{variable}"
        elif endpoint.type == "function":
            route = f"/{endpoint.module}/{endpoint.function}"
        elif endpoint.type == "function_variable":
            route = f"/{endpoint.module}/{endpoint.function}/" + "@{variable}"
        else:
            raise Exception("Not implemented.")

        endpoint.route = route
        endpoint.handler = handler

        if route in endpoints:
            log.error(f"Endpoint '{route}' is already registered.")
        else:
            endpoints[route] = endpoint
            if app is not None and cors is not None:
                # Register immediatelly, if endpoint is created after the server initialzation.
                register_endpoint(endpoint)

        return inner

    return wrapper

# @todo add full user here - username, name, etc.
class User(BaseModel):
    permissions: list[str]
    auth: str
    username: str
    fullname: str

get_user: Callable[[int], Awaitable[User | None]]

def error_handler(endpoint: Endpoint, function: Callable[[engine.Request], Awaitable[engine.StreamResponse]]):

    async def inner(request):
        try:
            return await function(request)
        except Exception as er:
            log.error(f"{colorama.Fore.RED}ENDPOINT PANIC{colorama.Fore.RESET}, for endpoint '{endpoint.display()}': {er}", trace=er)
            # We'll try to return normal response with status 500 for all our protocols. Might be subject of change later, if it works badly, e.g. for websockets.
            return engine.Response(status=500)

    return inner

def register_endpoint(endpoint: Endpoint):
    if app is None or cors is None:
        raise Exception("Server is not initialized.")

    # Note, when it comes to networking, everything is especially error-prone. Client might be disconnected, server might experience troubles, etc., etc. In such cases, we use `error_handler` function to unwind our panics, and produce meaningful responses, if they can be delivered or, at least, logged.

    if endpoint.protocol == "http":
        resource: engine.Resource = cors.add(app.router.add_resource(endpoint.route))
        # add both get and post methods for compatibility
        cors.add(
            resource.add_route(
                "GET",
                error_handler(endpoint, http_handler(endpoint)),
            ),
            {
                "*": engine_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*"
                )
            }
        )
        cors.add(
            resource.add_route(
                "POST",
                error_handler(endpoint, http_handler(endpoint)),
            ),
            {
                "*": engine_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*"
                )
            }
        )
    elif endpoint.protocol == "ws":
        resource: engine.Resource = cors.add(app.router.add_resource(endpoint.route))
        cors.add(
            resource.add_route(
                # Websockets are connected through GET.
                "GET",
                error_handler(endpoint, ws_handler(endpoint)),
            ),
            {
                "*": engine_cors.ResourceOptions(
                    allow_credentials=True,
                    expose_headers="*",
                    allow_headers="*"
                )
            }
        )
    else:
        log.error(f"Endpoint '{endpoint.display()}' has unsupported protocol '{endpoint.protocol}'.")
        del endpoints[endpoint.route]
        return

async def run():
    if app is None or cors is None:
        log.error("In sky, cannot run application: uninitialized module.")
        return

    parser = argparse.ArgumentParser()
    parser.add_argument("-host", type=str, default="localhost")
    parser.add_argument("-port", type=int, default="3000")

    args = parser.parse_args()
    host = args.host
    port = args.port

    log.info(f"Started server:\n{indentation}host: {host}\n{indentation}port: {port}")
    await engine._run_app(  # noqa: SLF001
        app,
        host=host,
        port=port,
    )

# @postgres.record_exporter("role")
# async def role_exporter(r: postgres.Record) -> Result[dict]:
#     return {
#         "id": r.id,
#         "name": r.name,
#         "description": r.description,
#         "permissions": r.permissions.split(","),
#     }, 0

class Register(BaseModel):
    username: str
    password: str
    fullname: str

# @todo Rewrite using `pagination.py`.
class GetUsersRequest(BaseModel):
    page:  int | None = None
    limit: int | None = None
    # Sorts are in format: `{column}_asc` or `{column}_desc`.
    sort: list[str] | None = None
    id: list[int] | None = None
    username: list[str] | None = None
    fullname: list[str] | None = None

class Auth(BaseModel):
    user_id: int
    created: int

def get_permissions_for_roles(roles: list[dict]) -> list[str]:
    permissions = []
    for role in roles:
        p = role.get("permissions", "").split(",")
        if p:
            permissions.extend(p)
    return permissions

def encode_auth(user_id: int) -> str:
    return jwt.encode(
        Auth(user_id=user_id, created=xtime.timestamp()).model_dump(),
        config.get("server", "auth_secret", "donuts"),
    )

def decode_auth(auth: str) -> Auth | None:
    model = Auth.model_validate(jwt.decode(auth, config.get("server", "auth_secret", "donuts"), [config.get("server", "auth_algo", "HS256")]))
    if model.created + int(config.get("server", "auth_lifetime", str(30 * 24 * 60 * 60 * 1000))) < xtime.timestamp():
        return None
    return model

class UpdateRolePermissions(BaseModel):
    id: int
    action: str
    permissions: list[str]

# While true permissions are just regex-strings, client wants to see what permissions are in the system, to make reasonable updates to the roles. We could pass just regex-strings, but that's not human-friendly to manage.
#
# The solution is to have this model, and populate it's `description` field with auto-generated information about endpoints (their description, etc.), that match the permission's route regex.
class PrettyPermission(BaseModel):
    route: str
    description: str

def display_auth_mode(auth_mode: int) -> str:
    if auth_mode == mode_permission:
        return "Permission"
    if auth_mode == mode_authorized:
        return "Authorized"
    if auth_mode == mode_all:
        return "All"
    else:
        return "*unknown auth mode {auth_mode}*"

def build_permission_description(permission: str) -> str:
    description = ""
    for endpoint in endpoints.values():
        # @todo @critical This won't work with `operation/{id}` routes, as typical permissions like `operation/[0-9]+` won't match it. Find a way to enforce types on route parameters and replace them here. Like `operation/0` with a default value.
        # @todo @critical some permissions might give regex parsing error, so we better of disabling it for now
        continue
        if re.match(permission, endpoint.route):
            # We collect description from all endpoints, doesn't matter if their auth mode is not `PERMISSION`.
            # @todo Translate this description and endpoint description to chosen language. Language should be chosen from a header, default is `en`. Endpoint translation keys are prefixed with `ENDPOINT_`, then route is used, where `/` are replaced by underscores, and `{param_name}` are replaced with `(PARAM_NAME)`. For example, an endpoint `users/{username}/controls` is associated with translation key `ENDPOINT_USERS_(USERNAME)_CONTROLS`.
            description += f"* Connected to endpoint '{endpoint.display()}' with auth mode '{display_auth_mode(endpoint.auth_mode)}' and description: *no description temporarily*\n"
    if not description:
        description = "*no matched endpoints*"
    description.removesuffix("\n")
    return description

@endpoint_function("web", "get_permissions", mode_authorized)
async def get_permissions(data: bytes) -> bytes:
    class R(BaseModel):
        codes: list[str] | None = None

    model = byteop.bytes_to_struct(R, data)
    if model is None:
        response_code(STRUCT_VALIDATION_ERROR)
        return bytes()
    codes = model.codes
    used_permissions: list[str] = []
    pretty_permissions: list[PrettyPermission] = []
    async with transaction() as con:
        # @perf Search using LIKE filter.
        roles = await con.fetch("SELECT * FROM role")
        for role in roles:
            for permission in role.permissions.split(","):
                if (codes is None or permission in codes) and (permission not in used_permissions):
                    used_permissions.append(permission)
                    pretty_permissions.append(PrettyPermission(
                        route=permission,
                        description=build_permission_description(permission),
                    ))

    return byteop.structs_to_bytes(pretty_permissions)

@endpoint_function("server", "update-role-permissions", mode_permission)
async def update_role_permissions(data: bytes) -> bytes:
    async with transaction() as con:
        model = byteop.bytes_to_struct(UpdateRolePermissions, data)
        if not model:
            response_code(STRUCT_VALIDATION_ERROR)
            return bytes()

        role = await con.fetch_first("SELECT * FROM role WHERE id = $1", model.id)
        if role is None:
            response_code(ROLE_NOT_FOUND)
            return bytes()

        permissions = set(role.permissions.split(","))

        if model.action == "push":
            permissions.update(model.permissions)
        elif model.action == "pop":
            permissions.difference_update(model.permissions)
        else:
            response_code(UNKNOWN_UPDATE_ACTION)
            return bytes()

        new_permissions = ",".join(permissions)
        await con.execute("UPDATE role SET permissions = $1 WHERE id = $2", new_permissions, model.id)

        return bytes()

bus_connections = {}

async def bus_send(token_rule: str, code: int, data: bytes):
    tokens = []
    if token_rule == "*":
        tokens = bus_connections.keys()
    else:
        tokens = [token_rule]

    for token in tokens:
        ws = bus_connections.get(token, None)
        if ws is None:
            raise Exception(f"cannot find connection with token '{token}'")
        code_bytes = c_struct.pack("<H", code)
        final_data = code_bytes + data
        await ws.send_bytes(final_data)

@endpoint_function_variable("web", "bus", mode_all, protocol="ws")
async def bus(data: bytes) -> bytes:
    """
    Connected via `/web/bus/@{auth_token}`.
    """
    if data == connect_token:
        token = request_route_variable()
        if token is None or token == "":
            raise Exception("token is required to connect to the bus")
        ws = request_websocket()
        bus_connections[token] = ws

    if data == disconnect_token:
        token = request_route_variable()
        if token is None or token == "":
            return bytes()
        if token in bus_connections:
            del bus_connections[token]

    return bytes()

def init(get_user_: Callable[[int], Awaitable[User | None]]):
    global get_user
    get_user = get_user_

    global app
    app = engine.Application(client_max_size=16386**2)
    global cors
    cors = engine_cors.setup(app)

    # Register all previously defined endpoints.
    for endpoint in endpoints.values():
        register_endpoint(endpoint)

def deinit():
    pass
