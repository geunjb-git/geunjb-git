"""공유오피스 결제율 분석: 공개용 집계와 기존 기본 회귀 재현."""
import os
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

MONTHS = ['2022-11', '2022-12', '2023-11', '2023-12']
FILES = {
    'register': 'trial_register_dropduplicates.csv',
    'payment': 'trial_payment_dropduplicates.csv',
    'visit': 'trial_visit_info_dropduplicates.csv',
}
REQUIRED = {
    'register': ['user_uuid', 'trial_date'],
    'payment': ['user_uuid', 'is_payment'],
    'visit': ['user_uuid', 'date', 'site_id', 'stay_time_second'],
}


def load_tables(data_dir=None):
    """원본은 외부에서 별도 제공해야 한다. 사용자별 레코드를 출력하지 않는다."""
    data_dir = Path(data_dir or os.environ.get('OFFICE_DATA_DIR', 'data'))
    tables, checks = {}, []
    for name, filename in FILES.items():
        path = data_dir / filename
        if not path.is_file():
            raise FileNotFoundError(f'필요한 비공개 입력 파일이 없습니다: {filename}')
        df = pd.read_csv(path)
        missing = set(REQUIRED[name]) - set(df.columns)
        if missing:
            raise ValueError(f'{filename}: 필수 컬럼 누락 {sorted(missing)}')
        checks.append({
            'table': name, 'rows': len(df),
            'exact_duplicate_rows': int(df.duplicated().sum()),
            'missing_user_id_rows': int(df.user_uuid.isna().sum()),
        })
        tables[name] = df
    tables['register']['trial_date'] = pd.to_datetime(
        tables['register']['trial_date'], errors='raise')
    tables['visit']['date'] = pd.to_datetime(tables['visit']['date'], errors='raise')
    tables['visit']['stay_time_second'] = pd.to_numeric(
        tables['visit']['stay_time_second'], errors='raise')
    payment_values = set(tables['payment']['is_payment'].dropna().unique())
    if not payment_values <= {0, 1}:
        raise ValueError('결제 여부는 0/1이어야 합니다.')
    return tables, pd.DataFrame(checks)


def build_cohort(tables):
    """기존 3-2 기준 보존: 사용자별 최신 신청, 마지막 결제 레코드, 전체 방문 기록.

    방문일을 체험기간/결제 전으로 제한하지 않는다. 따라서 인과 분석이나
    결제 전 행동에 기반한 미래 예측 결과로 해석할 수 없다.
    """
    register = (tables['register'][['user_uuid', 'trial_date']]
                .dropna(subset=['user_uuid', 'trial_date'])
                .sort_values('trial_date')
                .drop_duplicates('user_uuid', keep='last').copy())
    register['month'] = register.trial_date.dt.to_period('M').astype(str)
    visit = tables['visit']
    visitor = (visit[['user_uuid']].dropna().drop_duplicates().assign(is_visit=1))
    payment = (tables['payment'][['user_uuid', 'is_payment']]
               .dropna(subset=['user_uuid'])
               .drop_duplicates('user_uuid', keep='last'))
    cohort = (register.merge(visitor, on='user_uuid', how='left', validate='one_to_one')
              .merge(payment, on='user_uuid', how='left', validate='one_to_one'))
    cohort['payment_missing_before_fill'] = cohort.is_payment.isna()
    # 기존 집계 재현 정책. 결측 결제는 미결제로 간주하며 그 건수도 따로 기록한다.
    cohort[['is_visit', 'is_payment']] = (
        cohort[['is_visit', 'is_payment']].fillna(0).astype(int))
    behavior = (visit.groupby('user_uuid', as_index=False)
                .agg(visit_days=('date', 'nunique'),
                     total_stay_second=('stay_time_second', 'sum'),
                     mean_stay_per_record_second=('stay_time_second', 'mean'),
                     used_site_count=('site_id', 'nunique'),
                     first_visit_date=('date', 'min')))
    cohort = cohort.merge(behavior, on='user_uuid', how='left', validate='one_to_one')
    for c in ['visit_days', 'total_stay_second', 'mean_stay_per_record_second', 'used_site_count']:
        cohort[c] = cohort[c].fillna(0)
    cohort['total_stay_hour'] = cohort.total_stay_second / 3600
    cohort['mean_stay_per_record_hour'] = cohort.mean_stay_per_record_second / 3600
    # 회귀에서 사용한 원래 정의를 보존한다. 날짜 정규화 여부에 따라 달라질 수 있다.
    cohort['days_to_first_visit'] = (cohort.first_visit_date - cohort.trial_date).dt.days
    cohort['year'] = cohort.month.str[:4]
    cohort['visit_days_group'] = cohort.visit_days.clip(upper=3).astype(int)
    cohort['visitor_payer'] = cohort.is_visit.eq(1) & cohort.is_payment.eq(1)
    return cohort.loc[cohort.month.isin(MONTHS)].copy()


