#!/usr/bin/env python3
"""Clawd 像素风自我介绍动画 —— 全部用代码画，Pillow 逐帧 + ffmpeg 合成。

画布在 360x640 的低分辨率上逐像素绘制，再用最近邻 x3 放大到 1080x1920，
最后叠一层轻微扫描线，做出 CRT 终端的感觉。

用法:
  python3 clawd_intro.py preview [out_dir]   # 渲染若干关键帧 + 拼图
  python3 clawd_intro.py render  [out.mp4]   # 渲染完整视频（含 8-bit 音效）
  python3 clawd_intro.py gif     [out.gif]   # 渲染 GitHub 主页用的 GIF
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
# 按官方形象：8x6 的橙色方块身体，两只 1x1 的黑眼睛，两侧 2x2 的小短手，四条腿。
# 内部用「半格」网格绘制（hs = s/2），这样眯眼、抬手、钳口开合都能更细腻。
#   身体  x 0..15, y 0..11      眼睛 (2..3, 2..3) / (12..13, 2..3)
#   左手  x -4..-1, y 4..7      腿   x 0-1, 4-5, 10-11, 14-15, y 12..15
def draw_clawd(d, cx, by, s, *, claw_l=0, claw_r=0, lift_l=0, lift_r=0,
               leg=0, eyes="open", look=0, blush=False, jump=0):
    """cx: 身体中心 x；by: 身体顶部 y（站在地面时）；s: 一格的像素数（4 的倍数最好）。
    claw_*: 小手张开程度 0/1/2；lift_*: 手抬高的半格数；leg: 步态 0..3。"""
    hs = s / 2.0
    bx = cx - 4 * s
    gy = by
    top = by - jump

    def h(x, y, w=1, hh=1, c=ORANGE):
        x0 = int(round(bx + x * hs))
        y0 = int(round(top + y * hs))
        x1 = int(round(bx + (x + w) * hs))
        y1 = int(round(top + (y + hh) * hs))
        rect(d, x0, y0, x1 - x0, y1 - y0, c)

    # 影子（贴地，跳起来时缩小）
    shrink = int(clamp(jump / (3 * s), 0, 1) * 4)
    rect(d, bx + (1 + shrink) * hs, gy + 16 * hs + 2, (14 - 2 * shrink) * hs, max(3, hs // 2), SHADOW)

    # 腿：两两交替抬起
    for lx, group in ((0, 0), (4, 1), (10, 0), (14, 1)):
        lifted = (leg == 1 and group == 0) or (leg == 3 and group == 1)
        h(lx, 12, 2, 3 if lifted else 4)

    # 身体
    h(0, 0, 16, 12)

    # 小手 / 钳子
    for side, o, lift in (("L", claw_l, lift_l), ("R", claw_r, lift_r)):
        cells = set()
        for x in range(-4, 0):
            for y in range(4, 8):
                cells.add((x, y - lift))
        if o >= 1:   # 外侧张开一道口子
            for x in range(-4, -4 + o):
                for y in (5, 6):
                    cells.discard((x, y - lift))
        if o >= 2:   # 上下两瓣再往外撇一点
            cells.add((-4, 3 - lift))
            cells.add((-4, 8 - lift))
        for x, y in cells:
            h(x if side == "L" else 15 - x, y)

    # 眼睛（以 1/4 格为单位画表情）
    q = s / 4.0
    for ex in (2 + look, 12 + look):
        x0, y0 = bx + ex * hs, top + 2 * hs

        def e(i, j, w=1, hh=1):
            xa, ya = int(round(x0 + i * q)), int(round(y0 + j * q))
            xb, yb = int(round(x0 + (i + w) * q)), int(round(y0 + (j + hh) * q))
            rect(d, xa, ya, xb - xa, yb - ya, EYE)

        if eyes == "open":
            e(0, 0, 4, 4)
        elif eyes == "blink":
            e(0, 2, 4, 1)
        elif eyes == "happy":
            e(1, 1, 2, 1)
            e(0, 2, 1, 2)
            e(3, 2, 1, 2)
    if blush:
        for x in (1, 13):
            x0 = int(round(bx + x * hs))
            rect(d, x0, int(round(top + 5 * hs)), int(round(2 * hs)), max(2, int(hs / 2)), PINK)


def clawd_grab_point(cx, by, s, side, lift=0):
    """钳口中心（用来对准 bug）"""
    hs = s / 2.0
    off = 4 * s + 3.5 * hs
    return (cx - off if side == "L" else cx + off, by + (6 - lift) * hs)


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

STAGE_Y = 300          # Clawd 站位（身体顶部）
CS = 12                # Clawd 常规尺寸

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
        off = 5.75 * CS
        target = (b["x"] + off if side == "L" else b["x"] - off, b["y"] - 3 * CS)
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
            st["lift_l"] = st["lift_r"] = 1 if (t < 7.35 or t > 9.2) else 3
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
            st["jump"] = 30 * abs(math.sin(math.pi * tt / 0.45))
        st["eyes"] = "happy"
        st["lift_l"] = st["lift_r"] = 3
        st["claw_l"] = st["claw_r"] = 2 if int(tt * 6) % 2 == 0 else 1
    elif t < 25.7:                                  # 镜头推近
        k = smooth((t - 25.0) / 0.6)
        st["s"] = 12 if t < 25.2 else (14 if t < 25.4 else 16)
        st["by"] = lerp(STAGE_Y, 116, k)
    else:                                           # S5 / S6 面对镜头
        st["s"] = 16
        st["by"] = 116 + (2 if int(t * 2) % 2 else 0)
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
            if t > 37.3:
                up = int(t * 5) % 2 == 0
                st["lift_r"] = 4 if up else 2
                st["claw_r"] = 2 if up else 0
            else:
                st["lift_r"] = 2
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
        draw_bug(d, x, y, 4, int(t * 10) if moving else 0)
        # 被盯上时冒个 "!"
        if b["tc"] - 0.5 <= t < b["tc"]:
            sprite(d, x - 1, y - 40, 3, BANG_ROWS, {"X": YELLOW})


def draw_catches(d, t, st):
    for b in BUGS:
        tc = b["tc"]
        if tc <= t < tc + 0.3:
            # 夹在钳子里
            gx, gy = clawd_grab_point(st["cx"], st["by"], st["s"], b["side"])
            draw_bug(d, gx, gy, 4, 0)
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
            draw_bubble(d, st["cx"] + 44, st["by"] - 44, "Hi~!")
        if 10.3 <= t < 10.9:
            sprite(d, st["cx"] - 2, st["by"] - 34, 4, BANG_ROWS, {"X": ORANGE})

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


# ---------------------------------------------------------------- 8-bit 音效 & 配乐
SR = 44100


def midi_hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


class Mixer:
    def __init__(self, dur):
        self.n = int(SR * dur)
        self.buf = np.zeros(self.n, dtype=np.float64)
        self.rng = np.random.default_rng(7)

    def add(self, t0, sig, vol=1.0):
        i = int(t0 * SR)
        if i >= self.n or i + len(sig) <= 0:
            return
        if i < 0:
            sig, i = sig[-i:], 0
        seg = sig[: self.n - i]
        self.buf[i:i + len(seg)] += seg * vol

    # --- 振荡器
    @staticmethod
    def _phase(f0, f1, dur):
        k = int(dur * SR)
        f = np.linspace(f0, f1, k) if f1 is not None else np.full(k, f0)
        return np.cumsum(f) / SR

    def square(self, f0, dur, f1=None, duty=0.5):
        ph = self._phase(f0, f1, dur)
        return np.where((ph % 1.0) < duty, 1.0, -1.0)

    def tri(self, f0, dur, f1=None):
        ph = self._phase(f0, f1, dur)
        return 4.0 * np.abs((ph % 1.0) - 0.5) - 1.0

    def noise(self, dur, lp=1.0):
        x = self.rng.uniform(-1, 1, int(dur * SR))
        if lp < 1.0:          # 一阶低通，让爆炸声更闷
            y = np.empty_like(x)
            acc = 0.0
            for i, v in enumerate(x):
                acc += lp * (v - acc)
                y[i] = acc
            x = y / max(1e-6, np.abs(y).max())
        return x

    @staticmethod
    def env(sig, attack=0.003, decay=None, release=0.01):
        k = len(sig)
        t = np.arange(k) / SR
        e = np.ones(k)
        if attack > 0:
            e *= np.clip(t / attack, 0, 1)
        if decay:
            e *= np.exp(-t / decay)
        if release > 0:
            e *= np.clip((k / SR - t) / release, 0, 1)
        return sig * e

    # --- 音色
    def key(self, t, soft=False):
        f = self.rng.uniform(1700, 2300)
        if soft:
            self.add(t, self.env(self.tri(f * 0.6, 0.03), decay=0.01), 0.10)
        else:
            self.add(t, self.env(self.square(f, 0.025, duty=0.25), decay=0.008), 0.10)
            self.add(t, self.env(self.noise(0.02), decay=0.004), 0.06)

    def enter(self, t):
        self.add(t, self.env(self.square(620, 0.06, duty=0.25), decay=0.03), 0.16)
        self.add(t + 0.06, self.env(self.square(930, 0.08, duty=0.25), decay=0.04), 0.16)

    def notes(self, t, ms, step=0.07, dur=0.09, vol=0.14, duty=0.25, wave="square"):
        for i, m in enumerate(ms):
            f = midi_hz(m)
            sig = self.square(f, dur, duty=duty) if wave == "square" else self.tri(f, dur)
            self.add(t + i * step, self.env(sig, decay=dur * 0.6), vol)

    def step(self, t):
        self.add(t, self.env(self.noise(0.03, lp=0.25), decay=0.008), 0.10)

    def snap(self, t):
        self.add(t, self.env(self.square(520, 0.07, f1=160, duty=0.5), decay=0.025), 0.16)
        self.add(t, self.env(self.noise(0.05), decay=0.01), 0.10)

    def click(self, t):
        self.add(t, self.env(self.square(2400, 0.02, duty=0.125), decay=0.006), 0.08)

    def boom(self, t):
        self.add(t - 0.22, self.env(self.square(500, 0.2, f1=1600, duty=0.125), decay=0.12), 0.05)
        self.add(t, self.env(self.noise(0.7, lp=0.08), decay=0.18), 0.45)
        self.add(t, self.env(self.tri(110, 0.3, f1=40), decay=0.1), 0.35)
        for _ in range(14):
            dt = float(self.rng.uniform(0.15, 1.1))
            self.add(t + dt, self.env(self.noise(0.012), decay=0.003), float(self.rng.uniform(0.04, 0.10)))

    def boing(self, t):
        k = int(0.35 * SR)
        tt = np.arange(k) / SR
        f = 260 + 520 * tt / 0.35 + 40 * np.sin(2 * np.pi * 18 * tt)
        ph = np.cumsum(f) / SR
        sig = np.sin(2 * np.pi * ph)
        self.add(t, self.env(sig, decay=0.2), 0.25)


# 配乐：C - G - Am - F，120 BPM，三角波贝斯 + 12.5% 方波琶音 + 噪声小鼓
CHORDS = [(48, [60, 64, 67, 72]), (43, [59, 62, 67, 71]), (45, [57, 60, 64, 69]), (41, [57, 60, 65, 69])]
BEAT = 0.5


def add_music(mx, t_start, t_end, vol=1.0):
    t = t_start
    bar = 0
    while t < t_end - 0.01:
        root, tones = CHORDS[bar % 4]
        for b in range(4):
            tb = t + b * BEAT
            if tb >= t_end:
                break
            # 贝斯：根音 / 五度
            m = root if b % 2 == 0 else root + 7
            mx.add(tb, mx.env(mx.tri(midi_hz(m), 0.42), decay=0.25), 0.22 * vol)
            # 底鼓 & 小镲
            if b in (0, 2):
                mx.add(tb, mx.env(mx.tri(140, 0.12, f1=45), decay=0.05), 0.30 * vol)
            mx.add(tb + BEAT / 2, mx.env(mx.noise(0.03), decay=0.006), 0.05 * vol)
            if b in (1, 3):
                mx.add(tb, mx.env(mx.noise(0.08, lp=0.35), decay=0.03), 0.10 * vol)
            # 琶音（16 分音符）
            for k in range(4):
                tk = tb + k * BEAT / 4
                if tk >= t_end:
                    break
                tone = tones[(b * 4 + k) % 4] + 12
                mx.add(tk, mx.env(mx.square(midi_hz(tone), 0.1, duty=0.125), decay=0.04), 0.035 * vol)
        t += 4 * BEAT
        bar += 1


def build_audio(path):
    mx = Mixer(DURATION)
    # ---- 打字
    for ct in CMD1_T + CMD2_T + WHOAMI_T + CAPTION_T:
        mx.key(ct)
    for ct, ch in zip(INTRO_T, INTRO_FLAT):
        if ch != " ":
            mx.key(ct, soft=True)
    mx.enter(ENTER1)
    mx.enter(ENTER2)
    mx.notes(2.62, [72, 76, 79, 84], step=0.07)                 # 欢迎框
    mx.click(20.1)                                             # 切到 bash 模式

    # ---- 根据动画状态找脚步、钳子开合、跳跃落地
    prev = None
    for i in range(NFRAMES):
        t = i / FPS
        st = clawd_state(t)
        if prev and st["visible"]:
            if st["leg"] != prev["leg"] and st["leg"] in (1, 3):
                mx.step(t)
            for k in ("claw_l", "claw_r"):
                if st[k] > prev[k] and prev[k] == 0:
                    mx.click(t)
                elif st[k] == 0 and prev[k] > 0:
                    mx.snap(t)
            if prev["jump"] > 3 and st["jump"] <= 3 and t < 25:
                mx.step(t)
        prev = st

    # ---- 剧情音效
    mx.notes(7.3, [79, 84], step=0.12, dur=0.12, vol=0.12, wave="tri")   # Hi~
    mx.notes(10.3, [88, 93], step=0.06, dur=0.06, vol=0.10)              # Clawd 发现 bug
    for i, b in enumerate(BUGS):
        mx.notes(b["t0"] + 0.2, [62, 61], step=0.08, dur=0.06, vol=0.06)  # bug 出没
        mx.notes(b["tc"] - 0.5, [86, 90], step=0.05, dur=0.05, vol=0.08)  # bug 被盯上
        base = [72, 74, 76, 79, 81][i]
        mx.notes(b["tc"] + 0.3, [base, base + 7, base + 12], step=0.06, dur=0.1, vol=0.13)  # ✓
    mx.notes(18.95, [72, 76, 79, 84, 88, 91, 96], step=0.05, dur=0.08, vol=0.10)  # 5/5
    for bt, _, _, _ in BURSTS:
        mx.boom(bt)
    mx.notes(ENTER2 + 0.3, [84, 83, 84, 88, 91], step=0.09, dur=0.12, vol=0.10)
    mx.add(25.0, mx.env(mx.square(1400, 0.35, f1=180, duty=0.25), decay=0.2), 0.10)  # clear
    mx.notes(25.2, [76, 83], step=0.2, dur=0.08, vol=0.10)                            # 推镜头
    mx.notes(25.75, [72, 79], step=0.08, dur=0.1, vol=0.10)                           # 对话框

    # ---- 配乐
    add_music(mx, 4.3, 25.0, vol=1.0)
    add_music(mx, 26.0, 37.0, vol=0.7)

    # ---- 彩蛋：Rhett 的小主题
    mx.boing(37.0)
    jingle = [(37.6, 79, .14), (37.75, 84, .14), (37.9, 88, .14), (38.05, 91, .3),
              (38.45, 88, .14), (38.6, 91, .14), (38.75, 96, .45)]
    for tj, m, dj in jingle:
        mx.add(tj, mx.env(mx.square(midi_hz(m), dj, duty=0.25), decay=dj * 0.8), 0.12)
        mx.add(tj, mx.env(mx.tri(midi_hz(m - 12), dj), decay=dj), 0.10)
    mx.notes(38.6, [96, 100, 103], step=0.04, dur=0.06, vol=0.06)        # 小爱心
    for m in (48, 60, 64, 67, 72):                                          # 收尾和弦
        mx.add(39.2, mx.env(mx.tri(midi_hz(m), 0.8), decay=0.5, release=0.3), 0.12)
    for m in (76, 79):
        mx.add(39.2, mx.env(mx.square(midi_hz(m), 0.8, duty=0.125), decay=0.35, release=0.3), 0.04)

    y = mx.buf
    y = np.tanh(y * 1.1) / np.tanh(1.1)
    y = y / max(1e-6, np.abs(y).max()) * 0.89
    fade = int(0.25 * SR)
    y[-fade:] *= np.linspace(1, 0, fade)
    pcm = (y * 32767).astype(np.int16)
    import wave
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
    print("audio written to", path)


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
    wav = os.path.splitext(out)[0] + ".wav"
    build_audio(wav)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W * SCALE}x{H * SCALE}",
           "-r", str(FPS), "-i", "-", "-i", wav,
           "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-tune", "animation",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
           "-movflags", "+faststart", "-shortest", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(NFRAMES):
        p.stdin.write(upscale(render(i / FPS)).tobytes())
        if i % 150 == 0:
            print(f"frame {i}/{NFRAMES}", flush=True)
    p.stdin.close()
    p.wait()
    print("video written to", out)


def render_gif(out, fps=15, scale=1):
    """GitHub 主页用的 GIF：原生像素尺寸，无扫描线，无损调色板。"""
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W * scale}x{H * scale}",
           "-r", str(fps), "-i", "-",
           "-vf", "split[a][b];[a]palettegen=max_colors=128:stats_mode=full:reserve_transparent=0[p];"
                  "[b][p]paletteuse=dither=none:diff_mode=rectangle",
           "-loop", "0", out]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(DURATION * fps)
    for i in range(n):
        img = render(i / fps)
        if scale != 1:
            img = img.resize((W * scale, H * scale), Image.NEAREST)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()
    print("gif written to", out)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "preview"
    here = os.path.dirname(os.path.abspath(__file__))
    if mode == "preview":
        preview(sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "preview"))
    elif mode == "gif":
        render_gif(sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "clawd_intro.gif"))
    else:
        render_video(sys.argv[2] if len(sys.argv) > 2 else os.path.join(here, "clawd_intro.mp4"))
