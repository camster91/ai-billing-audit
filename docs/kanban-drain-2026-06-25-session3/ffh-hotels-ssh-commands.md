# ffh-hotels — 7 SSH-only tasks, one-command runbook

All 7 tasks require SSH access to ffh-hotels production / staging.
This runbook gives Cam (or an SSH-capable agent) the exact commands.

---

## Task `t_dec4c7a9` — Verify staging robots.txt blocks Googlebot

**Host:** staging — peru-dotterel-980473.hostingersite.com
**Goal:** Confirm Googlebot is disallowed.

```bash
# SSH in
ssh staging_user@peru-dotterel-980473.hostingersite.com  # or via ashbi-hostinger profile

# Find the webroot
find /home/*/domains/peru-dotterel-980473.hostingersite.com -name robots.txt 2>/dev/null
# Common paths:
ROBOTS=/home/u633679196/domains/peru-dotterel-980473.hostingersite.com/public_html/robots.txt

# Read it
cat "$ROBOTS"
# Required content:
#   User-agent: Googlebot
#   Disallow: /
# (plus optionally Allow: /.well-known/ for sitemap verification)

# If missing or wrong, add the block (append if file has other rules):
echo -e "\nUser-agent: Googlebot\nDisallow: /" >> "$ROBOTS"

# Confirm
grep -A1 -B1 -i 'googlebot' "$ROBOTS"
# Expected:
#   User-agent: Googlebot
#   Disallow: /
```

**Accept:** Path documented, Googlebot block present, timestamp noted.

---

## Task `t_33b5cfd0` — SSH-verify H1 architecture on template 765 + newsletter widgets

