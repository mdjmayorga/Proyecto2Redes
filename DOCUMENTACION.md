# Proyecto2Redes — Documentación Completa del Juego

## 1. Estructura del Proyecto

```
Proyecto2Redes/
├── Proyecto2/
│   ├── client.py          # Aplicación cliente (Pygame)
│   ├── server.py          # Servidor autoritativo (UDP)
│   ├── common.py          # Constantes, utilidades y obstáculos compartidos
│   └── assets/
│       └── sounds/
│           ├── shoot.wav
│           ├── hit.wav
│           ├── kill.wav
│           └── game_over.wav
└── .git/
```

---

## 2. Constantes y Valores de Configuración

### Pantalla
| Constante | Valor | Unidad |
|-----------|-------|--------|
| `WIDTH` | 960 | píxeles |
| `HEIGHT` | 540 | píxeles |

### Jugadores
| Constante | Valor | Unidad |
|-----------|-------|--------|
| `PLAYER_RADIUS` | 18 | píxeles |
| `PLAYER_SPEED` | 220 | px/s |
| `PLAYER_HEALTH` | 100 | HP |
| `MAX_PLAYERS` | 4 | jugadores |
| `MIN_PLAYERS_TO_START` | 2 | jugadores |

### Balas
| Constante | Valor | Unidad |
|-----------|-------|--------|
| `BULLET_RADIUS` | 5 | píxeles |
| `BULLET_SPEED` | 520 | px/s |
| `BULLET_TTL` | 1.4 | segundos |
| `BASE_DAMAGE` | 10 | HP |
| `SHOOT_COOLDOWN` | 0.35 | segundos |
| `POWER_SHOOT_COOLDOWN` | 0.12 | segundos |

### Pickups
| Constante | Valor | Unidad |
|-----------|-------|--------|
| `PICKUP_RADIUS` | 14 | píxeles |
| `PICKUP_RESPAWN_TIME` | 10.0 | segundos |
| `POWER_WEAPON_DURATION` | 15.0 | segundos |
| `SPAWN_MARGIN` | 60 | píxeles (desde los bordes) |

### Obstáculos
| Constante | Valor | Descripción |
|-----------|-------|-------------|
| `OBSTACLES` | lista de 6 tuplas | Rectángulos `(x, y, w, h)` generados con semilla 42 |
| Zona permitida X | 180 – 780 px | Alejado de bordes y spawn corners |
| Zona permitida Y | 150 – 390 px | Zona central del mapa |
| Ancho mínimo/máximo | 42 – 72 px | — |
| Alto mínimo/máximo | 30 – 56 px | — |
| Exclusión spawn | 70 px | Radio alrededor de cada punto de spawn |
| Separación mínima | 15 px | Gap entre obstáculos adyacentes |

### Partida
| Constante | Valor | Unidad |
|-----------|-------|--------|
| `MATCH_SECONDS` | 120 | segundos |
| `KILLS_TO_WIN` | 3 | kills |
| `COUNTDOWN_SECONDS` | 3 | segundos |

### Red
| Constante | Valor | Unidad |
|-----------|-------|--------|
| `SERVER_TICK` | 60 | Hz |
| `BROADCAST_RATE` | 20 | Hz |
| `CLIENT_INPUT_RATE` | 30 | Hz |
| `DISCONNECT_SECONDS` | 10 | segundos |

### Puntos de Spawn
```python
SPAWN_POINTS = [
    (80, 80),    # Arriba-izquierda
    (880, 80),   # Arriba-derecha
    (80, 460),   # Abajo-izquierda
    (880, 460),  # Abajo-derecha
]
```

### Colores por Jugador
| ID | Color (relleno) | Color (nave) |
|----|-----------------|--------------|
| 1  | (70, 160, 255) Azul | (100, 180, 255) Azul claro |
| 2  | (255, 95, 95) Rojo | (255, 120, 120) Rojo claro |
| 3  | (120, 220, 120) Verde | (140, 255, 140) Verde claro |
| 4  | (240, 210, 80) Amarillo | (255, 230, 120) Amarillo claro |

---

## 3. Entidades del Juego

### Jugador (Dataclass `Player`)

