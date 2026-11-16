-- BigQuery GoogleSQL · 가상 데이터 기반 점심 판매 준비 요청 분석
-- 원본 테이블 경로를 본인 환경에 맞춰 수정한 뒤 전체 실행합니다.
-- 공통 CTE를 한 번 계산해 임시 테이블에 보관하고 조회문 11개를 순서대로 실행합니다.
-- 결과 탭/작업 기록에서 각 조회 결과를 확인할 수 있습니다.
-- 시뮬레이션은 처리 시간을 고정하고 배정 대기만 줄인 계산입니다.

CREATE TEMP TABLE analysis_rows AS
WITH request_analysis AS (
  SELECT
    *,
    -- 한국시간 표시
    DATETIME(received_at, 'Asia/Seoul') AS received_at_kst,
    DATETIME(assigned_at, 'Asia/Seoul') AS assigned_at_kst,
    DATETIME(completed_at, 'Asia/Seoul') AS completed_at_kst,
    DATETIME(snapshot_at, 'Asia/Seoul') AS snapshot_at_kst,
    DATETIME(target_at, 'Asia/Seoul') AS target_at_kst,

    TIMESTAMP_DIFF(assigned_at, received_at, MINUTE) AS assign_wait_min,
    TIMESTAMP_DIFF(completed_at, assigned_at, MINUTE) AS processing_min,
    TIMESTAMP_DIFF(target_at, received_at, MINUTE) AS minutes_to_target,

    CASE WHEN status = 'unassigned'
      THEN TIMESTAMP_DIFF(snapshot_at, received_at, MINUTE)
    END AS unassigned_wait_so_far_min,
    CASE WHEN status = 'in_progress'
      THEN TIMESTAMP_DIFF(snapshot_at, assigned_at, MINUTE)
    END AS processing_so_far_min,

    CASE
      WHEN TIME(received_at, 'Asia/Seoul') >= TIME '10:00:00'
       AND TIME(received_at, 'Asia/Seoul') < TIME '10:30:00'
        THEN '10:00~10:29'
      WHEN TIME(received_at, 'Asia/Seoul') >= TIME '10:30:00'
       AND TIME(received_at, 'Asia/Seoul') < TIME '11:00:00'
        THEN '10:30~10:59'
      ELSE '분석 범위 외'
    END AS received_time_group,

    CASE
      WHEN completed_at IS NULL THEN '미완료'
      WHEN completed_at <= target_at THEN '목표 내 완료'
      ELSE '목표 초과 완료'
    END AS target_status,

    CASE
      WHEN completed_at IS NULL THEN '미완료'
      WHEN completed_at <= target_at THEN '목표 내 완료'
      WHEN assigned_at > target_at THEN '배정 전 목표 시각 초과'
      ELSE '배정 후 처리 중 목표 시각 초과'
    END AS deadline_stage
  FROM `bonggeunj.merchant_ops_demo.merchant_requests_prelunch`
)
SELECT * FROM request_analysis;

-- 01. 요청별 시간과 계산 결과
-- 기대 결과 · 100건 · 한국시간·분 단위 소요 시간 확인
SELECT *
FROM analysis_rows
ORDER BY received_at, request_id;

-- 02. 전체 목표 내 완료율
-- 기대 결과 · 100건 중 35건 · 35.0%
SELECT
  COUNT(*) AS total_requests,
  COUNTIF(target_status = '목표 내 완료') AS on_time_count,
  COUNTIF(target_status = '목표 초과 완료') AS overdue_count,
  ROUND(100.0 * COUNTIF(target_status = '목표 내 완료') / COUNT(*), 1)
    AS on_time_rate_pct
FROM analysis_rows;

-- 03. 접수 시간대별 완료율
-- 기대 결과 · 32/53건 · 60.4%, 3/47건 · 6.4%
SELECT
  received_time_group,
  COUNT(*) AS request_count,
  COUNTIF(target_status = '목표 내 완료') AS on_time_count,
  COUNTIF(target_status = '목표 초과 완료') AS overdue_count,
  ROUND(100.0 * COUNTIF(target_status = '목표 내 완료') / COUNT(*), 1)
    AS on_time_rate_pct
FROM analysis_rows
GROUP BY received_time_group
ORDER BY received_time_group;

-- 04. 유형·시간대별 평균과 중앙값
-- 기대 결과 · 유형 3종 × 시간대 2개 · 총 6행
SELECT DISTINCT
  request_type,
  received_time_group,
  COUNT(*) OVER request_group AS request_count,
  COUNTIF(target_status = '목표 내 완료') OVER request_group AS on_time_count,
  ROUND(100.0 * COUNTIF(target_status = '목표 내 완료') OVER request_group
    / COUNT(*) OVER request_group, 1) AS on_time_rate_pct,
  ROUND(AVG(assign_wait_min) OVER request_group, 1) AS avg_assign_wait_min,
  ROUND(AVG(processing_min) OVER request_group, 1) AS avg_processing_min,
  PERCENTILE_CONT(assign_wait_min, 0.5) OVER request_group AS median_assign_wait_min,
  PERCENTILE_CONT(processing_min, 0.5) OVER request_group AS median_processing_min
