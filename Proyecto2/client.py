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
    SPAWN_POINTS,
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


class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5000, name="Jugador"):
        pygame.init()
        pygame.display.set_caption("Tank Wars – Multijugador")
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("Arial", 18)
        self.big_font = pygame.font.SysFont("Arial", 36, bold=True)
        self.hud_font = pygame.font.SysFont("Arial", 16, bold=True)

        
        self.bg_surface = self._prerender_map()

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

        self.ready_button_rect = pygame.Rect(WIDTH // 2 - 110, HEIGHT // 2 + 50, 220, 58)
        self.is_ready = False

        pygame.mixer.init(frequency=22050, size=-16, channels=2, buffer=512)
        self.sounds = {}
        sound_files = {
            "shoot": "assets/sounds/shoot.wav",
            "hit": "assets/sounds/hit.wav",
            "kill": "assets/sounds/kill.wav",
            "game_over": "assets/sounds/game_over.wav",
        }
        for sname, path in sound_files.items():
            try:
                self.sounds[sname] = pygame.mixer.Sound(path)
            except Exception:
                self.sounds[sname] = pygame.mixer.Sound(buffer=bytes([0] * 1000))

        self.player_sprites = {}
        for pid in range(1, 5):
            try:
                img = pygame.image.load(f"assets/sprites/player_{pid}.png").convert_alpha()
                img = pygame.transform.scale(img, (PLAYER_RADIUS * 2, PLAYER_RADIUS * 2))
                self.player_sprites[pid] = img
            except Exception:
                self.player_sprites[pid] = None

    # -------------------------------------------------------------------------
    # Map pre-rendering
    # -------------------------------------------------------------------------

    def _prerender_map(self):
        rng = random.Random(42)   # fixed seed → same map every run
        surface = pygame.Surface((WIDTH, HEIGHT))

        # Alternating grass row bands
        for row_y in range(0, HEIGHT, 8):
            c = (72, 110, 44) if (row_y // 8) % 2 == 0 else (63, 97, 37)
            pygame.draw.rect(surface, c, (0, row_y, WIDTH, 8))

        # Dirt/mud patches
        for _ in range(30):
            px = rng.randint(60, WIDTH - 60)
            py = rng.randint(90, HEIGHT - 40)
            rw = rng.randint(22, 70)
            rh = rng.randint(14, 40)
            pygame.draw.ellipse(surface, (108, 84, 50), (px - rw, py - rh, rw * 2, rh * 2))
            if rw > 30:
                pygame.draw.ellipse(surface, (94, 72, 43),
                                    (px - rw + 5, py - rh + 4, rw * 2 - 10, rh * 2 - 8))

        # Lighter grass tufts
        for _ in range(80):
            px = rng.randint(0, WIDTH)
            py = rng.randint(70, HEIGHT)
            r = rng.randint(6, 20)
            pygame.draw.ellipse(surface, (82, 122, 50), (px - r, py - r // 2, r * 2, r))

        # Tactical grid
        for gx in range(0, WIDTH, 60):
            pygame.draw.line(surface, (55, 86, 33), (gx, 0), (gx, HEIGHT), 1)
        for gy in range(60, HEIGHT, 60):
            pygame.draw.line(surface, (55, 86, 33), (0, gy), (WIDTH, gy), 1)

        # Spawn area markers
        for sx, sy in SPAWN_POINTS:
            pygame.draw.circle(surface, (86, 130, 52), (sx, sy), 30, 2)
            pygame.draw.circle(surface, (86, 130, 52), (sx, sy), 16, 1)

        # Border wall band
        wall_c = (38, 58, 22)
        pygame.draw.rect(surface, wall_c, (0, 0, WIDTH, 20))
        pygame.draw.rect(surface, wall_c, (0, HEIGHT - 20, WIDTH, 20))
        pygame.draw.rect(surface, wall_c, (0, 0, 20, HEIGHT))
        pygame.draw.rect(surface, wall_c, (WIDTH - 20, 0, 20, HEIGHT))

        return surface

    # -------------------------------------------------------------------------
    # Network helpers (unchanged)
    # -------------------------------------------------------------------------

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
                phase = self.state.get("phase") if self.state else "waiting"
                if phase == "playing":
                    self.sounds["shoot"].play()
            self.local_keys["shoot"] = shoot_pressed
            self.mouse_pos = pygame.mouse.get_pos()

    # -------------------------------------------------------------------------
    # Drawing utilities
    # -------------------------------------------------------------------------

    def draw_text(self, text, x, y, color=(235, 235, 235), font=None):
        img = (font or self.font).render(str(text), True, color)
        self.screen.blit(img, (x, y))

    def draw_center_text(self, text, y, color=(255, 255, 255), font=None):
        f = font or self.big_font
        img = f.render(text, True, color)
        x = WIDTH // 2 - img.get_width() // 2
        self.screen.blit(img, (x, y))

    def _rotated_rect_points(self, cx, cy, length, width, angle):
        """Return 4 corners of a rectangle: `length` along `angle`, `width` perpendicular."""
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        hl, hw = length / 2, width / 2
        local = [(hl, hw), (hl, -hw), (-hl, -hw), (-hl, hw)]
        return [
            (cx + lx * cos_a - ly * sin_a, cy + lx * sin_a + ly * cos_a)
            for lx, ly in local
        ]

    # -------------------------------------------------------------------------
    # Background
    # -------------------------------------------------------------------------

    def draw_background(self):
        self.screen.blit(self.bg_surface, (0, 0))

    # -------------------------------------------------------------------------
    # HUD
    # -------------------------------------------------------------------------

    def draw_hud(self):
        with self.state_lock:
            state = self.state
        if not state:
            return

        phase = state.get("phase")
        time_left = state.get("time_left", 0)
        players = state.get("players", [])

        # HUD panel (dark olive, military style)
        hud_surf = pygame.Surface((WIDTH, 62))
        hud_surf.set_alpha(218)
        hud_surf.fill((20, 30, 14))
        self.screen.blit(hud_surf, (0, 0))
        pygame.draw.line(self.screen, (80, 118, 48), (0, 62), (WIDTH, 62), 2)

        # LEFT ZONE: timer + my player label
        minutes = time_left // 60
        seconds = time_left % 60
        if time_left <= 20:
            timer_color = (240, 65, 65)
        elif time_left <= 60:
            timer_color = (255, 220, 55)
        else:
            timer_color = (198, 228, 162)
        timer_surf = self.big_font.render(f"{minutes}:{seconds:02d}", True, timer_color)
        self.screen.blit(timer_surf, (10, 4))

        my_player = next((p for p in players if p.get("id") == self.player_id), None)
        if my_player:
            p_color = PLAYER_COLORS.get(self.player_id, (200, 200, 200))
            pygame.draw.circle(self.screen, p_color, (14, 52), 5)
            self.draw_text(f" TANK #{self.player_id} – {my_player.get('name', '?')}",
                           16, 44, p_color, self.hud_font)

        # CENTER ZONE: one card per player
        card_w = 140
        n = len(players)
        cards_total = n * card_w
        card_start = max(185, WIDTH // 2 - cards_total // 2)

        for idx, player in enumerate(players):
            pid = player.get("id")
            pname = player.get("name", "?")[:7]
            php = player.get("hp", 0)
            pkills = player.get("score", 0)
            ppw = player.get("pw", False)
            is_local = (pid == self.player_id)
            tank_color = SHIP_COLORS.get(pid, (180, 180, 180))

            cx = card_start + idx * card_w

            # Card background
            card_surf = pygame.Surface((card_w - 4, 56))
            card_surf.set_alpha(215)
            card_surf.fill((50, 70, 30) if is_local else (30, 44, 18))
            self.screen.blit(card_surf, (cx + 2, 3))
            if is_local:
                pygame.draw.rect(self.screen, tank_color,
                                 (cx + 2, 3, card_w - 4, 56), 2, border_radius=3)

            # Color dot + name + kills
            pygame.draw.circle(self.screen, tank_color, (cx + 11, 14), 6)
            self.draw_text(pname, cx + 21, 6, (220, 226, 190), self.hud_font)
            kc = (255, 215, 50) if pkills > 0 else (128, 138, 108)
            self.draw_text(f"K:{pkills}", cx + 102, 6, kc, self.hud_font)

            # HP bar
            hp_ratio = max(0.0, php / PLAYER_HEALTH)
            if hp_ratio > 0.6:
                hp_color = (55, 195, 55)
            elif hp_ratio > 0.3:
                hp_color = (215, 185, 35)
            else:
                hp_color = (215, 50, 50)
            bw = card_w - 16
            pygame.draw.rect(self.screen, (26, 34, 16), (cx + 6, 26, bw, 8))
            pygame.draw.rect(self.screen, hp_color, (cx + 6, 26, int(bw * hp_ratio), 8))
            pygame.draw.rect(self.screen, (66, 90, 42), (cx + 6, 26, bw, 8), 1)

            hp_label = f"{php} HP"
            hp_label_c = (182, 198, 152)
            if ppw:
                hp_label += "  PWR"
                hp_label_c = (255, 125, 55)
            self.draw_text(hp_label, cx + 6, 38, hp_label_c, self.hud_font)

        # RIGHT ZONE: phase objective / status
        rx = WIDTH - 182
        if phase == "waiting":
            self.draw_text("ESPERANDO...", rx, 6, (200, 185, 78), self.hud_font)
            self.draw_text(f"Jugadores: {n}", rx, 24, (158, 198, 108), self.hud_font)
            self.draw_text("Min. 2 para iniciar", rx, 42, (138, 152, 102), self.hud_font)
        elif phase == "ready_check":
            ready = state.get("ready_count", 0)
            total = state.get("total_players", 0)
            rc = (78, 228, 78) if ready == total else (200, 185, 78)
            self.draw_text(f"LISTOS: {ready}/{total}", rx, 6, rc, self.hud_font)
            sub = "Esperando a los demas..." if ready < total else "¡Comenzando!"
            self.draw_text(sub, rx, 24, (168, 198, 128), self.hud_font)
        elif phase == "playing":
            self.draw_text(f"META: {KILLS_TO_WIN} KILLS", rx, 14, (220, 195, 68), self.hud_font)
        elif phase == "finished":
            winner = state.get("winner_id")
            wname = next((p.get("name", "?") for p in players if p.get("id") == winner),
                         f"#{winner}")
            self.draw_text("GANADOR:", rx, 6, (255, 215, 0), self.hud_font)
            self.draw_text(wname, rx, 24, (255, 215, 0), self.hud_font)

        # Countdown overlay (big centered panel)
        if phase == "countdown":
            countdown = state.get("countdown", 0)
            ov = pygame.Surface((240, 110))
            ov.set_alpha(192)
            ov.fill((14, 22, 10))
            self.screen.blit(ov, (WIDTH // 2 - 120, HEIGHT // 2 - 65))
            pygame.draw.rect(self.screen, (88, 148, 55),
                             (WIDTH // 2 - 120, HEIGHT // 2 - 65, 240, 110), 2, border_radius=6)
            self.draw_center_text("COMIENZA EN", HEIGHT // 2 - 62, (158, 212, 102), self.hud_font)
            self.draw_center_text(str(countdown), HEIGHT // 2 - 38, (255, 235, 52), self.big_font)

    # -------------------------------------------------------------------------
    # Tank rendering (replaces draw_ship)
    # -------------------------------------------------------------------------

    def draw_tank(self, x, y, angle, color, player_id, hp):
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        # Right perpendicular direction (clockwise 90° on screen)
        rgt_x, rgt_y = sin_a, -cos_a

        HULL_LEN   = 36
        HULL_W     = 26
        TRACK_LEN  = 38
        TRACK_W    = 9
        TRACK_OFF  = 17   # lateral offset from hull center to track center
        TURRET_R   = 11
        BARREL_LEN = 22
        BARREL_W   = 5

        track_c  = (50, 44, 34)
        tread_c  = (36, 32, 24)
        turret_c = tuple(min(255, c + 25) for c in color)
        hull_hi  = tuple(min(255, c + 35) for c in color)
        hull_dk  = tuple(max(0, c - 45) for c in color)

        # Drop shadow
        shd = [(p[0] + 4, p[1] + 5)
               for p in self._rotated_rect_points(x, y, HULL_LEN + 4, HULL_W + 4, angle)]
        pygame.draw.polygon(self.screen, (28, 44, 16), shd)

        # Tracks (left side = -1, right side = +1)
        for side in (-1, 1):
            tx = x + rgt_x * TRACK_OFF * side
            ty = y + rgt_y * TRACK_OFF * side
            pygame.draw.polygon(self.screen, track_c,
                                self._rotated_rect_points(tx, ty, TRACK_LEN, TRACK_W, angle))
            # Tread segments (cross-lines along the track)
            for step in range(-2, 3):
                tc_cx = tx + cos_a * step * 7
                tc_cy = ty + sin_a * step * 7
                pygame.draw.polygon(self.screen, tread_c,
                                    self._rotated_rect_points(tc_cx, tc_cy, 2, TRACK_W, angle))

        # Hull body
        hull_pts = self._rotated_rect_points(x, y, HULL_LEN, HULL_W, angle)
        pygame.draw.polygon(self.screen, color, hull_pts)
        # Front highlight panel (lighter front section)
        fc_x = x + cos_a * 8
        fc_y = y + sin_a * 8
        pygame.draw.polygon(self.screen, hull_hi,
                            self._rotated_rect_points(fc_x, fc_y, 16, HULL_W - 4, angle))
        pygame.draw.polygon(self.screen, hull_dk, hull_pts, 2)

        # Barrel (drawn before turret so turret sits on top)
        b_cx = x + cos_a * (TURRET_R + BARREL_LEN // 2 - 2)
        b_cy = y + sin_a * (TURRET_R + BARREL_LEN // 2 - 2)
        pygame.draw.polygon(self.screen, (84, 76, 66),
                            self._rotated_rect_points(b_cx, b_cy, BARREL_LEN, BARREL_W, angle))
        pygame.draw.polygon(self.screen, (52, 46, 38),
                            self._rotated_rect_points(b_cx, b_cy, BARREL_LEN, BARREL_W, angle), 1)

        # Turret circle
        pygame.draw.circle(self.screen, turret_c, (int(x), int(y)), TURRET_R)
        pygame.draw.circle(self.screen, hull_dk, (int(x), int(y)), TURRET_R, 2)
        # Hatch detail
        pygame.draw.circle(self.screen, hull_dk, (int(x), int(y)), 4)

        # Health bar
        bar_w = 38
        hp_ratio = max(0.0, hp / PLAYER_HEALTH)
        bx = int(x) - bar_w // 2
        by = int(y) + PLAYER_RADIUS + 6
        pygame.draw.rect(self.screen, (24, 24, 24), (bx - 1, by - 1, bar_w + 2, 7))
        if hp_ratio > 0.6:
            bar_color = (52, 198, 52)
        elif hp_ratio > 0.3:
            bar_color = (212, 192, 36)
        else:
            bar_color = (212, 48, 48)
        pygame.draw.rect(self.screen, bar_color, (bx, by, int(bar_w * hp_ratio), 5))

        # Player ID label (dark background for readability on grass)
        id_surf = self.hud_font.render(str(player_id), True, (238, 238, 208))
        lx = int(x) - id_surf.get_width() // 2
        ly = int(y) - PLAYER_RADIUS - 22
        pygame.draw.rect(self.screen, (18, 18, 18),
                         (lx - 2, ly, id_surf.get_width() + 4, id_surf.get_height()))
        self.screen.blit(id_surf, (lx, ly))

    # -------------------------------------------------------------------------
    # Players
    # -------------------------------------------------------------------------

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
                hp_ratio = max(0, hp) / PLAYER_HEALTH
                bx = x - 19
                by = y + PLAYER_RADIUS + 4
                pygame.draw.rect(self.screen, (24, 24, 24), (bx - 1, by - 1, 40, 7))
                bc = (52, 198, 52) if hp_ratio > 0.6 else (212, 192, 36) if hp_ratio > 0.3 else (212, 48, 48)
                pygame.draw.rect(self.screen, bc, (bx, by, int(38 * hp_ratio), 5))
            else:
                self.draw_tank(x, y, angle, color, player_id, hp)

            # Yellow selection ring for local player
            if player_id == self.player_id:
                pygame.draw.circle(self.screen, (255, 255, 78), (x, y), PLAYER_RADIUS + 5, 2)

    # -------------------------------------------------------------------------
    # Ready button
    # -------------------------------------------------------------------------

    def draw_ready_button(self):
        if self.player_id is None:
            return
        phase = self.state.get("phase") if self.state else "waiting"
        if phase not in ("waiting", "ready_check"):
            return

        btn_cy = self.ready_button_rect.y + self.ready_button_rect.height // 2 - 18

        if self.is_ready:
            pygame.draw.rect(self.screen, (50, 180, 80), self.ready_button_rect, border_radius=10)
            pygame.draw.rect(self.screen, (100, 230, 120), self.ready_button_rect, 2, border_radius=10)
            self.draw_center_text("LISTO", btn_cy, (255, 255, 255), self.big_font)
            return

        # Hint text with dark backing for grass readability
        hint_surf = self.font.render("Presiona el boton para estar listo", True, (198, 210, 162))
        hx = WIDTH // 2 - hint_surf.get_width() // 2
        hy = self.ready_button_rect.y - 38
        bg_h = pygame.Surface((hint_surf.get_width() + 10, hint_surf.get_height() + 4))
        bg_h.set_alpha(162)
        bg_h.fill((18, 28, 12))
        self.screen.blit(bg_h, (hx - 5, hy - 2))
        self.screen.blit(hint_surf, (hx, hy))

        btn_c = (70, 130, 200) if self.ready_button_rect.collidepoint(pygame.mouse.get_pos()) else (40, 80, 150)
        pygame.draw.rect(self.screen, btn_c, self.ready_button_rect, border_radius=10)
        pygame.draw.rect(self.screen, (198, 218, 178), self.ready_button_rect, 2, border_radius=10)
        self.draw_center_text("EMPEZAR", btn_cy, (255, 255, 255), self.big_font)

    # -------------------------------------------------------------------------
    # Pickups
    # -------------------------------------------------------------------------

    def draw_pickups(self):
        with self.state_lock:
            state = self.state
        if not state:
            return
        for pickup in state.get("pickups", []):
            x, y = int(pickup.get("x", 0)), int(pickup.get("y", 0))
            ptype = pickup.get("type")
            if ptype == "weapon":
                # Golden circle with 5-pointed star
                pygame.draw.circle(self.screen, (210, 165, 16), (x, y), PICKUP_RADIUS)
                pygame.draw.circle(self.screen, (255, 215, 68), (x, y), PICKUP_RADIUS, 2)
                star_pts = []
                for i in range(10):
                    angle = -math.pi / 2 + i * math.pi / 5
                    r = 9 if i % 2 == 0 else 4
                    star_pts.append((x + r * math.cos(angle), y + r * math.sin(angle)))
                pygame.draw.polygon(self.screen, (255, 252, 180), star_pts)
                pygame.draw.polygon(self.screen, (160, 90, 0), star_pts, 1)
            elif ptype == "health":
                # White medkit with red cross
                pygame.draw.circle(self.screen, (212, 212, 208), (x, y), PICKUP_RADIUS)
                pygame.draw.circle(self.screen, (208, 38, 38), (x, y), PICKUP_RADIUS, 2)
                arm = PICKUP_RADIUS - 4
                pygame.draw.rect(self.screen, (198, 26, 26), (x - 2, y - arm, 4, arm * 2))
                pygame.draw.rect(self.screen, (198, 26, 26), (x - arm, y - 2, arm * 2, 4))

    # -------------------------------------------------------------------------
    # Bullets
    # -------------------------------------------------------------------------

    def draw_bullets(self):
        with self.state_lock:
            state = self.state
        if not state:
            return
        for bullet in state.get("bullets", []):
            x, y = int(bullet.get("x", 0)), int(bullet.get("y", 0))
            # Orange shell — clearly visible on green grass
            pygame.draw.circle(self.screen, (255, 178, 26), (x, y), BULLET_RADIUS)
            pygame.draw.circle(self.screen, (255, 228, 118), (x, y), BULLET_RADIUS - 1)
            pygame.draw.circle(self.screen, (158, 82, 0), (x, y), BULLET_RADIUS + 1, 1)

    # -------------------------------------------------------------------------
    # Ranking screen
    # -------------------------------------------------------------------------

    def draw_ranking(self, state):
        ranking = state.get("ranking", [])
        if not ranking:
            return

        # Semi-transparent dark overlay
        bg = pygame.Surface((WIDTH, HEIGHT))
        bg.set_alpha(202)
        bg.fill((10, 18, 8))
        self.screen.blit(bg, (0, 0))

        # Centered panel
        panel_w = 520
        panel_h = 108 + len(ranking) * 34
        panel_x = WIDTH // 2 - panel_w // 2
        panel_y = HEIGHT // 2 - panel_h // 2
        panel_surf = pygame.Surface((panel_w, panel_h))
        panel_surf.set_alpha(240)
        panel_surf.fill((20, 35, 12))
        self.screen.blit(panel_surf, (panel_x, panel_y))
        pygame.draw.rect(self.screen, (80, 130, 45),
                         (panel_x, panel_y, panel_w, panel_h), 2, border_radius=6)

        y = panel_y + 16
        self.draw_center_text("RESULTADO FINAL", y, (255, 215, 0), self.big_font)
        y += 52

        # Column headers
        hx = panel_x + 20
        self.draw_text("Jugador",  hx,       y, (138, 182, 102), self.hud_font)
        self.draw_text("Kills",    hx + 228, y, (138, 182, 102), self.hud_font)
        self.draw_text("Muertes",  hx + 308, y, (138, 182, 102), self.hud_font)
        self.draw_text("Dano",     hx + 408, y, (138, 182, 102), self.hud_font)
        y += 18
        pygame.draw.line(self.screen, (68, 112, 40),
                         (panel_x + 15, y), (panel_x + panel_w - 15, y))
        y += 8

        for entry in ranking:
            rank   = entry.get("rank", 0)
            ename  = entry.get("name", "?")
            score  = entry.get("score", 0)
            deaths = entry.get("deaths", 0)
            damage = entry.get("damage", 0)
            ec = (255, 215, 0) if rank == 1 else (198, 216, 172)
            self.draw_text(f"{rank}. {ename}", hx,       y, ec, self.font)
            self.draw_text(str(score),          hx + 235, y, ec, self.font)
            self.draw_text(str(deaths),         hx + 318, y, ec, self.font)
            self.draw_text(str(damage),         hx + 418, y, ec, self.font)
            y += 30

    # -------------------------------------------------------------------------
    # Render pipeline
    # -------------------------------------------------------------------------

    def render(self):
        self.draw_background()
        self.draw_pickups()
        self.draw_bullets()
        self.draw_players()
        self.draw_hud()
        self.draw_ready_button()
        if self.state and self.state.get("phase") == "finished":
            self.draw_ranking(self.state)
        pygame.display.flip()

    # -------------------------------------------------------------------------
    # Main loop (unchanged game logic)
    # -------------------------------------------------------------------------

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
                    phase = self.state.get("phase") if self.state else "waiting"
                    if self.player_id is not None and phase in ("waiting", "ready_check"):
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
                    if curr_hp < prev_hp and curr_hp > 0:
                        self.sounds["hit"].play()
                    if prev_hp > 0 and curr_hp == 100 and prev_hp <= 20:
                        self.sounds["kill"].play()

                if prev_state.get("phase") != "finished" and current_state.get("phase") == "finished":
                    self.sounds["game_over"].play()

                prev_phase = prev_state.get("phase")
                curr_phase = current_state.get("phase")
                if (curr_phase in ("waiting", "ready_check")
                        and prev_phase not in ("waiting", "ready_check")):
                    self.is_ready = False

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