| Campo | Tipo | Valor por defecto | Descripción |
|-------|------|-------------------|-------------|
| `player_id` | int | — | ID único (1–4) |
| `address` | tuple[str, int] | — | Dirección IP:puerto |
| `name` | str | — | Nombre (máx. 16 chars) |
| `x`, `y` | float | — | Posición |
| `hp` | int | 100 | Vida actual |
| `score` | int | 0 | Kills |
| `deaths` | int | 0 | Muertes |
| `damage_dealt` | int | 0 | Daño total infligido |
| `aim_x`, `aim_y` | float | [1, 0] | Dirección de apuntado |
| `last_seen` | float | — | Timestamp último mensaje |
| `next_shot_time` | float | — | Cooldown de disparo |
| `has_power_weapon` | bool | False | Arma potenciada activa |
| `power_weapon_end` | float | — | Timestamp fin arma potenciada |
| `was_shooting` | bool | False | Estado anterior del disparo |
| `ready` | bool | False | Listo para iniciar partida |
| `keys` | dict | — | Estado de teclas de movimiento |

**Forma visual:** Triángulo con cockpit, motor y barra de vida (ver sección 7).

---

### Bala (Dataclass `Bullet`)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `owner_id` | int | ID del jugador que disparó |
| `x`, `y` | float | Posición actual |
| `vx`, `vy` | float | Componentes de velocidad |
| `ttl` | float | Tiempo de vida restante (inicio: 1.4s) |

**Forma visual:** Círculo crema/blanco apagado de 5px de radio con borde de 7px.

**Mecánica de disparo:**
- La bala se genera desplazada desde el jugador en la dirección de apuntado:
  ```
  offset = PLAYER_RADIUS + BULLET_RADIUS + 2 = 25 px
  start_x = player.x + aim_x * 25
  start_y = player.y + aim_y * 25
  vx = aim_x * 520
  vy = aim_y * 520
  ```
- El disparo normal requiere soltar y volver a presionar (detección de flanco).
- El arma potenciada dispara automáticamente mientras se mantiene presionado.

---

### Pickup (Dataclass `Pickup`)

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `pickup_id` | int | ID único |
| `pickup_type` | str | `"weapon"` o `"health"` |
| `x`, `y` | float | Posición |
| `active` | bool | Disponible para recoger |
| `respawn_at` | float | Timestamp de respawn |

---

### Obstáculos

Los obstáculos son rectángulos estáticos generados una sola vez al importar `common.py` con semilla fija (`seed=42`). Son idénticos en servidor y cliente sin necesidad de sincronización por red.

**Posiciones generadas (seed=42):**
| # | x | y | w | h |
|---|---|---|---|---|
| 1 | 205 | 339 | 62 | 33 |
| 2 | 408 | 185 | 50 | 37 |
| 3 | 210 | 173 | 55 | 31 |
| 4 | 697 | 304 | 48 | 37 |
| 5 | 383 | 333 | 42 | 47 |
| 6 | 609 | 206 | 62 | 52 |

**Forma visual:** Bloque de concreto/bunker con highlight en aristas superior-izquierda, sombra en aristas inferior-derecha y línea central decorativa.

| Tipo | Color relleno | Color borde | Etiqueta | Efecto |
|------|--------------|-------------|----------|--------|
| `weapon` | (220, 50, 50) Rojo | (255, 100, 100) | "W" | Arma potenciada 15s |
| `health` | (50, 180, 80) Verde | (100, 230, 130) | "+" | Vida al máximo (100 HP) |

**Forma visual:** Círculo de 14px de radio con borde de 2px y etiqueta centrada.

---

## 4. Mecánicas de Juego

### Movimiento
- **Teclas:** W/↑ (arriba), S/↓ (abajo), A/← (izquierda), D/→ (derecha).
- El movimiento diagonal se **normaliza** (no multiplica la velocidad):
  ```
  dx, dy = normalize(raw_input)
  player.x = clamp(player.x + dx * 220 * dt, 18, 942)
  player.y = clamp(player.y + dy * 220 * dt, 18, 522)
  ```
- Los jugadores no pueden salir del mapa (clamping a `PLAYER_RADIUS` desde los bordes).

