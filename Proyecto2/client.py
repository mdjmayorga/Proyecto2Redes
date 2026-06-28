import json
import math
import socket
import sys
import threading
import time
import random

import pygame

from common import (
    BULLET_RADIUS,
    CLIENT_INPUT_RATE,
    HEIGHT,
    PICKUP_RADIUS,
    PLAYER_COLORS,
    SHIP_COLORS,
    PLAYER_HEALTH,
    PLAYER_RADIUS,
    PLAYER_SPEED,
    WIDTH,
    MAX_PLAYERS,
    KILLS_TO_WIN,
    COUNTDOWN_SECONDS,
    clamp,
    decode_message,
    encode_message,
    normalize,
)


class LocalPredictor:
    def __init__(self):
        self.predicted_x = 0.0
        self.predicted_y = 0.0
        self.initialized = False

    def apply_input(self, keys, dt):
        if not self.initialized:
            return
        dx = int(keys["right"]) - int(keys["left"])
        dy = int(keys["down"]) - int(keys["up"])
        dx, dy = normalize(dx, dy)
        self.predicted_x = clamp(
            self.predicted_x + dx * PLAYER_SPEED * dt,
            PLAYER_RADIUS,
            WIDTH - PLAYER_RADIUS,
        )
        self.predicted_y = clamp(
            self.predicted_y + dy * PLAYER_SPEED * dt,
            PLAYER_RADIUS,
            HEIGHT - PLAYER_RADIUS,
        )

    def correct(self, server_x, server_y, lerp_factor=0.3):
        if not self.initialized:
            self.predicted_x = server_x
            self.predicted_y = server_y
            self.initialized = True
            return
        self.predicted_x += (server_x - self.predicted_x) * lerp_factor
        self.predicted_y += (server_y - self.predicted_y) * lerp_factor

    def get_position(self):
        return self.predicted_x, self.predicted_y


class Star:
    def __init__(self):
        self.x = random.randint(0, WIDTH)
        self.y = random.randint(0, HEIGHT)
        self.size = random.uniform(1, 3)
        self.brightness = random.randint(100, 255)
        self.speed = random.uniform(0.1, 0.5)
        self.phase = random.uniform(0, 2 * math.pi)

    def update(self):
        self.y += self.speed
        if self.y > HEIGHT:
            self.y = 0
            self.x = random.randint(0, WIDTH)
            self.size = random.uniform(1, 3)
            self.brightness = random.randint(100, 255)
            self.speed = random.uniform(0.1, 0.5)
            self.phase = random.uniform(0, 2 * math.pi)

    def draw(self, screen):
        flicker = 0.7 + 0.3 * math.sin(time.time() * 2 + self.phase)
        alpha = int(self.brightness * flicker)
        alpha = max(0, min(255, alpha))
        color = (alpha, alpha, min(255, alpha + 30))
        pygame.draw.circle(screen, color, (int(self.x), int(self.y)), int(self.size))


