"""Canonical Chinese templates for messages requiring context or runtime values."""
CATALOG = {}
FRAGMENTS = {}
MESSAGES = {
    'csv.field': '{label}',
    'csv.distance': '距 {reference}（ly）',
    'csv.planets': '匹配星球（{index}）',
    'csv.rings': '匹配星环（{index}）',
    'csv.indexed': '{title}（{index}）',
    'progress.unknown': '{stage}：{done:,}；总量未知',
    'details.summary': '星球组 {bodies} ({body_mode})；星环组 {rings} ({ring_mode})；最近距离 ly：{minimum} ~ {maximum}；人口 > {population}',
    'colonisation.summary': '扫描 {scanned:,}；匹配 {matches:,}；数据未知 {unknown:,}。{reason}',
    'colonisation.page': '分页 {page:,}；已扫描 {scanned:,}；匹配 {matches:,}',
    'colonisation.batch': '天体批次 {done}/{total}；匹配 {matches}',
    'shopping.summary': '已扫描：{scanned}；命中：{matches}。{notes}',
    'shopping.separator': '；',
}