### Apuntado
- Dirección del mouse → vector normalizado `(aim_x, aim_y)`.
- El ángulo de rotación de la nave: `angle = atan2(aim_y, aim_x)`.
- La nave siempre apunta hacia el cursor.

### Sistema de Disparo

| Modo | Cooldown | Activación | Duración |
|------|----------|------------|----------|
| Normal | 0.35 s | Clic (flanco de subida) | — |
| Arma potenciada | 0.12 s | Mantener clic | 15 s |

### Colisiones

**Bala → Jugador** (radio combinado = 23px):
```
if dist² ≤ (18 + 5)² → hit
    player.hp -= 10
    if player.hp ≤ 0 → player muere, respawn
```

**Jugador → Jugador** (separación física):
```
min_dist = 36 px
if dist < 36:
    overlap = (36 - dist) / 2 * 1.8
    separar jugadores a lo largo de la normal de colisión
```
Factor `1.8` exagera la separación para evitar superposición visual.

**Jugador → Pickup** (radio combinado = 32px):
```
if dist² ≤ (18 + 14)² → pickup recogido
    pickup.active = False
    pickup.respawn_at = now + 10.0
```

**Jugador → Obstáculo** (círculo vs. rectángulo AABB):
```
# Para cada obstáculo (ox, oy, ow, oh):
closest_x = clamp(player.x, ox, ox + ow)
closest_y = clamp(player.y, oy, oy + oh)
dist² = (player.x - closest_x)² + (player.y - closest_y)²
if dist² < PLAYER_RADIUS² → push_circle_from_rect()
    # El jugador es empujado en la dirección normal al punto más cercano
    # Caso especial: si el centro está dentro del rect, empujar por la arista más cercana
```

**Bala → Obstáculo** (círculo vs. rectángulo AABB):
```
# Para cada obstáculo:
closest_x = clamp(bullet.x, ox, ox + ow)
closest_y = clamp(bullet.y, oy, oy + oh)
dist² = (bullet.x - closest_x)² + (bullet.y - closest_y)²
if dist² < BULLET_RADIUS² → bala destruida (no pasa a active_bullets)
```

### Respawn
Al morir, el jugador reaparece en un punto aleatorio de `SPAWN_POINTS` con:
- HP = 100
- `has_power_weapon = False`
- `power_weapon_end = 0.0`
- `was_shooting = False`

### Sistema de Puntuación
- **+1 kill** al atacante cuando elimina a un jugador.
- **+1 muerte** al jugador eliminado.
- `damage_dealt` acumula el daño total infligido.
- **Desempate en ranking:** más kills → menos muertes → más daño total.

### Condición de Victoria
- Primer jugador en alcanzar **3 kills**, o
- Al expirar el tiempo (**120 segundos**).

---

## 5. Máquina de Estados de la Partida

```
        INICIO
           ↓
      [WAITING] ──(≥2 jugadores)──→ [READY_CHECK]
           ↑                              ↓
           └──(jugador sale, <2)←── (todos listos)──→ [COUNTDOWN]
                                          ↑                ↓
                                  (jugador sale)      (3 s elapsed)
                                                           ↓
                                                      [PLAYING]
                                                           ↓
                                           (3 kills ó 120 s)
                                                           ↓
                                                      [FINISHED]
                                                           ↓
                                           (8 s ó <2 jugadores)
                                                           ↓
                                                      [WAITING]
```

| Fase | Descripción | Transición salida |
|------|-------------|-------------------|
| `waiting` | Esperando conexiones | ≥2 jugadores → `ready_check` |
| `ready_check` | Jugadores confirman inicio | Todos listos → `countdown`; <2 jugadores → `waiting` |
| `countdown` | Cuenta regresiva 3-2-1 | 3 s → `playing`; resetea estado de todos |
| `playing` | Partida activa | 3 kills ó 120 s → `finished`; <2 jugadores → `waiting` |
| `finished` | Muestra ranking | 8 s ó <2 jugadores → `waiting`; resetea flags `ready` |

---

## 6. Protocolo de Red

