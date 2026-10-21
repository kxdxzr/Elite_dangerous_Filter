"""Single source for application identity and derived Windows version fields."""
import re

PROJECT_AUTHOR = 'kxdxzr'
PROJECT_NAME = 'Elite_dangerous_Filter'
PROJECT_VERSION = '0.1.4'
PROJECT_URL = 'https://github.com/kxdxzr/Elite_dangerous_Filter'


def windows_version_fields(version=None):
    """Keep the public version string; derive four numeric fields for Windows."""
    version = PROJECT_VERSION if version is None else version
    match = re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?', version)
    if not match:
        raise ValueError('Application version must use major.minor.patch[-prerelease][+build]')
    numeric = tuple(map(int, match.group(1, 2, 3))) + (0,)
    if any(part > 65535 for part in numeric):
        raise ValueError('Windows version components must not exceed 65535')
    return dict(
        filevers=numeric, prodvers=numeric, flags=0x2 if match.group(4) else 0,
        strings={
            'CompanyName': PROJECT_AUTHOR,
            'FileDescription': 'Elite Dangerous system and station filter',
            'FileVersion': '.'.join(map(str, numeric)),
            'InternalName': 'EliteDangerousFilter',
            'LegalCopyright': 'GPL-3.0-only; see LICENSE',
            'OriginalFilename': 'EliteDangerousFilter.exe',
            'ProductName': PROJECT_NAME,
            'ProductVersion': version,
        },
    )
