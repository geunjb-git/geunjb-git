"""할인 유입 코호트의 12월 갱신과 첫 결제 후 30일 행동을 집계한다.

제공된 고객 마스터의 renewed와 이번 분석의 renewed_dec는 다른 정의다.
사용자별 원본 레코드는 공개 출력하지 않는다.
"""
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

INPUTS = {
    'master': '15920_1개월플랜_분석/plan15920_user_level_data.csv',
    'renew': 'renew_subscription_df.csv',
    'start': 'start_content_df.csv',
    'end': 'end_content_df.csv',
}
COLS = {
    'master': ['user_id', 'first_payment_date', 'first_plan_price', 'has_discount',
               'renewed', 'active_days_30', 'days_since_last_activity_day30',
               'first_activity_date_30', 'last_activity_date_30', 'day30_reference_date'],
    'renew': ['user_id', 'client_event_time', 'plan.price'],
    'start': ['user_id', 'client_event_time', 'content.id', 'content.difficulty'],
    'end': ['user_id', 'client_event_time', 'content.id'],
}
GROUPS = ['12월 갱신 기록 없음', '월간권 기록만', '연간권 기록 있음']


def load_tables(data_dir=None):
    root = Path(data_dir or os.environ.get('SUBSCRIPTION_DATA_DIR', 'data'))
    tables, checks = {}, []
    for name, rel in INPUTS.items():
        path = root / rel
        if not path.is_file():
            raise FileNotFoundError(f'필요한 비공개 입력 파일이 없습니다: {rel}')
        dtypes = {'user_id': 'string'}
        if name in ['start', 'end']:
            dtypes['content.id'] = 'string'
        df = pd.read_csv(path, usecols=COLS[name], dtype=dtypes)
        df['user_id'] = df.user_id.str.strip().replace('', pd.NA)
        for c in df.columns:
            if c in ['client_event_time', 'first_payment_date', 'first_activity_date_30',
                     'last_activity_date_30', 'day30_reference_date']:
                df[c] = pd.to_datetime(df[c], errors='raise', format='mixed')
        checks.append({'table': name, 'rows': len(df),
                       'missing_user_id_rows': int(df.user_id.isna().sum()),
                       'unique_users': int(df.user_id.nunique())})
        tables[name] = df
    if not tables['master'].user_id.is_unique:
        raise ValueError('고객 마스터에 중복 ID가 있습니다.')
    return tables, pd.DataFrame(checks)


def build_cohort(tables):
    master = tables['master']
    n = master.loc[
        master.first_payment_date.dt.to_period('M').astype(str).eq('2022-11')
        & master.first_plan_price.eq(15920) & master.has_discount.eq(1)
    ].copy()
    n = n.rename(columns={'renewed': 'renewed_in_source_master'})
    dec = tables['renew'].loc[
        tables['renew'].client_event_time.ge('2022-12-01')
        & tables['renew'].client_event_time.lt('2023-01-01')
        & tables['renew'].user_id.isin(n.user_id)
    ].copy()
    if not set(dec['plan.price'].dropna().unique()) <= {15920, 79200}:
        raise ValueError('12월에 미정의 상품이 있어 상품 분류 검토가 필요합니다.')
    flags = dec.groupby('user_id', as_index=False).agg(
        has_monthly_dec=('plan.price', lambda s: bool(s.eq(15920).any())),
        has_annual_dec=('plan.price', lambda s: bool(s.eq(79200).any())),
        first_dec_renew=('client_event_time', 'min'))
    n = n.merge(flags, on='user_id', how='left', validate='one_to_one')
    for c in ['has_monthly_dec', 'has_annual_dec']:
        n[c] = n[c].fillna(False).astype(bool)
    n['renewed_dec'] = n.has_monthly_dec | n.has_annual_dec
    # 두 상품 기록이 있는 고객은 연간권 기록 그룹에 한 번만 포함한다.
    n['group'] = np.select(
        [n.has_annual_dec, n.has_monthly_dec],
        [GROUPS[2], GROUPS[1]], default=GROUPS[0])
    n['observation_end'] = n.first_payment_date + pd.Timedelta(days=30)
    if not n.user_id.is_unique:
        raise ValueError('집계 전 코호트에 고객 중복이 있습니다.')
    return n


