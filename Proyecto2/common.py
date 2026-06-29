import json
import math
import random 

WIDTH = 960
HEIGHT = 540

MAX_PLAYERS = 4
MIN_PLAYERS_TO_START = 2

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
KILLS_TO_WIN = 3

SERVER_TICK = 60
BROADCAST_RATE = 20
CLIENT_INPUT_RATE = 30
DISCONNECT_SECONDS = 10


COUNTDOWN_SECONDS = 3

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


SHIP_COLORS = {
    1: (100, 180, 255),  
    2: (255, 120, 120),  
    3: (140, 255, 140),  
    4: (255, 230, 120),
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


def circle_rect_overlap(cx, cy, r, rx, ry, rw, rh):
    """True if circle (cx,cy,r) overlaps axis-aligned rect (rx,ry,rw,rh)."""
    px = clamp(cx, rx, rx + rw)
    py = clamp(cy, ry, ry + rh)
    dx = cx - px
    dy = cy - py
    return dx * dx + dy * dy < r * r


def push_circle_from_rect(cx, cy, r, rx, ry, rw, rh):
    """Return (cx, cy) with circle pushed outside rect. No-op if no overlap."""
    px = clamp(cx, rx, rx + rw)
    py = clamp(cy, ry, ry + rh)
    dx = cx - px
    dy = cy - py
    dist_sq = dx * dx + dy * dy
    if dist_sq >= r * r:
        return cx, cy
    if dist_sq == 0:
        # Center is inside rect; push out via nearest edge
        d_left = cx - rx
        d_right = (rx + rw) - cx
        d_top = cy - ry
        d_bottom = (ry + rh) - cy
        m = min(d_left, d_right, d_top, d_bottom)
        if m == d_left:
            return rx - r, cy
        if m == d_right:
            return rx + rw + r, cy
        if m == d_top:
            return cx, ry - r
        return cx, ry + rh + r
    dist = math.sqrt(dist_sq)
    return cx + (dx / dist) * (r - dist), cy + (dy / dist) * (r - dist)


def _generate_obstacles(seed=42):
    """Generate obstacle rects (x,y,w,h) in the central map zone, away from spawns."""
    rng = random.Random(seed)
    result = []
    max_w, max_h = 72, 56
    # Central zone: x in [180, 780], y in [150, 390] (away from corners/borders)
    attempts = 0
    while len(result) < 6 and attempts < 500:
        attempts += 1
        w = rng.randint(42, max_w)
        h = rng.randint(30, max_h)
        x = rng.randint(180, 780 - w)
        y = rng.randint(150, 390 - h)
        # Reject if too close to any spawn point (70 px exclusion zone)
        near_spawn = any(
            x - 70 < sx < x + w + 70 and y - 70 < sy < y + h + 70
            for sx, sy in SPAWN_POINTS
        )
        if near_spawn:
            continue
        # Reject if overlaps (with 15 px gap) an already-placed obstacle
        overlapping = any(
            x < ox + ow + 15 and x + w > ox - 15 and
            y < oy + oh + 15 and y + h > oy - 15
            for ox, oy, ow, oh in result
        )
        if overlapping:
            continue
        result.append((x, y, w, h))
    return result


OBSTACLES = _generate_obstacles()