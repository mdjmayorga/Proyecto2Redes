import socket
import sys
import threading
import time

import pygame

from common import (
    BULLET_RADIUS,
    CLIENT_INPUT_RATE,
    HEIGHT,
    PLAYER_COLORS,
    PLAYER_HEALTH,
    PLAYER_RADIUS,
    PLAYER_SPEED,
    WIDTH,
    clamp,
    decode_message,
    encode_message,
    normalize,
)


class LocalPredictor:
    """Predice la posición local del jugador entre actualizaciones del servidor.

    Aplica la ecuación: pos_predicha = pos_oficial + vel_actual * dt
    y corrige con interpolación cuando llega un nuevo estado del servidor.
    """

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

        pygame.display.set_caption("Shooter 2D - Cliente")

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("Arial", 18)
        self.big_font = pygame.font.SysFont("Arial", 36, bold=True)

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

    def send(self, message):
        self.sock.sendto(encode_message(message), self.server_address)

    def send_connect(self):
        self.send({"type": "connect", "name": self.name})

    def _send_loop(self):
        print(f"[{threading.current_thread().name}] Hilo iniciado")
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
        print(f"[{threading.current_thread().name}] Hilo iniciado")
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

            elif msg_type == "state":
                with self.state_lock:
                    self.state = message

                if self.player_id is not None:
                    for player in message.get("players", []):
                        if player.get("id") == self.player_id:
                            self.predictor.correct(
                                player.get("x", 0),
                                player.get("y", 0),
                            )
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
            self.local_keys["shoot"] = bool(mouse_buttons[0])
            self.mouse_pos = pygame.mouse.get_pos()

    def draw_text(self, text, x, y, color=(235, 235, 235), font=None):
        image = (font or self.font).render(str(text), True, color)
        self.screen.blit(image, (x, y))

    def draw_center_text(self, text, y, color=(255, 255, 255)):
        image = self.big_font.render(text, True, color)
        x = WIDTH // 2 - image.get_width() // 2

        self.screen.blit(image, (x, y))

    def draw_hud(self):
        with self.state_lock:
            state = self.state

        if not state:
            self.draw_text("Conectando al servidor...", 20, 20)
            return

        phase = state.get("phase")
        time_left = state.get("time_left", 0)

        self.draw_text(f"ID: {self.player_id}", 20, 16)
        self.draw_text(f"Tiempo: {time_left}s", 20, 40)

        y = 70

        self.draw_text("Puntajes", 20, y)

        y += 24

        for player in state.get("players", []):
            marker = "*" if player.get("id") == self.player_id else " "
            text = (
                f"{marker} {player.get('name')} | "
                f"HP {player.get('hp')} | "
                f"Kills {player.get('score')}"
            )

            self.draw_text(text, 20, y)

            y += 22

        if phase == "waiting":
            self.draw_center_text("Esperando jugadores...", HEIGHT // 2 - 20)

        elif phase == "finished":
            winner_id = state.get("winner_id")
            self.draw_center_text(
                f"Partida finalizada - Ganador ID {winner_id}",
                HEIGHT // 2 - 20,
            )

    def draw_players(self):
        with self.state_lock:
            state = self.state

        if not state:
            return

        for player in state.get("players", []):
            player_id = player.get("id")

            if player_id == self.player_id and self.predictor.initialized:
                px, py = self.predictor.get_position()
                x = int(px)
                y = int(py)
            else:
                x = int(player.get("x", 0))
                y = int(player.get("y", 0))

            color = PLAYER_COLORS.get(player_id, (210, 210, 210))

            pygame.draw.circle(
                self.screen,
                color,
                (x, y),
                PLAYER_RADIUS,
            )

            if player_id == self.player_id:
                pygame.draw.circle(
                    self.screen,
                    (255, 255, 255),
                    (x, y),
                    PLAYER_RADIUS + 3,
                    2,
                )

            aim = player.get("aim", [1, 0])
            aim_x = int(x + aim[0] * 28)
            aim_y = int(y + aim[1] * 28)

            pygame.draw.line(
                self.screen,
                (20, 20, 20),
                (x, y),
                (aim_x, aim_y),
                4,
            )

            label = self.font.render(str(player_id), True, (20, 20, 20))

            self.screen.blit(
                label,
                (
                    x - label.get_width() // 2,
                    y - label.get_height() // 2,
                ),
            )

            hp_width = 44
            hp_ratio = max(0, player.get("hp", 0)) / PLAYER_HEALTH

            pygame.draw.rect(
                self.screen,
                (60, 60, 60),
                (x - 22, y - 34, hp_width, 6),
            )

            pygame.draw.rect(
                self.screen,
                (80, 230, 100),
                (x - 22, y - 34, int(hp_width * hp_ratio), 6),
            )

    def draw_bullets(self):
        with self.state_lock:
            state = self.state

        if not state:
            return

        for bullet in state.get("bullets", []):
            x = int(bullet.get("x", 0))
            y = int(bullet.get("y", 0))

            pygame.draw.circle(
                self.screen,
                (250, 245, 210),
                (x, y),
                BULLET_RADIUS,
            )

    def render(self):
        self.screen.fill((28, 31, 38))

        pygame.draw.rect(
            self.screen,
            (80, 85, 95),
            (0, 0, WIDTH, HEIGHT),
            4,
        )

        self.draw_bullets()
        self.draw_players()
        self.draw_hud()

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

            if self.player_id is None and now - self.last_connect_sent > 1:
                self.send_connect()
                self.last_connect_sent = now

            self.capture_input()

            with self.input_lock:
                keys_for_prediction = dict(self.local_keys)

            self.predictor.apply_input(keys_for_prediction, dt)

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
