#!/usr/bin/env bash
# Create standard OSS triage labels. Run once per repo.
# Requires `gh` authenticated against the target repo.
set -euo pipefail

REPO="${REPO:-nicholasglazer/gnosis-mcp}"

create_label() {
  local name="$1" color="$2" description="$3"
  gh label create "$name" --repo "$REPO" --color "$color" --description "$description" --force
}

create_label "good-first-issue" "7057ff" "Beginner-friendly, well-scoped tasks"
create_label "help-wanted"      "008672" "Extra attention / outside help is welcome"
create_label "bug"              "d73a4a" "Something isn't working"
create_label "enhancement"      "a2eeef" "New feature or request"
create_label "documentation"    "0075ca" "Improvements or additions to docs"
create_label "question"         "d876e3" "Further information is requested"
create_label "security"         "ee0701" "Security issues — see SECURITY.md for private reports"

echo "Labels ensured on $REPO."
