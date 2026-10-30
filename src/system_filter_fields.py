"""Local-only system fields shared by the engine and main-window editor."""

STATION_COUNT_FIELDS = {
    'station_count': '站点总数（含航母）', 'carrier_count': '航母数量',
    'non_carrier_station_count': '非航母站点数量',
    'orbital_station_count': '轨道站数量（不含航母）',
    'planetary_station_count': '地表站数量',
}

COUNT_FIELDS = dict(STATION_COUNT_FIELDS, **{
    'minor_faction_count': '小派系总数（含无政府）',
    'federation_faction_count': '联邦小派系数量（含无政府）',
    'empire_faction_count': '帝国小派系数量（含无政府）',
    'alliance_faction_count': '联盟小派系数量（含无政府）',
    'potential_issuer_count': '潜在任务派系数量（非无政府）',
    'federation_issuer_count': '联邦潜在任务派系数量（非无政府）',
    'empire_issuer_count': '帝国潜在任务派系数量（非无政府）',
})
