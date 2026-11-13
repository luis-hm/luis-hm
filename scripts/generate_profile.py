#!/usr/bin/env python3
"""Generate a Fastfetch-like SVG profile card. Uses Python standard library only.

Run locally: python scripts/generate_profile.py
Update public stats: GITHUB_TOKEN=... python scripts/generate_profile.py --live

The logo is original ASCII art, generated from the geometry below: a single
isometric block. No remote font, image, or image API is required.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'assets'
USERNAME = 'luis-hm'

DEFAULT = {'repos': '—', 'stars': '—', 'followers': '—',
           'commits': '—', 'contributions': '—', 'joined': '—', 'age': '—'}


def api(url: str, token: str, payload: dict | None = None):
    headers = {'Accept': 'application/vnd.github+json',
               'User-Agent': f'{USERNAME}-profile-readme',
               'X-GitHub-Api-Version': '2022-11-28'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    if data:
        headers['Content-Type'] = 'application/json'
    request = Request(url, data=data, headers=headers)
    with urlopen(request, timeout=18) as response:
        return json.load(response)


def get_live_stats(saved: dict) -> dict:
    stats = dict(saved)
    token = os.getenv('GITHUB_TOKEN', '').strip()
    try:
        user = api(f'https://api.github.com/users/{USERNAME}', token)
        stats['followers'] = str(user['followers'])
        created = datetime.fromisoformat(user['created_at'].replace('Z', '+00:00')).date()
        today = datetime.now(timezone.utc).date()
        months = (today.year-created.year)*12 + (today.month-created.month) - (today.day < created.day)
        stats['joined'] = str(created.year)
        stats['age'] = f'{months//12}y {months%12}m' if months >= 0 else '—'
    except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as e:
        print(f'Could not retrieve account metadata: {e}')

    # Public repositories and their stars, excluding forks. API pagination
    # makes the total accurate even for accounts with >100 repositories.
    try:
        stars = repos = 0
        for page in range(1, 21):
            entries = api(f'https://api.github.com/users/{USERNAME}/repos?type=owner&per_page=100&page={page}', token)
            if not isinstance(entries, list):
                raise ValueError('Unexpected repository response')
            repos += sum(not repo.get('fork', False) for repo in entries)
            stars += sum(repo.get('stargazers_count', 0) for repo in entries if not repo.get('fork', False))
            if len(entries) < 100:
                break
        stats['repos'], stats['stars'] = str(repos), str(stars)
    except (HTTPError, URLError, KeyError, ValueError, TimeoutError) as e:
        print(f'Could not retrieve repositories: {e}')

    # GitHub's own contribution counts for the trailing 12 months. They
    # are not lifetime commit counts and are labelled honestly on the card.
    if token:
        try:
            query = '''query($login: String!) {
              user(login: $login) {
                contributionsCollection {
                  totalCommitContributions
                  contributionCalendar { totalContributions }
                }
              }
            }'''
            result = api('https://api.github.com/graphql', token,
                         {'query': query, 'variables': {'login': USERNAME}})
            if result.get('errors'):
                raise ValueError(result['errors'])
            contributions = result['data']['user']['contributionsCollection']
            stats['commits'] = str(contributions['totalCommitContributions'])
            stats['contributions'] = str(contributions['contributionCalendar']['totalContributions'])
        except (HTTPError, URLError, KeyError, ValueError, TimeoutError, TypeError) as e:
            print(f'Could not retrieve contribution counts: {e}')
    return stats


# --- Original ASCII logo -----------------------------------------------
# An isometric block, drawn from geometry rather than traced from an image,
# so every edge lands on an exact character cell and the logo renders the
# same everywhere. Tones: 'W' top face, 'b' left side, 's' right side,
# 'e' front edge and contact shadow.
GRID_W, GRID_H = 43, 34
BOX_X, BOX_A, BOX_B, BOX_Y = 21, 18, 6, 11   # centre, half-width, half-height
BOX_H = 10                                   # height of the visible side faces


def build_art() -> dict:
    """A single isometric block: bright top face, two shaded sides."""
    chars = [[' '] * GRID_W for _ in range(GRID_H)]
    tones = [[' '] * GRID_W for _ in range(GRID_H)]

    def put(x, y, char, tone):
        if 0 <= x < GRID_W and 0 <= y < GRID_H:
            chars[y][x], tones[y][x] = char, tone

    lowest: dict[int, int] = {}
    for dy in range(-BOX_B, BOX_B + 1):
        half = int(BOX_A * (1 - abs(dy) / BOX_B) + 0.5)
        for x in range(BOX_X - half, BOX_X + half + 1):
            put(x, BOX_Y + dy, '\u2588', 'W')
            lowest[x] = max(lowest.get(x, -99), BOX_Y + dy)

    for x, bottom in lowest.items():
        side = 'b' if x < BOX_X else ('s' if x > BOX_X else 'e')
        for k in range(1, BOX_H + 1):
            put(x, bottom + k, '\u2588', side)
        put(x, bottom + BOX_H + 1, '\u2580', 'e')

    return {'chars': [''.join(row).rstrip() for row in chars],
            'tones': [''.join(row) for row in tones]}


def render_art(art: dict, colors: dict) -> list[str]:
    result = []
    x, y0, advance = 50, 51, 16.9
    palette = {'W': colors['top'], 'b': colors['left'],
               's': colors['right'], 'e': colors['edge']}
    for i, (chars, tones) in enumerate(zip(art['chars'], art['tones'])):
        if not chars.strip():
            continue
        spans = []
        for c, t in zip(chars, tones):
            if c == ' ':  # preserve gaps in text, but no unnecessary spans
                spans.append(' ')
            else:
                spans.append(f'<tspan fill="{palette.get(t, colors["top"])}">{escape(c)}</tspan>')
        result.append(f'<text x="{x}" y="{y0+i*advance:.1f}" class="mono" '
                      f'font-size="15.8" letter-spacing="0" xml:space="preserve">'
                      f'{"".join(spans)}</text>')
    return result


# --- Card text ----------------------------------------------------------
FONT_STEP = 8.8
TEXT_END = 1085


def section(x: int, y: float, text: str, colors: dict) -> str:
    # Thin rule exactly like the horizontal separators on a terminal.
    name_width = len(text) * 9.1 + 28
    return (f'<text x="{x}" y="{y:.1f}" class="mono" fill="{colors["fg"]}" '
            f'font-size="15">- {escape(text)}</text>'
            f'<line x1="{x+name_width:.1f}" x2="1091" y1="{y-5:.1f}" '
            f'y2="{y-5:.1f}" stroke="{colors["rule"]}" stroke-width="1" />')


def leader(key: str, val: str, start: float, end: float, colors: dict, indent: str = '  ') -> str:
    # Dot leaders are computed from font metrics so the right-hand values
    # line up in a column and the two sides never overlap.
    used = (len(indent) + len(key) + 1 + len(val)) * FONT_STEP
    dots = max(2, int((end - start - used - 11) / FONT_STEP))
    return (f'<tspan fill="{colors["fg"]}">{indent}</tspan>'
            f'<tspan fill="{colors["accent"]}">{escape(key)}:</tspan>'
            f'<tspan fill="{colors["rule"]}"> {"·" * dots} </tspan>'
            f'<tspan fill="{colors["value"]}">{escape(val)}</tspan>')


def info(x: int, y: float, key: str, val: str, colors: dict) -> str:
    return (f'<text x="{x}" y="{y:.1f}" class="mono" font-size="14.6">'
            f'{leader(key, val, x, TEXT_END, colors)}</text>')


def stat_pair(x: int, y: float, key1: str, value1: str,
              key2: str, value2: str, colors: dict) -> str:
    # Two leader columns of equal width, so the numbers align in a grid.
    mid = x + (TEXT_END - x) / 2
    return (f'<text x="{x}" y="{y:.1f}" class="mono" font-size="14.6">'
            f'{leader(key1, value1, x, mid - 18, colors)}</text>'
            f'<text x="{mid:.1f}" y="{y:.1f}" class="mono" font-size="14.6">'
            f'{leader(key2, value2, mid, TEXT_END, colors, indent="")}</text>')


def build(theme: str, stats: dict, art: dict) -> str:
    if theme == 'dark':
        colors = {'bg': '#151a22', 'border': '#303741', 'fg': '#dbe5f7',
                  'accent': '#ffa34b', 'value': '#91bdff', 'rule': '#6c7d92',
                  'top': '#93c5ff', 'left': '#3d6da8', 'right': '#1d3c5e',
                  'edge': '#16212e'}
    else:
        colors = {'bg': '#f6f8fa', 'border': '#d0d7de', 'fg': '#24292f',
                  'accent': '#ab5700', 'value': '#0969da', 'rule': '#8c959f',
                  'top': '#7fb3e8', 'left': '#3c7cbd', 'right': '#215184',
                  'edge': '#dbe3ea'}
    x, y, step = 449, 55., 21.6
    body = render_art(art, colors)
    body.append(section(x, y, 'luis-hm@github', colors)); y += step*1.4
    body.append(info(x, y, 'OS', 'Software Engineering @ UFC', colors)); y += step
    body.append(info(x, y, 'Role', 'Full Stack Developer', colors)); y += step
    body.append(info(x, y, 'Uptime', stats['age'] + ' on GitHub' if stats['age'] != '—' else '—', colors)); y += step
    body.append(info(x, y, 'Location', 'Brazil', colors)); y += step
    body.append(info(x, y, 'Focus', 'Applied ML, AI, IoT', colors)); y += step*1.40
    body.append(section(x, y, 'Technologies', colors)); y += step
    body.append(info(x, y, 'Languages', 'Python, TypeScript, JavaScript', colors)); y += step
    body.append(info(x, y, 'Frontend', 'Next.js, React', colors)); y += step
    body.append(info(x, y, 'Backend', 'Django, NestJS', colors)); y += step
    body.append(info(x, y, 'Database', 'PostgreSQL', colors)); y += step
    body.append(info(x, y, 'DevOps', 'Docker, GitHub Actions', colors)); y += step*1.40
    body.append(section(x, y, 'Contact', colors)); y += step
    body.append(info(x, y, 'Email.Personal', 'luisfelipeholanda12@gmail.com', colors)); y += step
    body.append(info(x, y, 'LinkedIn', 'linkedin.com/in/luisdevhm', colors)); y += step
    body.append(info(x, y, 'GitHub', 'github.com/luis-hm', colors)); y += step*1.4
    body.append(section(x, y, 'GitHub Stats', colors)); y += step
    body.append(stat_pair(x, y, 'Repos', stats['repos'], 'Stars', stats['stars'], colors)); y += step
    body.append(stat_pair(x, y, 'Commits/yr', stats['commits'], 'Followers', stats['followers'], colors)); y += step
    body.append(info(x, y, 'Contributions/yr', stats['contributions'], colors)); y += step
    # Small footer line, consistent with command-line aesthetics.
    body.append(f'<text x="{x+16}" y="{y+10:.1f}" class="mono" font-size="13" '
                f'fill="{colors["rule"]}">~ building thoughtful software, end to end.</text>')
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
           'width="1134" height="635" viewBox="0 0 1134 635" role="img" '
           'aria-labelledby="title desc">\n'
           '<title id="title">Luis Felipe — Fastfetch-style GitHub profile</title>\n'
           '<desc id="desc">Terminal-style card: an isometric stack logo beside software '
           'engineering details, tech stack, contact links, and automatically updated GitHub metrics.</desc>\n'
           '<style>.mono{font-family:Consolas,Menlo,Monaco,DejaVu Sans Mono,monospace;white-space:pre;}</style>\n'
           f'<rect x="1" y="1" width="1132" height="633" rx="16" fill="{colors["bg"]}" stroke="{colors["border"]}"/>\n'
           + '\n'.join(body) + '\n</svg>\n')
    return svg


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', help='Fetch current stats from GitHub API')
    args = parser.parse_args()
    ASSETS.mkdir(exist_ok=True)
    cache = ASSETS / 'stats.json'
    try:
        loaded = json.loads(cache.read_text(encoding='utf-8'))
    except (FileNotFoundError, ValueError):
        loaded = {}
    stats = dict(DEFAULT)
    stats.update({k: str(v) for k, v in loaded.items() if k in DEFAULT})
    if args.live:
        stats = get_live_stats(stats)
        cache.write_text(json.dumps(stats, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    art = build_art()
    for theme in ('dark', 'light'):
        file = ASSETS / f'{theme}_mode.svg'
        file.write_text(build(theme, stats, art), encoding='utf-8')
        print('Wrote', file)


if __name__ == '__main__':
    main()