### Capa de transporte
- **Protocolo:** UDP (no bloqueante, best-effort)
- **Formato:** JSON con separadores compactos (sin espacios)
- **Codificación:** UTF-8

### Mensajes Cliente → Servidor

**Conectar:**
```json
{"type":"connect","name":"Jugador"}
```
Enviado cada ~1 segundo hasta recibir `welcome`.

**Input (30 Hz):**
```json
{
  "type": "input",
  "id": 1,
  "keys": {"up": false, "down": false, "left": false, "right": false, "shoot": false},
  "aim": [480, 270]
}
```

**Listo:**
```json
{"type":"ready"}
```

**Desconectar:**
```json
{"type":"disconnect","id":1}
```

### Mensajes Servidor → Cliente

**Bienvenida:**
```json
{"type":"welcome","id":1}
```

**Servidor lleno:**
```json
{"type":"full","reason":"La partida ya tiene 4 jugadores."}
```

**Estado del juego (20 Hz):**
```json
{
  "type": "state",
  "phase": "playing",
  "time_left": 95,
  "winner_id": null,
  "ranking": [],
  "ready_count": 2,
  "total_players": 2,
  "countdown": 0,
  "players": [
    {"id":1,"name":"P1","x":100.5,"y":270.0,"hp":80,"score":1,"aim":[1.0,0.0],"pw":false,"ready":true}
  ],
  "bullets": [
    {"owner_id":1,"x":200.0,"y":270.0}
  ],
  "pickups": [
    {"id":1,"type":"weapon","x":480.0,"y":270.0},
    {"id":2,"type":"health","x":640.0,"y":400.0}
  ]
}
```

### Temporización de Red
| Parámetro | Valor | Período |
|-----------|-------|---------|
| Server tick | 60 Hz | 16.67 ms |
| Broadcast state | 20 Hz | 50 ms |
| Client input | 30 Hz | 33.3 ms |
| Timeout desconexión | 10 s | — |

---

## 7. Renderizado

### Fondo
- Base sólida: `(8, 10, 20)` (azul muy oscuro).
- Degradado vertical en franjas de 4 px: intensidad de `10` a `25` con tono azulado `(i, i, i+20)`.
- **150 estrellas** con parpadeo sinusoidal:
  - Tamaño: 1–3 px
  - Brillo: 100–255
  - Velocidad: 0.1–0.5 px/frame (hacia abajo, reaparecen en la parte superior)
  - Parpadeo: `alpha = brightness * (0.7 + 0.3 * sin(time * 2 + phase))`

### Nave (Jugador)
Triángulo escalado desde `PLAYER_RADIUS = 18`:

| Componente | Cálculo | Descripción |
|------------|---------|-------------|
| Punta (tip) | `(x + cos(angle) * 27, y + sin(angle) * 27)` | Frente de la nave |
| Ala izquierda | `(x + cos(angle + 2.5) * 14.4, ...)` | Ala trasera izq. |
| Ala derecha | `(x + cos(angle - 2.5) * 14.4, ...)` | Ala trasera der. |
| Sombra | Offset 3 px, color `(20, 20, 30)` | Profundidad |
| Borde | Blanco, 2 px de grosor | Contorno |
| Cockpit exterior | Círculo 6 px, azul claro | Cabina |
| Cockpit interior | Círculo 3 px, azul oscuro | Visor |
| Motor | Rectángulo 10×6 px, naranja | Propulsor trasero |

**Barra de vida (debajo de la nave):**
- Ancho total: 30 px, alto: 4 px
- Relleno: verde proporcional a `hp / 100`
- Fondo: rojo oscuro

**Etiqueta:** ID del jugador encima de la nave.

### Balas
```
Color relleno:  (250, 245, 210)  — crema/blanco apagado
Color borde:    (255, 255, 200)  — amarillo muy claro
Radio relleno:  5 px
Radio borde:    7 px (grosor 1 px)
```

### Pickups
```
Weapon:  radio 14 px, relleno (220,50,50), borde (255,100,100), etiqueta "W"
Health:  radio 14 px, relleno (50,180,80),  borde (100,230,130), etiqueta "+"
```

