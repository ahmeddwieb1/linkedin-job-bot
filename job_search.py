import os
import re
import sys
import json
import time
import requests
from datetime import datetime, timedelta
from dotenv import load_dotenv
from bs4 import BeautifulSoup

load_dotenv()

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SEEN_JOBS_FILE    = os.path.join(os.path.dirname(__file__), "seen_jobs.json")
SEEN_JOBS_TTL_DAYS = 7
TOP_N_EGYPT   = 15
TOP_N_EUROPE  = 15
TOP_N_GULF    = 15   # الخليج + الوطن العربي مع بعض
TOP_N_AMERICA = 15
TOP_N_COMPANY = 5

EUROPE_COUNTRY_CODES = {
    "de", "nl", "pl", "ie", "gb", "es", "pt", "fr", "it",
    "se", "ch", "be", "dk", "fi", "no",
}
GULF_ARAB_COUNTRY_CODES = {
    "ae", "sa", "qa", "kw", "bh", "om", "jo", "lb", "iq", "ma", "tn", "dz",
}
AMERICA_COUNTRY_CODES = {"us", "ca"}

# البحث شامل onsite + hybrid + remote (شيلنا فلتر f_WT في search_linkedin)،
# ومحصور في مصر (الأولوية الأولى) وأوروبا. غيّر القايمة دي حسب البلاد
# اللي إنت عايز تشتغل فيها.
LINKEDIN_SEARCHES = [
    # مصر — الأولوية الأولى
    {"keywords": "devops engineer intern",    "location": "Egypt"},
    {"keywords": "junior devops engineer",    "location": "Egypt"},
    {"keywords": "cloud engineer intern",     "location": "Egypt"},
    {"keywords": "junior cloud engineer",     "location": "Egypt"},
    {"keywords": "devops intern",             "location": "Egypt"},
    {"keywords": "cloud support engineer",    "location": "Egypt"},
    {"keywords": "site reliability intern",   "location": "Egypt"},
    {"keywords": "infrastructure engineer",   "location": "Egypt"},
    # أوروبا
    {"keywords": "junior devops engineer",    "location": "Germany"},
    {"keywords": "devops engineer intern",    "location": "Germany"},
    {"keywords": "junior devops engineer",    "location": "Netherlands"},
    {"keywords": "cloud engineer intern",     "location": "Netherlands"},
    {"keywords": "junior devops engineer",    "location": "Poland"},
    {"keywords": "junior cloud engineer",     "location": "Poland"},
    {"keywords": "junior devops engineer",    "location": "Ireland"},
    {"keywords": "junior devops engineer",    "location": "United Kingdom"},
    {"keywords": "junior devops engineer",    "location": "Spain"},
    {"keywords": "junior devops engineer",    "location": "Portugal"},
    {"keywords": "junior devops engineer",    "location": "France"},
    {"keywords": "junior devops engineer",    "location": "Italy"},
    {"keywords": "junior devops engineer",    "location": "Sweden"},
    # الخليج والوطن العربي
    {"keywords": "junior devops engineer",    "location": "United Arab Emirates"},
    {"keywords": "devops engineer intern",    "location": "United Arab Emirates"},
    {"keywords": "cloud engineer intern",     "location": "United Arab Emirates"},
    {"keywords": "junior devops engineer",    "location": "Saudi Arabia"},
    {"keywords": "cloud engineer intern",     "location": "Saudi Arabia"},
    {"keywords": "junior devops engineer",    "location": "Qatar"},
    {"keywords": "junior devops engineer",    "location": "Kuwait"},
    {"keywords": "junior devops engineer",    "location": "Bahrain"},
    {"keywords": "junior devops engineer",    "location": "Oman"},
    {"keywords": "junior devops engineer",    "location": "Jordan"},
    {"keywords": "junior devops engineer",    "location": "Lebanon"},
    {"keywords": "junior devops engineer",    "location": "Morocco"},
    {"keywords": "junior devops engineer",    "location": "Iraq"},
    # أمريكا
    {"keywords": "junior devops engineer",    "location": "United States"},
    {"keywords": "devops engineer intern",    "location": "United States"},
    {"keywords": "cloud engineer intern",     "location": "United States"},
    {"keywords": "junior cloud engineer",     "location": "United States"},
    {"keywords": "junior devops engineer",    "location": "Canada"},
    {"keywords": "cloud engineer intern",     "location": "Canada"},
    {"keywords": "devops intern",             "location": "Worldwide", "remote_only": True},
    {"keywords": "junior devops engineer",    "location": "Worldwide", "remote_only": True},
    {"keywords": "junior cloud engineer",     "location": "Worldwide", "remote_only": True},
]

