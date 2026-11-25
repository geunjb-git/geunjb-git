"""외부 호출 없이 검수·실패 보존·같은 날 재실행을 확인하는 테스트."""
import copy
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import csv
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

    def facilities(self, parking='', stations=''):
        extra = '<PRK_STTS>'+parking+'</PRK_STTS><CHARGER_STTS>'+stations+'</CHARGER_STTS>'
        return self.parse(XML.replace('</CITYDATA>', extra+'</CITYDATA>'))

    def parking(self, flag='Y', count='20'):
        return f'''<PRK_STTS><PRK_CD>001</PRK_CD><PRK_NM>시험 주차장</PRK_NM>
        <CPCTY>100</CPCTY><CUR_PRK_YN>{flag}</CUR_PRK_YN><CUR_PRK_CNT>{count}</CUR_PRK_CNT>
        <CUR_PRK_TIME>2026-11-24 07:25</CUR_PRK_TIME></PRK_STTS>'''

    def station(self, identifier='S1', flag='Y', children=None):
        children = children if children is not None else self.charger()
        return f'''<CHARGER_STTS><STAT_ID>{identifier}</STAT_ID><STAT_NM>시험 충전소</STAT_NM>
        <STAT_LIMITYN>{flag}</STAT_LIMITYN><CHARGER_DETAILS>{children}</CHARGER_DETAILS></CHARGER_STTS>'''

    def charger(self):
        return '''<CHARGER_DETAILS><CHARGER_ID>01</CHARGER_ID><CHARGER_STAT>사용가능</CHARGER_STAT>
        <STATUPDDT>2026-11-20 06:00</STATUPDDT><OUTPUT>7</OUTPUT></CHARGER_DETAILS>'''

    def test_missing_parking_availability_does_not_mean_zero(self):
        row = self.facilities(self.parking('N', ''))['parking'][0]
        self.assertIsNone(row['available_spaces'])
        self.assertEqual(row['capacity'], 100)

    def test_available_parking_is_not_occupied_parking(self):
        row = self.facilities(self.parking())['parking'][0]
        self.assertEqual(row['available_spaces'], 20)
        self.assertEqual(row['parking_id'], '001')
        self.assertEqual(self.facilities(self.parking(count='0'))['parking'][0]['available_spaces'], 0)

    def test_bad_facility_is_quarantined_without_losing_region(self):
        for count in ['-1', '101']:
            row = self.facilities(self.parking(count=count))
            self.assertEqual(row['parking'], [])
            self.assertEqual(len(row['facility_issues']), 1)
            self.assertEqual(row['area_name'], '교대역')

    def test_ready_charger_is_not_necessarily_publicly_accessible(self):
        row = self.facilities(stations=self.station())
        self.assertEqual(row['chargers'][0]['status'], '사용가능')
        self.assertEqual(row['chargers'][0]['access_status'], 'restricted')
        unknown = self.facilities(stations=self.station(flag=''))
        self.assertEqual(unknown['charging_stations'][0]['access_status'], 'unknown')

    def test_charger_id_is_unique_within_station_and_keeps_leading_zero(self):
        row = self.facilities(stations=self.station()+self.station('S2'))
        self.assertEqual(len(row['chargers']), 2)
        self.assertEqual(row['chargers'][0]['charger_id'], '01')
        duplicate = self.facilities(stations=self.station(children=self.charger()*2))
        self.assertEqual(len(duplicate['chargers']), 1)
        self.assertEqual(duplicate['charging_stations'][0]['received_charger_count'], 2)
        self.assertEqual(duplicate['charging_stations'][0]['charger_count'], 1)
        self.assertEqual(len(duplicate['facility_issues']), 1)

    def test_old_charger_status_change_time_is_not_collection_time(self):
        row = self.facilities(stations=self.station())
        self.assertEqual(row['chargers'][0]['quality_notes'], [])

    def test_facility_exports_history_and_failure_preservation(self):
        with TemporaryDirectory() as folder:
            out = Path(folder)
            old = out/'daily'/'2026-11-23.json'
            old.parent.mkdir(parents=True)
            old.write_text('{}', encoding='utf-8')
            row = self.facilities(self.parking(), self.station()+self.station('S2'))
            save_run(out, [row], [], [AREA], NOW, 'manual')
            with (out/'chargers.csv').open(encoding='utf-8-sig', newline='') as stream:
                records = list(csv.DictReader(stream))
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]['charger_id'], '01')
            original = (out/'parking.csv').read_bytes()
            save_run(out, [], [{'area': '교대역', 'reason': '연결 실패'}], [AREA], NOW, 'manual')
            self.assertEqual((out/'parking.csv').read_bytes(), original)
            archive = json.loads((out/'archive.json').read_text(encoding='utf-8'))['days']
            self.assertIn('parking_csv', archive[0])
            self.assertNotIn('parking_csv', archive[1])


if __name__ == '__main__':
    unittest.main()
