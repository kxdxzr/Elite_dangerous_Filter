"""Shared provenance preamble for CSV exports (not result records)."""
from datetime import datetime
from i18n import translate
from app_metadata import PROJECT_AUTHOR, PROJECT_NAME, PROJECT_VERSION, PROJECT_URL


def write_csv_provenance(writer, column_count, language='zh', search_conditions=None, metadata_rows=None):
    """Write provenance, optional context and conditions, then a blank separator.

    Importers should skip this preamble before reading the result header.
    Timestamp is generated per export, with an explicit local UTC offset.
    """
    exported_at = datetime.now().astimezone().isoformat(timespec='seconds')
    labels = [translate(label, language) for label in
              ('源于 GitHub 项目作者', '项目名', '版本号', '导出时间', '项目链接')]
    values = (PROJECT_AUTHOR, PROJECT_NAME, PROJECT_VERSION, exported_at, PROJECT_URL)
    padding = [''] * max(0, column_count - 2)
    for label, value in zip(labels, values):
        writer.writerow(['# ' + label, value] + padding)
    for label, value in metadata_rows or ():
        writer.writerow(['# ' + label, value] + padding)
    if search_conditions is not None:
        label = translate('检索条件', language)
        writer.writerow(['# ' + label, search_conditions] + padding)
    writer.writerow([])
