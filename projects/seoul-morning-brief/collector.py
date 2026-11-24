"""서울시 실시간 도시데이터 수집 → 검수 → 공개 JSON/CSV 저장.

인증키는 SEOUL_API_KEY 환경변수로만 받으며 URL이나 인증키를 출력하지 않습니다.
외부 패키지 없이 Python 3.11 이상에서 실행할 수 있습니다.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import quote
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
import xml.etree.ElementTree as ET

KST = timezone(timedelta(hours=9))
SOURCE = "https://data.seoul.go.kr/dataList/OA-21285/A/1/datasetView.do"
FIELDS = ["area_name", "area_code", "collected_at", "population_time", "congestion",
          "population_min", "population_max", "traffic_time", "traffic_status",
          "traffic_speed_kmh", "weather_time", "temperature_c", "humidity_pct",
          "precipitation_type", "precipitation_message", "pm25", "pm25_status",
          "quality_notes"]


class DataError(Exception):
    """공개 로그에 인증 정보를 포함하지 않는 검수 오류."""


def text(node: ET.Element | None, tag: str) -> str | None:
    if node is None:
        return None
    found = node.find(".//" + tag)
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def number(value: str | None, label: str, required: bool = False) -> int | float | None:
    if value in (None, "", "-", "정보없음"):
        if required:
            raise DataError(f"{label}: 필수값 누락")
        return None
    try:
        value = float(value.replace(",", ""))
    except (ValueError, TypeError):
        raise DataError(f"{label}: 숫자 형식 오류") from None
    if not (-1e9 < value < 1e9):
        raise DataError(f"{label}: 유효하지 않은 숫자")
    return int(value) if value.is_integer() else value


def observation_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.replace(tzinfo=KST) if result.tzinfo is None else result.astimezone(KST)
    except ValueError:
        return None


def parse_record(raw: bytes, area: dict, now: datetime, stale_minutes: int) -> dict:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise DataError("응답을 XML로 해석할 수 없음") from None
    code = text(root, "RESULT.CODE")
    if code != "INFO-000":
        raise DataError("API 응답 코드 오류: " + (code or "코드 없음"))
    city = root.find("CITYDATA")
    if city is None:
        raise DataError("CITYDATA 항목 없음")
    if text(city, "AREA_NM") != area["name"] or text(city, "AREA_CD") != area["code"]:
        raise DataError("요청한 지역과 응답 지역이 다름")
    ppl = city.find("LIVE_PPLTN_STTS")
    road = city.find("ROAD_TRAFFIC_STTS")
    weather = city.find("WEATHER_STTS")
    row = {
        "area_name": area["name"], "area_code": area["code"],
        "collected_at": now.isoformat(timespec="seconds"),
        "population_time": text(ppl, "PPLTN_TIME"),
        "congestion": text(ppl, "AREA_CONGEST_LVL"),
        "congestion_message": text(ppl, "AREA_CONGEST_MSG"),
        "population_min": number(text(ppl, "AREA_PPLTN_MIN"), "최소 추정 인구", True),
        "population_max": number(text(ppl, "AREA_PPLTN_MAX"), "최대 추정 인구", True),
        "traffic_time": text(road, "ROAD_TRAFFIC_TIME"),
        "traffic_status": text(road, "ROAD_TRAFFIC_IDX"),
        "traffic_speed_kmh": number(text(road, "ROAD_TRAFFIC_SPD"), "도로 평균 속도"),
        "traffic_message": text(road, "ROAD_MSG"),
        "weather_time": text(weather, "WEATHER_TIME"),
        "temperature_c": number(text(weather, "TEMP"), "기온"),
        "humidity_pct": number(text(weather, "HUMIDITY"), "습도"),
        "precipitation_type": text(weather, "PRECPT_TYPE"),
        "precipitation_message": text(weather, "PCP_MSG"),
        "pm25": number(text(weather, "PM25"), "초미세먼지"),
        "pm25_status": text(weather, "PM25_INDEX"),
        "quality_notes": [],
    }
    if row["population_min"] < 0 or row["population_max"] < row["population_min"]:
        raise DataError("추정 인구의 최소·최대 범위 오류")
    if row["population_min"] % 1 or row["population_max"] % 1:
        raise DataError("추정 인구가 정수가 아님")
    for field, label in [("population_time", "인구"), ("traffic_time", "도로"), ("weather_time", "날씨")]:
        observed = observation_time(row[field])
        if observed is None:
            row["quality_notes"].append(label + " 기준 시각 누락·형식 확인 필요")
        elif (now - observed).total_seconds() > stale_minutes * 60:
            row["quality_notes"].append(label + " 정보가 2시간 이상 경과")
        elif (observed - now).total_seconds() > 10 * 60:
            row["quality_notes"].append(label + " 기준 시각이 수집 시각보다 미래임")
    for field, label in [("congestion", "혼잡도"), ("traffic_status", "도로 상황"), ("temperature_c", "기온")]:
        if row[field] is None:
            row["quality_notes"].append(label + " 정보 없음")
    if row["humidity_pct"] is not None and not 0 <= row["humidity_pct"] <= 100:
        raise DataError("습도가 0~100 범위를 벗어남")
    for field in ["traffic_speed_kmh", "pm25"]:
        if row[field] is not None and row[field] < 0:
            raise DataError(field + ": 음수 확인 필요")
    return row


def fetch(area: dict, key: str) -> bytes:
    # 서울시가 문서화한 API 주소. 인증키가 포함된 URL은 로그에 출력하지 않음.
    url = "http://openapi.seoul.go.kr:8088/" + quote(key, safe="") + "/xml/citydata/1/5/" + quote(area["code"])
    for attempt in range(3):
        try:
            with urlopen(url, timeout=25) as response:
                data = response.read(8_000_001)
                if len(data) > 8_000_000:
                    raise DataError("응답이 허용 크기를 초과함")
                return data
        except (HTTPError, URLError, TimeoutError, OSError):
            if attempt == 2:
                raise DataError("API 연결 실패: 재시도 3회 후 중단") from None
            time.sleep(2 ** attempt)
    raise DataError("API 연결 실패")


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def write_csv(path: Path, rows: list[dict]) -> None:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "; ".join(v) if isinstance(v, list) else v for k, v in row.items() if k in FIELDS})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stream.getvalue(), encoding="utf-8-sig", newline="")


def save_run(out: Path, rows: list[dict], errors: list[dict], areas: list[dict], now: datetime, mode: str) -> dict:
    if len({r["area_code"] for r in rows}) != len(rows):
        raise DataError("같은 실행에서 지역 코드가 중복됨")
    status = "success" if len(rows) == len(areas) and not errors else ("partial" if rows else "failed")
    report = {"schema_version": 1, "collected_at": now.isoformat(timespec="seconds"),
              "timezone": "Asia/Seoul", "run_mode": mode, "scheduled_time": "07:30",
              "status": status, "expected_areas": areas, "records": rows, "errors": errors,
              "source": SOURCE, "source_name": "서울특별시 서울 열린데이터광장",
              "notes": ["지역 인구 혼잡도는 지하철 객차 혼잡도나 실제 소요시간이 아닙니다.",
                        "인구·도로·날씨의 기준 시각은 서로 다르며 수집 시각과 구분합니다."]}
    # 전부 실패한 경우 마지막 성공 데이터는 유지하고 실패 상태만 새로 공개.
    if rows:
        write_json(out / "latest.json", report)
        write_csv(out / "latest.csv", rows)
        day = now.strftime("%Y-%m-%d")
        # 같은 날 재실행은 일자별 마지막 성공 스냅샷을 대체하여 중복 누적 방지.
        write_json(out / "daily" / (day + ".json"), report)
        write_csv(out / "daily" / (day + ".csv"), rows)
    write_json(out / "status.json", {k: v for k, v in report.items() if k != "records"})
    index = [{"date": p.stem, "json": "daily/" + p.name, "csv": "daily/" + p.stem + ".csv"}
             for p in sorted((out / "daily").glob("*.json"), reverse=True)] if (out / "daily").exists() else []
    write_json(out / "archive.json", {"days": index})
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(__file__).with_name("config.json"))
    parser.add_argument("--output", type=Path, default=Path("docs/projects/seoul-morning-brief/data"))
    parser.add_argument("--mode", choices=["manual", "scheduled"], default="manual")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    now = datetime.now(KST)
    rows, errors = [], []
    key = os.environ.get("SEOUL_API_KEY", "").strip()
    for area in config["areas"]:
        if not key:
            errors.append({"area": area["name"], "reason": "SEOUL_API_KEY가 설정되지 않음"})
            continue
        try:
            rows.append(parse_record(fetch(area, key), area, now, config.get("stale_after_minutes", 120)))
        except DataError as error:
            errors.append({"area": area["name"], "reason": str(error)})
        except Exception:
            # 예기치 않은 예외에도 인증키·요청 URL·응답 전문은 공개 로그에 남기지 않음.
            errors.append({"area": area["name"], "reason": "예상하지 못한 처리 오류: 검토 필요"})
    report = save_run(args.output, rows, errors, config["areas"], now, args.mode)
    summary = f"{report['status']}: {len(rows)}/{len(config['areas'])}개 지역 수집 · {report['collected_at']}"
    print(summary)
    for error in errors:
        print(error["area"] + ": " + error["reason"])
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as f:
            f.write("## 서초 아침 도시정보\n\n" + summary + "\n\n")
            f.write("[웹에서 확인](https://geunjb-git.github.io/geunjb-git/projects/seoul-morning-brief/)\n\n")
            for row in rows:
                f.write(f"- {row['area_name']}: {row['congestion']} / 도로 {row['traffic_status']} / 기온 {row['temperature_c']}℃\n")
            for error in errors:
                f.write("- 확인 필요: " + error["area"] + " " + error["reason"] + "\n")
    return 0 if report["status"] == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
