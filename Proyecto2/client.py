import socket
import sys
import time

import pygame

from common import (
    BULLET_RADIUS,
    CLIENT_INPUT_RATE,
    HEIGHT,
    PLAYER_COLORS,
    PLAYER_HEALTH,
    PLAYER_RADIUS,
    WIDTH,
    decode_message,
    encode_message,
)


class GameClient:
    def __init__(self, server_ip="127.0.0.1", server_port=5000, name="Jugador"):
        pygame.init()

        pygame.display.set_caption("Shooter 2D - Cliente")

        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()

        self.font = pygame.font.SysFont("Arial", 18)
        self.big_font = pygame.font.SysFont("Arial", 36, bold=True)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)

        self.server_address = (server_ip, server_port)

        self.name = name[:16]
        self.player_id = None
        self.state = None

        self.running = True

        self.last_connect_sent = 0.0
        self.last_input_sent = 0.0

    def send(self, message):
        self.sock.sendto(encode_message(message), self.server_address)

    def send_connect(self):
        self.send(
            {
                "type": "connect",
                "name": self.name,
            }
        )

    def send_input(self):
        if self.player_id is None:
            return

        keys = pygame.key.get_pressed()
        mouse_buttons = pygame.mouse.get_pressed()
        mouse_x, mouse_y = pygame.mouse.get_pos()

        message = {
            "type": "input",
            "id": self.player_id,
            "keys": {
                "up": keys[pygame.K_w] or keys[pygame.K_UP],
                "down": keys[pygame.K_s] or keys[pygame.K_DOWN],
                "left": keys[pygame.K_a] or keys[pygame.K_LEFT],
                "right": keys[pygame.K_d] or keys[pygame.K_RIGHT],
                "shoot": mouse_buttons[0],
            },
            "aim": [mouse_x, mouse_y],
        }

        self.send(message)

    def receive_messages(self):
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            except ConnectionResetError:
                break

            message = decode_message(data)

            if not isinstance(message, dict):
                continue

            if message.get("type") == "welcome":
                self.player_id = message.get("id")

            elif message.get("type") == "state":
                self.state = message

            elif message.get("type") == "full":
                print(message.get("reason", "Servidor lleno"))
                self.running = False

    def draw_text(self, text, x, y, color=(235, 235, 235), font=None):
        image = (font or self.font).render(str(text), True, color)
        self.screen.blit(image, (x, y))

    def draw_center_text(self, text, y, color=(255, 255, 255)):
        image = self.big_font.render(text, True, color)
        x = WIDTH // 2 - image.get_width() // 2

        self.screen.blit(image, (x, y))

    def draw_hud(self):
        if not self.state:
            self.draw_text("Conectando al servidor...", 20, 20)
            return

        phase = self.state.get("phase")
        time_left = self.state.get("time_left", 0)

        self.draw_text(f"ID: {self.player_id}", 20, 16)
        self.draw_text(f"Tiempo: {time_left}s", 20, 40)

        y = 70

        self.draw_text("Puntajes", 20, y)

        y += 24

        for player in self.state.get("players", []):
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
            winner_id = self.state.get("winner_id")
            self.draw_center_text(
                f"Partida finalizada - Ganador ID {winner_id}",
                HEIGHT // 2 - 20,
            )

    def draw_players(self):
        if not self.state:
            return

        for player in self.state.get("players", []):
            player_id = player.get("id")
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
        if not self.state:
            return

        for bullet in self.state.get("bullets", []):
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
        while self.running:
            now = time.perf_counter()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False

            if self.player_id is None and now - self.last_connect_sent > 1:
                self.send_connect()
                self.last_connect_sent = now

            if now - self.last_input_sent >= 1 / CLIENT_INPUT_RATE:
                self.send_input()
                self.last_input_sent = now

            self.receive_messages()
            self.render()

            self.clock.tick(60)

        if self.player_id is not None:
            self.send(
                {
                    "type": "disconnect",
                    "id": self.player_id,
                }
            )

        pygame.quit()


if __name__ == "__main__":
    server_ip = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    server_port = int(sys.argv[2]) if len(sys.argv) > 2 else 5000
    name = sys.argv[3] if len(sys.argv) > 3 else "Jugador"

    client = GameClient(server_ip, server_port, name)
    client.run()