def build_features(tables, cohort):
    """콘텐츠 지표를 [첫 결제, 첫 결제+30일) 범위로 다시 계산한다.

    활동일수·최근 활동 간격은 제공된 30일 마스터 값을 활용한다.
    이 특징들은 회고적 집단 비교용이며 미래 갱신 예측의 검증 자료가 아니다.
    """
    frames = {}
    for name in ['start', 'end']:
        d = tables[name].merge(
            cohort[['user_id', 'first_payment_date', 'observation_end']],
            on='user_id', how='inner', validate='many_to_one')
        frames[name] = d.loc[
            d.client_event_time.ge(d.first_payment_date)
            & d.client_event_time.lt(d.observation_end)].copy()
    starts, ends = frames['start'], frames['end']
    start_counts = starts.groupby('user_id').agg(
        start_content_unique_30=('content.id', 'nunique'),
        difficulty_count_30=('content.difficulty', 'nunique'))
    end_counts = ends.groupby('user_id').agg(end_content_unique_30=('content.id', 'nunique'))
    # 시작한 콘텐츠와 완료한 콘텐츠의 교집합으로 완주율 분자를 정의한다.
    completed = (starts[['user_id', 'content.id']].dropna().drop_duplicates()
                 .merge(ends[['user_id', 'content.id']].dropna().drop_duplicates(),
                        on=['user_id', 'content.id'], how='inner', validate='one_to_one')
                 .groupby('user_id').size().rename('completed_started_content_30'))
    result = (cohort.merge(start_counts, on='user_id', how='left', validate='one_to_one')
              .merge(end_counts, on='user_id', how='left', validate='one_to_one')
              .merge(completed, on='user_id', how='left', validate='one_to_one'))
    for c in ['start_content_unique_30', 'difficulty_count_30', 'end_content_unique_30',
              'completed_started_content_30']:
        result[c] = result[c].fillna(0).astype(int)
    # 시작 기록이 없는 고객은 0으로 대체하지 않고 미정의로 보존한다.
    result['completion_rate_30_pct'] = (
        result.completed_started_content_30.div(
            result.start_content_unique_30.replace(0, np.nan)) * 100)
    result['has_start_content_30'] = result.start_content_unique_30.gt(0)
    all_difficulty = (tables['start'].loc[tables['start'].user_id.isin(cohort.user_id)]
                      .groupby('user_id')['content.difficulty'].nunique())
    new_counts = result.set_index('user_id').difficulty_count_30
    all_counts = all_difficulty.reindex(new_counts.index, fill_value=0)
    result.attrs['changed_difficulty_users'] = int(all_counts.ne(new_counts).sum())
    return result


def summarize(tables, cohort, features):
    n, renewed, annual = len(cohort), int(cohort.renewed_dec.sum()), int(cohort.has_annual_dec.sum())
    funnel = pd.DataFrame([
        {'stage': '11월 할인 유입', 'users': n, 'denominator': n, 'pct': 100.0},
        {'stage': '12월 갱신 기록', 'users': renewed, 'denominator': n, 'pct': renewed / n * 100},
        {'stage': '연간권 기록', 'users': annual, 'denominator': renewed, 'pct': annual / renewed * 100},
    ])
    grouped = features.groupby('group').agg(
        users=('user_id', 'nunique'),
        mean_active_days=('active_days_30', 'mean'),
        mean_days_since_last_activity=('days_since_last_activity_day30', 'mean'),
        mean_start_content_unique_30=('start_content_unique_30', 'mean'),
        mean_difficulty_count_30=('difficulty_count_30', 'mean'),
        mean_completion_rate_30_pct=('completion_rate_30_pct', 'mean'),
        completion_rate_defined_users=('completion_rate_30_pct', 'count'),
        users_with_start_content_30=('has_start_content_30', 'sum'),
    ).reindex(GROUPS)
    # 제공 마스터 전체 요약과 11월 코호트 집계를 구분한다.
    master_rates = tables['master'].groupby('has_discount').agg(
        users=('user_id', 'nunique'), renewed_in_source_master=('renewed', 'sum'))
    master_rates['source_master_renewal_pct'] = (
        master_rates.renewed_in_source_master / master_rates.users * 100)
    dec = tables['renew'].loc[
        tables['renew'].client_event_time.ge('2022-12-01')
        & tables['renew'].client_event_time.lt('2023-01-01')]
    nov_master = tables['master'].loc[
        tables['master'].first_payment_date.dt.to_period('M').astype(str).eq('2022-11')
        & tables['master'].first_plan_price.eq(15920)]
    reconciliation = []
    for label, pop in [('11월 전체 15,920원 플랜', nov_master), ('11월 할인 고객', cohort)]:
        events = dec.loc[dec.user_id.isin(pop.user_id)]
        reconciliation.append({'cohort': label, 'users': len(pop),
                               'dec_renew_users': int(events.user_id.nunique()),
                               'dec_annual_users': int(events.loc[events['plan.price'].eq(79200), 'user_id'].nunique())})
    audit = {
        'cohort_unique_users': int(cohort.user_id.nunique()),
        'customers_with_both_dec_plans': int((cohort.has_monthly_dec & cohort.has_annual_dec).sum()),
        'source_master_renewed_in_discount_cohort': int(cohort.renewed_in_source_master.sum()),
        'source_master_flag_vs_dec_target_disagreements': int(cohort.renewed_in_source_master.astype(bool).ne(cohort.renewed_dec).sum()),
        'renewed_before_30d_observation_end': int((cohort.first_dec_renew < cohort.observation_end).sum()),
        'changed_difficulty_users_after_window_filter': features.attrs['changed_difficulty_users'],
        'master_first_activity_before_payment': int((cohort.first_activity_date_30 < cohort.first_payment_date).sum()),
        'master_last_activity_after_reference': int((cohort.last_activity_date_30 > cohort.day30_reference_date).sum()),
        'master_active_days_max': int(cohort.active_days_30.max()),
        'completion_undefined_users': int(features.completion_rate_30_pct.isna().sum()),
    }
    assert int(grouped.users.sum()) == n
    assert annual <= renewed <= n
    assert (features.completed_started_content_30 <= features.start_content_unique_30).all()
    return {'funnel': funnel, 'groups': grouped, 'master_rates': master_rates,
            'cohort_reconciliation': pd.DataFrame(reconciliation), 'audit': audit,
            'annual_share_of_all_discount_pct': annual / n * 100}


