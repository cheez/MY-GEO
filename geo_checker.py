import streamlit as st
import requests
import re
import json
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
from bs4 import BeautifulSoup

st.set_page_config(page_title="AI Crawling & GEO Checker", layout="wide")
st.title("🤖 AI 크롤링 & GEO 종합 점검 리포트")
st.caption("robots.txt · llms.txt · agents.md · sitemap.xml · Schema.org · OG태그 · UCP · hreflang 분석 — sanghee kim")
st.markdown("---")

url = st.text_input("진단할 사이트 주소 (https:// 필수)", "https://")

AI_BOTS = [
    "GPTBot", "ChatGPT-User", "ClaudeBot", "anthropic-ai",
    "Google-Extended", "PerplexityBot", "cohere-ai",
    "Applebot-Extended", "Amazonbot", "Meta-ExternalAgent",
    "Bytespider", "Diffbot", "CCBot", "DataForSeoBot",
]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def safe_fetch(url, timeout=10):
    try:
        start = time.time()
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        elapsed = round(time.time() - start, 2)
        if r.status_code == 200:
            return r.text, None, elapsed
        return None, f"HTTP {r.status_code}", elapsed
    except Exception as e:
        return None, str(e), 0

def parse_robots(txt):
    blocks = []
    cur = None
    sitemap_refs = []
    for line in txt.splitlines():
        raw = line.strip()
        low = raw.lower()
        if not raw:
            cur = None
            continue
        if raw.startswith('#'):
            continue
        if low.startswith('sitemap:'):
            sitemap_refs.append(raw[8:].strip())
            continue
        if low.startswith('user-agent:'):
            ua = raw[11:].strip()
            if cur is None:
                cur = {'agents': [], 'allow': [], 'disallow': []}
                blocks.append(cur)
            cur['agents'].append(ua)
        elif cur is not None:
            if low.startswith('allow:'):
                cur['allow'].append(raw[6:].strip())
            elif low.startswith('disallow:'):
                cur['disallow'].append(raw[9:].strip())
    return blocks, sitemap_refs

def check_bot_status(bot_name, blocks):
    key = bot_name.lower()
    specific = next((b for b in blocks if key in [a.lower() for a in b['agents']]), None)
    wildcard = next((b for b in blocks if '*' in b['agents']), None)
    has_specific = specific is not None
    active = specific or wildcard
    if not active:
        return 'unknown', False
    al = active['allow']
    dis = active['disallow']
    root_allowed = any(a in ('/', '') for a in al)
    if root_allowed:
        return 'allowed', has_specific
    root_blocked = any(d in ('/', '/*') for d in dis)
    if root_blocked:
        return 'blocked', has_specific
    if not dis or all(d == '' for d in dis):
        return 'allowed', has_specific
    return 'partial', has_specific

def parse_sitemap(txt):
    try:
        root = ET.fromstring(txt)
        ns = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        is_index = 'sitemapindex' in root.tag
        if is_index:
            locs = [el.text for el in root.findall('.//sm:loc', ns) if el.text]
            lastmods = [el.text for el in root.findall('.//sm:lastmod', ns) if el.text]
            return {'type': 'index', 'count': len(locs), 'lastmod': lastmods[0] if lastmods else '-', 'locs': locs[:5]}
        else:
            urls = root.findall('.//sm:url', ns)
            lastmods = [u.find('sm:lastmod', ns) for u in urls]
            lastmods = [l.text for l in lastmods if l is not None]
            return {'type': 'single', 'count': len(urls), 'lastmod': lastmods[0] if lastmods else '-', 'locs': []}
    except Exception as e:
        return {'type': 'error', 'count': 0, 'lastmod': '-', 'locs': [], 'error': str(e)}

