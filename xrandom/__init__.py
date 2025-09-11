import uuid
import random
from vector import Vector2


def makeid() -> str:
    """Creates unique id.

    Returns:
        Id created.
    """
    return uuid.uuid4().hex

def random_float(min: float, max: float) -> float:
    return random.uniform(min, max)

def random_float_rounded(min: float, max: float, r: int) -> float:
    return round(random_float(min, max), r)

def random_vector2(v1: Vector2, v2: Vector2) -> Vector2:
    x = random_float(v1.x, v2.x)
    y = random_float(v1.y, v2.y)
    return Vector2(x, y)

def random_vector2_from_float_lists(min: list[float], max: list[float]) -> Vector2:
    min_vector = Vector2(min[0], min[1])
    max_vector = Vector2(max[0], max[1])
    return random_vector2(min_vector, max_vector)