import random
import socket
import sys
import time
from dataclasses import dataclass, field

from common import (
    BROADCAST_RATE,
    BULLET_RADIUS,
    BULLET_SPEED,
    BULLET_TTL,
    DISCONNECT_SECONDS,
    HEIGHT,
    MATCH_SECONDS,
    MAX_PLAYERS,
    MIN_PLAYERS_TO_START,
    PLAYER_HEALTH,
    PLAYER_RADIUS,
    PLAYER_SPEED,
    SERVER_TICK,
    SHOOT_COOLDOWN,
    SPAWN_POINTS,
    WIDTH,
    clamp,
    decode_message,
    distance_squared,
    encode_message,
    normalize,
)


@dataclass
class Player:
    player_id: int
    address: tuple[str, int]
    name: str
    x: float
    y: float
    hp: int = PLAYER_HEALTH
    score: int = 0
    aim_x: float = 1
    aim_y: float = 0
    last_seen: float = 0
    next_shot_time: float = 0
    keys: dict = field(
        default_factory=lambda: {
            "up": False,
            "down": False,
            "left": False,
            "right": False,
            "shoot": False,
        }
    )


@dataclass
class Bullet:
    owner_id: int
    x: float
    y: float
    vx: float
    vy: float
    ttl: float = BULLET_TTL


