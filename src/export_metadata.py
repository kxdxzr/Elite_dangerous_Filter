"""Shared provenance preamble for CSV exports (not result records)."""
from datetime import datetime

PROJECT_AUTHOR = 'kxdxzr'
PROJECT_NAME = 'Elite_dangerous_Filter'
PROJECT_VERSION = '0.1.4-beta.2'
PROJECT_URL = 'https://github.com/kxdxzr/Elite_dangerous_Filter'


def write_csv_provenance(writer, column_count, language='zh'):
    """Write five labelled metadata rows followed by a blank separator.

    Importers should skip this preamble before reading the result header.
    Timestamp is generated per export, with an explicit local UTC offset.
    """
    exported_at = datetime.now().astimezone().isoformat(timespec='seconds')
    labels = (('GitHub project author', 'Project name', 'Version', 'Exported at', 'Project URL')
              if language == 'en' else ('源于 GitHub 项目作者', '项目名', '版本号', '导出时间', '项目链接'))
    values = (PROJECT_AUTHOR, PROJECT_NAME, PROJECT_VERSION, exported_at, PROJECT_URL)
    padding = [''] * max(0, column_count - 2)
    for label, value in zip(labels, values):
        writer.writerow(['# ' + label, value] + padding)
    writer.writerow([])