### Obstáculos
Bloques de concreto/bunker estilo militar. Se dibujan entre el fondo y los pickups/balas/jugadores.

```
Cuerpo principal:       (82, 74, 58)  — gris-marrón concreto
Highlight superior:     (108, 98, 78) — arista top, 4 px alto
Highlight izquierdo:    (100, 90, 72) — arista left, 4 px ancho
Sombra inferior:        (50, 44, 34)  — arista bottom, 4 px alto
Sombra derecha:         (56, 50, 40)  — arista right, 4 px ancho
Línea central:          (64, 58, 46)  — detalle horizontal central, 1 px
Borde exterior:         (36, 32, 24)  — contorno 2 px
```

**Orden de render:** fondo → obstáculos → pickups → balas → jugadores → HUD

### HUD (Barra superior, 60 px de alto)
- Fondo semi-transparente oscuro.
- **Izquierda:** `ID: X` en azul claro.
- **Centro:** `Tiempo: Xs` en amarillo claro + lista de jugadores con HP, kills, indicador `[PW]`.
- **Derecha:** Varía según fase:
  - `waiting` → `"Esperando jugadores... Jugadores: X"`
  - `ready_check` → `"Listos: X/Y"`
  - `countdown` → número grande centrado en pantalla
  - `playing` → `"Objetivo: 3 kills"`
  - `finished` → `"¡Ganador: ID X!"` en dorado

### Pantalla de Ranking (fase `finished`)
Superposición semi-transparente oscura con tabla:
```
          RANKING FINAL
1. Jugador1   Kills:3  Muertes:0  Daño:30
2. Jugador2   Kills:1  Muertes:2  Daño:10
...
```

### Botón "EMPEZAR" (fases `waiting` / `ready_check`)
- Posición: centro de pantalla + 50 px en Y
- Tamaño: 150×50 px
- Sin listo: azul oscuro `(40, 80, 150)` / hover `(70, 130, 200)`
- Listo: verde `(50, 180, 80)` con texto `"✓ LISTO"`

### Fuentes
| Objeto | Fuente | Tamaño | Negrita |
|--------|--------|--------|---------|
| `font` | Arial | 18 pt | No |
| `big_font` | Arial | 36 pt | Sí |
| `hud_font` | Arial | 16 pt | Sí |

---

## 8. Clases Principales

### `common.py` — Utilidades Compartidas

| Función | Firma | Descripción |
|---------|-------|-------------|
| `clamp` | `(value, min, max) → value` | Limita un valor a un rango |
| `normalize` | `(dx, dy) → (nx, ny)` | Vector unitario; retorna (0,0) si longitud=0 |
| `distance_squared` | `(ax,ay,bx,by) → float` | `(ax-bx)²+(ay-by)²` sin sqrt |
| `encode_message` | `(msg) → bytes` | Serialización JSON compacta UTF-8 |
| `decode_message` | `(data) → dict\|None` | Deserialización JSON UTF-8 |
| `circle_rect_overlap` | `(cx,cy,r, rx,ry,rw,rh) → bool` | Colisión círculo vs. rectángulo AABB |
| `push_circle_from_rect` | `(cx,cy,r, rx,ry,rw,rh) → (float,float)` | Empuja el círculo fuera del rectángulo |
| `_generate_obstacles` | `(seed=42) → list[tuple]` | Genera lista de rectángulos `(x,y,w,h)` |

**Constante generada al importar:**

| Nombre | Tipo | Descripción |
|--------|------|-------------|
| `OBSTACLES` | `list[tuple[int,int,int,int]]` | 6 rectángulos `(x,y,w,h)` en zona central |

---

### `client.py` — Clases del Cliente

#### `LocalPredictor`
Predicción del lado del cliente para movimiento suave.

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `predicted_x/y` | float | Posición estimada local |
| `initialized` | bool | Ha recibido estado inicial |

| Método | Descripción |
|--------|-------------|
| `apply_input(keys, dt)` | Aplica movimiento local + colisión con obstáculos (misma lógica que servidor) |
| `correct(server_x, server_y, lerp=0.3)` | Reconciliación: `predicted = predicted + 0.3 * (server - predicted)` |
| `get_position()` | Retorna posición predicha actual |

