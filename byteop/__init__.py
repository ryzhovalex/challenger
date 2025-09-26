"""
Operations with bytes.
"""

from enum import Enum
import struct
import json
from typing import Any, Sequence, TypeVar

from pydantic import BaseModel, ValidationError


ENCODING = "utf-8"
T_Model = TypeVar("T_Model", bound=BaseModel)

def bytes_to_struct(struct_type: type[T_Model], input: bytes) -> T_Model | None:
    try:
        return struct_type.model_validate(bytes_to_json(input))
    except ValidationError:
        return None

# @legacy
def _convert_enums(data: Any) -> Any:
    if isinstance(data, dict):
        new = {}
        for k, v in data.items():
            new[k] = _convert_enums_v(v)
        return new
    elif isinstance(data, (list, tuple, set)):
        r = []
        for x in data:
            r.append(_convert_enums(x))
        return r
    else:
        return data

# @legacy
def _convert_enums_v(v: Any) -> Any:
    final_v = v
    if isinstance(v, Enum):
        final_v = v.value
    elif isinstance(v, dict):
        final_v = _convert_enums(v)
    elif isinstance(v, (list, tuple, set)):
        final_v = []
        for x in v:
            final_v.append(_convert_enums_v(x))
    return final_v

def bytes_to_string(input: bytes) -> str:
    return input.decode(ENCODING)

def string_to_bytes(input: str) -> bytes:
    return input.encode(ENCODING)

def structs_to_bytes(structs: Sequence[BaseModel]) -> bytes:
    return json.dumps([x.model_dump() for x in structs]).encode(ENCODING)

def struct_to_bytes(struct_: BaseModel) -> bytes:
    return struct_.model_dump_json().encode(ENCODING)

def json_to_bytes(input: Any) -> bytes:
    return json.dumps(_convert_enums(input)).encode(ENCODING)

def bytes_to_json(input: bytes) -> Any:
    if input == bytes():
        return {}
    return json.loads(input.decode(ENCODING))

def float_to_bytes(input: float) -> bytes:
    return struct.pack("<f", input)

def bytes_to_float(input: bytes) -> float:
    return struct.unpack("<f", input)[0]

def int_to_bytes(input: int, size: int) -> bytes:
    return input.to_bytes(size, byteorder="little")

def adaptively_to_bytes(input: Any):
    if isinstance(input, str):
        return string_to_bytes(input)
    elif isinstance(input, int):
        return int_to_bytes(input, 8)
    elif isinstance(input, bytes):
        return input
    else:
        raise TypeError("Unsupported data type")
