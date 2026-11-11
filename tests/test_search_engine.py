"""检索正确性回归：不依赖网络，覆盖集合 AND、分页及取消。"""
import copy
import json
import os
import threading
import random
import unittest
from unittest.mock import patch

import filter_engine as engine


def field(name, op, **values):
    return dict(type="field", field=name, op=op, **values)


class SearchTests(unittest.TestCase):
    def setUp(self):
        # 名称校验会调用get_options；禁止其后台联网刷新，避免解释器退出时
        # 守护线程仍在SSL请求中（Ubuntu/Python3.10可出现退出阶段崩溃）。
        import field_options as fo
        refresh = patch.object(fo, "_bg_refresh")
        refresh.start()
        self.addCleanup(refresh.stop)
        network = patch.object(fo, "_http_json", side_effect=OSError("offline unit test"))
        network.start()
        self.addCleanup(network.stop)

    def test_collection_conditions_are_and_not_intersection(self):
        conditions = [field("services", "in", values=["Market"]),
                      field("services", "in", values=["Shipyard"])]
        response = {"count": 2, "results": [
            {"id": 1, "services": [{"name": "Market"}]},
            {"id": 2, "services": [{"name": "Market"}, {"name": "Shipyard"}]}]}
        with patch.object(engine, "_http_json", return_value=response) as http:
            rows, _, _ = engine.search("stations", conditions)
        self.assertEqual([r["id"] for r in rows], [2])
        values = http.call_args.args[1]["filters"]["services"][0]["name"]["value"]
        self.assertEqual(values, ["Market", "Shipyard"])

    def test_contradictions_make_no_requests(self):
        cases = [
            [field("primary_economy", "in", values=["High Tech"]),
             field("primary_economy", "in", values=["Extraction"])],
            [field("has_market", "true"), field("has_market", "false")],
            [field("population", ">", text=10), field("population", "<=", text=10)],
            [dict(type="distance", ref_system="Sol", min_ly=20, max_ly=10)],
        ]
        with patch.object(engine, "_http_json") as http:
            for conditions in cases:
                self.assertEqual(engine.search("systems", conditions) if "population" in str(conditions)
                                 else engine.search("stations", conditions), ([], 0, 0))
            http.assert_not_called()

    def test_deduplicates_and_does_not_use_capped_count_as_end(self):
        batches = [
            {"count": 10000, "results": [{"id": i, "name": "no"} for i in range(100)]},
            {"count": 10000, "results": [{"id": 99, "name": "no"},
                                          {"id": 100, "name": "target"}]}]
        notes = []
        with patch.object(engine, "_http_json", side_effect=batches) as http:
            rows, total, scanned = engine.search("stations", [field("name", "contains", text="target")],
                                                 want=2, notes=notes, page_size=100)
        self.assertEqual((len(rows), total, scanned, http.call_count), (1, 10000, 101, 2))
        self.assertIn("候选分页已取完", notes)

    def test_page_limit_is_explicitly_incomplete(self):
        notes = []
        with patch.object(engine, "_http_json", return_value={"count": 10000,
                          "results": [{"id": i, "name": "no"} for i in range(100)]}):
            engine.search("stations", [field("name", "contains", text="target")],
                          max_pages=1, notes=notes, page_size=100)
        self.assertTrue(any("达到翻页上限" in n for n in notes))

    def test_stop_before_and_during_request(self):
        stop = threading.Event()
        stop.set()
        with patch.object(engine, "_http_json") as http:
            self.assertEqual(engine.search("stations", [], stop=stop), ([], 0, 0))
            http.assert_not_called()
        stop.clear()
        def response(*args):
            stop.set()
            return {"count": 1, "results": [{"id": 1}]}
        notes = []
        with patch.object(engine, "_http_json", side_effect=response) as http:
            rows, _, scanned = engine.search("stations", [], stop=stop, notes=notes)
        self.assertEqual((rows, scanned, http.call_count), ([], 0, 1))
        self.assertTrue(any("已手动停止" in n for n in notes))

    def test_resolution_does_not_modify_input(self):
        conditions = [dict(type="distance", ref_system="Typo", min_ly=0, max_ly=50)]
        original = copy.deepcopy(conditions)
        with patch.object(engine, "resolve_ref", return_value=("Sol", (0, 0, 0), True)), \
             patch.object(engine, "_http_json", return_value={"count": 1, "results": [
                 {"id": 1, "system_x": 1, "system_y": 0, "system_z": 0}]}):
            rows, _, _ = engine.search("stations", conditions)
        self.assertEqual(conditions, original)
        self.assertEqual(rows[0]["_distances"], {"Sol": 1.0})

    def test_missing_server_only_field_and_unknown_local_field(self):
        response = {"count": 1, "results": [{"id": 1}]}
        with patch.object(engine, "_http_json", return_value=response):
            rows, _, _ = engine.search("stations", [field("has_shipyard", "true")])
            self.assertEqual(len(rows), 1)
            notes = []
            rows, _, _ = engine.search("stations", [field("has_shipyard", "false")], notes=notes)
            self.assertEqual(rows, [])
            self.assertTrue(any("无法确认" in n for n in notes))

    def test_text_inequality_and_timestamp_timezone(self):
        self.assertFalse(engine.match_field("stations", {"name": "Sol"}, field("name", "!=", text="Sol")))
        self.assertTrue(engine.match_field("stations", {"updated_at": "2026-01-01T01:00:00+01:00"},
                        field("updated_at", "<=", text="2026-01-01T00:00:00Z")))

    def test_progress_reports_structured_info(self):
        seen = []
        with patch.object(engine, "_http_json", return_value={"count": 250, "results": [{"id": 1}]}):
            engine.search("stations", [], want=5, max_pages=3, page_size=100,
                          progress=lambda msg, info: seen.append((msg, info)))
        self.assertTrue(seen)
        self.assertIn("fetch", {info.get("phase") for _, info in seen})
        last = seen[-1][1]
        self.assertEqual((last["scanned"], last["hits"], last["total"], last["pages"]), (1, 1, 250, 3))

    def test_progress_single_arg_callback_still_works(self):
        seen = []
        with patch.object(engine, "_http_json", return_value={"count": 1, "results": [{"id": 1}]}):
            engine.search("stations", [], progress=lambda msg: seen.append(msg))
        self.assertTrue(seen)

    def test_invalid_number_and_malformed_response(self):
        with self.assertRaises(ValueError):
            engine.search("systems", [field("population", ">", text="nan")])
        with patch.object(engine, "_http_json", return_value={"error": "bad query"}):
            with self.assertRaises(ValueError):
                engine.search("systems", [])

    def test_case_insensitive_group_and_exclusion_contradiction(self):
        filters, _, _, impossible = engine.plan_server_filters("stations", [
            field("primary_economy", "in", values=["High Tech"]),
            field("primary_economy", "in", values=["high tech"])])
        self.assertIsNone(impossible)
        self.assertTrue(filters)
        with patch.object(engine, "_http_json") as http:
            self.assertEqual(engine.search("stations", [
                field("primary_economy", "in", values=["High Tech"]),
                field("primary_economy", "!=", text="high tech")]), ([], 0, 0))
            http.assert_not_called()

    def test_outside_distance_is_pushed_and_strictly_rechecked(self):
        conditions = [dict(type="distance", ref_system="Sol", min_ly=0, max_ly=50, mode="outside")]
        self.assertEqual(engine.build_server_payload("stations", conditions)["filters"]["distance"], {"min": 50.0})
        self.assertFalse(engine.match_distance("stations", {"system_x": 50, "system_y": 0, "system_z": 0},
                                              conditions[0], {"sol": (0, 0, 0)}))

    def test_disjoint_spheres_do_not_search(self):
        conditions = [dict(type="distance", ref_system=name, max_ly=10)
                      for name in ("A", "B")]
        with patch.object(engine, "resolve_ref", side_effect=[("A", (0, 0, 0), False),
                                                             ("B", (100, 0, 0), False)]), \
             patch.object(engine, "_http_json") as http:
            self.assertEqual(engine.search("stations", conditions), ([], 0, 0))
            http.assert_not_called()

    def test_numeric_equality_is_numeric(self):
        self.assertTrue(engine.match_field("systems", {"population": 100.0}, field("population", "=", text="100")))

    def test_bundled_ship_module_lists(self):
        import field_options as fo
        ships, mods = fo.BUNDLED_OPTIONS["stations/ships"], fo.BUNDLED_OPTIONS["stations/modules"]
        self.assertEqual((len(ships), len(mods)), (48, 153))
        for lst in (ships, mods):
            self.assertEqual(len(lst), len({x.casefold() for x in lst}))
        self.assertIn("Anaconda", ships)
        self.assertIn("Fuel Scoop", mods)

    def test_options_offline_and_additive(self):
        import field_options as fo
        mem, refreshed = dict(fo._mem), set(fo._refreshed)
        fo._mem.clear()
        fo._refreshed.update(("stations/ships", "stations/modules"))
        try:
            # This checks the bundled offline baseline, not optional records
            # learned by other tests or a user's existing additive cache.
            with patch.object(fo, "_http_json", side_effect=OSError("offline")), \
                    patch.object(fo, '_load_disk', return_value={}), patch.object(fo, '_save_disk'):
                self.assertEqual(len(fo.get_options("stations", "modules")), 153)
                self.assertEqual(len(fo.get_options("stations", "ships")), 48)
            fo._mem.pop('stations/ships', None)
            with patch.object(fo, '_load_disk', return_value={'stations/ships': ['Cached Test Ship']}), \
                    patch.object(fo, '_save_disk'):
                ships = fo.get_options('stations', 'ships')
                self.assertEqual(len(ships), 49)
                self.assertIn('Cached Test Ship', ships)
            merged = fo._merge_lists(["A", "b"], ["B", "c"], ["a"])
            self.assertEqual(merged, ["A", "b", "c"])
        finally:
            fo._mem.clear()
            fo._mem.update(mem)
            fo._refreshed.clear()
            fo._refreshed.update(refreshed)

    def test_resolve_option(self):
        canon, fixed = engine.resolve_option("stations", "ships", "anaconda")
        self.assertEqual((canon, fixed), ("Anaconda", False))
        canon, fixed = engine.resolve_option("stations", "modules", "Fule Scoop")
        self.assertEqual((canon, fixed), ("Fuel Scoop", True))
        with self.assertRaises(ValueError) as ctx:
            engine.resolve_option("stations", "modules", "不存在的东西zzzzz")
        self.assertIn("你是不是想找", str(ctx.exception))

    def test_search_corrects_option_values(self):
        conds = [field("ships", "in", values=["Ananconda", "python"])]
        corr = []
        fake = {"count": 1, "results": [{"id": 1, "ships": [{"name": "Anaconda"}, {"name": "Python"}]}]}
        with patch.object(engine, "_http_json", return_value=fake):
            rows, _, _ = engine.search("stations", conds, corrections=corr)
        # 调用者条件不被修改, 纠正走 corrections (GUI 回写行内); 命中证明纠正值已用于查询
        self.assertEqual(conds[0]["values"], ["Ananconda", "python"])
        self.assertEqual(corr, [("Ananconda", "Anaconda"), ("python", "Python")])
        self.assertEqual(len(rows), 1)

    def test_fresh_days_normalize(self):
        cs = engine.normalize_conditions("stations", [
            field("ships", "in", values=["Anaconda"], **{"fresh_days": "7"})])
        self.assertEqual(cs[0]["fresh_days"], 7)
        for bad in (0, -3, True, "x"):
            with self.assertRaises(ValueError):
                engine.normalize_conditions("stations", [
                    field("ships", "in", values=["Anaconda"], **{"fresh_days": bad})])

    def test_fresh_ok_and_match(self):
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        iso = lambda d: (now - d).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertTrue(engine.fresh_ok({"t": iso(timedelta(hours=1))}, "t", 7))
        self.assertFalse(engine.fresh_ok({"t": iso(timedelta(days=8))}, "t", 7))
        self.assertFalse(engine.fresh_ok({}, "t", 7))
        self.assertFalse(engine.fresh_ok({"t": "bad"}, "t", 7))
        self.assertFalse(engine.fresh_ok({"t": iso(timedelta(days=-1))}, "t", 7))
        fresh_row = {"ships": [{"name": "Anaconda"}],
                     "shipyard_updated_at": iso(timedelta(hours=2))}
        stale_row = {"ships": [{"name": "Anaconda"}],
                     "shipyard_updated_at": iso(timedelta(days=30))}
        no_ts_row = {"ships": [{"name": "Anaconda"}]}
        cond = dict(type="field", field="ships", op="in", values=["Anaconda"], fresh_days=7)
        self.assertTrue(engine.match_field("stations", fresh_row, cond))
        self.assertFalse(engine.match_field("stations", stale_row, cond))
        self.assertFalse(engine.match_field("stations", no_ts_row, cond))
        self.assertIn("[数据7天内]", engine.cond_desc(cond))

    def test_fresh_blocks_trust_and_notes(self):
        from datetime import datetime, timedelta, timezone
        iso = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
        cond = dict(type="field", field="ships", op="in", values=["Anaconda"], fresh_days=7)
        notes = []
        f, pushed, pnotes, imp = engine.plan_server_filters("stations", [dict(cond)])
        notes.extend(pnotes)
        self.assertTrue(any("船厂新鲜度" in n for n in notes))
        # 服务端命中但无船厂明细+时间过期: 不能信任, 必须过滤
        with patch.object(engine, "_http_json",
                          return_value={"count": 1, "results": [{"id": 1, "shipyard_updated_at": iso}]}):
            rows, _, _ = engine.search("stations", [dict(cond)], notes=notes)
        self.assertEqual(rows, [])
        self.assertTrue(any("ships" in n or "船厂" in n for n in notes))

    def test_gui_fresh_opt_days(self):
        import filter_gui as g
        self.assertEqual((g.fresh_opt_days("近7天"), g.fresh_opt_days("不限"),
                          g.fresh_opt_days("近15天"), g.fresh_opt_days("x")),
                         (7, None, 15, None))

    def test_data_age(self):
        import filter_gui as g
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        iso = lambda d: (now - d).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(g.data_age(None), "未知")
        self.assertEqual(g.data_age("not-a-date"), "未知")
        self.assertEqual(g.data_age(iso(timedelta(seconds=30))), "刚刚")
        self.assertEqual(g.data_age(iso(timedelta(hours=5))), "5小时前")
        self.assertEqual(g.data_age(iso(timedelta(days=3))), "3天前")
        self.assertEqual(g.data_age((now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")), "未知")

    def test_module_spec_normalize(self):
        cs = engine.normalize_conditions("stations", [
            field("modules", "in", values=["Fuel Scoop"], **{"class": ["5级", "3"], "rating": ["b"]})])
        self.assertEqual((cs[0]["class"], cs[0]["rating"]), ([5, 3], ["B"]))
        cs = engine.normalize_conditions("stations", [field("modules", "in", values=["Fuel Scoop"])])
        self.assertNotIn("class", cs[0])
        with self.assertRaises(ValueError):
            engine.normalize_conditions("stations", [
                field("modules", "in", values=["Fuel Scoop"], **{"class": ["9"]})])
        with self.assertRaises(ValueError):
            engine.normalize_conditions("stations", [
                field("modules", "in", values=["Fuel Scoop"], **{"rating": ["Z"]})])

    def test_module_entries_pushed_per_row(self):
        cs = engine.normalize_conditions("stations", [
            field("modules", "in", values=["Fuel Scoop"], **{"class": [5], "rating": ["B"]}),
            field("modules", "in", values=["Shield Generator"])])
        f, pushed, notes, imp = engine.plan_server_filters("stations", cs)
        self.assertIsNone(imp)
        self.assertEqual(f["modules"], [
            {"name": {"value": ["Fuel Scoop"]}, "class": {"value": [5]}, "rating": {"value": ["B"]}},
            {"name": {"value": ["Shield Generator"]}}])
        self.assertEqual(pushed, 2)

    def test_module_contains_pushes_spec_only(self):
        cs = engine.normalize_conditions("stations", [
            dict(type="field", field="modules", op="contains", text="Scoop", **{"class": [5]})])
        f, _, notes, imp = engine.plan_server_filters("stations", cs)
        self.assertIsNone(imp)
        self.assertEqual(f["modules"], [{"class": {"value": [5]}}])
        self.assertTrue(any("本地" in n for n in notes))

    def test_bundled_module_specs(self):
        import field_options as fo
        self.assertEqual(len(fo.BUNDLED_MODULE_SPECS), 153)
        self.assertEqual(fo.BUNDLED_MODULE_SPECS["Fuel Scoop"],
                         {"class": [1, 2, 3, 4, 5, 6, 7, 8],
                          "rating": ["A", "B", "C", "D", "E"]})
        self.assertEqual(fo.BUNDLED_MODULE_SPECS["Heat Sink Launcher"],
                         {"class": [0], "rating": ["I"]})
        self.assertEqual(fo.BUNDLED_MODULE_SPECS["Lightweight Alloy"],
                         {"class": [1], "rating": ["C", "I"]})
        # 内置即默认子集: 无磁盘无学习也命中
        saved_specs, saved_dirty = fo._specs, fo._specs_dirty
        fo._specs, fo._specs_dirty = None, False
        try:
            self.assertEqual(fo.get_module_specs("Heat Sink Launcher"), ([0], ["I"]))
            self.assertEqual(fo.get_module_classes("Electronic Countermeasure"), ["0"])
            self.assertEqual(fo.get_module_ratings("Planetary Vehicle Hangar"), ["G", "H"])
            self.assertEqual(fo.get_module_specs("不存在的模块XYZ"), (None, None))
            self.assertEqual(fo.get_module_classes("不存在的模块XYZ"),
                             [str(i) for i in range(9)])
        finally:
            fo._specs, fo._specs_dirty = saved_specs, saved_dirty

    def test_module_spec_options_and_learning(self):
        import field_options as fo
        saved_specs, saved_dirty = fo._specs, fo._specs_dirty
        fo._specs, fo._specs_dirty = None, False
        try:
            self.assertEqual(fo.get_module_classes(), [str(i) for i in range(9)])
            self.assertEqual(fo.get_module_ratings(),
                             ["A", "B", "C", "D", "E", "F", "G", "H", "I"])
            # 用假模块名隔离内置数据, 验证合并/排序/清洗
            self.assertEqual(fo.get_module_specs("测试模块ZZZ"), (None, None))
            added = fo.learn_module_specs([
                {"name": "测试模块ZZZ", "class": 5, "rating": "B"},
                {"name": "测试模块ZZZ", "class": 3, "rating": "A"},
                {"name": "测试模块ZZZ", "class": 5, "rating": "B"},
                {"name": "测试模块ZZZ", "class": "bad", "rating": ""},
                {"name": "", "class": 2}, {"nope": 1}, None])
            self.assertEqual(added, 6)  # Four marginals plus two actual pairs.
            self.assertEqual(fo.get_module_specs("测试模块zzz"), ([3, 5], ["A", "B"]))
            self.assertEqual(fo.get_module_classes("测试模块ZZZ"), ["3", "5"])
            self.assertEqual(fo.get_module_ratings("测试模块ZZZ"), ["A", "B"])
            # 磁盘条目: 新名字直接采用; 已有内置的名字只增不减
            # 注意: 为避免污染用户真实学习库, 先备份再恢复
            had_disk, disk_bak = os.path.exists(fo.SPECS_FILE), None
            if had_disk:
                with open(fo.SPECS_FILE, encoding="utf-8") as f:
                    disk_bak = f.read()
            fo._specs, fo._specs_dirty = None, False
            disk = {"测试模块ZZZ": {"name": "测试模块ZZZ", "class": [7], "rating": ["C"]},
                    "Fuel Scoop": {"name": "Fuel Scoop", "class": [8], "rating": ["E", "Z"]}}
            with open(fo.SPECS_FILE, "w", encoding="utf-8") as f:
                json.dump(disk, f)
            try:
                self.assertEqual(fo.get_module_specs("测试模块ZZZ"), ([7], ["C"]))
                cls, rats = fo.get_module_specs("Fuel Scoop")
                self.assertEqual(cls, [1, 2, 3, 4, 5, 6, 7, 8])
                self.assertEqual(rats, ["A", "B", "C", "D", "E", "Z"])
            finally:
                try:
                    if had_disk:
                        with open(fo.SPECS_FILE, "w", encoding="utf-8") as f:
                            f.write(disk_bak)
                    else:
                        os.remove(fo.SPECS_FILE)
                except OSError:
                    pass
        finally:
            fo._specs, fo._specs_dirty = saved_specs, saved_dirty

    def test_module_spec_persist_roundtrip(self):
        import field_options as fo
        import tempfile
        saved_specs, saved_dirty, saved_file = fo._specs, fo._specs_dirty, fo.SPECS_FILE
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tmp.close()
        try:
            fo._specs, fo._specs_dirty, fo.SPECS_FILE = None, False, tmp.name
            fo.learn_module_specs([{"name": "测试模块ZZZ", "class": 5, "rating": "B"}])
            self.assertTrue(fo.save_module_specs())
            self.assertFalse(fo.save_module_specs())  # 无新增不再写盘
            fo._specs, fo._specs_dirty = None, False
            self.assertEqual(fo.get_module_specs("测试模块ZZZ"), ([5], ["B"]))
        finally:
            fo._specs, fo._specs_dirty, fo.SPECS_FILE = saved_specs, saved_dirty, saved_file
            try:
                os.remove(tmp.name)
            except OSError:
                pass

    def test_module_item_level_match(self):
        row = {"modules": [{"name": "Fuel Scoop", "class": 3, "rating": "A"},
                           {"name": "Fuel Scoop", "class": 5, "rating": "B"}]}
        ok = dict(type="field", field="modules", op="in", values=["Fuel Scoop"], **{"class": [5]})
        bad_cls = dict(type="field", field="modules", op="in", values=["Fuel Scoop"], **{"class": [6]})
        bad_rat = dict(type="field", field="modules", op="in", values=["Fuel Scoop"], **{"rating": ["C"]})
        bad_name = dict(type="field", field="modules", op="in", values=["Shield Generator"], **{"class": [5]})
        eq = dict(type="field", field="modules", op="=", text="Fuel Scoop", **{"class": [5], "rating": ["B"]})
        contains = dict(type="field", field="modules", op="contains", text="scoop", **{"class": [5]})
        plain = field("modules", "in", values=["Fuel Scoop"])
        self.assertTrue(engine.match_field("stations", row, ok))
        self.assertFalse(engine.match_field("stations", row, bad_cls))
        self.assertFalse(engine.match_field("stations", row, bad_rat))
        self.assertFalse(engine.match_field("stations", row, bad_name))
        self.assertTrue(engine.match_field("stations", row, eq))
        self.assertTrue(engine.match_field("stations", row, contains))
        self.assertTrue(engine.match_field("stations", row, plain))
        self.assertIn("[5级]", engine.cond_desc(ok))
        self.assertIn("[5级/B级]", engine.cond_desc(eq))

    def test_freshness_markers(self):
        from datetime import datetime, timezone
        s = engine.resolve_freshness("近7天")
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400
        self.assertTrue(6.9 < days < 7.1)
        self.assertEqual(engine.resolve_freshness("2026-01-01"), "2026-01-01")
        conds = engine.normalize_conditions("stations", [
            field("shipyard_last_updated_at", "between", min="近30天", max="")])
        self.assertTrue(conds[0]["min"].startswith("202"))
        self.assertEqual(conds[0]["max"], "")

    def test_intersection_boxes_containment_tangent_and_disjoint(self):
        self.assertEqual(engine.sphere_intersection_box((0, 0, 0), 10, (1, 0, 0), 2),
                         [(-1, 3), (-2, 2), (-2, 2)])
        box = engine.sphere_intersection_box((0, 0, 0), 5, (10, 0, 0), 5)
        self.assertEqual(box, [(5, 5), (0, 0), (0, 0)])
        with self.assertRaises(engine.Contradiction):
            engine.sphere_intersection_box((0, 0, 0), 5, (11, 0, 0), 5)

    def test_geometry_does_not_discard_valid_points(self):
        rng = random.Random(314)
        for a, ra, b, rb in [((0, 0, 0), 50, (55.71875, 17.59375, 27.15625), 50),
                             ((-3, 7, 2), 20, (14, -5, 8), 30),
                             ((0, 0, 0), 50, (20, 0, 0), 10)]:
            conditions = [dict(type="distance", ref_system="A", max_ly=ra),
                          dict(type="distance", ref_system="B", max_ly=rb)]
            payload = engine.tighten_distance_payload("systems",
                engine.build_server_payload("systems", conditions), conditions,
                {"a": a, "b": b}, [])
            verified = 0
            for _ in range(3000):
                point = tuple(a[k] + rng.uniform(-ra, ra) for k in range(3))
                if engine.dist3(point, a) > ra or engine.dist3(point, b) > rb:
                    continue
                verified += 1
                for axis, value in zip(("x", "y", "z"), point):
                    lo, hi = payload["filters"][axis]["value"]
                    self.assertLessEqual(lo, value)
                    self.assertLessEqual(value, hi)
                if "reference_coords" in payload:
                    center = tuple(payload["reference_coords"][k] for k in ("x", "y", "z"))
                    self.assertLessEqual(engine.dist3(point, center), payload["filters"]["distance"]["max"])
            self.assertGreater(verified, 0)

    def test_geometry_preserves_explicit_coordinate_bounds(self):
        conditions = [dict(type="distance", ref_system="A", max_ly=50),
                      dict(type="distance", ref_system="B", max_ly=50),
                      field("x", "between", min=20, max=30)]
        payload = engine.tighten_distance_payload("systems",
            engine.build_server_payload("systems", conditions), conditions,
            {"a": (0, 0, 0), "b": (60, 0, 0)}, [])
        self.assertEqual(payload["filters"]["x"]["value"], [20, 30])


if __name__ == "__main__":
    unittest.main()