#### `Star`
Estrella de fondo para efecto parallax.

| Campo | Tipo | Rango |
|-------|------|-------|
| `x`, `y` | float | 0 – WIDTH/HEIGHT |
| `size` | float | 1 – 3 px |
| `brightness` | int | 100 – 255 |
| `speed` | float | 0.1 – 0.5 px/frame |
| `phase` | float | 0 – 2π |

#### `GameClient`
Aplicación principal del cliente.

**Parámetros constructor:** `server_ip`, `server_port`, `name`

| Componente | Descripción |
|------------|-------------|
| Socket UDP no bloqueante | Comunicación con el servidor |
| `threading.Lock` | Protección del estado compartido |
| Thread `_send_loop` | Envía inputs a 30 Hz |
| Thread `_receive_loop` | Recibe estado del servidor |
| `predictor` | Instancia de `LocalPredictor` |
| `stars` | Lista de 150 instancias de `Star` |
| `sounds` | Dict con efectos de sonido cargados |

---

### `server.py` — Servidor Autoritativo

#### `AuthoritativeServer`

**Parámetros constructor:** `host="0.0.0.0"`, `port=5000`

| Campo | Tipo | Descripción |
|-------|------|-------------|
| `players` | dict[int, Player] | Jugadores conectados |
| `address_to_id` | dict[tuple, int] | Mapeo dirección→ID |
| `bullets` | list[Bullet] | Balas activas |
| `pickups` | list[Pickup] | Pickups en mapa |
| `phase` | str | Estado actual de la partida |
| `next_player_id` | int | Contador incremental (inicia en 1) |

| Método | Descripción |
|--------|-------------|
| `handle_connect` | Registra nuevo jugador o rechaza si lleno |
| `handle_input` | Actualiza teclas/aim del jugador (solo en `playing`) |
| `handle_ready` | Marca jugador como listo |
| `remove_player` | Elimina jugador por desconexión o timeout |
| `update_phase` | Máquina de estados de la partida |
| `update_game` | Física: movimiento, disparos, colisiones, pickups y obstáculos |
| `update_player_collisions` | Separación física entre jugadores |
| `spawn_bullet` | Crea bala en la posición correcta |
| `update_bullets` | Mueve balas, verifica TTL, colisiones con jugadores y obstáculos |
| `update_pickups` | Detección de recogida y respawn |
| `random_pickup_pos` | Genera posición libre de obstáculos para pickup (hasta 200 intentos) |
| `respawn_player` | Teletransporta y restaura jugador |
| `build_state` | Serializa estado completo para broadcast |
| `finish_match` | Calcula ranking y transiciona a `finished` |
| `run` | Bucle principal del servidor (60 Hz) |

---

## 9. Fórmulas y Cálculos

### Física

```
# Actualización de posición de bala
bullet.x += bullet.vx * dt
bullet.y += bullet.vy * dt
bullet.ttl -= dt

# Actualización de posición de jugador
dx, dy = normalize(input)
player.x = clamp(player.x + dx * 220 * dt, 18, 942)
player.y = clamp(player.y + dy * 220 * dt, 18, 522)

# Normalización de vector
length = hypot(dx, dy)
return (dx/length, dy/length) if length > 0 else (0, 0)
```

### Colisiones

```
# Bala vs jugador (colisión circular)
hit_radius = PLAYER_RADIUS + BULLET_RADIUS = 23 px
hit = dist² ≤ 23²

# Jugador vs jugador (separación)
min_dist = PLAYER_RADIUS * 2 = 36 px
overlap = (36 - dist) / 2 * 1.8
p1 += normal * overlap
p2 -= normal * overlap

# Jugador vs pickup
pickup_radius = PLAYER_RADIUS + PICKUP_RADIUS = 32 px
pickup = dist² ≤ 32²

# Jugador/Bala vs obstáculo (círculo vs. rectángulo AABB)
closest = (clamp(cx, ox, ox+ow), clamp(cy, oy, oy+oh))
dist² = (cx - closest.x)² + (cy - closest.y)²
# Jugador: si dist² < PLAYER_RADIUS² → empujar a lo largo de la normal
# Bala:    si dist² < BULLET_RADIUS² → destruir bala
```

