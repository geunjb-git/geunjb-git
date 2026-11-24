"""외부 호출 없이 검수·실패 보존·같은 날 재실행을 확인하는 테스트."""
import copy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from collector import DataError, KST, parse_record, save_run

NOW = datetime(2026, 11, 24, 7, 30, tzinfo=KST)
AREA = {"name": "교대역", "code": "POI018"}
XML = """<SeoulRtd.citydata><RESULT><RESULT.CODE>INFO-000</RESULT.CODE></RESULT>
<CITYDATA><AREA_NM>교대역</AREA_NM><AREA_CD>POI018</AREA_CD>
<LIVE_PPLTN_STTS><LIVE_PPLTN_STTS><AREA_CONGEST_LVL>여유</AREA_CONGEST_LVL>
<AREA_PPLTN_MIN>1,000</AREA_PPLTN_MIN><AREA_PPLTN_MAX>1500</AREA_PPLTN_MAX>
<PPLTN_TIME>2026-11-24 07:25</PPLTN_TIME></LIVE_PPLTN_STTS></LIVE_PPLTN_STTS>
<WEATHER_STTS><WEATHER_STTS><TEMP>-2.5</TEMP><HUMIDITY>40</HUMIDITY>
<WEATHER_TIME>2026-11-24 07:00</WEATHER_TIME><FCST24HOURS><FCST24HOURS><TEMP>99</TEMP>
</FCST24HOURS></FCST24HOURS></WEATHER_STTS></WEATHER_STTS></CITYDATA></SeoulRtd.citydata>"""

class CollectorTests(unittest.TestCase):
    def parse(self, xml=XML):
        return parse_record(xml.encode(), AREA, NOW, 120)

    def test_nested_current_weather_does_not_use_forecast(self):
        row = self.parse()
        self.assertEqual(row['temperature_c'], -2.5)
        self.assertEqual(row['population_min'], 1000)

    def test_missing_required_value_is_not_zero(self):
        with self.assertRaises(DataError):
            self.parse(XML.replace('1,000', ''))

    def test_reversed_range_is_rejected(self):
        with self.assertRaises(DataError):
            self.parse(XML.replace('1500', '500'))

    def test_area_mismatch_is_rejected(self):
        with self.assertRaises(DataError):
            self.parse(XML.replace('교대역', '다른역'))

    def test_api_error_is_rejected(self):
        with self.assertRaises(DataError):
            self.parse(XML.replace('INFO-000', 'ERROR-300'))

    def test_missing_optional_road_information_stays_missing(self):
        row = self.parse()
        self.assertIsNone(row['traffic_speed_kmh'])
        self.assertIn('도로 상황 정보 없음', row['quality_notes'])

    def test_stale_information_is_flagged(self):
        row = self.parse(XML.replace('07:25', '04:00'))
        self.assertIn('인구 정보가 2시간 이상 경과', row['quality_notes'])

    def test_failure_preserves_last_success(self):
        with TemporaryDirectory() as folder:
            out = Path(folder)
            save_run(out, [self.parse()], [], [AREA], NOW, 'manual')
            original = (out/'latest.json').read_bytes()
            save_run(out, [], [{'area': '교대역', 'reason': '연결 실패'}], [AREA], NOW, 'scheduled')
            self.assertEqual((out/'latest.json').read_bytes(), original)
            self.assertEqual(json.loads((out/'status.json').read_text(encoding='utf-8'))['status'], 'failed')

    def test_same_day_retry_does_not_duplicate_archive(self):
        with TemporaryDirectory() as folder:
            out = Path(folder)
            for _ in range(2):
                save_run(out, [self.parse()], [], [AREA], NOW, 'manual')
            self.assertEqual(len(list((out/'daily').glob('*.json'))), 1)
            self.assertEqual(len(json.loads((out/'archive.json').read_text(encoding='utf-8'))['days']), 1)

    def test_duplicate_area_is_rejected(self):
        with TemporaryDirectory() as folder:
            with self.assertRaises(DataError):
                save_run(Path(folder), [self.parse(), self.parse()], [], [AREA], NOW, 'manual')


if __name__ == '__main__':
    unittest.main()
