import streamlit as st
import requests
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

st.set_page_config(page_title="AI Crawling Geo Checker", layout="wide")
st.title("🤖 AI 크롤링 & Geo 점검 리포트")
st.caption("robots.txt · llms.txt · agents.md · sitemap.xml 종합 분석 — sanghee kim")
st.markdown("---")

url = st.text_input("진단할 사이트 주소 (https:// 필수)", "https://")

AI_BOTS = [
    "GPTBot", "ChatGPT-User", "ClaudeBot", "anthropic-ai",
    "Google-Extended", "PerplexityBot", "cohere-ai",
    "Applebot-Extended", "Amazonbot", "Meta-ExternalAgent",
    "Bytespider", "Diffbot", "CCBot", "DataForSeoBot",
]

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; GeoChecker/1.0)"}

def safe_fetch(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.text, None
        return None, f"HTTP {r.status_code}"
    except Exception as e:
        return None, str(e)

def parse_robots(txt):
    """
    robots.txt를 파싱해 user-agent별 allow/disallow 규칙과 sitemap 목록을 반환.
    빈 줄을 만나면 현재 블록 종료 (표준 동작).
    """
    blocks = []   # [{'agents': [...], 'allow': [...], 'disallow': [...]}]
    cur = None
    sitemap_refs = []

    for line in txt.splitlines():
        raw = line.strip()
        low = raw.lower()

        # 빈 줄 → 현재 블록 종료
        if not raw:
            cur = None
            continue

        # 주석 스킵
        if raw.startswith('#'):
            continue

        if low.startswith('sitemap:'):
            sitemap_refs.append(raw[8:].strip())
            continue

        if low.startswith('user-agent:'):
            ua = raw[11:].strip()
            # 연속된 user-agent 라인이면 같은 블록에 추가
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

def find_block(bot_name, blocks):
    """특정 봇에 적용될 블록 반환. specific 우선, 없으면 wildcard."""
    key = bot_name.lower()
    specific = next((b for b in blocks if key in [a.lower() for a in b['agents']]), None)
    wildcard = next((b for b in blocks if '*' in b['agents']), None)
    return specific, wildcard

def check_bot_status(bot_name, blocks):
    """
    허용/차단/부분/불명 판단 로직:
    - Allow: / 가 있으면 → 루트 전체 허용 (일부 Disallow는 정상적인 제외) → allowed
    - Disallow: / 또는 /* 있고 Allow: / 없음 → blocked
    - Disallow 일부만 있고 Allow: / 없음 → partial
    - 규칙 없음 → unknown
    """
    specific, wildcard = find_block(bot_name, blocks)
    has_specific = specific is not None
    active = specific or wildcard

    if not active:
        return 'unknown', False

    al = active['allow']
    dis = active['disallow']

    # Allow: / 또는 Allow: (빈값) → 루트 전체 허용
    root_allowed = any(a in ('/', '') for a in al)
    if root_allowed:
        return 'allowed', has_specific

    # Disallow: / 또는 /* → 전체 차단
    root_blocked = any(d in ('/', '/*') for d in dis)
    if root_blocked:
        return 'blocked', has_specific

    # Disallow 없거나 모두 빈값 → 허용
    if not dis or all(d == '' for d in dis):
        return 'allowed', has_specific

    # 일부 경로만 Disallow → 부분 제한
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

def extract_special_comments(txt):
    special_keys = ['agents.md', 'ucp', 'mcp', 'skill.md', 'bots@']
    return [
        l.strip()[1:].strip()
        for l in txt.splitlines()
        if l.strip().startswith('#') and any(k in l.lower() for k in special_keys)
    ]

def score_color(s):
    if s >= 70: return "🟢"
    if s >= 40: return "🟡"
    return "🔴"

if st.button("🔍 종합 점검 시작"):
    if not url.startswith("http"):
        st.warning("https:// 로 시작하는 주소를 입력해주세요.")
        st.stop()

    base = url.rstrip('/')
    parsed = urlparse(base)
    domain = f"{parsed.scheme}://{parsed.netloc}"

    with st.spinner("robots.txt · llms.txt · agents.md · sitemap.xml 분석 중..."):
        robots_txt, robots_err = safe_fetch(domain + "/robots.txt")
        llms_txt,   llms_err   = safe_fetch(domain + "/llms.txt")
        agents_txt, agents_err = safe_fetch(domain + "/agents.md")
        sitemap_txt, sitemap_err = safe_fetch(domain + "/sitemap.xml")

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

        sitemap_info = None
        if sitemap_txt:
            sitemap_info = parse_sitemap(sitemap_txt)

        # 점수 계산
        score = 0
        if robots_txt:                                    score += 25
        if llms_txt:                                      score += 25
        if sitemap_txt:                                   score += 15
        if agents_txt:                                    score += 15
        if blocked_c == 0 and partial_c == 0:             score += 10
        elif blocked_c == 0:                              score += 5
        if sitemap_refs_in_robots:                        score += 5
        if sitemap_info and sitemap_info['count'] > 0:    score += 5

    # ── 종합 요약 ──────────────────────────────────────
    st.header("📊 종합 요약")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(f"{score_color(score)} 종합 점수", f"{score} / 100")
    c2.metric("✅ AI 봇 허용", f"{allowed_c} / {len(AI_BOTS)}")
    c3.metric("❌ AI 봇 차단", f"{blocked_c} / {len(AI_BOTS)}")
    c4.metric("⚠️ 부분 제한", f"{partial_c} / {len(AI_BOTS)}")
    c5.metric("llms.txt", "✅ 있음" if llms_txt else "❌ 없음")
    st.divider()

    # ── robots.txt ─────────────────────────────────────
    st.header("1️⃣ robots.txt 분석")
    if robots_err:
        st.error(f"robots.txt 접근 실패: {robots_err}")
    else:
        r1, r2 = st.columns([1, 1])
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
                if status == 'allowed':
                    icon, label = "✅", "허용"
                elif status == 'blocked':
                    icon, label = "❌", "차단"
                elif status == 'partial':
                    icon, label = "⚠️", "부분 제한"
                else:
                    icon, label = "❓", "규칙 없음"
                spec_tag = " *(개별 규칙 적용)*" if is_specific else " *(wildcard 적용)*"
                st.markdown(f"{icon} **{bot}** — {label}{spec_tag}")

        with st.expander("robots.txt 원문 보기"):
            st.code(robots_txt, language="text")

    st.divider()

    # ── llms.txt ───────────────────────────────────────
    st.header("2️⃣ llms.txt 분석")
    if llms_err:
        st.warning(f"llms.txt 없음: {llms_err}")
        st.info("llms.txt는 AI 언어모델에게 사이트 정보를 제공하는 표준 파일입니다. → [llmstxt.org](https://llmstxt.org)")
    else:
        lines = llms_txt.splitlines()
        h1 = next((l[2:].strip() for l in lines if l.startswith('# ')), '(H1 없음)')
        h2s = [l[3:].strip() for l in lines if l.startswith('## ')]
        links = re.findall(r'\[([^\]]+)\]\(([^)]+)\)', llms_txt)

        l1, l2, l3 = st.columns(3)
        l1.metric("총 줄 수", f"{len(lines)}줄")
        l2.metric("섹션(H2) 수", f"{len(h2s)}개")
        l3.metric("링크 수", f"{len(links)}개")

        st.markdown(f"**H1 제목:** {h1}")
        if h2s:
            st.markdown("**섹션 목록:** " + " · ".join(h2s))
        if links:
            st.markdown("**포함된 링크 (상위 5개):**")
            for name, href in links[:5]:
                st.caption(f"• [{name}]({href})")

        with st.expander("llms.txt 원문 보기"):
            st.code(llms_txt, language="markdown")

    st.divider()

    # ── agents.md ──────────────────────────────────────
    st.header("3️⃣ agents.md 분석")
    if agents_err:
        st.warning(f"agents.md 없음: {agents_err}")
        st.caption("Shopify 스토어의 경우 /agents.md 파일로 AI 쇼핑 에이전트에게 행동 지침을 제공합니다.")
    else:
        lines = agents_txt.splitlines()
        h1 = next((l[2:].strip() for l in lines if l.startswith('# ')), '(H1 없음)')
        st.markdown(f"**H1 제목:** {h1}")
        st.metric("총 줄 수", f"{len(lines)}줄")
        with st.expander("agents.md 원문 보기"):
            st.code(agents_txt, language="markdown")

    st.divider()

    # ── sitemap.xml ────────────────────────────────────
    st.header("4️⃣ sitemap.xml 분석")
    if sitemap_err:
        st.error(f"sitemap.xml 접근 실패: {sitemap_err}")
    else:
        s1, s2, s3 = st.columns(3)
        s1.metric("타입", "Sitemap Index" if sitemap_info['type'] == 'index' else "단일 Sitemap")
        s2.metric("URL / 사이트맵 수", f"{sitemap_info['count']}개")
        s3.metric("최근 lastmod", sitemap_info['lastmod'])

        if sitemap_info.get('locs'):
            st.markdown("**포함된 사이트맵 (상위 5개):**")
            for loc in sitemap_info['locs']:
                st.caption(f"• {loc}")

        if sitemap_info['type'] == 'error':
            st.warning(f"XML 파싱 오류: {sitemap_info.get('error', '')}")

        with st.expander("sitemap.xml 원문 보기 (상위 3000자)"):
            st.code(sitemap_txt[:3000], language="xml")

    st.divider()

    # ── 개선 권고사항 ──────────────────────────────────
    st.header("💡 개선 권고사항")
    recs = []
    if not robots_txt:
        recs.append(("❌", "robots.txt가 없습니다. 반드시 생성하세요."))
    if blocked_c > 0:
        blocked_names = [b for b, s, _ in bot_statuses if s == 'blocked']
        recs.append(("❌", f"차단된 AI 봇 {blocked_c}개: {', '.join(blocked_names)}"))
    if partial_c > 0:
        partial_names = [b for b, s, _ in bot_statuses if s == 'partial']
        recs.append(("⚠️", f"부분 제한 AI 봇 {partial_c}개: {', '.join(partial_names)} — 주요 경로 허용 여부 확인 필요"))
    if not llms_txt:
        recs.append(("⚠️", "llms.txt가 없습니다. AI 언어모델의 사이트 이해도를 높이려면 추가를 권장합니다."))
    if not agents_txt:
        recs.append(("⚠️", "agents.md가 없습니다. Shopify 스토어라면 AI 쇼핑 에이전트 지침 파일 추가를 권장합니다."))
    if not sitemap_refs_in_robots:
        recs.append(("⚠️", "robots.txt에 Sitemap 참조가 없습니다. `Sitemap: https://...` 라인을 추가하세요."))
    if sitemap_info and sitemap_info['count'] == 0:
        recs.append(("⚠️", "sitemap.xml에 URL이 없습니다. 확인이 필요합니다."))
    if not recs:
        recs.append(("✅", "주요 점검 항목 모두 통과! AI 크롤링 설정이 잘 되어 있습니다."))

    for icon, msg in recs:
        st.markdown(f"{icon} {msg}")
