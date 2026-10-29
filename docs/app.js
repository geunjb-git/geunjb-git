/* Published figures are aggregates. No customer-level data is loaded by this page. */
'use strict';
const subChart = document.querySelector('#subscription-chart');
const subNote = document.querySelector('#subscription-note');
const subButtons = document.querySelectorAll('[data-view]');
const subViews = {
  funnel: {
    html: `<h3 class="chart-title">11월 할인 유입 고객의 12월 갱신</h3><p class="chart-subtitle">고객 수 · 중복 고객을 제거한 집계</p><div class="funnel-rows">${[
      ['11월 할인 유입',797,100],['12월 갱신 기록',368,368/797*100],['연간권 기록',136,136/797*100]
    ].map(([label,n,p])=>`<div class="funnel-row"><div class="funnel-caption"><span>${label}</span><strong>${n}<small>명</small></strong></div><div class="funnel-track" aria-hidden="true"><span style="--value:${p}%"></span></div></div>`).join('')}</div><p class="chart-highlight">갱신자 368명 중 연간권 기록 136명 <strong>37.0%</strong></p>`,
    note:'연간권 비중의 분모는 12월 갱신자 368명입니다. 연간권 기록은 12월 해당 상품의 갱신 기록이 한 번 이상 있는 고객을 뜻합니다.'
  },
  learning: {
    html: `<h3 class="chart-title">할인 유입 고객의 콘텐츠 완주율</h3><p class="chart-subtitle">2022년 11월 첫 결제 · 15,920원 플랜 · 고객별 비율의 평균</p><div class="learning-bars" role="img" aria-label="정상가 고객 89명의 평균 완주율 14.2%, 할인 고객 797명의 평균 완주율 30.0%"><div class="learning-bar"><b>14.2%</b><span style="--height:56.8px"></span></div><div class="learning-bar"><b>30.0%</b><span style="--height:120px"></span></div></div><div class="learning-labels"><div>정상가 고객<small>89명</small></div><div>할인 유입 고객<small>797명</small></div></div><p class="learning-explainer">원본 전처리 CSV의 고객별 완주율을 평균했습니다. 시작 콘텐츠가 없는 고객도 원본의 0 값을 유지했습니다.</p>`,
    note:'원본 user_content_completion_rate(%) 기준입니다. 정상가·할인 집단의 관측 차이이며, 할인이 완주율을 높였다는 인과효과를 뜻하지 않습니다.'
  }
};
function showSubscription(view){
  subChart.innerHTML=subViews[view].html; subNote.textContent=subViews[view].note;
  subButtons.forEach(b=>{const active=b.dataset.view===view;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
}
subButtons.forEach(b=>b.addEventListener('click',()=>showSubscription(b.dataset.view)));
showSubscription('funnel');

const officeData={
  applicant:{title:'전체 신청자 기준 결제율',a:[100/203*100,163/414*100],b:[57/246*100,68/281*100],note:'월별 결제 고객 수 ÷ 해당 월 전체 신청자 수. 같은 달의 두 연도를 비교했습니다.'},
  visitor:{title:'방문 기록 고객 기준 결제율',a:[71/141*100,110/269*100],b:[43/200*100,61/263*100],note:'월별 방문 기록과 결제 기록이 모두 있는 고객 수 ÷ 해당 월 방문 기록 고객 수. 전체 신청자 기준과 분모가 다릅니다.'}
};
function showOffice(view){
  const d=officeData[view],xs=[100,370],y=v=>245-(v-20)/40*180;
  const ticks=[20,30,40,50,60].map(v=>`<line x1="48" x2="444" y1="${y(v)}" y2="${y(v)}" stroke="#e2e6df"/><text x="35" y="${y(v)+4}" text-anchor="end" fill="#7a8279" font-size="11">${v}%</text>`).join('');
  const series=(arr,color)=>`<polyline points="${arr.map((v,i)=>`${xs[i]},${y(v)}`).join(' ')}" fill="none" stroke="${color}" stroke-width="3"/>${arr.map((v,i)=>`<circle cx="${xs[i]}" cy="${y(v)}" r="5" fill="${color}"/><text x="${xs[i]}" y="${y(v)-14}" text-anchor="middle" fill="${color}" font-size="16" font-weight="700">${v.toFixed(1)}%</text>`).join('')}`;
  document.querySelector('#office-chart').innerHTML=`<h3 class="chart-title">${d.title}</h3><p class="chart-subtitle">2022년 · 2023년 동월 비교 / 세로축 20~60%</p><div class="chart-legend"><span class="legend-item"><i class="legend-dot" style="background:#5c8f76"></i>2022년</span><span class="legend-item"><i class="legend-dot" style="background:#8770ad"></i>2023년</span></div><svg class="line-chart" viewBox="0 0 470 282" role="img" aria-label="${d.title}. 2022년 11월 ${d.a[0].toFixed(1)}%, 12월 ${d.a[1].toFixed(1)}%. 2023년 11월 ${d.b[0].toFixed(1)}%, 12월 ${d.b[1].toFixed(1)}%.">${ticks}${series(d.a,'#5c8f76')}${series(d.b,'#8770ad')}<text x="100" y="274" text-anchor="middle" fill="#53624f" font-size="12">11월</text><text x="370" y="274" text-anchor="middle" fill="#53624f" font-size="12">12월</text></svg>`;
  document.querySelector('#office-note').textContent=d.note;
  document.querySelectorAll('[data-office]').forEach(b=>{const active=b.dataset.office===view;b.classList.toggle('active',active);b.setAttribute('aria-pressed',String(active));});
}
document.querySelectorAll('[data-office]').forEach(b=>b.addEventListener('click',()=>showOffice(b.dataset.office)));
showOffice('applicant');

const dialog=document.querySelector('#image-dialog');
document.querySelector('.image-zoom').addEventListener('click',()=>dialog.showModal());
document.querySelector('.dialog-close').addEventListener('click',()=>dialog.close());
dialog.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
const navLinks=document.querySelectorAll('nav a[href^="#"]');
if('IntersectionObserver' in window){
  const observer=new IntersectionObserver(entries=>{entries.forEach(e=>{if(e.isIntersecting){navLinks.forEach(a=>a.removeAttribute('aria-current'));document.querySelector(`nav a[href="#${e.target.id}"]`)?.setAttribute('aria-current','location');}});},{rootMargin:'-10% 0px -65% 0px'});
  ['work','about'].forEach(id=>observer.observe(document.getElementById(id)));
}