def analyze_homepage(html, base_url):
    soup = BeautifulSoup(html, 'html.parser')

    # Schema.org JSON-LD
    schemas = []
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '{}')
            if isinstance(data, list):
                schemas.extend(data)
            else:
                schemas.append(data)
        except:
            pass
    schema_types = [s.get('@type', 'Unknown') for s in schemas if isinstance(s, dict)]

    # OG 태그
    og = {}
    for tag in soup.find_all('meta'):
        prop = tag.get('property', '') or tag.get('name', '')
        if prop.startswith('og:') or prop.startswith('twitter:'):
            og[prop] = tag.get('content', '')

    # Canonical
    canonical = soup.find('link', rel='canonical')
    canonical_url = canonical['href'] if canonical else None

    # hreflang
    hreflang_tags = soup.find_all('link', rel='alternate', hreflang=True)
    hreflangs = [{'lang': t.get('hreflang'), 'href': t.get('href')} for t in hreflang_tags]

    # 텍스트 비중
    text = soup.get_text()
    text_ratio = round(len(text) / len(html) * 100, 1) if html else 0

    # title / meta description
    title = soup.find('title')
    title_text = title.get_text().strip() if title else None
    desc = soup.find('meta', attrs={'name': 'description'})
    desc_text = desc.get('content', '').strip() if desc else None

    return {
        'schemas': schemas,
        'schema_types': schema_types,
        'og': og,
        'canonical': canonical_url,
        'hreflangs': hreflangs,
        'text_ratio': text_ratio,
        'title': title_text,
        'description': desc_text,
    }

def extract_special_comments(txt):
    special_keys = ['agents.md', 'ucp', 'mcp', 'skill.md', 'bots@']
    return [
        l.strip()[1:].strip()
        for l in txt.splitlines()
        if l.strip().startswith('#') and any(k in l.lower() for k in special_keys)
    ]

def score_color(s):
    if s >= 80: return "🟢"
    if s >= 50: return "🟡"
    return "🔴"

# ── 배점표 (총 100점) ──────────────────────────────
# robots.txt 존재        : 8
# AI 봇 전체 허용        : 12
# sitemap.xml 존재       : 5
# sitemap URL > 0        : 5
# robots Sitemap 참조    : 5
# llms.txt 존재          : 10
# agents.md 존재         : 8
# UCP .well-known        : 7
# Schema.org JSON-LD     : 10
# OG 태그 (og:title 등)  : 8
# Canonical 태그         : 7
# hreflang 태그          : 8
# 텍스트 비중 > 10%      : 5
# 응답속도 < 3초         : 2
# ──────────────────────────────────────── 합계 100

