import json
import math

WIDTH = 960
HEIGHT = 540

MAX_PLAYERS = 4
MIN_PLAYERS_TO_START = 2  # Cambie a 1 si quiere probar con un solo cliente.

PLAYER_RADIUS = 18
BULLET_RADIUS = 5

PLAYER_SPEED = 220
BULLET_SPEED = 520

PLAYER_HEALTH = 100
BASE_DAMAGE = 10
SHOOT_COOLDOWN = 0.35
BULLET_TTL = 1.4

POWER_WEAPON_DURATION = 15.0
POWER_SHOOT_COOLDOWN = 0.12

PICKUP_RADIUS = 14
PICKUP_RESPAWN_TIME = 10.0

MATCH_SECONDS = 120

SERVER_TICK = 60
BROADCAST_RATE = 20
CLIENT_INPUT_RATE = 30
DISCONNECT_SECONDS = 10

SPAWN_POINTS = [
    (80, 80),
    (WIDTH - 80, 80),
    (80, HEIGHT - 80),
    (WIDTH - 80, HEIGHT - 80),
]

PLAYER_COLORS = {
    1: (70, 160, 255),
    2: (255, 95, 95),
    3: (120, 220, 120),
    4: (240, 210, 80),
}


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def normalize(dx, dy):
    length = math.hypot(dx, dy)

    if length == 0:
        return 0, 0

    return dx / length, dy / length


def distance_squared(ax, ay, bx, by):
    dx = ax - bx
    dy = ay - by

    return dx * dx + dy * dy


def encode_message(message):
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def decode_message(data):
    try:
        return json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None