def summarize(cohort):
    monthly = (cohort.groupby('month').agg(
        applicants=('user_uuid', 'nunique'), visitors=('is_visit', 'sum'),
        all_payers=('is_payment', 'sum'), visitor_payers=('visitor_payer', 'sum')))
    monthly['applicant_payment_pct'] = monthly.all_payers / monthly.applicants * 100
    monthly['visitor_payment_pct'] = monthly.visitor_payers / monthly.visitors * 100
    monthly['first_visit_pct'] = monthly.visitors / monthly.applicants * 100
    yearly = cohort.groupby('year').agg(
        applicants=('user_uuid', 'nunique'), visitors=('is_visit', 'sum'),
        all_payers=('is_payment', 'sum'), visitor_payers=('visitor_payer', 'sum'),
        second_visitors=('visit_days', lambda s: int(s.ge(2).sum())),
        third_visitors=('visit_days', lambda s: int(s.ge(3).sum())))
    yearly['applicant_payment_pct'] = yearly.all_payers / yearly.applicants * 100
    # 수정: 분자도 방문자로 제한한다. 전체 신청자의 결제자 수를 사용하지 않는다.
    yearly['visitor_payment_pct'] = yearly.visitor_payers / yearly.visitors * 100
    yearly['first_visit_pct'] = yearly.visitors / yearly.applicants * 100
    yearly['second_given_first_pct'] = yearly.second_visitors / yearly.visitors * 100
    yearly['third_given_second_pct'] = yearly.third_visitors / yearly.second_visitors * 100
    visitors = cohort.loc[cohort.is_visit.eq(1)].copy()
    strata = (visitors.groupby(['year', 'visit_days_group']).agg(
        visitors=('user_uuid', 'nunique'), payers=('is_payment', 'sum'),
        payment_pct=('is_payment', lambda s: s.mean() * 100)))
    behavior = visitors.groupby('year').agg(
        visitors=('user_uuid', 'nunique'), mean_visit_days=('visit_days', 'mean'),
        mean_total_stay_hour=('total_stay_hour', 'mean'),
        mean_used_site_count=('used_site_count', 'mean'),
        mean_days_to_first_visit=('days_to_first_visit', 'mean'))
    quality = {
        'cohort_size': len(cohort),
        'missing_payment_before_fill': int(cohort.payment_missing_before_fill.sum()),
        'payers_without_visit_record': int((cohort.is_payment.eq(1) & cohort.is_visit.eq(0)).sum()),
        'first_visit_before_latest_application': int(cohort.days_to_first_visit.lt(0).sum()),
        'first_visit_over_3_days': int(cohort.days_to_first_visit.gt(3).sum()),
        'users_more_than_3_visit_days': int(cohort.visit_days.gt(3).sum()),
    }
    if not cohort.user_uuid.is_unique:
        raise ValueError('고객 단위 코호트에 중복 ID가 있습니다.')
    if not (monthly.visitor_payers <= monthly.visitors).all():
        raise ValueError('방문 결제자의 모집단이 잘못되었습니다.')
    return dict(monthly=monthly, yearly=yearly, strata=strata, behavior=behavior, quality=quality)