# بحث في شركات معيّنة — سيبناها فاضية دلوقتي، ضيف شركاتك المستهدفة هنا
# لما تحددها، بنفس الشكل: {"keywords": "Company Name", "location": "Egypt"}.
COMPANY_SEARCHES = [
]

# الوظيفة اللي بتيجي من بحث الشركات لازم يكون في عنوانها كلمة على الأقل من
# دول عشان تتحسب مناسبة.
COMPANY_RELEVANCE_TITLE_WORDS = {
    "devops", "cloud", "infrastructure", "platform", "sre", "reliability",
    "systems", "engineer", "intern", "automation", "backend", "developer",
    "administrator", "support", "security", "network",
}

LINKEDIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

# ── حساب النقط ────────────────────────────────────────────────────────────────

ROLE_SCORES = {
    # أول عنصر هو الوظيفة رقم ١ في الأولوية — دالة score_job() بتاخد أول
    # تطابق في العنوان، يعني الترتيب مهم. حط الوظيفة اللي بتحلم بيها الأول
    # وبأعلى رقم، وخلّي الوظايف القريبة منها عالية بس تحتها.
    "devops intern":          40,
    "cloud intern":           38,
    "junior devops":          38,
    "junior cloud":           36,
    "devops engineer":        34,
    "cloud engineer":         34,
    "cloud support":          28,
    "site reliability":       28,
    "sre engineer":           28,
    "platform engineer":      26,
    "infrastructure engineer": 26,
    "systems engineer":       20,
    "systems administrator":  18,
    "network engineer intern": 18,
    "it intern":              16,
}

SKILL_SCORES = {
    "aws": 20, "terraform": 16, "kubernetes": 16, "docker": 14,
    "ansible": 12, "gitlab": 10, "ci/cd": 10, "cicd": 10, "jenkins": 8,
    "linux": 10, "nginx": 6, "cloudflare": 4,
    "python": 8, "bash": 6, "java": 6, "spring boot": 6,
    "mongodb": 6, "mysql": 6, "redis": 6, "sql": 4, "git": 4,
    "devops": 12, "cloud": 8, "infrastructure as code": 10,
}

LOCATION_SCORES = {
    # مصر — الأولوية الأولى
    "eg": 26, "egypt": 26, "cairo": 26, "alexandria": 26, "giza": 26,
    # أوروبا
    "germany": 18, "berlin": 18, "munich": 18,
    "netherlands": 18, "amsterdam": 18,
    "poland": 18, "warsaw": 18,
    "ireland": 18, "dublin": 18,
    "united kingdom": 18, "uk": 18, "london": 18,
    "spain": 18, "madrid": 18, "barcelona": 18,
    "portugal": 18, "lisbon": 18,
    "france": 18, "paris": 18,
    "italy": 18, "milan": 18, "rome": 18,
    "sweden": 18, "stockholm": 18,
    "switzerland": 18, "zurich": 18,
    "belgium": 18, "brussels": 18,
    # الخليج والوطن العربي
    "united arab emirates": 18, "uae": 18, "dubai": 18, "abu dhabi": 18,
    "saudi arabia": 18, "riyadh": 18, "jeddah": 18,
    "qatar": 18, "doha": 18,
    "kuwait": 18, "bahrain": 18, "oman": 18, "muscat": 18,
    "jordan": 18, "amman": 18,
    "lebanon": 18, "beirut": 18,
    "morocco": 18, "iraq": 18,
    # أمريكا
    "united states": 18, "usa": 18, "canada": 18,
    "worldwide": 12, "global": 12,
    "remote": 10, "hybrid": 8,
}

