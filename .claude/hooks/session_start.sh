#!/usr/bin/env bash
# SessionStart: say if the rules are behind GitHub, and report Seafile conflict copies
# and drafts waiting in outbox/.
cd "$(dirname "$0")/../.." || exit 0
T=""; command -v timeout >/dev/null 2>&1 && T="timeout 5"
if $T git -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=5 fetch -q origin main 2>/dev/null; then
  local_v=$(sed -n 's/^version: *//p' conventions.yaml)
  remote_v=$(git show origin/main:conventions.yaml 2>/dev/null | sed -n 's/^version: *//p')
  behind=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  if [ -n "$remote_v" ] && [ "$local_v" != "$remote_v" ]; then
    echo "Knowledge base: the rules on GitHub are version $remote_v, this clone has $local_v. Run /sync before writing anything."
  elif [ "${behind:-0}" != "0" ]; then
    echo "Knowledge base: the skeleton is $behind commits behind GitHub. Run /sync."
  fi
fi
if [ -d live ]; then
  n=$(find live -name '*SFConflict*' 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" != "0" ] && echo "Knowledge base: $n Seafile conflict copies in live/. Run /resolve."
else
  echo "Knowledge base: live/ is missing. Sync the Keeper library 'astro-kb-notes' into ./live."
fi
if [ -d outbox ]; then
  n=$(find outbox -name '*.md' 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" != "0" ] && echo "Knowledge base: $n drafts in outbox/ are not shared yet. Run /publish when they are ready."
fi
exit 0