### Renderizado

```
# Barra de vida
hp_ratio = max(0, hp) / 100
bar_filled = 30 * hp_ratio

# Parpadeo de estrellas
flicker = 0.7 + 0.3 * sin(time.time() * 2 + phase)
alpha = clamp(int(brightness * flicker), 0, 255)

# Vector de apuntado
dx = mouse_x - player_x
dy = mouse_y - player_y
aim_x, aim_y = normalize(dx, dy)
angle = atan2(aim_y, aim_x)

# Offset de spawneo de bala
offset = 18 + 5 + 2 = 25 px
start_x = player.x + aim_x * 25
start_y = player.y + aim_y * 25
```

### Ranking

```python
sorted(players, key=lambda p: (-p.score, p.deaths, -p.damage_dealt))
```
1. Mayor número de kills (descendente)
2. Menor número de muertes (ascendente)
3. Mayor daño total (descendente)

---

## 10. Tabla Resumen — Todos los Valores Numéricos

| Parámetro | Valor | Unidad |
|-----------|-------|--------|
| `WIDTH` | 960 | px |
| `HEIGHT` | 540 | px |
| `PLAYER_RADIUS` | 18 | px |
| `BULLET_RADIUS` | 5 | px |
| `PICKUP_RADIUS` | 14 | px |
| `PLAYER_SPEED` | 220 | px/s |
| `BULLET_SPEED` | 520 | px/s |
| `PLAYER_HEALTH` | 100 | HP |
| `BASE_DAMAGE` | 10 | HP |
| `SHOOT_COOLDOWN` | 0.35 | s |
| `POWER_SHOOT_COOLDOWN` | 0.12 | s |
| `BULLET_TTL` | 1.4 | s |
| `POWER_WEAPON_DURATION` | 15.0 | s |
| `PICKUP_RESPAWN_TIME` | 10.0 | s |
| `MAX_PLAYERS` | 4 | — |
| `MIN_PLAYERS_TO_START` | 2 | — |
| `MATCH_SECONDS` | 120 | s |
| `KILLS_TO_WIN` | 3 | kills |
| `COUNTDOWN_SECONDS` | 3 | s |
| `SERVER_TICK` | 60 | Hz |
| `BROADCAST_RATE` | 20 | Hz |
| `CLIENT_INPUT_RATE` | 30 | Hz |
| `DISCONNECT_SECONDS` | 10 | s |
| `SPAWN_MARGIN` | 60 | px |
| Colisión: exageración separación | 1.8 | × |
| Predictor lerp | 0.3 | peso |
| Obstáculos totales | 6 | — |
| Obstáculo semilla RNG | 42 | fixed seed |
| Obstáculo ancho mín/máx | 42 / 72 | px |
| Obstáculo alto mín/máx | 30 / 56 | px |
| Obstáculo zona X | 180 – 780 | px |
| Obstáculo zona Y | 150 – 390 | px |
| Obstáculo exclusión spawn | 70 | px |
| Obstáculo separación mínima | 15 | px |
| Estrellas totales | 150 | — |
| Tamaño estrella mín. | 1 | px |
| Tamaño estrella máx. | 3 | px |
| Brillo estrella mín. | 100 | 0–255 |
| Velocidad estrella mín. | 0.1 | px/frame |
| Velocidad estrella máx. | 0.5 | px/frame |
| Nave: multiplicador largo | 1.5 | × PLAYER_RADIUS |
| Nave: multiplicador ancho | 0.8 | × PLAYER_RADIUS |
| Nave: ángulo alas | ±2.5 | rad |
| Cockpit radio exterior | 6 | px |
| Cockpit radio interior | 3 | px |
| Motor: ancho | 10 | px |
| Motor: alto | 6 | px |
| Barra vida: ancho | 30 | px |
| Barra vida: alto | 4 | px |
| HUD: altura | 60 | px |
| Botón listo: ancho | 150 | px |
| Botón listo: alto | 50 | px |
| Nombre: longitud máxima | 16 | chars |
| Spawn offset bala | 25 | px |
| Sombra nave offset | 3 | px |
