#!/usr/bin/env bash
# One-time bootstrap of the Engineering Points label taxonomy on
# Capmob-Financial-Services-LLC/BSA. Run this yourself with your own
# authenticated `gh` CLI (NOT the GH_SYNC_TOKEN secret — that's read-only).
#
# Usage:
#   1. First just review what's already there:
#        gh label list --repo Capmob-Financial-Services-LLC/BSA --limit 200
#      Check for manually-added look-alikes (e.g. "Bug", "size-M") under
#      different names than the target list below — those won't be touched
#      automatically; decide by hand whether to re-label existing issues and
#      delete the old one, or leave both for now.
#   2. Then run this script. It's idempotent: `gh label create --force`
#      creates a label if missing, or updates color/description in place if
#      a label with that EXACT name already exists. It never touches labels
#      outside this list.

set -euo pipefail
REPO="Capmob-Financial-Services-LLC/BSA"

label() { gh label create "$1" --repo "$REPO" --color "$2" --description "$3" --force; }

# --- size:* (purple family) ---
label "size:s" "e6d5fa" "Small effort (lowest sized-category points)"
label "size:m" "c19bf5" "Medium effort"
label "size:l" "5319e7" "Large effort (highest sized-category points)"

# --- type:* (green family) ---
label "type:bug-find" "0e8a16" "Bug report/discovery (scores reporter, needs sev:*+area:*+triaged)"
label "type:bug-fix"  "0e8a16" "Bug fix (scores assignee, needs sev:*+area:*+triaged)"
label "type:feat-be"  "0e8a16" "Backend feature (sized)"
label "type:feat-fe"  "0e8a16" "Frontend feature (sized)"
label "type:infra"    "0e8a16" "Infrastructure work (sized)"
label "type:design"   "0e8a16" "Design work (sized)"
label "type:chore"    "0e8a16" "Chore/maintenance (sized)"
label "type:perf"     "0e8a16" "Performance work (held for review before scoring)"
label "type:review"   "0e8a16" "Code/design review (flat points)"
label "type:spike"    "0e8a16" "Investigation/spike (flat points)"
label "type:ops-save" "0e8a16" "Ops cost/time save (flat points, high value)"
label "type:incident" "0e8a16" "Incident response (flat points, can get RCA bonus)"
label "type:security" "0e8a16" "Security work (held for review before scoring)"
label "type:ux"       "0e8a16" "UX work (flat points)"
label "type:analytics" "0e8a16" "Analytics work (flat points)"
label "type:copy"     "0e8a16" "Copywriting (held for review before scoring)"
label "type:a11y"     "0e8a16" "Accessibility work (flat points)"
label "type:docs"     "0e8a16" "Documentation (held for review before scoring)"

# --- sev:* (red family, graded) ---
label "sev:critical" "b60205" "Critical severity (bug scoring only)"
label "sev:major"    "d93f0b" "Major severity (bug scoring only)"
label "sev:minor"    "f4b5b0" "Minor severity (bug scoring only)"

# --- area:* (neutral blue family) ---
label "area:infra"    "bfd4f2" "Infra area (bug scoring only)"
label "area:backend"  "bfd4f2" "Backend area (bug scoring only)"
label "area:frontend" "bfd4f2" "Frontend area (bug scoring only)"
label "area:design"   "bfd4f2" "Design area (bug scoring only)"

# --- standalone modifier tags (distinct bright colors) ---
label "triaged"   "fbca04" "Unlocks bug find/fix scoring once present"
label "reverted"  "e11d21" "Reverses all prior point awards on this ticket (illegitimate/unshipped/careless work)"
label "rca-done"  "1d76db" "Grants incident RCA bonus points"
label "own-code"  "c5def5" "Reporter found a bug in their own code (zeroes bug-find points, fix points unaffected)"
label "trivial"   "cccccc" "Marks a ticket as trivial (reserved, not yet wired into scoring)"

echo "Done. Re-run 'gh label list --repo $REPO' to confirm."
