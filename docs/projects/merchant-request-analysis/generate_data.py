"""점심 판매 준비 요청 100건을 재현하는 가상 데이터 생성기.

한국시간 2026-11-02~06, 하루 20건, 10:00~10:59 접수.
배정 대기 1~40분, 처리 5~30분을 각각 정수 균등분포에서 추출한다.
두 분포는 접수 시각과 요청 유형에 공통으로 적용한다.
11시 완료 목표와 11월 6일 18시 관찰 기준은 별도의 시각이다.
이 생성기는 인력 수·동시 처리·요청 간 대기열을 모델링하지 않는다.
"""

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


SEED = 20261111
KST = timezone(timedelta(hours=9))
FIRST_DAY = datetime(2026, 11, 2, 10, tzinfo=KST)
SNAPSHOT_AT = datetime(2026, 11, 6, 18, tzinfo=KST)
REQUEST_TYPES = ("menu_update", "image_update", "store_info_update")
FIELDNAMES = (
    "request_id", "store_id", "request_type", "received_at", "assigned_at",
    "completed_at", "status", "snapshot_at", "target_at",
)


def generate_requests():
    rng = random.Random(SEED)
    requests = []
    for day_index in range(5):
        day_start = FIRST_DAY + timedelta(days=day_index)
        target_at = day_start.replace(hour=11)
        for _ in range(20):
            received_at = day_start + timedelta(minutes=rng.randrange(60))
            request_type = rng.choice(REQUEST_TYPES)
            wait_minutes = rng.randint(1, 40)
            processing_minutes = rng.randint(5, 30)
            assigned_at = received_at + timedelta(minutes=wait_minutes)
            completed_at = assigned_at + timedelta(minutes=processing_minutes)
            requests.append({
                "request_id": "",
                "store_id": f"STORE-{rng.randint(1, 32):03d}",
                "request_type": request_type,
                "received_at": received_at.isoformat(sep=" "),
                "assigned_at": assigned_at.isoformat(sep=" "),
                "completed_at": completed_at.isoformat(sep=" "),
                "status": "completed",
                "snapshot_at": SNAPSHOT_AT.isoformat(sep=" "),
                "target_at": target_at.isoformat(sep=" "),
            })
    requests.sort(key=lambda row: row["received_at"])
    for number, row in enumerate(requests, start=1):
        row["request_id"] = f"REQ-{number:04d}"
    return requests


if __name__ == "__main__":
    output_path = Path(__file__).with_name("sample_merchant_requests_prelunch.csv")
    with output_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(generate_requests())
    print(f"Created {output_path.name}: 100 fictional requests")
