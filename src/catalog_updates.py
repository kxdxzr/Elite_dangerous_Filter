"""Data-only, versioned GitHub catalogue updates. Never executes downloaded code."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import urllib.parse
import urllib.request

from runtime_paths import data_file
from file_io import atomic_write

REPOSITORY = 'kxdxzr/Elite_dangerous_Filter'
API = f'https://api.github.com/repos/{REPOSITORY}/releases?per_page=10'
FORMAT = 1
ACTIVE = 'outfitting_release.json'
PREVIOUS = 'outfitting_release.previous.json'
LIMIT = 16 * 1024 * 1024
LOCK = threading.RLock()
GROUPS = {'ordinary', 'power', 'ax', 'merc', 'excluded', 'armour'}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}\.\d{2}\.\d{2}\.\d{1,6}', value):
        raise ValueError('清单版本格式无效')
    return tuple(map(int, value.split('.')))


def download(url, limit=LIMIT):
    parsed = urllib.parse.urlsplit(url)
    allowed = {'api.github.com', 'github.com', 'release-assets.githubusercontent.com',
               'objects.githubusercontent.com'}
    if parsed.scheme != 'https' or parsed.hostname not in allowed:
        raise ValueError('清单下载地址不可信')
    request = urllib.request.Request(url, headers={'User-Agent': 'EliteDangerousFilter-catalog',
                                                  'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=45) as response:
        final = urllib.parse.urlsplit(response.geturl())
        if final.scheme != 'https' or final.hostname not in allowed:
            raise ValueError('清单重定向地址不可信')
        content = response.read(limit + 1)
    if len(content) > limit:
        raise ValueError('清单文件过大')
    return content


def validate(package):
    """Fail closed on unknown semantics, contradictory IDs or incomplete records."""
    if not isinstance(package, dict) or package.get('format') != FORMAT:
        raise ValueError('清单格式不兼容，请升级程序')
    version(package.get('version'))
    if type(package.get('engine')) is not int or package['engine'] != 1:
        raise ValueError('清单规则不兼容，请升级程序')
    if not isinstance(package.get('sources'), list) or not package['sources'] or not all(
            isinstance(x, str) and x for x in package['sources']):
        raise ValueError('清单缺少来源版本')
    entries = package.get('entries')
    facts = package.get('module_facts')
    ships = package.get('ships')
    if (not isinstance(entries, list) or not entries or not isinstance(facts, list) or not facts
            or not isinstance(ships, list) or not ships or not all(isinstance(x, str) and x for x in ships)):
        raise ValueError('清单内容不完整')
    def records(rows):
        result = {}
        for item in rows:
            if (not isinstance(item, dict) or type(item.get('ed_id')) is not int or item['ed_id'] <= 0
                    or not isinstance(item.get('name'), str) or not item['name']
                    or not isinstance(item.get('ed_symbol'), str) or not item['ed_symbol']
                    or type(item.get('class')) is not int or not 0 <= item['class'] <= 8
                    or item.get('rating') not in tuple('ABCDEFGHI')
                    or not isinstance(item.get('category'), str)):
                raise ValueError('清单含无效装备规格')
            if item['ed_id'] in result:
                raise ValueError('清单数字ID重复')
            result[item['ed_id']] = item
        return result
    indexed = records(facts)
    classified = records(entries)
    if set(classified) != set(indexed):
        raise ValueError('清单含未分类或无身份事实的装备')
    for ident, item in classified.items():
        if item.get('group') not in GROUPS:
            raise ValueError('清单含未知装备分类')
        if any(item.get(k) != indexed[ident].get(k) for k in
               ('name', 'ed_symbol', 'class', 'rating', 'category', 'ship', 'weapon_mode')):
            raise ValueError('清单身份与规格不一致')
        if item['group'] == 'excluded' and (not isinstance(item.get('reason'), str) or not item['reason'].strip()):
            raise ValueError('排除项缺少理由')
        if item['group'] == 'armour' and item.get('ship') not in ships:
            raise ValueError('装甲缺少对应舰船')
    if not {'ordinary', 'power', 'ax'}.issubset({x['group'] for x in entries}):
        raise ValueError('清单必需分类不完整')
    return copy.deepcopy(package)


def read_package(filename=ACTIVE):
    path = Path(data_file(filename))
    if not path.exists():
        return None
    if path.stat().st_size > LIMIT:
        raise ValueError('本地清单文件过大')
    return validate(json.loads(path.read_text(encoding='utf-8')))


def check(fetch=download):
    releases = json.loads(fetch(API, 2 * 1024 * 1024))
    if not isinstance(releases, list):
        raise ValueError('GitHub清单响应无效')
    candidates = []
    prefix = f'https://github.com/{REPOSITORY}/releases/download/'
    for release in releases:
        tag = release.get('tag_name', '')
        if release.get('draft') or not tag.startswith('catalog-'):
            continue
        ver = tag[len('catalog-'):]
        try:
            parsed = version(ver)
        except ValueError:
            continue
        for asset in release.get('assets', []):
            if asset.get('name') == 'catalog-manifest.json':
                url = asset.get('browser_download_url', '')
                if not url.startswith(prefix + tag + '/'):
                    raise ValueError('清单发布地址不匹配')
                candidates.append((parsed, ver, url, tag))
    if not candidates:
        return None
    _, ver, url, tag = max(candidates)
    manifest = json.loads(fetch(url, 128 * 1024))
    if (not isinstance(manifest, dict) or manifest.get('version') != ver
            or manifest.get('format') != FORMAT or manifest.get('engine') != 1
            or manifest.get('file') != 'catalog.json'
            or not re.fullmatch(r'[0-9a-f]{64}', str(manifest.get('sha256', '')))
            or not isinstance(manifest.get('summary'), str)):
        raise ValueError('清单更新不兼容或发布说明无效')
    return dict(manifest, url=prefix + tag + '/catalog.json')


def install(manifest, fetch=download):
    content = fetch(manifest['url'], LIMIT)
    if hashlib.sha256(content).hexdigest() != manifest['sha256']:
        raise ValueError('清单校验失败，保留原版本')
    package = validate(json.loads(content))
    if package['version'] != manifest['version']:
        raise ValueError('清单版本不匹配')
    with LOCK:
        try:
            previous = read_package()
        except ValueError:
            previous = None  # A corrupt local update must not prevent repair.
        if previous and version(package['version']) <= version(previous['version']):
            raise ValueError('当前清单已经是此版本或更新版本')
        if previous:
            atomic_write(data_file(PREVIOUS), json.dumps(previous, ensure_ascii=False).encode('utf-8'))
        atomic_write(data_file(ACTIVE), content)
    return package['version']


def rollback():
    with LOCK:
        old = read_package(PREVIOUS)
        if old is None:
            if read_package() is None:
                raise ValueError('没有可回退的清单')
            # The first installation's predecessor is the original catalogue.
            os.replace(data_file(ACTIVE), data_file(PREVIOUS))
            return '内置目录'
        atomic_write(data_file(ACTIVE), json.dumps(old, ensure_ascii=False).encode('utf-8'))
    return old['version']


def as_catalog(package):
    package = validate(package)
    groups = {name: [] for name in GROUPS}
    for entry in package['entries']:
        item = dict(entry, catalog_group=entry['group'])
        groups[entry['group']].append(item)
    return dict(items=[*groups['ordinary'], *groups['power'], *groups['ax']],
                special_items=groups['merc'], armours=groups['armour'], ships=package['ships'],
                module_facts=package['module_facts'], issues=[], special_issues=[],
                special_errors=[], release_version=package['version'],
                release_sources=package['sources'], release_engine=1,
                built_at=package.get('built_at', ''), identity_revision=package['version'])
