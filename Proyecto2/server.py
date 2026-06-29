import random
import socket
import sys
import time
import math
from dataclasses import dataclass, field

from common import (
    BASE_DAMAGE,
    BROADCAST_RATE,
    BULLET_RADIUS,
    BULLET_SPEED,
    BULLET_TTL,
    COUNTDOWN_SECONDS,
    DISCONNECT_SECONDS,
    HEIGHT,
    MATCH_SECONDS,
    MAX_PLAYERS,
    MIN_PLAYERS_TO_START,
    PICKUP_RADIUS,
    PICKUP_RESPAWN_TIME,
    PLAYER_HEALTH,
    PLAYER_RADIUS,
    PLAYER_SPEED,
    POWER_SHOOT_COOLDOWN,
    POWER_WEAPON_DURATION,
    SERVER_TICK,
    SHOOT_COOLDOWN,
    SPAWN_POINTS,
    WIDTH,
    KILLS_TO_WIN,
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
    deaths: int = 0
    damage_dealt: int = 0
    aim_x: float = 1
    aim_y: float = 0
    last_seen: float = 0
    next_shot_time: float = 0
    has_power_weapon: bool = False
    power_weapon_end: float = 0.0
    was_shooting: bool = False
    keys: dict = field(
        default_factory=lambda: {
            "up": False,
            "down": False,
            "left": False,
            "right": False,
            "shoot": False,
        }
    )
    # NUEVO: estado de "listo"
    ready: bool = False


@dataclass
class Bullet:
    owner_id: int
    x: float
    y: float
    vx: float
    vy: float
    ttl: float = BULLET_TTL


@dataclass
class Pickup:
    pickup_id: int
    pickup_type: str
    x: float
    y: float
    active: bool = True
    respawn_at: float = 0.0


class AuthoritativeServer:
    def __init__(self, host="0.0.0.0", port=5000):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.setblocking(False)

        self.players: dict[int, Player] = {}
        self.address_to_id: dict[tuple[str, int], int] = {}
        self.bullets: list[Bullet] = []
        self.pickups: list[Pickup] = []

        self.next_player_id = 1
        self.next_pickup_id = 1

        
        self.phase = "waiting"
        self.match_end_time = 0.0
        self.finished_at = 0.0
        self.countdown_start = 0.0
        self.countdown_value = COUNTDOWN_SECONDS

        self.ranking = []
        self.winner_id = None

        print(f"Servidor UDP escuchando en {host}:{port}")
        print(f"Partida termina cuando un jugador alcance {KILLS_TO_WIN} kills")

    def random_pickup_pos(self):
        margin = 60
        x = random.uniform(margin, WIDTH - margin)
        y = random.uniform(margin, HEIGHT - margin)
        return x, y

    def spawn_pickups(self):
        self.pickups.clear()
        self.next_pickup_id = 1
        for pickup_type in ("weapon", "health"):
            x, y = self.random_pickup_pos()
            self.pickups.append(Pickup(
                pickup_id=self.next_pickup_id,
                pickup_type=pickup_type,
                x=x,
                y=y,
            ))
            self.next_pickup_id += 1

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

            msg_type = message.get("type")
            if msg_type == "connect":
                self.handle_connect(address, message)
            elif msg_type == "input":
                self.handle_input(address, message)
            elif msg_type == "disconnect":
                self.remove_player(address)
            # NUEVO: mensaje "ready"
            elif msg_type == "ready":
                self.handle_ready(address, message)

    def handle_connect(self, address, message):
        if address in self.address_to_id:
            player_id = self.address_to_id[address]
            self.send_to(address, {"type": "welcome", "id": player_id})
            return

        if len(self.players) >= MAX_PLAYERS:
            self.send_to(address, {
                "type": "full",
                "reason": "La partida ya tiene 4 jugadores.",
            })
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
            ready=False,  # NUEVO
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

        
        if self.phase != "playing":
            return

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

    
    def handle_ready(self, address, message):
        player_id = self.address_to_id.get(address)
        if player_id is None:
            return
        player = self.players.get(player_id)
        if player is None:
            return

        if self.phase == "waiting" or self.phase == "ready_check":
            player.ready = True
            print(f"Jugador {player_id} ({player.name}) está listo")
            # Verificar si todos están listos
            all_ready = all(p.ready for p in self.players.values())
            if all_ready and len(self.players) >= MIN_PLAYERS_TO_START:
                self.start_countdown()

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

    def start_countdown(self):
        self.phase = "countdown"
        self.countdown_start = time.perf_counter()
        self.countdown_value = COUNTDOWN_SECONDS
        print(f"Cuenta regresiva: {COUNTDOWN_SECONDS}...")

    def start_match(self, now):
        self.phase = "playing"
        self.match_end_time = now + MATCH_SECONDS
        self.bullets.clear()
        self.ranking = []
        self.winner_id = None

        for index, player in enumerate(self.players.values()):
            spawn = SPAWN_POINTS[index % len(SPAWN_POINTS)]
            player.x, player.y = spawn
            player.hp = PLAYER_HEALTH
            player.score = 0
            player.deaths = 0
            player.damage_dealt = 0
            player.next_shot_time = 0
            player.has_power_weapon = False
            player.power_weapon_end = 0.0
            player.was_shooting = False
            player.ready = False  # Reset para la próxima ronda

        self.spawn_pickups()
        print(f"Partida iniciada (objetivo: {KILLS_TO_WIN} kills)")

    def finish_match(self, now, reason="Tiempo agotado"):
        self.phase = "finished"
        self.finished_at = now
        self.bullets.clear()

        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.deaths, -p.damage_dealt)
        )
        self.ranking = [
            {
                "id": p.player_id,
                "name": p.name,
                "score": p.score,
                "deaths": p.deaths,
                "damage": p.damage_dealt,
                "rank": idx + 1
            }
            for idx, p in enumerate(sorted_players)
        ]
        self.winner_id = sorted_players[0].player_id if sorted_players else None
        print(f"Partida finalizada: {reason}")
        print("Ranking:", self.ranking)

    def update_phase(self, dt, now):
        if self.phase == "waiting":
            
            if len(self.players) >= MIN_PLAYERS_TO_START:
                self.phase = "ready_check"
                print("Esperando a que todos los jugadores estén listos...")
            return

        if self.phase == "ready_check":
            
            if len(self.players) < MIN_PLAYERS_TO_START:
                self.phase = "waiting"
                for p in self.players.values():
                    p.ready = False
            return

        if self.phase == "countdown":
            elapsed = now - self.countdown_start
            remaining = max(0, COUNTDOWN_SECONDS - int(elapsed))
            if remaining != self.countdown_value:
                self.countdown_value = remaining
                print(f"Cuenta regresiva: {remaining}")
            if elapsed >= COUNTDOWN_SECONDS:
                self.start_match(now)
            return

        if self.phase == "playing":
            if len(self.players) < MIN_PLAYERS_TO_START:
                self.phase = "waiting"
                self.bullets.clear()
                for p in self.players.values():
                    p.ready = False
                return

            self.update_game(dt, now)

            
            for player in self.players.values():
                if player.score >= KILLS_TO_WIN:
                    self.finish_match(now, f"¡Jugador {player.name} alcanzó {KILLS_TO_WIN} kills!")
                    return

            if now >= self.match_end_time:
                self.finish_match(now, "Tiempo agotado")
            return

        if self.phase == "finished":
            if len(self.players) < MIN_PLAYERS_TO_START:
                self.phase = "waiting"
                for p in self.players.values():
                    p.ready = False
            elif now - self.finished_at > 8:
               
                self.phase = "waiting"
                for p in self.players.values():
                    p.ready = False
                print("Reiniciando partida...")

    def update_game(self, dt, now):
        for player in self.players.values():
            if player.has_power_weapon and now >= player.power_weapon_end:
                player.has_power_weapon = False

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

            shooting = player.keys["shoot"]
            if player.has_power_weapon:
                if shooting and now >= player.next_shot_time:
                    self.spawn_bullet(player, now, POWER_SHOOT_COOLDOWN)
            else:
                if shooting and not player.was_shooting and now >= player.next_shot_time:
                    self.spawn_bullet(player, now, SHOOT_COOLDOWN)
            player.was_shooting = shooting

        self.update_bullets(dt)
        self.update_pickups(now)
        self.update_player_collisions()

    def update_player_collisions(self):
        player_list = list(self.players.values())
        for i in range(len(player_list)):
            for j in range(i + 1, len(player_list)):
                p1 = player_list[i]
                p2 = player_list[j]
                dx = p1.x - p2.x
                dy = p1.y - p2.y
                dist_sq = dx * dx + dy * dy
                min_dist = PLAYER_RADIUS * 2
                if dist_sq < min_dist * min_dist and dist_sq > 0:
                    dist = math.sqrt(dist_sq)
                    overlap = (min_dist - dist) / 2 * 1.8
                    nx = dx / dist
                    ny = dy / dist
                    p1.x += nx * overlap
                    p1.y += ny * overlap
                    p2.x -= nx * overlap
                    p2.y -= ny * overlap
                    p1.x = clamp(p1.x, PLAYER_RADIUS, WIDTH - PLAYER_RADIUS)
                    p1.y = clamp(p1.y, PLAYER_RADIUS, HEIGHT - PLAYER_RADIUS)
                    p2.x = clamp(p2.x, PLAYER_RADIUS, WIDTH - PLAYER_RADIUS)
                    p2.y = clamp(p2.y, PLAYER_RADIUS, HEIGHT - PLAYER_RADIUS)

    def spawn_bullet(self, player, now, cooldown):
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
        player.next_shot_time = now + cooldown

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
                    player.hp -= BASE_DAMAGE
                    hit = True
                    attacker = self.players.get(bullet.owner_id)
                    if attacker:
                        attacker.damage_dealt += BASE_DAMAGE
                    if player.hp <= 0:
                        player.deaths += 1
                        if attacker:
                            attacker.score += 1
                            print(f"Jugador {attacker.player_id} eliminó a {player.player_id}")
                        self.respawn_player(player)
                    break

            if not hit:
                active_bullets.append(bullet)

        self.bullets = active_bullets

    def update_pickups(self, now):
        for pickup in self.pickups:
            if not pickup.active:
                if now >= pickup.respawn_at:
                    pickup.x, pickup.y = self.random_pickup_pos()
                    pickup.active = True
                continue

            for player in self.players.values():
                radius = PLAYER_RADIUS + PICKUP_RADIUS
                if distance_squared(pickup.x, pickup.y, player.x, player.y) <= radius * radius:
                    if pickup.pickup_type == "weapon":
                        player.has_power_weapon = True
                        player.power_weapon_end = now + POWER_WEAPON_DURATION
                    elif pickup.pickup_type == "health":
                        player.hp = PLAYER_HEALTH
                    pickup.active = False
                    pickup.respawn_at = now + PICKUP_RESPAWN_TIME
                    break

    def respawn_player(self, player):
        player.hp = PLAYER_HEALTH
        player.has_power_weapon = False
        player.power_weapon_end = 0.0
        player.was_shooting = False
        player.x, player.y = random.choice(SPAWN_POINTS)

    def build_state(self, now):
        if self.phase == "playing":
            time_left = max(0, int(self.match_end_time - now))
        else:
            time_left = MATCH_SECONDS

        
        ready_count = sum(1 for p in self.players.values() if p.ready)

        return {
            "type": "state",
            "phase": self.phase,
            "time_left": time_left,
            "winner_id": self.winner_id,
            "ranking": self.ranking,
            "ready_count": ready_count,
            "total_players": len(self.players),
            "countdown": self.countdown_value if self.phase == "countdown" else 0,
            "players": [
                {
                    "id": player.player_id,
                    "name": player.name,
                    "x": round(player.x, 2),
                    "y": round(player.y, 2),
                    "hp": player.hp,
                    "score": player.score,
                    "aim": [round(player.aim_x, 3), round(player.aim_y, 3)],
                    "pw": player.has_power_weapon,
                    "ready": player.ready,  # NUEVO
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
            "pickups": [
                {
                    "id": pickup.pickup_id,
                    "type": pickup.pickup_type,
                    "x": round(pickup.x, 2),
                    "y": round(pickup.y, 2),
                }
                for pickup in self.pickups
                if pickup.active
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