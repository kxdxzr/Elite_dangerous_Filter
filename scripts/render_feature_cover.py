"""Render feature-led README/social covers. Developer-only; requires Pillow.

Run from the project root: python scripts/render_feature_cover.py
No screenshots, network, application imports or personal data are used.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PROJECT = Path(__file__).resolve().parents[1]
SCALE = 2
BG = '#0C121C'
TEXT = '#F2F5FA'
MUTED = '#A6B4C8'
ORANGE = '#FFAA60'
COPY = {
    'en': {
        'file': 'social-preview.png',
        'eyebrow': 'ELITE DANGEROUS  /  SYSTEM & STATION SEARCH',
        'tagline': ['Your conditions. The right destination.',
                    'Combine filters. Plan your shopping. Find your next stop.'],
        'cards': [
            ('COMBINE FILTERS', 'Search with precision',
             ['Multiple reference distances', 'Planets, rings & station filters']),
            ('PLAN YOUR SHOPPING', 'Outfit in one stop',
             ['Full-outfitting station checks', 'Shopping on your engineer trip']),
            ('FIND YOUR NEXT STOP', 'Choose where to go',
             ['Colonisation & pirate targets', 'Recorded carrier counts']),
        ],
        'footer': 'Windows desktop  /  中文 + English  /  Saved conditions  /  CSV export',
        'note': 'Public data, not live guarantees. Verify availability in game.',
    },
    'zh': {
        'file': 'social-preview-zh.png',
        'eyebrow': 'ELITE DANGEROUS  /  星系与站点筛选',
        'tagline': ['组合你的条件，找到合适的目的地。',
                    '复杂筛选、装备采购、活动选址，一个工具完成。'],
        'cards': [
            ('组合筛选', '按需求，精确查找', ['多参考点距离条件', '天体、星环与站点筛选']),
            ('装备采购', '少跑站，一站配齐', ['按目录核验满配件站', '前往工程师途中采购']),
            ('活动选址', '下一站，有的放矢', ['殖民候选与海盗任务选址', '航母收录数量参考']),
        ],
        'footer': 'Windows 桌面工具  /  中文 + English  /  条件保存  /  CSV 导出',
        'note': '基于公开数据，不保证实时库存、空位或可认领状态，请在游戏内核实。',
    },
}


def find_font(override, bold=False):
    candidates = ([Path(override)] if override else []) + [
        Path('C:/Windows/Fonts') / ('msyhbd.ttc' if bold else 'msyh.ttc'),
        Path('/usr/share/fonts/opentype/noto') / ('NotoSansCJK-Bold.ttc' if bold else 'NotoSansCJK-Regular.ttc'),
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError('A CJK-capable font is required; pass --font and --bold-font.')


def render(copy, regular, bold, destination):
    image = Image.new('RGB', (1280 * SCALE, 640 * SCALE), BG)
    draw = ImageDraw.Draw(image)

    def line(points, fill, width=1):
        draw.line([(x * SCALE, y * SCALE) for x, y in points], fill=fill, width=width * SCALE)

    def rect(box, fill, outline=None, radius=0):
        draw.rounded_rectangle(tuple(v * SCALE for v in box), radius=radius * SCALE,
                               fill=fill, outline=outline, width=SCALE)

    def text(x, y, value, size, color=TEXT, strong=False, max_width=None):
        font = ImageFont.truetype(str(bold if strong else regular), size * SCALE)
        if max_width is not None and draw.textlength(value, font=font) > max_width * SCALE:
            raise ValueError(f'Cover text exceeds its layout: {value}')
        draw.text((x * SCALE, y * SCALE), value, font=font, fill=color, anchor='lt')

    # Decorative route, rather than a screenshot or a claim of a real game route.
    for y in range(40, 245, 36):
        for x in range(965, 1250, 36):
            rect((x, y, x + 1, y + 1), '#25354A')
    line([(1020, 215), (1072, 160), (1140, 188), (1208, 102)], '#33475E', 2)
    for x, y in ((1020, 215), (1072, 160), (1140, 188), (1208, 102)):
        rect((x - 4, y - 4, x + 4, y + 4), ORANGE, radius=4)
    rect((48, 44, 79, 48), ORANGE, radius=2)
    text(92, 38, copy['eyebrow'], 15, MUTED, max_width=1000)
    text(48, 88, 'Elite Dangerous Filter', 57, strong=True, max_width=1120)
    text(50, 172, copy['tagline'][0], 30, max_width=1120)
    text(50, 220, copy['tagline'][1], 20, MUTED, max_width=1120)

    for index, (label, title, details) in enumerate(copy['cards']):
        x = 48 + index * 400
        rect((x, 282, x + 384, 514), '#121D2C', '#293A50', radius=16)
        rect((x + 22, 307, x + 25, 329), ORANGE, radius=1)
        text(x + 38, 309, label, 14, ORANGE, strong=True, max_width=320)
        text(x + 24, 355, title, 25, strong=True, max_width=336)
        line([(x + 24, 399), (x + 360, 399)], '#2B3B50')
        for row, detail in enumerate(details):
            text(x + 24, 421 + row * 36, detail, 18, MUTED, max_width=336)

    text(50, 552, copy['footer'], 18, max_width=1180)
    text(50, 592, copy['note'], 14, MUTED, max_width=1180)
    image.resize((1280, 640), Image.Resampling.LANCZOS).save(destination, optimize=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=PROJECT / 'docs')
    parser.add_argument('--font', help='Regular CJK font path')
    parser.add_argument('--bold-font', help='Bold CJK font path')
    args = parser.parse_args()
    regular, bold = find_font(args.font), find_font(args.bold_font, bold=True)
    args.output.mkdir(parents=True, exist_ok=True)
    for copy in COPY.values():
        path = args.output / copy['file']
        render(copy, regular, bold, path)
        print(path)


if __name__ == '__main__':
    main()
