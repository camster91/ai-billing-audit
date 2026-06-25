# tkd-ux-qa — F7: Settings page tabbed layout (collapse to 3 tabs)

**Task:** `t_1f76c965` (blocked, priority 7)
**File:** `src/client/pages/TournamentSettings.tsx`
**Estimate:** ~6 hours

## Current state

The TournamentSettings page has 9 sections stacked vertically, with
**two Save buttons** (top + bottom). The page is 1200+px tall. New
directors get overwhelmed.

## Goal

Collapse the 9 sections into **3 tabs**, with a single Save button at
the bottom of the page (not per-tab).

## Proposed tab structure

### Tab 1 — "Auto-categorization"
Sections that control how registrants get bucketed into brackets:
- `BracketSizeRules` (sizes 4/8/16/32 + auto-balance)
- `BeltBasedGrouping` (group by belt, age, weight)
- `SkillLevelSplitting` (color/poom/black belt splits)

### Tab 2 — "Bracket generation"
Sections that control how brackets get generated and seeded:
- `SeedingMethod` (random / skill-based / coach-pick)
- `BracketStyle` (single elim / double elim / round robin)
- `SeedingTieBreakers` (head-to-head, age, etc.)

### Tab 3 — "Day-of rules"
Sections that control runtime / day-of event behavior:
- `MatchDurationRules` (round length, rest periods)
- `WeighInSchedule` (before / morning-of / staggered)
- `CoachCheckInPolicy` (when coaches must be present)

## Implementation outline

### Step 1 — Pull all 9 section components into a parent `<Tabs>` shell

```tsx
// src/client/pages/TournamentSettings.tsx

import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

export function TournamentSettings() {
  const [activeTab, setActiveTab] = useState("auto-cat");
  const [settings, setSettings] = useState<TournamentSettings>(defaultSettings);
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    await api.updateTournamentSettings(tournamentId, settings);
    setSaving(false);
  };

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-semibold mb-2">Tournament Settings</h1>
      <p className="text-sm text-muted-foreground mb-6">
        Configure how this tournament runs from registration through finals.
      </p>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid grid-cols-3 mb-6">
          <TabsTrigger value="auto-cat">Auto-categorization</TabsTrigger>
          <TabsTrigger value="brackets">Bracket generation</TabsTrigger>
          <TabsTrigger value="day-of">Day-of rules</TabsTrigger>
        </TabsList>

        <TabsContent value="auto-cat" className="space-y-6">
          <BracketSizeRules value={settings.bracketSize} onChange={...} />
          <BeltBasedGrouping value={settings.beltGrouping} onChange={...} />
          <SkillLevelSplitting value={settings.skillSplit} onChange={...} />
        </TabsContent>

        <TabsContent value="brackets" className="space-y-6">
          <SeedingMethod value={settings.seeding} onChange={...} />
          <BracketStyle value={settings.bracketStyle} onChange={...} />
          <SeedingTieBreakers value={settings.tieBreakers} onChange={...} />
        </TabsContent>

        <TabsContent value="day-of" className="space-y-6">
          <MatchDurationRules value={settings.matchDuration} onChange={...} />
          <WeighInSchedule value={settings.weighIn} onChange={...} />
          <CoachCheckInPolicy value={settings.coachCheckIn} onChange={...} />
        </TabsContent>
      </Tabs>

      {/* Single Save button at the bottom */}
      <div className="sticky bottom-0 bg-background pt-4 mt-8 border-t">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : "Save all settings"}
        </Button>
      </div>
    </div>
  );
}
```

### Step 2 — Remove the duplicate Save button

The current page has two Save buttons (top + bottom). Keep only the
bottom one (sticky so it's always visible).

### Step 3 — Add tab-change warning if unsaved

```tsx
const isDirty = /* compare settings to last-saved snapshot */;

useEffect(() => {
  const handler = (e: BeforeUnloadEvent) => {
    if (isDirty) e.preventDefault();
  };
  window.addEventListener("beforeunload", handler);
  return () => window.removeEventListener("beforeunload", handler);
}, [isDirty]);

// Also block tab switch when dirty:
<Tabs value={activeTab} onValueChange={(next) => {
  if (isDirty && !confirm("You have unsaved changes. Leave this tab?")) return;
  setActiveTab(next);
}}>
```

### Step 4 — Tests

- `tests/pages/TournamentSettings.test.tsx`:
  - Renders 3 tabs by default
  - Each tab has the right section components
  - Save button is in the DOM (only one)
  - Save button calls `api.updateTournamentSettings`
  - Tab switch warns when dirty
- Lighthouse a11y: tab roles, arrow-key navigation

## Acceptance criteria

- [ ] TournamentSettings renders 3 tabs, not 9 stacked sections
- [ ] Single Save button at bottom of page
- [ ] All 9 existing section components still render their content
- [ ] Save button is sticky / always visible on scroll
- [ ] Tab switch warns on unsaved changes
- [ ] Lighthouse a11y score ≥ 95
- [ ] Lighthouse best-practices ≥ 95
- [ ] Existing functionality (load/save) preserved
- [ ] Existing tests still pass

## Out of scope

- Adding new settings (this is a UX reorganization, not feature work)
- Changing the API surface
- Restyling individual section components (only their container changes)

## Estimated time

~6 hours: 2h shell refactor + 2h section component verification + 1h tests + 1h polish + a11y.