class AuthoritativeServer:
    def __init__(self, host="0.0.0.0", port=5000):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)

        self.players: dict[int, Player] = {}
        self.address_to_id: dict[tuple[str, int], int] = {}
        self.bullets: list[Bullet] = []

        self.next_player_id = 1

        self.phase = "waiting"
        self.match_end_time = 0.0
        self.finished_at = 0.0

        print(f"Servidor UDP escuchando en {host}:{port}")

    def send_to(self, address, message):
        self.sock.sendto(encode_message(message), address)

    def broadcast(self, message):
        packet = encode_message(message)

        for player in self.players.values():
            self.sock.sendto(packet, player.address)

    def receive_messages(self):
        while True:
            try:
                data, address = self.sock.recvfrom(4096)
            except BlockingIOError:
                break
            except ConnectionResetError:
                break

            message = decode_message(data)

            if not isinstance(message, dict):
                continue

            message_type = message.get("type")

            if message_type == "connect":
                self.handle_connect(address, message)

            elif message_type == "input":
                self.handle_input(address, message)

            elif message_type == "disconnect":
                self.remove_player(address)

    def handle_connect(self, address, message):
        if address in self.address_to_id:
            player_id = self.address_to_id[address]
            self.send_to(address, {"type": "welcome", "id": player_id})
            return

        if len(self.players) >= MAX_PLAYERS:
            self.send_to(
                address,
                {
                    "type": "full",
                    "reason": "La partida ya tiene 4 jugadores.",
                },
            )
            return

        player_id = self.next_player_id
        self.next_player_id += 1

        spawn = SPAWN_POINTS[(player_id - 1) % len(SPAWN_POINTS)]
        name = str(message.get("name", f"Jugador {player_id}"))[:16]

        self.players[player_id] = Player(
            player_id=player_id,
            address=address,
            name=name,
            x=spawn[0],
            y=spawn[1],
            last_seen=time.perf_counter(),
        )

        self.address_to_id[address] = player_id

        self.send_to(address, {"type": "welcome", "id": player_id})

        print(f"Conectado {name} con ID {player_id} desde {address}")

    def handle_input(self, address, message):
        player_id = self.address_to_id.get(address)

        if player_id is None:
            return

        player = self.players.get(player_id)

        if player is None:
            return

        player.last_seen = time.perf_counter()

        keys = message.get("keys", {})

        if isinstance(keys, dict):
            player.keys["up"] = bool(keys.get("up"))
            player.keys["down"] = bool(keys.get("down"))
            player.keys["left"] = bool(keys.get("left"))
            player.keys["right"] = bool(keys.get("right"))
            player.keys["shoot"] = bool(keys.get("shoot"))

        aim = message.get("aim", [player.x + player.aim_x, player.y + player.aim_y])

        if isinstance(aim, list) and len(aim) == 2:
            dx = float(aim[0]) - player.x
            dy = float(aim[1]) - player.y

            aim_x, aim_y = normalize(dx, dy)

            if aim_x != 0 or aim_y != 0:
                player.aim_x = aim_x
                player.aim_y = aim_y

    def remove_player(self, address):
        player_id = self.address_to_id.pop(address, None)

        if player_id is None:
            return

        player = self.players.pop(player_id, None)

        if player:
            print(f"Desconectado {player.name} ID {player_id}")

    def remove_inactive_players(self, now):
        inactive = [
            player.address
            for player in self.players.values()
            if now - player.last_seen > DISCONNECT_SECONDS
        ]

        for address in inactive:
            self.remove_player(address)

    def start_match(self, now):
        self.phase = "playing"
        self.match_end_time = now + MATCH_SECONDS
        self.bullets.clear()

        for index, player in enumerate(self.players.values()):
            spawn = SPAWN_POINTS[index % len(SPAWN_POINTS)]

            player.x, player.y = spawn
            player.hp = PLAYER_HEALTH
            player.score = 0
            player.next_shot_time = 0

        print("Partida iniciada")

    def finish_match(self, now):
        self.phase = "finished"
        self.finished_at = now
        self.bullets.clear()

        print("Partida finalizada")

    def update_phase(self, dt, now):
        if self.phase == "waiting":
            if len(self.players) >= MIN_PLAYERS_TO_START:
                self.start_match(now)

            return

        if self.phase == "playing":
            if len(self.players) < MIN_PLAYERS_TO_START:
                self.phase = "waiting"
                self.bullets.clear()
                return

            self.update_game(dt, now)

            if now >= self.match_end_time:
                self.finish_match(now)

            return

        if self.phase == "finished":
            if len(self.players) < MIN_PLAYERS_TO_START:
                self.phase = "waiting"

            elif now - self.finished_at > 8:
                self.start_match(now)

    def update_game(self, dt, now):
        for player in self.players.values():
            dx = int(player.keys["right"]) - int(player.keys["left"])
            dy = int(player.keys["down"]) - int(player.keys["up"])

            dx, dy = normalize(dx, dy)

            player.x = clamp(
                player.x + dx * PLAYER_SPEED * dt,
                PLAYER_RADIUS,
                WIDTH - PLAYER_RADIUS,
            )

            player.y = clamp(
                player.y + dy * PLAYER_SPEED * dt,
                PLAYER_RADIUS,
                HEIGHT - PLAYER_RADIUS,
            )

            if player.keys["shoot"] and now >= player.next_shot_time:
                self.spawn_bullet(player, now)

        self.update_bullets(dt)

    def spawn_bullet(self, player, now):
        start_x = player.x + player.aim_x * (PLAYER_RADIUS + BULLET_RADIUS + 2)
        start_y = player.y + player.aim_y * (PLAYER_RADIUS + BULLET_RADIUS + 2)

        bullet = Bullet(
            owner_id=player.player_id,
            x=start_x,
            y=start_y,
            vx=player.aim_x * BULLET_SPEED,
            vy=player.aim_y * BULLET_SPEED,
        )

        self.bullets.append(bullet)

        player.next_shot_time = now + SHOOT_COOLDOWN

    def update_bullets(self, dt):
        active_bullets = []

        for bullet in self.bullets:
            bullet.x += bullet.vx * dt
            bullet.y += bullet.vy * dt
            bullet.ttl -= dt

            if bullet.ttl <= 0:
                continue

            if bullet.x < 0 or bullet.x > WIDTH or bullet.y < 0 or bullet.y > HEIGHT:
                continue

            hit = False

            for player in self.players.values():
                if player.player_id == bullet.owner_id:
                    continue

                radius = PLAYER_RADIUS + BULLET_RADIUS

                if distance_squared(bullet.x, bullet.y, player.x, player.y) <= radius * radius:
                    player.hp -= 1
                    hit = True

                    if player.hp <= 0:
                        attacker = self.players.get(bullet.owner_id)

                        if attacker:
                            attacker.score += 1

                        self.respawn_player(player)

                    break

            if not hit:
                active_bullets.append(bullet)

        self.bullets = active_bullets

    def respawn_player(self, player):
        player.hp = PLAYER_HEALTH
        player.x, player.y = random.choice(SPAWN_POINTS)

    def build_state(self, now):
        winner_id = None

        if self.phase == "finished" and self.players:
            winner_id = max(
                self.players.values(),
                key=lambda player: player.score,
            ).player_id

        if self.phase == "playing":
            time_left = max(0, int(self.match_end_time - now))
        else:
            time_left = MATCH_SECONDS

        return {
            "type": "state",
            "phase": self.phase,
            "time_left": time_left,
            "winner_id": winner_id,
            "players": [
                {
                    "id": player.player_id,
                    "name": player.name,
                    "x": round(player.x, 2),
                    "y": round(player.y, 2),
                    "hp": player.hp,
                    "score": player.score,
                    "aim": [
                        round(player.aim_x, 3),
                        round(player.aim_y, 3),
                    ],
                }
                for player in self.players.values()
            ],
            "bullets": [
                {
                    "owner_id": bullet.owner_id,
                    "x": round(bullet.x, 2),
                    "y": round(bullet.y, 2),
                }
                for bullet in self.bullets
            ],
        }

    def run(self):
        last_time = time.perf_counter()
        broadcast_timer = 0.0

        while True:
            now = time.perf_counter()
            dt = min(now - last_time, 0.05)
            last_time = now

            self.receive_messages()
            self.remove_inactive_players(now)
            self.update_phase(dt, now)

            broadcast_timer += dt

            if broadcast_timer >= 1 / BROADCAST_RATE:
                self.broadcast(self.build_state(now))
                broadcast_timer = 0.0

            time.sleep(1 / SERVER_TICK)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

    server = AuthoritativeServer(port=port)
    server.run()