if st.button("🔍 종합 점검 시작"):
    if not url.startswith("http"):
        st.warning("https:// 로 시작하는 주소를 입력해주세요.")
        st.stop()

    base = url.rstrip('/')
    parsed = urlparse(base)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    with st.spinner("전체 항목 분석 중... (robots · llms · agents · sitemap · Schema · OG · UCP · hreflang)"):
        robots_txt, robots_err, _ = safe_fetch(domain + "/robots.txt")
        llms_txt,   llms_err,   _ = safe_fetch(domain + "/llms.txt")
        agents_txt, agents_err, _ = safe_fetch(domain + "/agents.md")
        sitemap_txt, sitemap_err, _ = safe_fetch(domain + "/sitemap.xml")
        ucp_txt,    ucp_err,    _  = safe_fetch(domain + "/.well-known/ucp")
        homepage_txt, homepage_err, resp_time = safe_fetch(base, timeout=15)

        # robots 파싱
        blocks = []
        sitemap_refs_in_robots = []
        bot_statuses = []
        allowed_c = blocked_c = partial_c = unknown_c = 0
        if robots_txt:
            blocks, sitemap_refs_in_robots = parse_robots(robots_txt)
            for bot in AI_BOTS:
                status, is_specific = check_bot_status(bot, blocks)
                bot_statuses.append((bot, status, is_specific))
                if status == 'allowed':   allowed_c += 1
                elif status == 'blocked': blocked_c += 1
                elif status == 'partial': partial_c += 1
                else:                     unknown_c += 1

        # sitemap 파싱
        sitemap_info = parse_sitemap(sitemap_txt) if sitemap_txt else None

        # 홈페이지 분석
        page = analyze_homepage(homepage_txt, domain) if homepage_txt else None

        # ── 점수 계산 ──────────────────────────────────
        score = 0
        score_detail = {}

        def add(key, pts, max_pts, condition):
            nonlocal score
            earned = pts if condition else 0
            score += earned
            score_detail[key] = (earned, max_pts)

        add('robots.txt 존재',           8,  8,  robots_txt is not None)
        if allowed_c == len(AI_BOTS) and blocked_c == 0 and partial_c == 0:
            add(f'AI 봇 전체 허용 ({len(AI_BOTS)}/{len(AI_BOTS)})', 12, 12, True)
        elif blocked_c == 0 and partial_c == 0:
            add('AI 봇 허용 (일부 unknown)',  8, 12, True)
        elif blocked_c == 0:
            add(f'AI 봇 부분 제한 ({partial_c}개)', 4, 12, True)
        else:
            add(f'AI 봇 차단 ({blocked_c}개)',  0, 12, False)
        add('sitemap.xml 존재',           5,  5,  sitemap_txt is not None)
        add('sitemap URL 수 > 0',         5,  5,  sitemap_info and sitemap_info['count'] > 0)
        add('robots.txt Sitemap 참조',    5,  5,  bool(sitemap_refs_in_robots))
        add('llms.txt 존재',             10, 10,  llms_txt is not None)
        add('agents.md 존재',             8,  8,  agents_txt is not None)
        add('UCP (.well-known/ucp)',      7,  7,  ucp_txt is not None)
        add('Schema.org JSON-LD',        10, 10,  page and len(page['schemas']) > 0)
        add('OG 태그 (og:title)',         8,  8,  page and 'og:title' in page['og'])
        add('Canonical 태그',             7,  7,  page and page['canonical'] is not None)
        add('hreflang 태그',              8,  8,  page and len(page['hreflangs']) > 0)
        add('텍스트 비중 > 10%',          5,  5,  page and page['text_ratio'] > 10)
        add('응답속도 < 3초',             2,  2,  resp_time > 0 and resp_time < 3)

    # ── 종합 요약 ──────────────────────────────────────
    st.header("📊 종합 요약")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric(f"{score_color(score)} 종합 점수", f"{score} / 100")
    c2.metric("✅ AI 봇 허용", f"{allowed_c} / {len(AI_BOTS)}")
    blocked_icon = "✅ 차단 없음" if blocked_c == 0 else "❌ AI 봇 차단"
    partial_icon = "✅ 제한 없음" if partial_c == 0 else "⚠️ 부분 제한"
    c3.metric(blocked_icon, f"{blocked_c} / {len(AI_BOTS)}", help="0이면 정상")
    c4.metric(partial_icon, f"{partial_c} / {len(AI_BOTS)}", help="0이면 정상")
    c5.metric("llms.txt", "✅ 있음" if llms_txt else "❌ 없음")
    c6.metric("응답속도", f"{resp_time}초" if resp_time else "-")

    with st.expander("📋 점수 항목별 상세 내역 (클릭해서 펼치기)"):
        for item, (earned, max_pts) in score_detail.items():
            icon = "✅" if earned > 0 else "❌"
            st.markdown(f"{icon} **{item}** — {earned}점 / {max_pts}점")
        st.markdown(f"---\n**합계: {score} / 100점**")
    st.divider()

    # ── 1. robots.txt ──────────────────────────────────
    st.header("1️⃣ robots.txt 분석")
    if robots_err:
        st.error(f"접근 실패: {robots_err}")
    else:
        r1, r2 = st.columns(2)
        with r1:
            st.markdown(f"**URL:** `{domain}/robots.txt`")
            st.markdown(f"**User-agent 블록 수:** {len(blocks)}개")
            sm_ref = sitemap_refs_in_robots[0] if sitemap_refs_in_robots else "❌ 없음"
            st.markdown(f"**Sitemap 참조:** `{sm_ref}`")
            special = extract_special_comments(robots_txt)
            if special:
                st.markdown("**🤖 AI 에이전트 특수 지시어:**")
                for s in special[:6]:
                    st.caption(f"• {s}")
        with r2:
            st.markdown("**AI 크롤러별 허용 상태:**")
            for bot, status, is_specific in bot_statuses:
                if status == 'allowed':   icon, label = "✅", "허용"
                elif status == 'blocked': icon, label = "❌", "차단"
                elif status == 'partial': icon, label = "⚠️", "부분 제한"
                else:                     icon, label = "❓", "규칙 없음"
                spec_tag = " *(개별)*" if is_specific else " *(wildcard)*"
                st.markdown(f"{icon} **{bot}** — {label}{spec_tag}")
        with st.expander("robots.txt 원문"):
            st.code(robots_txt, language="text")
    st.divider()

    # ── 2. llms.txt ────────────────────────────────────
    st.header("2️⃣ llms.txt 분석")
    if llms_err:
        st.warning(f"파일 없음: {llms_err}")
        st.info("llms.txt는 AI 언어모델에게 사이트 정보를 제공하는 표준 파일입니다. → [llmstxt.org](https://llmstxt.org)")
    else:
        lines = llms_txt.splitlines()
        h1 = next((l[2:].strip() for l in lines if l.startswith('# ')), '(H1 없음)')
        h2s = [l[3:].strip() for l in lines if l.startswith('## ')]
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', llms_txt)
        word_count = len(re.findall(r'\w+', llms_txt))

        l1, l2, l3, l4 = st.columns(4)
        l1.metric("총 줄 수", f"{len(lines)}줄")
        l2.metric("섹션(H2) 수", f"{len(h2s)}개")
        l3.metric("링크 수", f"{len(links)}개")
        l4.metric("단어 수", f"{word_count}개")

        st.markdown(f"**H1 제목:** {h1}")
        if h2s:
            st.markdown("**섹션 목록:** " + " · ".join(h2s))

        # 품질 평가
        quality_score = 0
        if len(lines) > 10: quality_score += 1
        if len(h2s) >= 2:   quality_score += 1
        if len(links) >= 3: quality_score += 1
        if word_count > 100: quality_score += 1
        quality_label = ["❌ 매우 부족", "⚠️ 부족", "🟡 보통", "🟢 양호", "✅ 우수"][quality_score]
        st.markdown(f"**llms.txt 품질:** {quality_label}")

        with st.expander("llms.txt 원문"):
            st.code(llms_txt, language="markdown")
    st.divider()

    # ── 3. agents.md ───────────────────────────────────
    st.header("3️⃣ agents.md 분석")
    if agents_err:
        st.warning(f"파일 없음: {agents_err}")
        st.caption("Shopify 스토어의 경우 /agents.md 파일로 AI 쇼핑 에이전트에게 행동 지침을 제공합니다.")
    else:
        lines = agents_txt.splitlines()
        h1 = next((l[2:].strip() for l in lines if l.startswith('# ')), '(H1 없음)')
        h2s = [l[3:].strip() for l in lines if l.startswith('## ')]
        has_ucp = 'ucp' in agents_txt.lower()
        has_mcp = 'mcp' in agents_txt.lower()

        a1, a2, a3, a4 = st.columns(4)
        a1.metric("총 줄 수", f"{len(lines)}줄")
        a2.metric("섹션 수", f"{len(h2s)}개")
        a3.metric("UCP 언급", "✅" if has_ucp else "❌")
        a4.metric("MCP 언급", "✅" if has_mcp else "❌")
        st.markdown(f"**H1 제목:** {h1}")
        with st.expander("agents.md 원문"):
            st.code(agents_txt, language="markdown")
    st.divider()

    # ── 4. UCP ─────────────────────────────────────────
    st.header("4️⃣ UCP (.well-known/ucp) 분석")
    if ucp_err:
        st.warning(f"UCP 미지원: {ucp_err}")
        st.caption("UCP(Universal Commerce Protocol)는 AI 에이전트가 커머스 기능을 API로 이용하는 표준입니다.")
    else:
        try:
            ucp_data = json.loads(ucp_txt)
            u1, u2 = st.columns(2)
            with u1:
                st.markdown(f"**스토어명:** {ucp_data.get('name', '-')}")
                st.markdown(f"**버전:** {ucp_data.get('version', '-')}")
            with u2:
                caps = ucp_data.get('capabilities', [])
                if caps:
                    st.markdown("**지원 기능:**")
                    for c in caps[:6]:
                        st.caption(f"• {c}")
        except:
            st.success("UCP 파일 존재 확인됨")
        with st.expander("UCP 원문"):
            st.code(ucp_txt[:2000], language="json")
    st.divider()

    # ── 5. sitemap.xml ─────────────────────────────────
    st.header("5️⃣ sitemap.xml 분석")
    if sitemap_err:
        st.error(f"접근 실패: {sitemap_err}")
    else:
        s1, s2, s3 = st.columns(3)
        s1.metric("타입", "Sitemap Index" if sitemap_info['type'] == 'index' else "단일 Sitemap")
        s2.metric("URL / 사이트맵 수", f"{sitemap_info['count']}개")
        s3.metric("최근 lastmod", sitemap_info['lastmod'])
        if sitemap_info.get('locs'):
            st.markdown("**포함된 사이트맵 (상위 5개):**")
            for loc in sitemap_info['locs']:
                st.caption(f"• {loc}")
        with st.expander("sitemap.xml 원문 (상위 3000자)"):
            st.code(sitemap_txt[:3000], language="xml")
    st.divider()

    # ── 6. Schema.org JSON-LD ──────────────────────────
    st.header("6️⃣ Schema.org 구조화 데이터 분석")
    if not page:
        st.error("홈페이지 로드 실패")
    elif not page['schemas']:
        st.warning("❌ Schema.org JSON-LD 없음 — AI가 페이지 콘텐츠를 구조적으로 이해하기 어렵습니다.")
        st.caption("추천 스키마 타입: Organization, WebSite, Product, BreadcrumbList")
    else:
        st.success(f"✅ JSON-LD {len(page['schemas'])}개 발견")
        sc1, sc2 = st.columns(2)
        with sc1:
            st.markdown("**발견된 Schema 타입:**")
            for t in page['schema_types']:
                st.caption(f"• {t}")
        with sc2:
            recommended = ['Organization', 'WebSite', 'Product', 'BreadcrumbList', 'FAQPage']
            found_set = set(page['schema_types'])
            st.markdown("**권장 타입 체크:**")
            for r in recommended:
                icon = "✅" if r in found_set else "❌"
                st.caption(f"{icon} {r}")
        with st.expander("JSON-LD 원문"):
            st.code(json.dumps(page['schemas'], indent=2, ensure_ascii=False)[:3000], language="json")
    st.divider()

    # ── 7. OG 태그 / Canonical / 메타데이터 ───────────
    st.header("7️⃣ 메타데이터 분석 (OG태그 · Canonical · Title)")
    if not page:
        st.error("홈페이지 로드 실패")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("og:title", "✅" if 'og:title' in page['og'] else "❌")
        m2.metric("og:description", "✅" if 'og:description' in page['og'] else "❌")
        m3.metric("og:image", "✅" if 'og:image' in page['og'] else "❌")
        m4.metric("Canonical", "✅" if page['canonical'] else "❌")

        if page['title']:
            st.markdown(f"**Title 태그:** {page['title']}")
        if page['description']:
            st.markdown(f"**Meta Description:** {page['description']}")
        if page['canonical']:
            st.markdown(f"**Canonical URL:** `{page['canonical']}`")

        if page['og']:
            with st.expander("OG 태그 전체 목록"):
                for k, v in page['og'].items():
                    st.caption(f"**{k}:** {v[:100]}")
    st.divider()

    # ── 8. hreflang ────────────────────────────────────
    st.header("8️⃣ hreflang 다국어 태그 분석")
    if not page:
        st.error("홈페이지 로드 실패")
    elif not page['hreflangs']:
        st.warning("❌ hreflang 태그 없음 — 다국어 사이트라면 AI가 올바른 언어 버전을 인식하지 못할 수 있습니다.")
    else:
        st.success(f"✅ hreflang 태그 {len(page['hreflangs'])}개 발견")
        h1_col, h2_col = st.columns(2)
        langs = [h['lang'] for h in page['hreflangs']]
        with h1_col:
            st.markdown("**언어 목록:**")
            for h in page['hreflangs'][:10]:
                st.caption(f"• `{h['lang']}` → {h['href'][:60]}")
        with h2_col:
            has_xdefault = any(h['lang'] == 'x-default' for h in page['hreflangs'])
            st.metric("x-default 설정", "✅" if has_xdefault else "❌ 없음")
            st.metric("언어 수", f"{len(langs)}개")
    st.divider()

    # ── 9. 개선 권고사항 ───────────────────────────────
    st.header("💡 개선 권고사항")
    recs = []
    if not robots_txt:
        recs.append(("❌", "robots.txt가 없습니다."))
    if blocked_c > 0:
        names = [b for b, s, _ in bot_statuses if s == 'blocked']
        recs.append(("❌", f"차단된 AI 봇 {blocked_c}개: {', '.join(names)}"))
    if partial_c > 0:
        names = [b for b, s, _ in bot_statuses if s == 'partial']
        recs.append(("⚠️", f"부분 제한 AI 봇 {partial_c}개: {', '.join(names)}"))
    if not llms_txt:
        recs.append(("⚠️", "llms.txt가 없습니다. AI 언어모델의 사이트 이해도를 높이려면 추가를 권장합니다."))
    if not agents_txt:
        recs.append(("⚠️", "agents.md가 없습니다. Shopify 스토어라면 AI 쇼핑 에이전트 지침 파일 추가를 권장합니다."))
    if not ucp_txt:
        recs.append(("⚠️", "UCP(.well-known/ucp)가 없습니다. AI 에이전트 커머스 지원을 위해 추가를 권장합니다."))
    if not sitemap_refs_in_robots:
        recs.append(("⚠️", "robots.txt에 Sitemap 참조가 없습니다."))
    if page and not page['schemas']:
        recs.append(("⚠️", "Schema.org JSON-LD가 없습니다. Organization, Product, BreadcrumbList 추가를 권장합니다."))
    if page and 'og:title' not in page['og']:
        recs.append(("⚠️", "og:title 태그가 없습니다."))
    if page and not page['canonical']:
        recs.append(("⚠️", "Canonical 태그가 없습니다. 중복 콘텐츠 방지를 위해 추가를 권장합니다."))
    if page and not page['hreflangs']:
        recs.append(("⚠️", "hreflang 태그가 없습니다. 다국어 사이트라면 추가를 권장합니다."))
    if page and page['text_ratio'] <= 10:
        recs.append(("⚠️", f"텍스트 비중이 {page['text_ratio']}%로 낮습니다. AI 크롤링에 불리할 수 있습니다."))
    if resp_time >= 3:
        recs.append(("⚠️", f"응답속도 {resp_time}초 — 3초 이상은 크롤링 타임아웃 위험이 있습니다."))
    if not recs:
        recs.append(("✅", "모든 점검 항목 통과! AI 크롤링 및 GEO 설정이 우수합니다."))

    for icon, msg in recs:
        st.markdown(f"{icon} {msg}")