class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5000, name="Jugador"):
        pygame.init()
        pygame.display.set_caption("Shooter 2D - Cliente")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("Arial", 18)
        self.big_font = pygame.font.SysFont("Arial", 36, bold=True)
        self.hud_font = pygame.font.SysFont("Arial", 16, bold=True)

        self.stars = [Star() for _ in range(150)]

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("", 0))
        self.sock.setblocking(False)
        self.server_address = (server_ip, server_port)

        self.name = name[:16]
        self.player_id = None
        self.state = None
        self.state_lock = threading.Lock()
        self.running = True

        self.local_keys = {
            "up": False,
            "down": False,
            "left": False,
            "right": False,
            "shoot": False,
        }
        self.mouse_pos = (0, 0)
        self.input_lock = threading.Lock()
        self.predictor = LocalPredictor()
        self.last_connect_sent = 0.0
        self.prev_state = None

        self.ready_button_rect = pygame.Rect(WIDTH//2 - 75, HEIGHT//2 + 50, 150, 50)
        self.is_ready = False

        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        self.sounds = {}
        sound_files = {
            "shoot": "assets/sounds/shoot.wav",
            "hit": "assets/sounds/hit.wav",
            "kill": "assets/sounds/kill.wav",
            "game_over": "assets/sounds/game_over.wav",
        }
        for name, path in sound_files.items():
            try:
                self.sounds[name] = pygame.mixer.Sound(path)
                print(f"Sonido {name} cargado desde {path}")
            except Exception as e:
                print(f"Error cargando {path}: {e} - Usando silencio")
                self.sounds[name] = pygame.mixer.Sound(buffer=bytes([0]*1000))

        self.player_sprites = {}
        for pid in range(1, 5):
            try:
                img = pygame.image.load(f"assets/sprites/player_{pid}.png").convert_alpha()
                img = pygame.transform.scale(img, (PLAYER_RADIUS*2, PLAYER_RADIUS*2))
                self.player_sprites[pid] = img
            except:
                self.player_sprites[pid] = None

    def send(self, message):
        self.sock.sendto(encode_message(message), self.server_address)

    def send_connect(self):
        self.send({"type": "connect", "name": self.name})

    def send_ready(self):
        self.send({"type": "ready"})
        self.is_ready = True

    def _send_loop(self):
        while self.running:
            if self.player_id is not None:
                with self.input_lock:
                    keys_copy = dict(self.local_keys)
                    mouse_x, mouse_y = self.mouse_pos
                self.send({
                    "type": "input",
                    "id": self.player_id,
                    "keys": keys_copy,
                    "aim": [mouse_x, mouse_y],
                })
            time.sleep(1 / CLIENT_INPUT_RATE)

    def _receive_loop(self):
        while self.running:
            try:
                data, _ = self.sock.recvfrom(65535)
            except BlockingIOError:
                time.sleep(0.001)
                continue
            except ConnectionResetError:
                time.sleep(0.01)
                continue
            message = decode_message(data)
            if not isinstance(message, dict):
                continue
            msg_type = message.get("type")
            if msg_type == "welcome":
                self.player_id = message.get("id")
                print(f"Bienvenido, tu ID es {self.player_id}")
            elif msg_type == "state":
                with self.state_lock:
                    self.prev_state = self.state
                    self.state = message
                if self.player_id is not None:
                    for player in message.get("players", []):
                        if player.get("id") == self.player_id:
                            self.predictor.correct(player.get("x", 0), player.get("y", 0))
                            break
            elif msg_type == "full":
                print(message.get("reason", "Servidor lleno"))
                self.running = False

    def capture_input(self):
        keys = pygame.key.get_pressed()
        mouse_buttons = pygame.mouse.get_pressed()
        with self.input_lock:
            self.local_keys["up"] = bool(keys[pygame.K_w] or keys[pygame.K_UP])
            self.local_keys["down"] = bool(keys[pygame.K_s] or keys[pygame.K_DOWN])
            self.local_keys["left"] = bool(keys[pygame.K_a] or keys[pygame.K_LEFT])
            self.local_keys["right"] = bool(keys[pygame.K_d] or keys[pygame.K_RIGHT])
            shoot_pressed = bool(mouse_buttons[0])
            if shoot_pressed and not self.local_keys["shoot"]:
                self.sounds["shoot"].play()
            self.local_keys["shoot"] = shoot_pressed
            self.mouse_pos = pygame.mouse.get_pos()

    def draw_text(self, text, x, y, color=(235, 235, 235), font=None):
        img = (font or self.font).render(str(text), True, color)
        self.screen.blit(img, (x, y))

    def draw_center_text(self, text, y, color=(255, 255, 255), font=None):
        f = font or self.big_font
        img = f.render(text, True, color)
        x = WIDTH // 2 - img.get_width() // 2
        self.screen.blit(img, (x, y))

    def draw_background(self):
        # Fondo oscuro sólido (cubre todo)
        self.screen.fill((8, 10, 20))
        # Degradado sutil con rectángulos (más rápido y sin huecos)
        for i in range(0, HEIGHT, 4):
            intensity = int(10 + 15 * (i / HEIGHT))
            color = (intensity, intensity, intensity + 20)
            pygame.draw.rect(self.screen, color, (0, i, WIDTH, 4))
        # Estrellas
        for star in self.stars:
            star.update()
            star.draw(self.screen)

    def draw_hud(self):
        with self.state_lock:
            state = self.state
        if not state:
            return

        hud_bg = pygame.Surface((WIDTH, 60))
        hud_bg.set_alpha(180)
        hud_bg.fill((10, 10, 20))
        self.screen.blit(hud_bg, (0, 0))
        pygame.draw.line(self.screen, (60, 60, 80), (0, 60), (WIDTH, 60), 2)

        phase = state.get("phase")
        time_left = state.get("time_left", 0)

        self.draw_text(f"ID: {self.player_id}", 15, 10, (200, 200, 255))
        self.draw_text(f"Tiempo: {time_left}s", 15, 35, (255, 255, 200))

        x_offset = WIDTH // 2 - 80
        y_offset = 10
        self.draw_text("Puntajes:", x_offset, y_offset, (255, 255, 200), self.hud_font)
        for idx, player in enumerate(state.get("players", [])):
            marker = "* " if player.get("id") == self.player_id else "  "
            hp_pct = max(0, int(player.get("hp", 0) / PLAYER_HEALTH * 100))
            pw = " [PW]" if player.get("pw") else ""
            text = f"{marker}{player.get('name')} HP:{hp_pct}% K:{player.get('score')}{pw}"
            self.draw_text(text, x_offset, y_offset + 20 + idx * 18, (220, 220, 220), self.hud_font)

        if phase == "waiting":
            self.draw_text("Esperando jugadores...", WIDTH - 220, 20, (255, 200, 100))
            self.draw_text(f"Jugadores: {len(state.get('players', []))}", WIDTH - 220, 40, (200, 200, 255))
        elif phase == "ready_check":
            ready = state.get("ready_count", 0)
            total = state.get("total_players", 0)
            self.draw_text(f"Listos: {ready}/{total}", WIDTH - 200, 20, (100, 255, 100))
            if ready == total:
                self.draw_text("¡Todos listos! Comenzando...", WIDTH - 250, 40, (255, 255, 100))
            else:
                self.draw_text("Esperando a los demás...", WIDTH - 200, 40, (255, 200, 100))
        elif phase == "countdown":
            countdown = state.get("countdown", 0)
            self.draw_center_text(f"¡{countdown}!", HEIGHT//2 - 40, (255, 255, 100), self.big_font)
        elif phase == "playing":
            self.draw_text(f"Objetivo: {KILLS_TO_WIN} kills", WIDTH - 220, 20, (255, 200, 100))
        elif phase == "finished":
            winner = state.get("winner_id")
            self.draw_text(f"¡Ganador: ID {winner}!", WIDTH - 250, 20, (255, 215, 0), self.big_font)

    def draw_ship(self, x, y, angle, color, player_id, hp):
        length = PLAYER_RADIUS * 1.5
        width = PLAYER_RADIUS * 0.8
        tip = (x + math.cos(angle) * length, y + math.sin(angle) * length)
        left = (x + math.cos(angle + 2.5) * width, y + math.sin(angle + 2.5) * width)
        right = (x + math.cos(angle - 2.5) * width, y + math.sin(angle - 2.5) * width)

        shadow_offset = 3
        shadow_points = [(tip[0]+shadow_offset, tip[1]+shadow_offset),
                         (left[0]+shadow_offset, left[1]+shadow_offset),
                         (right[0]+shadow_offset, right[1]+shadow_offset)]
        pygame.draw.polygon(self.screen, (20, 20, 30), shadow_points)

        pygame.draw.polygon(self.screen, color, [tip, left, right])
        pygame.draw.polygon(self.screen, (255, 255, 255), [tip, left, right], 2)

        cx = x + math.cos(angle) * (length * 0.5)
        cy = y + math.sin(angle) * (length * 0.5)
        pygame.draw.circle(self.screen, (200, 230, 255), (int(cx), int(cy)), 6)
        pygame.draw.circle(self.screen, (100, 150, 200), (int(cx), int(cy)), 3)

        back_x = x - math.cos(angle) * (length * 0.3)
        back_y = y - math.sin(angle) * (length * 0.3)
        motor_w = 10
        motor_h = 6
        motor_rect = pygame.Rect(back_x - motor_w//2, back_y - motor_h//2, motor_w, motor_h)
        pygame.draw.rect(self.screen, (200, 100, 50), motor_rect)
        pygame.draw.rect(self.screen, (255, 150, 50), motor_rect, 1)

        # Barra de vida (ahora debajo de la nave)
        hp_width = 30
        hp_ratio = max(0, hp) / PLAYER_HEALTH
        bar_x = x - hp_width//2
        bar_y = y + PLAYER_RADIUS + 4  # debajo
        pygame.draw.rect(self.screen, (40, 40, 40), (bar_x, bar_y, hp_width, 4))
        pygame.draw.rect(self.screen, (80, 220, 100), (bar_x, bar_y, int(hp_width * hp_ratio), 4))

        # ID sobre la nave (ligeramente arriba)
        id_text = self.font.render(str(player_id), True, (20, 20, 30))
        self.screen.blit(id_text, (x - id_text.get_width()//2, y - PLAYER_RADIUS - 8))

    def draw_players(self):
        with self.state_lock:
            state = self.state
        if not state:
            return

        for player in state.get("players", []):
            player_id = player.get("id")
            if player_id == self.player_id and self.predictor.initialized:
                px, py = self.predictor.get_position()
                x, y = int(px), int(py)
            else:
                x, y = int(player.get("x", 0)), int(player.get("y", 0))

            color = SHIP_COLORS.get(player_id, (210, 210, 210))
            aim = player.get("aim", [1, 0])
            angle = math.atan2(aim[1], aim[0])
            hp = player.get("hp", 100)

            sprite = self.player_sprites.get(player_id)
            if sprite:
                rot = pygame.transform.rotate(sprite, -math.degrees(angle))
                rect = rot.get_rect(center=(x, y))
                self.screen.blit(rot, rect)
                # Barra de vida debajo del sprite
                hp_width = 30
                hp_ratio = max(0, hp) / PLAYER_HEALTH
                bar_x = x - hp_width//2
                bar_y = y + PLAYER_RADIUS + 4
                pygame.draw.rect(self.screen, (40, 40, 40), (bar_x, bar_y, hp_width, 4))
                pygame.draw.rect(self.screen, (80, 220, 100), (bar_x, bar_y, int(hp_width * hp_ratio), 4))
            else:
                self.draw_ship(x, y, angle, color, player_id, hp)

            if player_id == self.player_id:
                pygame.draw.circle(self.screen, (255, 255, 100), (x, y), PLAYER_RADIUS + 4, 2)

    def draw_ready_button(self):
        phase = self.state.get("phase") if self.state else "waiting"
        if phase not in ("waiting", "ready_check"):
            return

        if self.is_ready:
            pygame.draw.rect(self.screen, (50, 180, 80), self.ready_button_rect, border_radius=8)
            self.draw_center_text("✓ LISTO", self.ready_button_rect.y + 10, (255, 255, 255), self.big_font)
            return

        color = (70, 130, 200) if self.ready_button_rect.collidepoint(pygame.mouse.get_pos()) else (40, 80, 150)
        pygame.draw.rect(self.screen, color, self.ready_button_rect, border_radius=8)
        pygame.draw.rect(self.screen, (255, 255, 255), self.ready_button_rect, 2, border_radius=8)
        self.draw_center_text("EMPEZAR", self.ready_button_rect.y + 10, (255, 255, 255), self.big_font)
        self.draw_center_text("Presiona el botón para estar listo", self.ready_button_rect.y - 35, (200, 200, 255), self.font)

    def draw_pickups(self):
        with self.state_lock:
            state = self.state
        if not state:
            return
        for pickup in state.get("pickups", []):
            x, y = int(pickup.get("x", 0)), int(pickup.get("y", 0))
            ptype = pickup.get("type")
            if ptype == "weapon":
                pygame.draw.circle(self.screen, (220, 50, 50), (x, y), PICKUP_RADIUS)
                pygame.draw.circle(self.screen, (255, 100, 100), (x, y), PICKUP_RADIUS, 2)
                label = self.font.render("W", True, (255, 255, 255))
                self.screen.blit(label, (x - label.get_width()//2, y - label.get_height()//2))
            elif ptype == "health":
                pygame.draw.circle(self.screen, (50, 180, 80), (x, y), PICKUP_RADIUS)
                pygame.draw.circle(self.screen, (100, 230, 130), (x, y), PICKUP_RADIUS, 2)
                label = self.font.render("+", True, (255, 255, 255))
                self.screen.blit(label, (x - label.get_width()//2, y - label.get_height()//2))

    def draw_bullets(self):
        with self.state_lock:
            state = self.state
        if not state:
            return
        for bullet in state.get("bullets", []):
            x, y = int(bullet.get("x", 0)), int(bullet.get("y", 0))
            pygame.draw.circle(self.screen, (250, 245, 210), (x, y), BULLET_RADIUS)
            pygame.draw.circle(self.screen, (255, 255, 200), (x, y), BULLET_RADIUS+2, 1)

    def draw_ranking(self, state):
        ranking = state.get("ranking", [])
        if not ranking:
            return
        bg = pygame.Surface((WIDTH, HEIGHT))
        bg.set_alpha(180)
        bg.fill((0, 0, 20))
        self.screen.blit(bg, (0, 0))

        y = 120
        self.draw_center_text("RANKING FINAL", y, (255, 215, 0), self.big_font)
        y += 60
        for entry in ranking:
            rank = entry.get("rank", 0)
            name = entry.get("name", "?")
            score = entry.get("score", 0)
            deaths = entry.get("deaths", 0)
            damage = entry.get("damage", 0)
            text = f"{rank}. {name}  Kills:{score}  Muertes:{deaths}  Daño:{damage}"
            color = (255, 215, 0) if rank == 1 else (235, 235, 235)
            self.draw_text(text, WIDTH//2 - 150, y, color, self.font)
            y += 30

    def render(self):
        self.draw_background()
        pygame.draw.line(self.screen, (80, 80, 100), (0, 60), (WIDTH, 60), 2)
        self.draw_pickups()
        self.draw_bullets()
        self.draw_players()
        self.draw_hud()
        self.draw_ready_button()
        if self.state and self.state.get("phase") == "finished":
            self.draw_ranking(self.state)
        pygame.display.flip()

    def run(self):
        send_thread = threading.Thread(target=self._send_loop, daemon=True)
        receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
        send_thread.start()
        receive_thread.start()

        last_frame = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            dt = min(now - last_frame, 0.05)
            last_frame = now

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.state and self.state.get("phase") in ("waiting", "ready_check"):
                        if not self.is_ready and self.ready_button_rect.collidepoint(event.pos):
                            self.send_ready()

            if self.player_id is None and now - self.last_connect_sent > 1:
                self.send_connect()
                self.last_connect_sent = now

            self.capture_input()
            with self.input_lock:
                keys_for_prediction = dict(self.local_keys)
            self.predictor.apply_input(keys_for_prediction, dt)

            with self.state_lock:
                current_state = self.state
                prev_state = self.prev_state

            if prev_state and current_state:
                prev_players = {p["id"]: p for p in prev_state.get("players", [])}
                curr_players = {p["id"]: p for p in current_state.get("players", [])}
                local_prev = prev_players.get(self.player_id) if self.player_id is not None else None
                local_curr = curr_players.get(self.player_id) if self.player_id is not None else None

                if local_prev and local_curr:
                    prev_hp = local_prev["hp"]
                    curr_hp = local_curr["hp"]
                    if prev_hp != curr_hp:
                        print(f"HP local: {prev_hp} -> {curr_hp}")
                    if curr_hp < prev_hp and curr_hp > 0:
                        self.sounds["hit"].play()
                    if prev_hp > 0 and curr_hp == 100 and prev_hp <= 20:
                        self.sounds["kill"].play()

                if prev_state.get("phase") != "finished" and current_state.get("phase") == "finished":
                    self.sounds["game_over"].play()

            self.render()
            self.clock.tick(60)

        if self.player_id is not None:
            self.send({"type": "disconnect", "id": self.player_id})
        self.running = False
        send_thread.join(timeout=1)
        receive_thread.join(timeout=1)
        pygame.quit()


if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    server_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    name = sys.argv[3] if len(sys.argv) > 3 else "Jugador"
    client = GameClient(server_ip, server_port, name)
    client.run()