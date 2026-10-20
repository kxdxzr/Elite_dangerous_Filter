"""Validate a reviewed JSON catalogue and create data-only GitHub release assets."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import catalog_updates


def build(source, output, summary, previous=None):
    package = catalog_updates.validate(json.loads(Path(source).read_text(encoding='utf-8')))
    content = (json.dumps(package, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    manifest = dict(format=catalog_updates.FORMAT, engine=1, version=package['version'],
                    file='catalog.json', sha256=hashlib.sha256(content).hexdigest(), summary=summary)
    changes = None
    if previous:
        old = catalog_updates.validate(json.loads(Path(previous).read_text(encoding='utf-8')))
        if catalog_updates.version(package['version']) <= catalog_updates.version(old['version']):
            raise ValueError('New catalogue version must be greater than the previous version')
        before = {item['ed_id']: item for item in old['entries']}
        after = {item['ed_id']: item for item in package['entries']}
        changes = dict(added=[after[i] for i in sorted(after.keys()-before.keys())],
                       removed=[before[i] for i in sorted(before.keys()-after.keys())],
                       changed=[dict(before=before[i], after=after[i]) for i in sorted(before.keys() & after.keys())
                                if before[i] != after[i]])
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / 'catalog.json').write_bytes(content)
    (output / 'catalog-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if changes is not None:
        (output / 'catalog-changes.json').write_text(json.dumps(changes, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', help='Reviewed JSON catalogue (see docs/catalog-updates.md)')
    parser.add_argument('output', help='Output asset directory, outside the repository')
    parser.add_argument('--summary', required=True, help='User-visible release change summary')
    parser.add_argument('--previous', help='Previous reviewed catalogue; writes a per-ID change report')
    args = parser.parse_args()
    manifest = build(args.source, args.output, args.summary, args.previous)
    print('Release tag: catalog-' + manifest['version'])
    print('Upload catalog.json and catalog-manifest.json. Assets contain data only.')
