#!/usr/bin/env python3
"""Clawd 像素风自我介绍动画 —— 全部用代码画，Pillow 逐帧 + ffmpeg 合成。

画布在 360x640 的低分辨率上逐像素绘制，再用最近邻 x3 放大到 1080x1920，
最后叠一层轻微扫描线，做出 CRT 终端的感觉。

用法:
  python3 clawd_intro.py preview [out_dir]   # 渲染若干关键帧 + 拼图
  python3 clawd_intro.py render  [out.mp4]   # 渲染完整视频
"""
import math
import os
import random
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- 基础设置
W, H = 360, 640          # 像素画布
SCALE = 3                # 放大倍数 -> 1080x1920
FPS = 30
DURATION = 40.0
NFRAMES = int(FPS * DURATION)

FONT = ImageFont.truetype("/usr/share/fonts/opentype/unifont/unifont.otf", 16)

# ---------------------------------------------------------------- 调色板
BG = (13, 13, 17)
BG_DOT = (22, 22, 29)
BAR = (26, 26, 33)
SHADOW = (6, 6, 8)
FG = (226, 224, 216)
DIM = (104, 104, 116)
ORANGE = (218, 119, 86)
ORANGE_D = (170, 82, 56)
ORANGE_L = (242, 162, 126)
EYE = (22, 16, 16)
PINK = (244, 132, 150)
GREEN = (80, 224, 130)
GREEN_D = (24, 120, 62)
YELLOW = (250, 204, 72)
WHITE = (250, 248, 240)
BUG = (196, 66, 120)
BUG_D = (110, 30, 70)
KIWI = (139, 94, 60)
KIWI_D = (104, 68, 42)
KIWI_L = (170, 122, 82)
BEAK = (226, 196, 150)
BLUE = (66, 135, 245)
BLUE_D = (30, 72, 190)
SKY = (150, 200, 255)


# ---------------------------------------------------------------- 小工具
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def lerp(a, b, t):
    return a + (b - a) * t


def smooth(t):
    t = clamp(t)
    return t * t * (3 - 2 * t)


def ease_out(t):
    t = clamp(t)
    return 1 - (1 - t) ** 3


def ease_out_back(t, c=1.8):
    t = clamp(t)
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def mix(c1, c2, t):
    t = clamp(t)
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


def rect(d, x, y, w, h, c):
    x, y, w, h = int(round(x)), int(round(y)), int(round(w)), int(round(h))
    if w > 0 and h > 0:
        d.rectangle([x, y, x + w - 1, y + h - 1], fill=c)


def outline(d, x, y, w, h, c):
    rect(d, x, y, w, 1, c)
    rect(d, x, y + h - 1, w, 1, c)
    rect(d, x, y, 1, h, c)
    rect(d, x + w - 1, y, 1, h, c)


def text(d, x, y, s, c):
    d.text((int(x), int(y)), s, font=FONT, fill=c)


def tw(s):
    return int(FONT.getlength(s))


def sprite(d, x, y, s, rows, colors):
    """rows: list of strings; colors: char -> rgb. '.' = 透明"""
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch in colors:
                rect(d, x + i * s, y + j * s, s, s, colors[ch])