**Host:** production (TBD — get from Cam's ashbi-hostinger config)
**Goal:** Confirm template 765 has a `theme-post-title` widget with H1, and all newsletter widgets use H2.

```bash
# SSH to prod
ssh prod_user@HOST  # populate from ~/.ssh/config or ashbi-hostinger profile

# 1. Find all posts/pages using template 765
wp db query "
  SELECT p.ID, p.post_title, p.post_type
  FROM wp_posts p
  INNER JOIN wp_postmeta m ON p.ID = m.post_id
  WHERE m.meta_key = '_wp_page_template'
    AND m.meta_value LIKE '%765%';
" --allow-root

# 2. Check each one's elementor_data for theme-post-title with header_size=h1
for pid in $(wp db query "SELECT post_id FROM wp_postmeta WHERE meta_key='_wp_page_template' AND meta_value LIKE '%765%'" --allow-root -s -N); do
  echo "=== Post $pid ==="
  wp post meta get "$pid" _elementor_data --allow-root | \
    python3 -c "import json,sys; d=json.loads(sys.stdin.read()); \
    [print(f'  widget={w[\"widgetType\"]} header_size={w[\"settings\"].get(\"header_size\",\"?\")}') \
     for w in d if w.get('widgetType')=='theme-post-title']"
done

# 3. Scan ALL elementor_data for newsletter widgets
wp db query "
  SELECT p.ID, p.post_title, pm.meta_value
  FROM wp_posts p
  INNER JOIN wp_postmeta pm ON p.ID = pm.post_id
  WHERE pm.meta_key = '_elementor_data'
" --allow-root -s | python3 -c "
import sys, json, re
total = h1 = h2 = other = 0
for line in sys.stdin:
    parts = line.split('\t', 2)
    if len(parts) < 3: continue
    pid, title, data = parts
    try:
        d = json.loads(data)
    except: continue
    for w in d:
        wtype = w.get('widgetType','')
        if any(n in wtype.lower() for n in ['newsletter','subscribe','email']):
            total += 1
            sz = w.get('settings',{}).get('header_size','?')
            if sz == 'h1': h1 += 1
            elif sz == 'h2': h2 += 1
            else: other += 1
print(f'Total newsletter widgets: {total}')
print(f'  H1: {h1}')
print(f'  H2: {h2}  (target: 100%)')
print(f'  Other: {other}')
"
```

**Accept:** All template-765 pages have theme-post-title=h1, all newsletter widgets report h2.

---

## Task `t_677c498a` — SSH-fix broken links (editorial card date 404s, share-button self-links, /contact-us/ empty social hrefs)

**Host:** production
**Goal:** Patch `_elementor_data` JSON to fix 3 classes of broken links.

```bash
ssh prod_user@HOST
cd /home/u633679196/domains/ffh.com/public_html  # adjust to real path

# 1. Find editorial cards with date 404s (usually missing 'YYYY/MM/' prefix)
wp db query "
  SELECT p.ID, p.post_title
  FROM wp_posts p
  INNER JOIN wp_postmeta pm ON p.ID = pm.post_id
  WHERE pm.meta_key = '_elementor_data'
    AND pm.meta_value LIKE '%\"post_date_link\"%'
" --allow-root

# 2. Find /contact-us/ empty social hrefs
wp post meta get $(wp post id --allow-root --path=/contact-us/ 2>/dev/null || \
  wp db query "SELECT ID FROM wp_posts WHERE post_name='contact-us' AND post_type='page'" --allow-root -s -N) \
  _elementor_data --allow-root | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
for w in d:
    if w.get('widgetType') == 'social-icons':
        for icon in w.get('settings',{}).get('social_icon_list',[]):
            if not icon.get('social_url',{}).get('url'):
                print(f'Empty social URL: {icon}')
"

# 3. Find share-button self-links (link to current page)
wp db query "
  SELECT p.ID, p.post_title, pm.meta_value
  FROM wp_posts p
  INNER JOIN wp_postmeta pm ON p.ID = pm.post_id
  WHERE pm.meta_key = '_elementor_data'
    AND pm.meta_value LIKE '%\"share_buttons\"%'
" --allow-root | python3 -c "
import sys, json, re
for line in sys.stdin:
    parts = line.split('\t', 2)
    if len(parts) < 3: continue
    pid, title, data = parts
    if json.loads(data).__repr__().count(re.escape(title)) > 2:
        print(f'Post {pid} ({title}): share buttons may self-link')
"

# Patches (do these via WP-CLI after audit, NOT as a bulk sed):
# 1. Editorial card date: regenerate the permalink in Elementor
#    (Elementor uses post permalink dynamically, so often the issue is a static URL field)
# 2. Empty social hrefs: edit page in Elementor → social widget → fill in URLs
# 3. Share-button self-links: same — edit page in Elementor
```

**Accept:** All 3 categories fixed, `curl -I` on 10 sample URLs returns expected codes.

---

## Task `t_02be9166` — SSH-triage Markup.io comments older than 1 week

**Host:** production (DB access)
**Goal:** Pull all unresolved Markup.io comments >7 days old, group by page.

```bash
ssh prod_user@HOST
cd /home/u633679196/domains/ffh.com/public_html

# Find markup_pin post type entries
wp post list --post_type=markup_pin --post_status=any \
  --date_query='before=1 week ago' --format=csv --allow-root | head -50

# Or via direct DB:
wp db query "
  SELECT p.ID, p.post_title, p.post_date, p.post_status,
         pm.meta_value AS pin_url,
         pm2.meta_value AS resolved
  FROM wp_posts p
  LEFT JOIN wp_postmeta pm ON p.ID = pm.post_id AND pm.meta_key='markup_url'
  LEFT JOIN wp_postmeta pm2 ON p.ID = pm.post_id AND pm.meta_key='markup_resolved'
  WHERE p.post_type = 'markup_pin'
    AND p.post_date < DATE_SUB(NOW(), INTERVAL 7 DAY)
    AND (pm2.meta_value IS NULL OR pm2.meta_value = '0')
  ORDER BY p.post_date ASC;
" --allow-root

# Triage output: for each pin, decide resolve / archive / escalate
# Group by page (extract page URL from pin_url), count per page
```

**Accept:** Triage list of N unresolved pins >7 days, grouped by page, with action per pin.

---

## Task `t_alex_p0_rankmath_reactivate` — Rank Math deactivate/reactivate

**Host:** production
**Goal:** Clear RankMath's runtime cache by deactivating + reactivating.

```bash
ssh prod_user@HOST
cd /home/u633679196/domains/ffh.com/public_html

# 1. Deactivate
wp plugin deactivate rank-math/rank-math.php --allow-root

# 2. Wait 5 seconds (let the autoloader drop the class)
sleep 5

# 3. Reactivate
wp plugin activate rank-math/rank-math.php --allow-root

# 4. Verify JSON-LD and OG tags appear on a hotel single page
hotel_id=$(wp post list --post_type=hotel --posts_per_page=1 --field=ID --allow-root)
curl -s "https://ffh.com/hotel/$(wp post list --post_type=hotel --posts_per_page=1 --field=slug --allow-root)/" \
  | grep -E '<script type="application/ld\+json"|<meta property="og:'

# Expected: at least 1 ld+json script (Hotel schema) + og:title, og:description, og:image
```

**Accept:** JSON-LD present, OG tags present, sitemap regenerated.

**Caveat:** This clears any Rank Math custom redirects / schema overrides that were set in the UI. Confirm with Alex that no destructive changes were made in the last 7 days.

---

## Task `t_alex_long_important_count` — Refactor 195 `!important` declarations

**Host:** local repo (theme files)
**Goal:** Reduce `!important` count in `design-overrides.css` from 195 toward <50.

```bash
cd /Users/biancabienaime/projects/ffh-hotel-design/  # adjust to real path

# 1. Audit current !important declarations
grep -n '!important' design-overrides.css | wc -l
# Confirm: 195

# 2. Group by selector specificity
grep -n '!important' design-overrides.css | \
  python3 -c "
import sys
from collections import Counter
counts = Counter()
for line in sys.stdin:
    selector = line.split('{')[0].strip().rstrip(',')
    counts[selector] += 1
for sel, n in counts.most_common(30):
    print(f'  {n:3}  {sel}')
"

# 3. Strategy:
#    - Group A: overrides that exist because a plugin sets !important
#      → wrap selector with .ffh-override class, drop !important
#    - Group B: Elementor widget defaults
#      → use Elementor's Custom CSS panel with higher specificity
#    - Group C: legacy 2019 declarations no longer needed
#      → delete entirely (test in staging first)
#    - Group D: hard-fought !important that nothing else beats
#      → keep, but document why in a comment

# 4. After each batch: regression test pass
#    - Lighthouse on /, /destinations/europe/, /destinations/asia/, /hotel/<random>/
#    - Visual diff against Pin set

# Estimated: ~2 hours for full pass, ~30 min per group of 50
```

**Accept:** `grep -c '!important' design-overrides.css` < 50, no visual regressions on top 20 pages.

---

## Task `t_alex_p1_continental_visual` — Continent pages visual review

**Host:** CLI (this one) — but blocked by hcdn body-strip
**Goal:** Confirm `/destinations/europe/`, `/destinations/asia/`, etc. are not visual shells.

```bash
# Use curl + heuristics to verify non-shell
for cont in europe asia africa americas oceania; do
  echo "=== /destinations/$cont/ ==="
  url="https://ffh.com/destinations/$cont/"
  
  # Fetch with desktop UA
  curl -s -A 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36' \
    "$url" --max-time 15 > /tmp/continent.html
  
  size=$(wc -c < /tmp/continent.html)
  echo "  body size: $size bytes"
  
  # Hotel cards detection
  cards=$(grep -c '<article\|hotel-card\|destination-card' /tmp/continent.html)
  echo "  hotel cards found: $cards"
  
  # H1 check
  h1=$(grep -oE '<h1[^>]*>[^<]+</h1>' /tmp/continent.html | head -1)
  echo "  H1: $h1"
  
  # Title/canonical uniqueness (shell would be identical to hub)
  title=$(grep -oE '<title>[^<]+</title>' /tmp/continent.html | head -1)
  echo "  Title: $title"
done

# Expected for non-shell:
#   body size: > 30 KB
#   hotel cards found: > 5
#   H1: continent-specific (e.g. "European Luxury Hotels")
#   Title: continent-specific (e.g. "Europe Hotels | Four Flags Hotels")
```

If shells are confirmed, the fix is to edit the destination CPT templates in Elementor → vary the title widget and add the hotel grid for each continent.

**Accept:** Each continent page has continent-specific title, ≥6 hotel cards, body >30KB.

---

## Closing checklist

After all 7 tasks:
- [ ] Run smoke probe: `./ffh-smoke.sh` (similar to joesheating-probe.sh)
- [ ] Lighthouse on /, /destinations/europe/, /hotel/<random>/
- [ ] Slack #ffh-internal — "T-alex batch + 4 routine SSH fixes done, [date]"