def fit_basic_logit(cohort):
    """기존 기본 모형 재현. 인과효과/운영 예측 성능 검증용 모형이 아니다."""
    model_df = cohort.loc[cohort.is_visit.eq(1)].copy()
    model_df['year_2023'] = model_df.year.eq('2023').astype(int)
    cols = ['visit_days', 'total_stay_hour', 'used_site_count',
            'days_to_first_visit', 'year_2023']
    complete = model_df[cols + ['is_payment']].replace([np.inf, -np.inf], np.nan).dropna()
    x = sm.add_constant(complete[cols].astype(float))
    fitted = sm.Logit(complete.is_payment.astype(int), x).fit(disp=False)
    ci = fitted.conf_int()
    result = pd.DataFrame({
        'coefficient': fitted.params, 'odds_ratio': np.exp(fitted.params),
        'p_value': fitted.pvalues, 'ci_low': np.exp(ci[0]), 'ci_high': np.exp(ci[1])})
    return result, {'nobs': int(fitted.nobs),
                    'converged': bool(fitted.mle_retvals['converged']),
                    'excluded_missing_or_infinite': len(model_df) - len(complete)}


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
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams.update({'font.size': 12, 'axes.spines.top': False,
                         'axes.spines.right': False})
    mint, purple = '#26876F', '#7961A8'
    monthly = summary['monthly']
    fig, ax = plt.subplots(figsize=(10, 4.8), layout='constrained')
    for year, color in [('2022', mint), ('2023', purple)]:
        rows = monthly.loc[[f'{year}-11', f'{year}-12']]
        values = rows.applicant_payment_pct.to_numpy()
        ax.plot([0, 1], values, '-o', color=color, linewidth=3, markersize=8, label=year)
        for x, y in enumerate(values):
            ax.annotate(f'{y:.1f}%', (x, y), xytext=(0, 12),
                        textcoords='offset points', ha='center', color=color, weight='bold')
    ax.set(xticks=[0, 1], xticklabels=['11월', '12월'], ylim=(20, 60),
           yticks=[20, 30, 40, 50, 60], ylabel='전체 신청자 중 결제율 (%)',
           title='방문은 늘었지만, 전체 신청자의 결제율은 하락')
    ax.grid(axis='y', alpha=.15)
    ax.legend(frameon=False)
    fig.savefig(assets / 'monthly_payment_rate.png', dpi=160)
    plt.close(fig)
    yearly = summary['yearly']
    fig, ax = plt.subplots(figsize=(9, 4.8), layout='constrained')
    values = yearly.visitor_payment_pct.to_numpy()
    bars = ax.bar(['2022년', '2023년'], values, color=[mint, purple], width=.5)
    for bar, (year, row) in zip(bars, yearly.iterrows()):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+1,
                f'{row.visitor_payment_pct:.2f}%\n({int(row.visitor_payers)} / {int(row.visitors)}명)',
                ha='center', va='bottom', weight='bold')
    ax.set(ylim=(0, 60), ylabel='방문 기록이 있는 고객 중 결제율 (%)',
           title='방문 고객의 결제율도 44.15%에서 22.46%로 하락')
    ax.grid(axis='y', alpha=.15)
    ax.set_axisbelow(True)
    fig.savefig(assets / 'visitor_payment_rate.png', dpi=160)
    plt.close(fig)


def export_aggregates(summary, logit, logit_info, path='aggregate_results.json'):
    import json
    payload = {name: json.loads(summary[name].reset_index().to_json(
        orient='records', double_precision=10))
        for name in ['monthly', 'yearly', 'strata', 'behavior']}
    payload['quality'] = summary['quality']
    payload['basic_logit'] = json.loads(logit.rename_axis('feature').reset_index().to_json(
        orient='records', double_precision=10))
    payload['basic_logit_info'] = logit_info
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    return payload


if __name__ == '__main__':
    import json
    tables, checks = load_tables()
    cohort = build_cohort(tables)
    summary = summarize(cohort)
    logit, info = fit_basic_logit(cohort)
    save_charts(summary)
    export_aggregates(summary, logit, info)
    print(json.dumps({'quality': summary['quality'], 'basic_logit_info': info}, ensure_ascii=False))