def save_charts(summary, assets_dir='assets'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    assets = Path(assets_dir)
    assets.mkdir(parents=True, exist_ok=True)
    fonts = {f.name for f in font_manager.fontManager.ttflist}
    for name in ['Malgun Gothic', 'AppleGothic', 'NanumGothic']:
        if name in fonts:
            plt.rcParams['font.family'] = name
            break
    plt.rcParams.update({'axes.unicode_minus': False, 'font.size': 11,
                         'axes.spines.top': False, 'axes.spines.right': False})
    gold, gray, dark = '#D5B476', '#D7D9DE', '#373D48'
    fig, ax = plt.subplots(figsize=(10, 5.4), layout='constrained')
    rows = summary['funnel']
    bars = ax.bar(rows.stage, rows.users, color=[gray, gray, gold], width=.56)
    for bar, value in zip(bars, rows.users):
        ax.text(bar.get_x() + bar.get_width()/2, value+18, f'{int(value):,}명',
                ha='center', va='bottom', fontsize=15, weight='bold', color=dark)
    ax.set(ylim=(0, 960), ylabel='고객 수', title='할인 유입 고객의 12월 갱신·연간권 전환')
    share = rows.iloc[2]['pct']
    ax.text(1.45, 890, f'갱신자 중 {share:.1f}%가 연간권 기록',
            ha='center', fontsize=15, weight='bold', color='#967039')
    ax.grid(axis='y', alpha=.15)
    ax.set_axisbelow(True)
    fig.savefig(assets / 'discount_cohort_funnel.png', dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(14, 5), layout='constrained')
    labels = ['12월 갱신\n기록 없음', '월간권\n기록만', '연간권\n기록 있음']
    choices = [('mean_active_days', '관찰기간 평균 활동 날짜 수', '일'),
               ('mean_start_content_unique_30', '30일 내 평균 시작 콘텐츠 수', '개'),
               ('mean_completion_rate_30_pct', '30일 내 시작 콘텐츠 완주율', '%')]
    for ax, (col, title, unit) in zip(axes, choices):
        values = summary['groups'][col].to_numpy()
        bars = ax.bar(labels, values, color=[gray, gray, gold], width=.6)
        for bar, val in zip(bars, values):
            ax.text(bar.get_x()+bar.get_width()/2, val+max(values)*.03,
                    f'{val:.1f}{unit}', ha='center', weight='bold', fontsize=12)
        ax.set(title=title, ylim=(0, max(values)*1.3))
        ax.grid(axis='y', alpha=.15)
        ax.set_axisbelow(True)
    fig.suptitle('고객을 한 번씩 분류한 학습 행동 비교', fontsize=17)
    fig.text(.5, -.025, '완주율은 시작 콘텐츠가 있는 고객의 평균 · 행동과 갱신의 인과관계를 뜻하지 않음',
             ha='center', fontsize=10, color='#5B6069')
    fig.savefig(assets / 'learning_behavior_comparison.png', dpi=150, bbox_inches='tight')
    plt.close(fig)


def export_aggregates(summary, path='aggregate_results.json'):
    payload = {}
    for name in ['funnel', 'groups', 'master_rates', 'cohort_reconciliation']:
        payload[name] = json.loads(summary[name].reset_index().to_json(orient='records', double_precision=10))
    payload['audit'] = summary['audit']
    payload['annual_share_of_all_discount_pct'] = summary['annual_share_of_all_discount_pct']
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    tables, input_checks = load_tables()
    cohort = build_cohort(tables)
    features = build_features(tables, cohort)
    summary = summarize(tables, cohort, features)
    save_charts(summary)
    export_aggregates(summary)
    print(json.dumps(summary['audit'], ensure_ascii=False))