TARGET_COMPANIES = [
]

LOCATION_CODE_MAP = {
    "united arab emirates": "ae", "uae": "ae", "dubai": "ae", "abu dhabi": "ae",
    "saudi arabia": "sa", "riyadh": "sa", "jeddah": "sa",
    "egypt": "eg", "cairo": "eg",
    "qatar": "qa", "doha": "qa",
    "kuwait": "kw", "bahrain": "bh",
    "oman": "om", "muscat": "om",
    "jordan": "jo", "amman": "jo",
    "lebanon": "lb", "beirut": "lb",
    "iraq": "iq", "baghdad": "iq",
    "morocco": "ma", "casablanca": "ma", "rabat": "ma",
    "tunisia": "tn", "tunis": "tn",
    "algeria": "dz", "algiers": "dz",
    "worldwide": "global",
    "united kingdom": "gb", "ireland": "ie",
    "germany": "de", "france": "fr", "netherlands": "nl",
    "spain": "es", "portugal": "pt", "italy": "it", "poland": "pl",
    "belgium": "be", "switzerland": "ch",
    "denmark": "dk", "finland": "fi", "sweden": "se", "norway": "no",
    "united states": "us", "usa": "us",
    "canada": "ca",
}


def infer_country_code(location: str) -> str:
    loc = location.lower()
    for k, v in LOCATION_CODE_MAP.items():
        if k in loc:
            return v
    return "global"


def score_job(job: dict) -> int:
    title   = (job.get("job_title") or "").lower()
    desc    = (job.get("job_description") or "")[:500].lower()
    city    = (job.get("job_city") or "").lower()
    country = (job.get("job_country") or "").lower()
    company = (job.get("employer_name") or "").lower()
    is_remote = job.get("job_is_remote", False)

    score = 0
    for kw, pts in ROLE_SCORES.items():
        if kw in title:
            score += pts
            break
    skill_pts = sum(pts for kw, pts in SKILL_SCORES.items() if kw in title + " " + desc)
    score += min(skill_pts, 30)
    loc_hay = f"{city} {country}" + (" remote" if is_remote else "")
    for loc, pts in LOCATION_SCORES.items():
        if loc in loc_hay:
            score += pts
            break
    if any(name in company for name in TARGET_COMPANIES):
        score += 10
    if is_remote:
        score += 8
    elif any(w in title for w in ("hybrid", "remote")):
        score += 5
    return score


def score_label(score: int) -> str:
    if score >= 60: return "Excellent match"
    if score >= 45: return "Strong match"
    if score >= 30: return "Good match"
    return "Possible match"


# ── المنافسة (عدد المتقدمين) ──────────────────────────────────────────────────
# الوظايف اللي عليها متقدمين أقل بتاخد أولوية أعلى — دي أسهل حاجة فعلاً
# تتقبل فيها. عدد المتقدمين بيتجاب بس لأعلى الوظايف في كل مجموعة
# (APPLICANT_FETCH_LIMIT)، عشان عدد الطلبات الزيادة على لينكدإن يفضل محدود.

APPLICANT_FETCH_LIMIT = 15


