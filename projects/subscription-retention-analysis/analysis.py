"""11월 할인 코호트의 12월 갱신을 집계하고 원본 CSV 행동 지표를 비교한다."""
import json
import os
from pathlib import Path
import pandas as pd

MASTER_COLUMNS = ['user_id','first_payment_date','first_plan_price','has_discount',
 'renewed','start_content_unique_count','active_days_30',
 'user_content_completion_rate(%)','total_activity_events_30']

def load_tables(data_dir=None):
    root=Path(data_dir or os.environ.get('SUBSCRIPTION_DATA_DIR','data'))
    master=pd.read_csv(root/'15920_1개월플랜_분석/plan15920_user_level_data.csv',
                       usecols=MASTER_COLUMNS,dtype={'user_id':'string'})
    renew=pd.read_csv(root/'renew_subscription_df.csv',
                     usecols=['user_id','client_event_time','plan.price'],dtype={'user_id':'string'})
    for df in [master,renew]:
        df['user_id']=df.user_id.str.strip()
        if df.user_id.isna().any() or df.user_id.eq('').any(): raise ValueError('입력 ID 결측')
    if not master.user_id.is_unique: raise ValueError('고객 마스터 ID 중복')
    master['first_payment_date']=pd.to_datetime(master.first_payment_date,format='mixed',errors='raise')
    renew['client_event_time']=pd.to_datetime(renew.client_event_time,format='mixed',errors='raise')
    return master,renew

def summarize(master,renew):
    nov=master.loc[master.first_payment_date.ge('2022-11-01') &
        master.first_payment_date.lt('2022-12-01') & master.first_plan_price.eq(15920)].copy()
    cohort=nov.loc[nov.has_discount.eq(1)]
    dec=renew.loc[renew.client_event_time.ge('2022-12-01') &
        renew.client_event_time.lt('2023-01-01') & renew.user_id.isin(cohort.user_id)]
    if not set(dec['plan.price'].dropna().unique()) <= {15920,79200}: raise ValueError('미정의 상품')
    renewed=set(dec.user_id)
    annual=set(dec.loc[dec['plan.price'].eq(79200),'user_id'])
    monthly=set(dec.loc[dec['plan.price'].eq(15920),'user_id'])
    n,r,a=len(cohort),len(renewed),len(annual)
    assert 0<a<=r<=n
    funnel=[dict(stage='11월 할인 유입',users=n,denominator=n,pct=100.0),
        dict(stage='12월 갱신 기록',users=r,denominator=n,pct=r/n*100),
        dict(stage='연간권 기록',users=a,denominator=r,pct=a/r*100)]
    comparison=[]
    for flag,label in [(0,'정상가 고객'),(1,'할인 고객')]:
        group=nov.loc[nov.has_discount.eq(flag)]
        # 미시작 고객의 원본 0 값을 포함하고 결측을 임의로 바꾸지 않는다.
        assert not group['user_content_completion_rate(%)'].isna().any()
        comparison.append(dict(group=label,users=len(group),
            mean_user_completion_pct=float(group['user_content_completion_rate(%)'].mean()),
            mean_activity_events_30=float(group.total_activity_events_30.mean())))
    groups=[]
    # 원본 탐색의 상품 기록별 집단을 유지한다. 월간·연간 13명 중복은 명시한다.
    for label,mask in [('12월 갱신 기록 없음',~cohort.user_id.isin(renewed)),
        ('월간권 기록 있음',cohort.user_id.isin(monthly)),
        ('연간권 기록 있음',cohort.user_id.isin(annual))]:
        g=cohort.loc[mask]
        groups.append(dict(group=label,users=len(g),
            mean_start_content_unique=float(g.start_content_unique_count.mean()),
            mean_active_days_30=float(g.active_days_30.mean()),
            mean_user_completion_pct=float(g['user_content_completion_rate(%)'].mean())))
    rates=[dict(has_discount=int(flag),users=len(g),renewed_in_source_master=int(g.renewed.sum()),
         source_master_renewal_pct=float(g.renewed.mean()*100)) for flag,g in master.groupby('has_discount')]
    return dict(funnel=funnel,november_discount_comparison=comparison,groups=groups,master_rates=rates,
        metric_basis='Original preprocessed CSV columns; no raw-log feature redefinition',
        group_membership='Monthly and annual record groups overlap; not a partition',
        audit=dict(cohort_unique_users=n,december_renewed_users=r,annual_record_users=a,
                   monthly_record_users=len(monthly),customers_with_both_dec_plans=len(monthly & annual)),
        annual_share_of_all_discount_pct=a/n*100)

def save_charts(result,assets_dir='assets'):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    assets=Path(assets_dir);assets.mkdir(parents=True,exist_ok=True)
    installed={f.name for f in font_manager.fontManager.ttflist}
    for font in ['Malgun Gothic','AppleGothic','NanumGothic']:
        if font in installed:plt.rcParams['font.family']=font;break
    plt.rcParams.update({'axes.unicode_minus':False,'axes.spines.top':False,'axes.spines.right':False})
    fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
    rows=result['funnel'];values=[row['users'] for row in rows]
    bars=ax.bar([row['stage'] for row in rows],values,color=['#a6b1a4','#a6b1a4','#deb46c'],width=.55)
    for b,n in zip(bars,values):ax.text(b.get_x()+b.get_width()/2,n+16,f'{n:,}명',ha='center',fontsize=14)
    ax.set(ylim=(0,1000),ylabel='고객 수',title='할인 유입 고객의 12월 갱신·연간권 기록')
    ax.text(1.1,900,f"갱신자 중 {rows[2]['pct']:.1f}%",ha='center',fontsize=15)
    fig.savefig(assets/'discount_cohort_funnel.png',dpi=160);plt.close(fig)
    fig,ax=plt.subplots(figsize=(9,5),layout='constrained')
    rows=result['november_discount_comparison'];values=[row['mean_user_completion_pct'] for row in rows]
    bars=ax.bar([f"{row['group']} (n={row['users']})" for row in rows],values,
                color=['#a6b1a4','#deb46c'],width=.5)
    for b,v in zip(bars,values):ax.text(b.get_x()+b.get_width()/2,v+.8,f'{v:.1f}%',ha='center',fontsize=15)
    ax.set(ylim=(0,40),ylabel='평균 완주율 (%)',title='11월 고객 완주율 비교 · 원본 CSV 정의')
    fig.savefig(assets/'learning_behavior_comparison.png',dpi=160);plt.close(fig)

def main():
    result=summarize(*load_tables())
    Path('aggregate_results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    save_charts(result)
    print(json.dumps(result['audit'],ensure_ascii=False))

if __name__=='__main__':main()