# ---------------------------------------------------------------- 背景
def make_base():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    for y in range(30, H, 12):
        for x in range(6, W, 12):
            d.point((x, y), fill=BG_DOT)
    # 终端标题栏
    rect(d, 0, 0, W, 22, BAR)
    for i, c in enumerate([(237, 106, 94), (245, 191, 79), (98, 197, 84)]):
        rect(d, 10 + i * 12, 8, 6, 6, c)
    title = "clawd@claude: ~"
    d.fontmode = "1"
    text(d, (W - tw(title)) // 2, 3, title, DIM)
    rect(d, 0, 22, W, 1, (34, 34, 42))
    return img


BASE = make_base()


# ---------------------------------------------------------------- Clawd 本蟹
def draw_clawd(d, cx, by, s, *, claw_l=0, claw_r=0, lift_l=0, lift_r=0,
               leg=0, eyes="open", look=0, blush=False, jump=0):
    """cx: 身体中心 x；by: 身体顶部 y（站在地面时）；s: 每个像素格的大小。
    claw_*: 钳子张开程度 0/1/2；lift_*: 手臂抬高格数；leg: 步态 0..3。"""
    bx = int(round(cx - 7 * s))
    gy = int(round(by))
    top = gy - int(round(jump))

    def u(x, y, c):
        rect(d, bx + x * s, top + y * s, s, s, c)

    # 影子（贴地，跳起来时变小）
    shrink = int(clamp(jump / (6 * s), 0, 1) * 3)
    rect(d, bx + (1 + shrink) * s, gy + 11 * s, (12 - 2 * shrink) * s, s, SHADOW)

    # 腿：四条，横着走时两两交替抬起
    for lx, group in ((1, 0), (4, 1), (9, 0), (12, 1)):
        lifted = (leg == 1 and group == 0) or (leg == 3 and group == 1)
        u(lx, 9, ORANGE_D)
        if not lifted:
            u(lx, 10, ORANGE_D)

    # 身体
    rect(d, bx, top, 14 * s, 9 * s, ORANGE)
    rect(d, bx + s, top, 12 * s, s, ORANGE_L)
    rect(d, bx, top + 8 * s, 14 * s, s, ORANGE_D)

    # 眼睛
    for ex in (4 + look, 9 + look):
        if eyes == "open":
            u(ex, 2, EYE)
            u(ex, 3, EYE)
        elif eyes == "blink":
            u(ex, 3, EYE)
        elif eyes == "happy":
            u(ex - 1, 3, EYE)
            u(ex, 2, EYE)
            u(ex + 1, 3, EYE)
    if blush:
        u(2, 5, PINK)
        u(3, 5, PINK)
        u(10, 5, PINK)
        u(11, 5, PINK)

    # 钳子
    for side, o, lift in (("L", claw_l, lift_l), ("R", claw_r, lift_r)):
        px, py = -5, 1 - lift
        pts = []
        # 手臂
        pts += [(-1, 5, ORANGE_D), (-2, 5, ORANGE_D)]
        for yy in range(py + 3, 6):
            pts.append((-3, yy, ORANGE_D))
        # 掌
        for xx in range(4):
            pts.append((px + xx, py, ORANGE))
            pts.append((px + xx, py + 1, ORANGE))
            pts.append((px + xx, py + 2, ORANGE_D))
        pts.append((px + 1, py, ORANGE_L))
        # 两根指头
        if o <= 0:
            fing = [(0, -1), (0, -2), (1, -3), (3, -1), (3, -2), (2, -3)]
        elif o == 1:
            fing = [(0, -1), (-1, -2), (-1, -3), (3, -1), (4, -2), (4, -3)]
        else:
            fing = [(0, -1), (-1, -1), (-2, -2), (-2, -3),
                    (3, -1), (4, -1), (5, -2), (5, -3)]
        for fx, fy in fing:
            pts.append((px + fx, py + fy, ORANGE))
        for x, y, c in pts:
            u(x if side == "L" else 13 - x, y, c)


def clawd_grab_point(cx, by, s, side):
    """钳口中心（用来对准 bug）"""
    off = 10.5 * s
    return (cx - off if side == "L" else cx + off, by - 1.5 * s)


# ---------------------------------------------------------------- bug
BUG_ROWS_A = [
    "..d.d..",
    "..dwd..",
    "lmmmmml",
    ".mmdmm.",
    "l.mmm.l",
    "...m...",
]
BUG_ROWS_B = [
    "..d.d..",
    "..dwd..",
    ".mmmmm.",
    "lmmdmml",
    "..mmm..",
    "l..m..l",
]


def draw_bug(d, cx, cy, s, phase):
    rows = BUG_ROWS_A if phase % 2 == 0 else BUG_ROWS_B
    sprite(d, cx - 3.5 * s, cy - 3 * s, s, rows,
           {"d": BUG_D, "w": WHITE, "m": BUG, "l": BUG_D})


CHECK_ROWS = [
    "......XX",
    ".....XX.",
    "XX..XX..",
    ".XXXX...",
    "..XX....",
]

HEART_ROWS = [
    ".XX.XX.",
    "XXXXXXX",
    "XXXXXXX",
    ".XXXXX.",
    "..XXX..",
    "...X...",
]

BANG_ROWS = ["X", "X", "X", ".", "X"]


def draw_check(d, cx, cy, s, c=GREEN, cd=GREEN_D):
    x, y = cx - 4 * s, cy - 2.5 * s
    sprite(d, x + s, y + s, s, CHECK_ROWS, {"X": cd})
    sprite(d, x, y, s, CHECK_ROWS, {"X": c})


# ---------------------------------------------------------------- kiwi（Rhett）
KIWI_OUT = (46, 29, 18)
KIWI_HEAD = (156, 108, 70)


def draw_kiwi(d, cx, cy, s, wing_up=False, eyes="open"):
    """细网格（s 像素一格）画的圆滚滚奇异鸟，面朝左。"""
    cells = {}

    def put(x, y, c):
        cells[(x, y)] = c

    # 身体
    for y in range(-15, 16):
        for x in range(-18, 19):
            if (x / 17.5) ** 2 + (y / 14.2) ** 2 <= 1.0:
                c = KIWI
                if y < -10 and (x + y) % 3:
                    c = KIWI_L
                elif y > 9:
                    c = KIWI_D
                elif (x * 2 + y * 3) % 9 == 0 or (x * 2 + y * 3) % 9 == 1:
                    c = KIWI_D
                put(x, y, c)
    # 头
    hx, hy = -14, -8
    for y in range(-8, 9):
        for x in range(-8, 9):
            if x * x + y * y <= 56:
                c = KIWI_HEAD
                if y < -4 and (x - y) % 3:
                    c = KIWI_L
                put(hx + x, hy + y, c)
    # 小翅膀：从肩膀伸出的一小截，挥动时绕肩膀转
    sx_, sy_ = 4, -5
    ang = math.radians(-66 if wing_up else 28)
    ca, sa = math.cos(ang), math.sin(ang)
    wing = []
    for y in range(-20, 10):
        for x in range(-6, 20):
            rx, ry = x - sx_, y - sy_
            along = rx * ca + ry * sa
            perp = -rx * sa + ry * ca
            if 0 <= along <= 12.5 and abs(perp) <= 3.4 * (1 - (along / 14) ** 2) + 0.4:
                wing.append((x, y))
    for x, y in wing:
        put(x, y, KIWI_D)
    # 长嘴（略向下弯）
    for i in range(24):
        bx = hx - 7 - i
        byy = hy + 1 + int(round(5 * (i / 23) ** 2))
        put(bx, byy, BEAK)
        if i < 10:
            put(bx, byy + 1, (196, 160, 112))
    # 描边
    filled = set(cells)
    for (x, y) in list(filled):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n not in filled and n not in cells:
                cells[n] = KIWI_OUT
    # 翅膀边线
    for x, y in (wing if wing_up else []):
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in filled and n not in wing:
                cells[n] = KIWI_OUT
    # 眼睛
    ex, ey = hx - 3, hy - 3
    if eyes == "happy":
        for x, y in ((ex - 2, ey + 1), (ex - 1, ey), (ex, ey - 1), (ex + 1, ey), (ex + 2, ey + 1)):
            cells[(x, y)] = EYE
    else:
        for x in (ex - 1, ex, ex + 1):
            for y in (ey - 1, ey, ey + 1):
                cells[(x, y)] = EYE
        cells[(ex - 1, ey - 1)] = WHITE
    # 脸蛋
    cells[(hx + 1, hy + 2)] = PINK
    cells[(hx + 2, hy + 2)] = PINK
    # 小蓝领结
    kx, ky = hx + 4, hy + 9
    for x in range(-6, 7):
        for y in range(-3, 4):
            ax = abs(x)
            if 2 <= ax <= 6 and abs(y) <= min(3, ax - 1):
                cells[(kx + x, ky + y)] = BLUE
            elif ax <= 1 and abs(y) <= 1:
                cells[(kx + x, ky + y)] = BLUE_D
    cells[(kx - 4, ky - 1)] = SKY
    cells[(kx - 5, ky - 2)] = SKY
    for (x, y), c in cells.items():
        rect(d, cx + x * s, cy + y * s, s, s, c)


# ---------------------------------------------------------------- 文字排版
NO_LINE_START = set("，。！？、～）」』,.!?~")


def wrap(s, maxw):
    lines, cur = [], ""
    for ch in s:
        if tw(cur + ch) > maxw and cur and ch not in NO_LINE_START:
            lines.append(cur)
            cur = ch.lstrip() if ch == " " else ch
        else:
            cur += ch
    if cur:
        lines.append(cur)
    return lines


def typed_schedule(t0, chars, base=0.09, jitter=0.04, seed=1, pauses=None):
    rng = random.Random(seed)
    times, t = [], t0
    for i, ch in enumerate(chars):
        times.append(t)
        dt = base + rng.uniform(-jitter, jitter)
        if pauses and ch in pauses:
            dt += pauses[ch]
        t += dt
    return times


# ---------------------------------------------------------------- 剧本时间轴
# S1 0-4    终端开机，敲 $ claude
# S2 4-10   Clawd 横着走进来，钳子开合打招呼
# S3 10-20  夹 bug
# S4 20-25  git commit + 烟花
# S5 25-37  自我介绍
# S6 37-40  彩蛋：Rhett 来串门

CMD1 = "claude"
CMD1_T = typed_schedule(1.25, CMD1, base=0.15, jitter=0.05, seed=3)
ENTER1 = 2.4

CMD2 = 'git commit -m "fixed everything"'
CMD2_T = typed_schedule(20.3, CMD2, base=0.064, jitter=0.03, seed=7)
ENTER2 = 22.65

STAGE_Y = 318          # Clawd 站位（身体顶部）
CS = 5                 # Clawd 常规尺寸

# bug: 出生时间、出生点、被抓点、被抓时间
BUGS = [
    dict(t0=10.0, sx=-16, sy=262, x=58, y=290, tc=12.2),
    dict(t0=10.3, sx=376, sy=306, x=300, y=236, tc=13.8),
    dict(t0=10.7, sx=64, sy=580, x=74, y=420, tc=15.4),
    dict(t0=11.2, sx=376, sy=470, x=304, y=410, tc=17.0),
    dict(t0=11.8, sx=200, sy=104, x=150, y=184, tc=18.6),
]


def plan_clawd_path():
    """生成 Clawd 在 S3 里的移动段落 (t_start, t_end, from, to, side)"""
    segs = []
    pos = (180.0, float(STAGE_Y))
    start = 10.9
    for b in BUGS:
        side = "L" if b["x"] < pos[0] else "R"
        off = 10.5 * CS
        target = (b["x"] + off if side == "L" else b["x"] - off, b["y"] + 1.5 * CS)
        segs.append(dict(t0=start, t1=b["tc"] - 0.08, a=pos, b=target, side=side, bug=b))
        b["side"] = side
        pos = target
        start = b["tc"] + 0.4
    segs.append(dict(t0=18.95, t1=19.8, a=pos, b=(180.0, float(STAGE_Y)), side=None, bug=None))
    return segs


SEGS = plan_clawd_path()


def bug_pos(b, t):
    """bug 当前位置；None 表示还没出来/已经被夹走"""
    if t < b["t0"]:
        return None
    k = ease_out((t - b["t0"]) / 1.6)
    x = lerp(b["sx"], b["x"], k)
    y = lerp(b["sy"], b["y"], k)
    amp = clamp((b["tc"] - 0.55 - t) / 0.6) * clamp((t - b["t0"] - 1.0) / 0.8)
    seed = b["t0"] * 7
    x += amp * 12 * math.sin(2.3 * t + seed)
    y += amp * 7 * math.sin(3.1 * t + seed * 1.7)
    return x, y


def clawd_state(t):
    st = dict(cx=180.0, by=float(STAGE_Y), s=CS, claw_l=0, claw_r=0, lift_l=0, lift_r=0,
              leg=0, eyes="open", look=0, blush=False, jump=0, visible=True)

    def blink(period, offset=0.0):
        return ((t + offset) % period) < 0.12

    if t < 4.3:
        st["visible"] = False
    elif t < 7.0:                                   # S2 横着走进来
        k = (t - 4.3) / 2.7
        st["cx"] = lerp(-80, 180, 1 - (1 - k) ** 1.6)
        st["leg"] = int(t * 12) % 4 if k < 0.97 else 0
        st["look"] = 1
    elif t < 10.0:                                  # 打招呼
        if 7.25 <= t < 9.3:
            st["lift_l"] = st["lift_r"] = 1 if (t < 7.35 or t > 9.2) else 2
            if 7.45 <= t < 9.05:
                ph = ((t - 7.45) / 0.8) % 1.0
                o = 2 if ph < 0.5 else 0
                st["claw_l"] = st["claw_r"] = o
            st["eyes"] = "happy"
        elif blink(1.0, 0.4) and t > 9.4:
            st["eyes"] = "blink"
    elif t < 20.0:                                  # S3 夹 bug
        pos = (180.0, float(STAGE_Y))
        moving = False
        side_active = None
        for sg in SEGS:
            if t >= sg["t0"]:
                if t < sg["t1"]:
                    k = smooth((t - sg["t0"]) / (sg["t1"] - sg["t0"]))
                    pos = (lerp(sg["a"][0], sg["b"][0], k), lerp(sg["a"][1], sg["b"][1], k))
                    moving = True
                    dx = sg["b"][0] - sg["a"][0]
                    st["look"] = 1 if dx > 0 else -1
                else:
                    pos = sg["b"]
                side_active = sg if t < sg["t1"] + 0.4 else side_active
        st["cx"], st["by"] = pos
        if moving:
            st["leg"] = int(t * 14) % 4
        # 钳子：靠近时张开，到点夹紧
        for b in BUGS:
            sd = b["side"]
            key = "claw_l" if sd == "L" else "claw_r"
            if b["tc"] - 0.6 <= t < b["tc"] - 0.05:
                st[key] = 2
                st["look"] = -1 if sd == "L" else 1
            elif b["tc"] - 0.05 <= t < b["tc"] + 0.35:
                st[key] = 0
                st["eyes"] = "happy"
        if 10.3 <= t < 10.9:
            st["look"] = 0
    elif t < 22.65:                                 # S4 打字
        if blink(1.6, 0.3):
            st["eyes"] = "blink"
        st["look"] = -1 if t > 20.3 else 0
    elif t < 25.0:                                  # 提交成功，蹦蹦跳跳
        tt = t - ENTER2
        if tt < 1.8:
            st["jump"] = 24 * abs(math.sin(math.pi * tt / 0.45))
        st["eyes"] = "happy"
        st["lift_l"] = st["lift_r"] = 2
        st["claw_l"] = st["claw_r"] = 2 if int(tt * 6) % 2 == 0 else 1
    elif t < 25.7:                                  # 镜头推近
        k = smooth((t - 25.0) / 0.6)
        st["s"] = 5 if t < 25.2 else (6 if t < 25.4 else 7)
        st["by"] = lerp(STAGE_Y, 150, k)
    else:                                           # S5 / S6 面对镜头
        st["s"] = 7
        st["by"] = 150 + (2 if int(t * 2) % 2 else 0)
        st["blush"] = True
        if blink(2.7, 0.9):
            st["eyes"] = "blink"
        if t < 37.0:
            if INTRO_T[0] <= t <= INTRO_T[-1] + 0.2:
                o = 1 if int(t * 2.5) % 2 else 0
                st["claw_l"] = o
                st["claw_r"] = 1 - o
        else:                                       # 彩蛋：朝 kiwi 挥钳子
            st["look"] = 1
            st["lift_r"] = 3 if t > 37.3 else 1
            if t > 37.5:
                st["claw_r"] = 2 if int(t * 5) % 2 == 0 else 0
            if t > 38.3:
                st["eyes"] = "happy"
    return st


# ---------------------------------------------------------------- S5 文案
INTRO = [   # 每段一句话，手动断行
    ["嗨～我是 Clawd，Claude Code 的小螃蟹！"],
    ["我住在你的终端里，", "每天读代码、横着走、顺手夹 bug。"],
    ["钳子虽小，夹 bug 一夹一个准，绝不手软～"],
    ["想做什么，就敲一句 claude，", "我马上横着跑过来！"],
]
BOX_X, BOX_Y, BOX_W = 10, 262, 340
TEXT_X = BOX_X + 12
LINE_H = 22
PARA_GAP = 8
INTRO_LINES = []      # (text, y)
_y = BOX_Y + 18
for para in INTRO:
    for ln in para:
        assert tw(ln) <= BOX_W - 24, ln
        INTRO_LINES.append((ln, _y))
        _y += LINE_H
    _y += PARA_GAP
BOX_H = _y - BOX_Y + 4 - PARA_GAP
INTRO_FLAT = "".join(ln for ln, _ in INTRO_LINES)
INTRO_T = typed_schedule(26.3, INTRO_FLAT, base=0.088, jitter=0.02, seed=11,
                         pauses={"！": 0.35, "。": 0.35, "～": 0.35, "，": 0.12})
WHOAMI = "claude --whoami"
WHOAMI_T = typed_schedule(25.45, WHOAMI, base=0.035, jitter=0.01, seed=5)

CAPTION = "Rhett 来串门"
CAPTION_T = typed_schedule(37.9, CAPTION, base=0.08, jitter=0.0, seed=2)


# ---------------------------------------------------------------- 烟花
BURSTS = []
_rng = random.Random(42)
for bt, bx, by, pal in [
    (22.75, 96, 200, [ORANGE_L, ORANGE, YELLOW]),
    (23.05, 266, 190, [GREEN, WHITE, YELLOW]),
    (23.4, 180, 236, [PINK, ORANGE_L, WHITE]),
    (23.75, 76, 380, [YELLOW, ORANGE, GREEN]),
    (23.95, 290, 360, [ORANGE_L, PINK, YELLOW]),
]:
    parts = []
    n = 32
    for i in range(n):
        a = 2 * math.pi * i / n + _rng.uniform(-0.12, 0.12)
        v = _rng.uniform(110, 170)
        parts.append((a, v, _rng.choice(pal), _rng.uniform(0.9, 1.35)))
    BURSTS.append((bt, bx, by, parts))


def draw_fireworks(d, t):
    for bt, bx, by, parts in BURSTS:
        tau = t - bt
        if tau < 0 or tau > 1.5:
            continue
        if tau < 0.1:
            rect(d, bx - 4, by - 4, 8, 8, WHITE)
            rect(d, bx - 10, by - 1, 20, 2, YELLOW)
            rect(d, bx - 1, by - 10, 2, 20, YELLOW)
        for a, v, c, life in parts:
            if tau > life:
                continue
            dist = v * (1 - math.exp(-2.6 * tau)) / 2.6
            x = bx + math.cos(a) * dist
            y = by + math.sin(a) * dist + 26 * tau * tau
            fade = tau / life
            if fade > 0.7 and int(t * FPS) % 2 == 0:
                continue
            col = mix(c, BG, max(0, fade - 0.5) * 1.6)
            # 尾巴
            dist2 = v * (1 - math.exp(-2.6 * max(0, tau - 0.06))) / 2.6
            x2 = bx + math.cos(a) * dist2
            y2 = by + math.sin(a) * dist2 + 26 * max(0, tau - 0.06) ** 2
            rect(d, x2, y2, 2, 2, mix(col, BG, 0.55))
            sz = 3 if fade < 0.45 else 2
            rect(d, x, y, sz, sz, col)


# ---------------------------------------------------------------- 终端内容
def draw_terminal(d, t):
    # 第一行：$ claude
    y1 = 30
    text(d, 10, y1, "$", ORANGE)
    typed = "".join(ch for ch, ct in zip(CMD1, CMD1_T) if t >= ct)
    text(d, 26, y1, typed, FG)
    if t < ENTER1:
        typing = CMD1_T[0] <= t < CMD1_T[-1] + 0.12
        if typing or (t % 1.0) < 0.5:
            rect(d, 26 + tw(typed), y1 + 1, 8, 15, FG)

    # 欢迎框
    if t >= 2.6:
        k = clamp((t - 2.6) / 0.25)
        bw = int(340 * k)
        outline(d, 10, 54, max(bw, 2), 52, ORANGE)
        if t >= 2.85:
            text(d, 20, 62, "✻", ORANGE)
            text(d, 36, 62, "Welcome to Claude Code!", FG)
        if t >= 3.0:
            text(d, 20, 82, "/help for help · cwd: ~/playground", DIM)

    # 输入框
    if t >= 3.3:
        outline(d, 10, 556, 340, 32, DIM)
        bash_mode = 20.1 <= t < ENTER2 + 0.05
        prompt = "$" if bash_mode else ">"
        text(d, 18, 564, prompt, ORANGE if bash_mode else FG)
        typed2 = "".join(ch for ch, ct in zip(CMD2, CMD2_T) if t >= ct) if t < ENTER2 else ""
        if typed2:
            text(d, 34, 564, typed2, FG)
        elif not bash_mode:
            text(d, 44, 564, 'Try "fix all the bugs"', DIM)
        if (CMD2_T[0] <= t < CMD2_T[-1] + 0.1) or (t % 1.0) < 0.5:
            rect(d, 34 + tw(typed2), 565, 8, 15, FG if typed2 or bash_mode else DIM)
        text(d, 12, 596, "? for shortcuts", DIM)

    # bug 计数
    if 10.0 <= t:
        n = sum(1 for b in BUGS if t >= b["tc"])
        s = f"bugs fixed {n}/5"
        col = GREEN if n == 5 else FG
        x = 350 - tw(s)
        text(d, x, 114, s, col)
        if n == 5:
            draw_check(d, x - 14, 121, 2)

    # commit 输出
    if t >= ENTER2 + 0.1:
        text(d, 10, 500, "[main 7c1a0de] fixed everything", DIM)
    if t >= ENTER2 + 0.25:
        text(d, 10, 520, " 5 bugs squashed, 0 left behind ✓", GREEN)


def draw_bugs(d, t):
    for b in BUGS:
        if t >= b["tc"]:
            continue
        p = bug_pos(b, t)
        if p is None:
            continue
        x, y = p
        moving = t < b["tc"] - 0.55
        draw_bug(d, x, y, 3, int(t * 10) if moving else 0)
        # 被盯上时冒个 "!"
        if b["tc"] - 0.5 <= t < b["tc"]:
            sprite(d, x - 1, y - 32, 3, BANG_ROWS, {"X": YELLOW})


def draw_catches(d, t, st):
    for b in BUGS:
        tc = b["tc"]
        if tc <= t < tc + 0.3:
            # 夹在钳子里
            gx, gy = clawd_grab_point(st["cx"], st["by"], st["s"], b["side"])
            draw_bug(d, gx, gy - 4, 3, 0)
        if tc + 0.3 <= t < tc + 0.45:
            gx, gy = clawd_grab_point(st["cx"], st["by"], st["s"], b["side"])
            r = int((t - tc - 0.3) * 80) + 4
            for dx, dy in ((-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (r, -r), (-r, r), (r, r)):
                rect(d, gx + dx * 0.8, gy + dy * 0.8 - 3, 2, 2, WHITE)
        # 弹出 ✓
        tt = t - (tc + 0.3)
        if 0 <= tt < 1.1:
            gx, gy = b["x"], b["y"]
            sc = 2 if tt < 0.05 else (6 if tt < 0.12 else 5)
            yy = gy - 34 - 26 * ease_out(tt / 1.1)
            if tt > 0.85 and int(t * FPS) % 2:
                continue
            draw_check(d, gx, yy, sc)


def draw_bubble(d, x, y, s):
    w = tw(s) + 12
    rect(d, x, y, w, 22, BAR)
    outline(d, x, y, w, 22, ORANGE)
    rect(d, x + 6, y + 22, 4, 2, ORANGE)
    rect(d, x + 4, y + 24, 3, 2, ORANGE)
    text(d, x + 6, y + 3, s, FG)


def draw_intro_box(d, t):
    k = clamp((t - 25.75) / 0.3)
    if k <= 0:
        return
    h = max(2, int(BOX_H * smooth(k)))
    rect(d, BOX_X, BOX_Y, BOX_W, h, (18, 18, 24))
    outline(d, BOX_X, BOX_Y, BOX_W, h, ORANGE)
    if k < 1:
        return
    tag = " clawd "
    rect(d, BOX_X + 10, BOX_Y - 8, tw(tag), 16, BG)
    text(d, BOX_X + 10, BOX_Y - 8, tag, ORANGE)
    idx = 0
    last = None
    for ln, y in INTRO_LINES:
        shown = ""
        for ch in ln:
            if t >= INTRO_T[idx]:
                shown += ch
            idx += 1
        if shown:
            text(d, TEXT_X, y, shown, FG)
            last = (TEXT_X + tw(shown), y)
        if len(shown) < len(ln):
            break
    if last is None:
        last = (TEXT_X, BOX_Y + 18)
    if (t % 0.8) < 0.45 or t < INTRO_T[-1] + 0.1:
        rect(d, last[0] + 1, last[1] + 1, 8, 15, ORANGE)


def draw_easter_egg(d, t):
    if t < 37.0:
        return
    k = ease_out_back((t - 37.0) / 0.6)
    kx = lerp(430, 298, k)
    ky = lerp(720, 596, k)
    waving = t > 37.6
    wing_up = waving and int(t * 5) % 2 == 0
    draw_kiwi(d, kx, ky, 3, wing_up=wing_up, eyes="happy" if t > 38.3 else "open")
    shown = "".join(ch for ch, ct in zip(CAPTION, CAPTION_T) if t >= ct)
    if shown:
        text(d, 18, 606, shown, SKY)
    if t > 38.6:
        tt = t - 38.6
        hy = 486 - 14 * ease_out(tt / 1.2)
        sc = 2 if tt < 0.08 else 4
        sprite(d, 210, hy, sc, HEART_ROWS, {"X": PINK})


# ---------------------------------------------------------------- 渲染一帧
def render(t):
    img = BASE.copy()
    d = ImageDraw.Draw(img)
    d.fontmode = "1"
    st = clawd_state(t)

    if t < 25.35:
        draw_terminal(d, t)
        if 10.0 <= t < 20.0:
            draw_bugs(d, t)
        # 输入框盖住从下面爬出来的 bug
        if t >= 3.3:
            pass
        if 7.3 <= t < 9.4:
            draw_bubble(d, st["cx"] + 58, st["by"] - 66, "Hi~!")
        if 10.3 <= t < 10.9:
            sprite(d, st["cx"] - 2, st["by"] - 48, 4, BANG_ROWS, {"X": ORANGE})

    if st["visible"]:
        draw_clawd(d, st["cx"], st["by"], st["s"],
                   claw_l=st["claw_l"], claw_r=st["claw_r"],
                   lift_l=st["lift_l"], lift_r=st["lift_r"], leg=st["leg"],
                   eyes=st["eyes"], look=st["look"], blush=st["blush"], jump=st["jump"])

    if 10.0 <= t < 21.0:
        draw_catches(d, t, st)
    if 22.7 <= t < 25.4:
        draw_fireworks(d, t)

    # clear 擦屏
    if 25.0 <= t < 25.35:
        wy = int(lerp(23, H, (t - 25.0) / 0.35))
        rect(d, 0, 23, W, wy - 23, BG)
        rect(d, 0, wy, W, 2, ORANGE)
        st2 = st
        draw_clawd(d, st2["cx"], st2["by"], st2["s"], eyes=st2["eyes"])

    if t >= 25.4:
        text(d, 10, 30, "$", ORANGE)
        text(d, 26, 30, "".join(c for c, ct in zip(WHOAMI, WHOAMI_T) if t >= ct), DIM)
    if t >= 25.7:
        draw_intro_box(d, t)
    draw_easter_egg(d, t)
    return img


def upscale(img):
    big = img.resize((W * SCALE, H * SCALE), Image.NEAREST)
    arr = np.asarray(big).copy()
    arr[SCALE - 1::SCALE] = (arr[SCALE - 1::SCALE].astype(np.uint16) * 200 >> 8).astype(np.uint8)
    return arr


# ---------------------------------------------------------------- 入口
PREVIEW_TIMES = [0.9, 3.2, 5.6, 7.6, 12.25, 15.0, 23.3, 29.5, 36.0, 39.0]


def preview(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    thumbs = []
    for t in PREVIEW_TIMES:
        img = render(t)
        Image.fromarray(upscale(img)).save(os.path.join(out_dir, f"frame_{t:05.2f}s.png"))
        thumbs.append((t, img))
    cols = 5
    rows = (len(thumbs) + cols - 1) // cols
    pad = 8
    sheet = Image.new("RGB", (cols * (W + pad) + pad, rows * (H + 24 + pad) + pad), (40, 40, 46))
    sd = ImageDraw.Draw(sheet)
    sd.fontmode = "1"
    for i, (t, img) in enumerate(thumbs):
        x = pad + (i % cols) * (W + pad)
        y = pad + (i // cols) * (H + 24 + pad)
        sd.text((x, y + 2), f"t = {t:.2f}s", font=FONT, fill=ORANGE_L)
        sheet.paste(img, (x, y + 22))
    sheet.save(os.path.join(out_dir, "contact_sheet.png"))
    print("preview written to", out_dir)


def render_video(out):
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W * SCALE}x{H * SCALE}", "-r", str(FPS), "-i", "-",
           "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(NFRAMES):
        p.stdin.write(upscale(render(i / FPS)).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{NFRAMES}", flush=True)
    p.stdin.close()
    p.wait()
    print("video written to", out)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    here = os.path.dirname(os.path.abspath(__file__))
    if mode == "preview":
        preview(sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "preview"))
    else:
        render_video(sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "clawd_intro.mp4"))