def fetch_applicant_count(url: str) -> int | None:
    if not url:
        return None
    try:
        resp = requests.get(url, headers=LINKEDIN_HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        m = re.search(r'([\d,]+)\+?\s*(?:applicants|people clicked apply)', resp.text, re.I)
        if m:
            return int(m.group(1).replace(",", ""))
    except requests.RequestException:
        pass
    return None


def applicant_bonus(count: int | None) -> int:
    if count is None:
        return 0
    if count <= 10:
        return 20
    if count <= 25:
        return 14
    if count <= 50:
        return 8
    if count <= 100:
        return 2
    return -8  # heavily-applied jobs are deprioritized, not just unboosted


def enrich_with_competition(jobs: list) -> list:
    """بيجيب عدد المتقدمين لأعلى الوظايف نقط في المجموعة، بيضيف بونص
    المنافسة القليلة على النتيجة النهائية، وبعدين بيعيد ترتيب المجموعة
    كلها حسب النتيجة دي."""
    ranked = sorted(jobs, key=score_job, reverse=True)
    top, rest = ranked[:APPLICANT_FETCH_LIMIT], ranked[APPLICANT_FETCH_LIMIT:]
    for job in top:
        count = fetch_applicant_count(job.get("job_apply_link"))
        job["_applicants"] = count
        job["_score"] = score_job(job) + applicant_bonus(count)
        time.sleep(0.3)
    for job in rest:
        job["_applicants"] = None
        job["_score"] = score_job(job)
    return sorted(top + rest, key=lambda j: j["_score"], reverse=True)


# ── سحب البيانات من لينكدإن ───────────────────────────────────────────────────

def parse_card(card, search_location: str) -> dict | None:
    link_tag = card.find("a", class_="base-card__full-link")
    if not link_tag:
        return None
    raw_url = link_tag.get("href", "")
    # بيسيب لينك لينكدإن نضيف (بيشيل باراميترز التتبّع اللي بعد ?)
    apply_url = raw_url.split("?")[0] if raw_url else ""
    match = re.search(r"-(\d{8,})$", apply_url)
    job_id = f"li_{match.group(1)}" if match else None
    if not job_id:
        return None

    title_tag   = card.find("h3", class_="base-search-card__title")
    company_tag = card.find("h4", class_="base-search-card__subtitle")
    loc_tag     = card.find("span", class_="job-search-card__location")

    title    = (title_tag.get_text(strip=True)   if title_tag   else "").strip()
    company  = (company_tag.get_text(strip=True) if company_tag else "").strip()
    location = (loc_tag.get_text(strip=True)     if loc_tag     else search_location).strip()

    # مفيش فلتر f_WT دلوقتي، يعني النتايج فيها onsite + hybrid + remote
    # مع بعض. بنحدد النوع من نص العنوان/المكان لأن لينكدإن الـ guest API
    # مابيرجعش badge صريح لنوع الشغل.
    hay = f"{title} {location}".lower()
    is_remote = "remote" in hay

    return {
        "job_id":        job_id,
        "job_title":     title,
        "employer_name": company,
        "job_city":      location,
        "job_country":   search_location,
        "_search_country": infer_country_code(search_location),
        "job_is_remote": is_remote,
        "job_apply_link": apply_url,
        "job_description": "",
        "apply_options": [{"apply_link": apply_url, "is_direct": False, "publisher": "LinkedIn"}],
    }


def search_linkedin(keywords: str, location: str, remote_only: bool = False) -> list:
    url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    params = {
        "keywords": keywords,
        "f_TPR":    "r259200",  # last 3 days
        "start":    0,
        # مفيش f_WT هنا خالص — يعني النتايج بتشمل onsite + hybrid + remote.
        # لو حبيت ترجع تحصر النتايج على ريموت بس، رجّع "f_WT": "2".
    }
    if remote_only:
        # من غير فلتر بلد — بيدوّر في كل الدول بدل قايمة
        # الخليج/مصر/أوروبا المحدودة.
        params["location"] = ""
    else:
        params["location"] = location
    try:
        resp = requests.get(url, headers=LINKEDIN_HEADERS, params=params, timeout=15)
        if resp.status_code != 200:
            print(f"Warning: LinkedIn returned {resp.status_code} for '{keywords}' / {location}")
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        for card in soup.find_all("li"):
            job = parse_card(card, location)
            if job:
                jobs.append(job)
        return jobs
    except requests.RequestException as e:
        print(f"Warning: LinkedIn search failed for '{keywords}': {e}")
        return []


# ── تليجرام ───────────────────────────────────────────────────────────────────

def esc(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_job(rank: int, job: dict) -> str:
    title      = esc(job.get("job_title") or "N/A")
    company    = esc(job.get("employer_name") or "N/A")
    location   = esc(job.get("job_city") or job.get("job_country") or "Unknown")
    is_remote  = job.get("job_is_remote", False)
    is_target  = job.get("_company_match", False)
    score      = job.get("_score", score_job(job))
    applicants = job.get("_applicants")

    title_lower = (job.get("job_title") or "").lower()
    if "hybrid" in title_lower or "hybrid" in location.lower():
        work_mode = "Hybrid"
    elif is_remote or "remote" in title_lower:
        work_mode = "Remote"
    else:
        work_mode = location

    apply_url  = job.get("job_apply_link") or ""
    safe_url   = apply_url.replace("&", "&amp;")
    apply_part = f' | <a href="{safe_url}">Apply on LinkedIn</a>' if safe_url else ""
    badge      = " [TARGET CO.]" if is_target else ""
    if applicants is None:
        competition = ""
    elif applicants <= 25:
        competition = f" | {applicants} applicants (low competition)"
    else:
        competition = f" | {applicants} applicants"

    return (
        f"<b>#{rank} {title}</b>{badge}\n"
        f"{company} | {work_mode}\n"
        f"<i>{score_label(score)} ({score} pts)</i>{competition}{apply_part}"
    )


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    lines = text.split("\n")
    chunks, current = [], ""
    for line in lines:
        candidate = current + line + "\n"
        if len(candidate) > 4000:
            if current:
                chunks.append(current.rstrip())
            current = line + "\n"
        else:
            current = candidate
    if current.strip():
        chunks.append(current.rstrip())
    for chunk in chunks:
        try:
            resp = requests.post(url, json={
                "chat_id":   TELEGRAM_CHAT_ID,
                "text":      chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }, timeout=15)
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"Error sending Telegram message: {e}")


# ── حفظ الذاكرة ───────────────────────────────────────────────────────────────

def check_config():
    missing = [k for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID")
               if not os.getenv(k) or "your_" in os.getenv(k)]
    if missing:
        print(f"ERROR: Missing values in .env: {', '.join(missing)}")
        sys.exit(1)


def load_seen_jobs() -> dict:
    if not os.path.exists(SEEN_JOBS_FILE):
        return {}
    with open(SEEN_JOBS_FILE, "r") as f:
        data = json.load(f)
    cutoff = (datetime.now() - timedelta(days=SEEN_JOBS_TTL_DAYS)).isoformat()
    return {jid: ts for jid, ts in data.items() if ts >= cutoff}


def save_seen_jobs(seen: dict):
    with open(SEEN_JOBS_FILE, "w") as f:
        json.dump(seen, f)


# ── الدالة الرئيسية ───────────────────────────────────────────────────────────

def main():
    check_config()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting LinkedIn job search...")

    seen = load_seen_jobs()
    this_run_ids: set = set()
    general_jobs: list = []
    company_jobs: list = []

    # ── الجولة ١: البحث العام عن الوظايف ──────────────────────────────────────
    print("--- General searches ---")
    for s in LINKEDIN_SEARCHES:
        jobs = search_linkedin(s["keywords"], s["location"], s.get("remote_only", False))
        kept = 0
        for job in jobs:
            job_id = job.get("job_id")
            if not job_id or job_id in seen or job_id in this_run_ids:
                continue
            this_run_ids.add(job_id)
            general_jobs.append(job)
            kept += 1
        print(f"  '{s['keywords']}' / {s['location']} -> {kept} new")

    # ── الجولة ٢: البحث في الشركات المستهدفة ──────────────────────────────────
    print("--- Target company searches ---")
    for s in COMPANY_SEARCHES:
        jobs = search_linkedin(s["keywords"], s["location"])
        kept = 0
        for job in jobs:
            job_id = job.get("job_id")
            if not job_id or job_id in seen or job_id in this_run_ids:
                continue
            # فلترة — بيسيب بس الوظايف اللي ليها علاقة بمجالك
            title_words = set((job.get("job_title") or "").lower().split())
            if not title_words & COMPANY_RELEVANCE_TITLE_WORDS:
                continue
            job["_company_match"] = True
            this_run_ids.add(job_id)
            company_jobs.append(job)
            kept += 1
        print(f"  '{s['keywords']}' / {s['location']} -> {kept} relevant")

    print(f"General: {len(general_jobs)} | Company: {len(company_jobs)}")

    all_new = general_jobs + company_jobs
    if not all_new:
        send_telegram(
            "<b>Daily Job Report - " + datetime.now().strftime("%b %d, %Y") + "</b>\n"
            "No new LinkedIn jobs since last run. Check back tomorrow!"
        )
    else:
        # بيجيب عدد المتقدمين لأعلى وظايف كل مجموعة (بونص المنافسة
        # القليلة)، بيعيد الترتيب، وبعدين بيقسّم الوظايف حسب المنطقة
        # (مصر / أوروبا) قبل ما ياخد أحسن ١٥ من كل واحدة.
        general_jobs = enrich_with_competition(general_jobs)
        company_jobs = enrich_with_competition(company_jobs)

        egypt_jobs   = [j for j in general_jobs if j.get("_search_country") == "eg"]
        europe_jobs  = [j for j in general_jobs if j.get("_search_country") in EUROPE_COUNTRY_CODES]
        gulf_jobs    = [j for j in general_jobs if j.get("_search_country") in GULF_ARAB_COUNTRY_CODES]
        america_jobs = [j for j in general_jobs if j.get("_search_country") in AMERICA_COUNTRY_CODES]
        placed = egypt_jobs + europe_jobs + gulf_jobs + america_jobs
        other_jobs   = [j for j in general_jobs if j not in placed]

        top_egypt   = egypt_jobs[:TOP_N_EGYPT]
        top_europe  = europe_jobs[:TOP_N_EUROPE]
        top_gulf    = gulf_jobs[:TOP_N_GULF]
        top_america = america_jobs[:TOP_N_AMERICA]
        top_other   = other_jobs[:5]
        top_company = company_jobs[:TOP_N_COMPANY]

        date_str = datetime.now().strftime("%b %d, %Y")
        lines = [
            f"<b>Daily Job Report - {date_str}</b>\n"
            f"Onsite + Hybrid + Remote | Egypt, Europe, Gulf & Arab World, "
            f"America | LinkedIn only\n"
        ]

        sections = [
            ("-- Egypt --", top_egypt),
            ("-- Europe --", top_europe),
            ("-- Gulf & Arab World --", top_gulf),
            ("-- America --", top_america),
            ("-- Worldwide Remote --", top_other),
            ("-- Target Company Openings --", top_company),
        ]
        for header, jobs in sections:
            if not jobs:
                continue
            lines.append(f"<b>{header}</b>")
            lines.append("")
            for i, job in enumerate(jobs, 1):
                lines.append(format_job(i, job))
                lines.append("")

        send_telegram("\n".join(lines))
        print(
            f"Telegram sent: {len(top_egypt)} Egypt + {len(top_europe)} Europe "
            f"+ {len(top_gulf)} Gulf/Arab + {len(top_america)} America "
            f"+ {len(top_other)} worldwide + {len(top_company)} company matches."
        )

    now_iso = datetime.now().isoformat()
    for job_id in this_run_ids:
        seen[job_id] = now_iso
    save_seen_jobs(seen)


if __name__ == "__main__":
    main()