FROM analysis_rows
WINDOW request_group AS (PARTITION BY request_type, received_time_group)
ORDER BY request_type, received_time_group;

-- 05. 목표 초과 발생 단계
-- 기대 결과 · 이른 접수 3·18건 / 늦은 접수 34·10건
SELECT
  received_time_group,
  deadline_stage,
  COUNT(*) AS request_count,
  ROUND(100.0 * COUNT(*)
    / SUM(COUNT(*)) OVER (PARTITION BY received_time_group), 1)
    AS delayed_request_share_pct
FROM analysis_rows
WHERE target_status = '목표 초과 완료'
GROUP BY received_time_group, deadline_stage
ORDER BY received_time_group, request_count DESC;

-- 06. 일찍 접수했지만 늦어진 18건
-- 기대 결과 · 18건 중 16건은 배정 당시 10분 이하만 남음
SELECT
  request_id, request_type, received_at_kst, assigned_at_kst,
  minutes_to_target, assign_wait_min,
  TIMESTAMP_DIFF(target_at, assigned_at, MINUTE) AS minutes_left_after_assignment,
  processing_min,
  TIMESTAMP_DIFF(completed_at, target_at, MINUTE) AS deadline_overrun_min
FROM analysis_rows
WHERE received_time_group = '10:00~10:29'
  AND deadline_stage = '배정 후 처리 중 목표 시각 초과'
ORDER BY deadline_overrun_min DESC, request_id;

-- 07. 배정 대기 상한 시뮬레이션
-- 기대 결과 · 기존 35건 → 20분 상한 45건 → 10분 상한 59건 → 즉시 70건
SELECT
  COUNT(*) AS total_requests,
  COUNTIF(completed_at <= target_at) AS actual_on_time_count,
  COUNTIF(LEAST(assign_wait_min, 20) + processing_min <= minutes_to_target)
    AS on_time_if_wait_capped_at_20min,
  COUNTIF(LEAST(assign_wait_min, 10) + processing_min <= minutes_to_target)
    AS on_time_if_wait_capped_at_10min,
  COUNTIF(processing_min <= minutes_to_target)
    AS on_time_if_assigned_immediately
FROM analysis_rows;

-- 08. 즉시 배정해도 시간이 부족한 요청
-- 기대 결과 · 접수 당시부터 실제 처리 시간이 부족한 요청 30건
SELECT
  COUNT(*) AS total_requests,
  COUNTIF(processing_min > minutes_to_target)
    AS insufficient_time_even_without_wait
FROM analysis_rows;

-- 09. 배정을 기다릴 수 있었던 시간
-- 기대 결과 · 시간 부족 30 / 0~10분 12 / 11~20분 17 / 21분 이상 41건
SELECT
  CASE
    WHEN minutes_to_target - processing_min < 0 THEN '접수 당시부터 시간 부족'
    WHEN minutes_to_target - processing_min <= 10 THEN '배정 대기 여유 0~10분'
    WHEN minutes_to_target - processing_min <= 20 THEN '배정 대기 여유 11~20분'
    ELSE '배정 대기 여유 21분 이상'
  END AS wait_budget_group,
  COUNT(*) AS request_count
FROM analysis_rows
GROUP BY wait_budget_group
ORDER BY MIN(minutes_to_target - processing_min);

-- 10. 추가 완료되는 요청의 유형과 시간대
-- 기대 결과 · 추가 24건 중 19건은 10시 30분 이전 접수
SELECT
  request_type, received_time_group, COUNT(*) AS request_count,
  COUNTIF(completed_at <= target_at) AS actual_on_time_count,
  COUNTIF(LEAST(assign_wait_min, 10) + processing_min <= minutes_to_target)
    AS simulated_on_time_count,
  COUNTIF(LEAST(assign_wait_min, 10) + processing_min <= minutes_to_target)
    - COUNTIF(completed_at <= target_at) AS additional_on_time_count
FROM analysis_rows
GROUP BY request_type, received_time_group
ORDER BY additional_on_time_count DESC, request_type, received_time_group;

-- 11. 접수 시간대별 시뮬레이션 완료율
-- 기대 결과 · 10:30 이전 60.4→96.2% / 이후 6.4→17.0%
SELECT
  received_time_group, COUNT(*) AS request_count,
  COUNTIF(completed_at <= target_at) AS actual_on_time_count,
  ROUND(100.0 * COUNTIF(completed_at <= target_at) / COUNT(*), 1)
    AS actual_on_time_rate_pct,
  COUNTIF(LEAST(assign_wait_min, 10) + processing_min <= minutes_to_target)
    AS simulated_on_time_count,
  ROUND(100.0 * COUNTIF(LEAST(assign_wait_min, 10) + processing_min
    <= minutes_to_target) / COUNT(*), 1) AS simulated_on_time_rate_pct,
  COUNTIF(LEAST(assign_wait_min, 10) + processing_min <= minutes_to_target)
    - COUNTIF(completed_at <= target_at) AS additional_on_time_count
FROM analysis_rows
GROUP BY received_time_group
ORDER BY received_time_group;

