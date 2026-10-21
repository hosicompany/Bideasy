// GA4 "Bideasy Web" 속성(p543510220) 28일·90일 스냅샷을 텍스트로 뽑는다.
// 실행: ego-browser nodejs < scripts/ga4_snapshot.mjs   (브라우저에 GA4 로그인돼 있어야 함)
// 출력: 표 텍스트 → docs/data/ga4/YYYY-MM-DD.md 에 저장 (ga4-reader 에이전트가 수행)
// ponytail: GA4 Data API 대신 로그인된 브라우저를 읽는다. 서비스 계정 세팅이 되면 API 로 교체.
const PROP = "a399535688p543510220";
const BASE = `https://analytics.google.com/analytics/web/#/${PROP}/reports/explorer?params=`;
const ymd = (d) => d.toISOString().slice(0, 10).replace(/-/g, "");
const today = new Date(); today.setDate(today.getDate() - 1);           // GA4 는 어제까지 확정
const since = (n) => { const d = new Date(today); d.setDate(d.getDate() - n + 1); return ymd(d); };
const RANGES = { "28일": [since(28), ymd(today)], "90일": [since(90), ymd(today)] };
const REPORTS = {
  "페이지 경로별 조회수": "%26_r.explorerCard..selmet%3D%5B%22screenPageViews%22%5D%26_r.explorerCard..seldim%3D%5B%22unifiedPagePathScreen%22%5D&r=all-pages-and-screens",
  "세션 소스/매체": "%26_r.explorerCard..seldim%3D%5B%22sessionSourceMedium%22%5D&r=lifecycle-traffic-acquisition-v2",
  "신규 사용자 채널": "&r=lifecycle-user-acquisition-v2",
  "이벤트": "&r=top-events",
};
const clean = (t) => t.replace(/\n{2,}/g, "\n")
  .replace(/열의 요약 총계 셀이 비어 있음|의 요약 총계 셀이 비어 있음|총계 대비 100%|평균과 동일|선택 행 도표 만들기/g, "")
  .replace(/\t+/g, "\t");

const task = await taskSpace("bideasy-ga4-snapshot");
const page = task.page("p1");
console.log(`# GA4 스냅샷 ${new Date().toISOString().slice(0, 10)} (속성 Bideasy Web)\n`);
for (const [rname, [d0, d1]] of Object.entries(RANGES)) {
  for (const [label, q] of Object.entries(REPORTS)) {
    await page.goto(`${BASE}_u.date00%3D${d0}%26_u.date01%3D${d1}${q}`);
    await page.waitForTimeout(8000);
    const t = await page.evaluate(() => document.body.innerText);
    const a = t.indexOf("합계"), b = t.indexOf("©2026");
    const body = a > 0 && b > a ? clean(t.slice(a, b)) : "(읽기 실패 — 로그인/보고서 ID 확인)";
    console.log(`\n## ${label} — ${rname} (${d0}~${d1})\n\n\`\`\`\n${body.slice(0, 3000)}\n\`\`\``);
  }
}
await task.finish({ keep: [] });
