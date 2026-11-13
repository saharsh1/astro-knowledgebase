#!/usr/bin/env python
"""Check the knowledge base against conventions.yaml.

Usage:
    python scripts/check_vault.py                      # all notes in live/ and keeper/generated/
    python scripts/check_vault.py --keeper             # also check keeper/locks/ against the files
    python scripts/check_vault.py --draft outbox/X.md --dest live/binary-stars/lessons/X.md
                                                       # one draft, as if it were at --dest (/publish)

With no live/ folder (e.g. on GitHub), only the skeleton is checked.
Exit status 1 if any error is found. Warnings do not fail the check.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WIKILINK = re.compile(r"(?<!\!)\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
FENCE = re.compile(r"```.*?```", re.S)
COMMENT = re.compile(r"<!--.*?-->", re.S)
ATTACHMENT = re.compile(r"\.(pdf|png|jpe?g|csv|fits|zip|json)$", re.I)


def frontmatter(text: str) -> dict | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end < 0:
        return None
    try:
        data = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    return data if isinstance(data, dict) else None


def as_list(v) -> list:
    if v in (None, ""):
        return []
    return v if isinstance(v, list) else [v]


def link_target(v) -> str | None:
    """'[[Title]]' or '[[Title|alias]]' -> 'Title'; anything else -> None."""
    m = WIKILINK.fullmatch(str(v).strip())
    return m.group(1).strip() if m else None


class Vault:
    def __init__(self, conv: dict):
        self.conv = conv
        self.live = ROOT / conv["live_dir"]
        self.keeper = ROOT / conv["keeper_dir"]
        self.arms = conv["arms"]

    def place(self, path: Path) -> tuple[str | None, str | None]:
        """(arm, place) of a note path: place is 'arm:<folder>', a shared folder, or 'generated'."""
        try:
            parts = path.relative_to(self.live).parts
        except ValueError:
            try:
                parts = path.relative_to(self.keeper).parts
            except ValueError:
                return None, None
            if not parts or parts[0] not in self.conv["generated_folders"]:
                return None, None
            return (parts[1] if len(parts) >= 3 and parts[1] in self.arms else None), "generated"
        if len(parts) >= 3 and parts[0] in self.arms and parts[1] in self.conv["arm_folders"]:
            return parts[0], f"arm:{parts[1]}"
        if len(parts) >= 2 and parts[0] in self.conv["shared_folders"]:
            return None, parts[0]
        return None, None

    def notes(self) -> list[Path]:
        out = []
        for arm in self.arms:
            for f in self.conv["arm_folders"]:
                out += sorted((self.live / arm / f).rglob("*.md"))
        for f in self.conv["shared_folders"]:
            out += sorted((self.live / f).rglob("*.md"))
        for f in self.conv["generated_folders"]:
            out += sorted((self.keeper / f).rglob("*.md"))
        return [p for p in out if not p.name.startswith(".") and p.name != "README.md"]

    def missing_arms(self) -> list[str]:
        return [a for a in self.arms if not (self.live / a).is_dir()]

    def layer(self, arm: str | None) -> int | None:
        """0 gaia, 1 software, 2 science arms (conventions.yaml); None for shared notes."""
        return None if arm is None else int((self.arms.get(arm) or {}).get("layer", 2))

    def allowed_tags(self, arm: str | None, fm: dict) -> set[str]:
        tags = set(self.conv["common_tags"])
        lower = {a for a in self.arms if arm and self.layer(a) < self.layer(arm)}
        arms = set(self.arms) if arm is None else {arm, *as_list(fm.get("arms")), *lower}
        for a in arms:
            tags |= set(self.arms.get(a, {}).get("tags", []))
        return tags


def check_skeleton(conv: dict, errors: list[str]) -> None:
    types = set(conv["types"])
    for t, places in conv["type_places"].items():
        if t not in types:
            errors.append(f"conventions.yaml: type_places names unknown type '{t}'")
        for p in places:
            if "/" in p:
                a, p = p.split("/", 1)
                if a not in conv["arms"]:
                    errors.append(f"conventions.yaml: type '{t}' placed in unknown arm '{a}'")
            p = p.removeprefix("arm:")
            if p not in conv["arm_folders"] + conv["shared_folders"] + conv["generated_folders"]:
                errors.append(f"conventions.yaml: type '{t}' placed in unknown folder '{p}'")
    for t, pat in conv.get("name_patterns", {}).items():
        try:
            re.compile(pat)
        except re.error as e:
            errors.append(f"conventions.yaml: name_patterns.{t} is not a valid pattern ({e})")
    for name in ["Lesson", "Note", "Discussion", "Topic", "Request"]:
        if not (ROOT / "templates" / f"{name}.md").exists():
            errors.append(f"templates/{name}.md is missing")
    if conv.get("code_arm") and conv["code_arm"] not in conv["arms"]:
        errors.append(f"conventions.yaml: code_arm '{conv['code_arm']}' is not an arm")
    for a, spec in conv["arms"].items():
        if not isinstance((spec or {}).get("layer"), int):
            errors.append(f"conventions.yaml: arm '{a}' needs an integer 'layer'")
    overlap = set(conv["common_tags"]) & {t for a in conv["arms"].values() for t in a.get("tags", [])}
    if overlap:
        errors.append(f"conventions.yaml: tags both common and arm-specific: {sorted(overlap)}")


def check_note(v: Vault, path: Path, rel: str, text: str, place_path: Path,
               stems: dict[str, str | None], strict_links: bool, errors: list, warnings: list,
               pending: frozenset = frozenset()) -> dict | None:
    """stems: file stem -> arm of every note (None for shared and generated notes)."""
    conv = v.conv
    stem = path.stem
    if conv["conflict_marker"] in path.name:
        errors.append(f"{rel}: Seafile conflict copy; keep one version (/resolve) and delete the other")
        return None
    if bad := sorted(set(stem) & set(conv["forbidden_filename_chars"])):
        errors.append(f"{rel}: file name contains {' '.join(bad)}")
    fm = frontmatter(text)
    if fm is None:
        errors.append(f"{rel}: missing or unreadable YAML frontmatter")
        return None
    for field in conv["required_common"]:
        if fm.get(field) in (None, "", []) and not (field == "tags" and "tags" in fm):
            errors.append(f"{rel}: missing field '{field}'")
    ntype = fm.get("type")
    if ntype not in conv["types"]:
        errors.append(f"{rel}: unknown type '{ntype}'")
        return fm
    for field in conv["types"][ntype]:
        if field not in fm:
            errors.append(f"{rel}: type '{ntype}' needs field '{field}'")
    for field, values in conv["enums"].items():
        if field in fm and fm[field] not in values:
            errors.append(f"{rel}: {field}='{fm[field]}' not in {values}")

    arm, place = v.place(place_path)
    if place is None:
        errors.append(f"{rel}: not in an arm folder, a shared folder or a generated folder")
    elif place not in conv["type_places"].get(ntype, []) and \
            not (arm and place.startswith("arm:") and f"{arm}/{place[4:]}" in conv["type_places"].get(ntype, [])):
        where = f"{arm}/{place[4:]}" if place.startswith("arm:") else place
        errors.append(f"{rel}: a '{ntype}' does not belong in {where} "
                      f"(allowed: {', '.join(conv['type_places'].get(ntype, []))})")
    if place == "generated" and not fm.get("generated") and ntype not in ("hub",):
        warnings.append(f"{rel}: in a generated folder but has no 'generated: true'")

    for a in as_list(fm.get("arms")) + ([fm["arm"]] if ntype == "request" and fm.get("arm") else []):
        if a not in v.arms:
            errors.append(f"{rel}: arm '{a}' is not in conventions.yaml")
    allowed = v.allowed_tags(None if place == "generated" else arm, fm)
    for tag in as_list(fm.get("tags")):
        if tag not in allowed:
            errors.append(f"{rel}: tag '{tag}' is not allowed here (common tags or tags of its arms)")

    pat = conv.get("name_patterns", {}).get(ntype)
    if pat:
        m = re.match(pat, stem)
        if not m:
            errors.append(f"{rel}: file name does not follow the pattern for a {ntype} (conventions.yaml)")
        elif m.groupdict().get("author") and m.group("author") != str(fm.get("author")):
            errors.append(f"{rel}: file name names '{m.group('author')}', but author is '{fm.get('author')}'")

    targets = []
    for field in ("about", "consolidates", "supersedes"):
        for val in as_list(fm.get(field)):
            target = link_target(val)
            if target is None:
                errors.append(f"{rel}: '{field}' must hold wikilinks like \"[[Title]]\", not {val!r}")
            else:
                targets.append(target)
    if ntype == "discussion" and len(as_list(fm.get("about"))) != 1:
        errors.append(f"{rel}: a discussion is about exactly one note")

    if not (fm.get("generated") or fm.get("markers_reviewed")):
        for marker in conv.get("review_markers", []):
            hit = re.search(marker[3:], text) if marker.startswith("re:") else marker.lower() in text.lower()
            if hit:
                warnings.append(f"{rel}: contains '{marker}' — check it is not from an internal (non-public) document")

    body = COMMENT.sub("", FENCE.sub("", text))
    targets += [t.strip().rstrip("\\") for t in WIKILINK.findall(body)]   # [[a\|b]] inside a table
    if arm and place != "generated":                # links run down the layers: science -> software -> gaia
        for target in sorted(set(targets)):
            other = stems.get(target)
            if other and v.layer(other) > v.layer(arm):
                errors.append(f"{rel}: a {arm} note (layer {v.layer(arm)}) links to [[{target}]] in {other} "
                              f"(layer {v.layer(other)}); links run from higher layers to lower ones only, "
                              f"so put this link in a note of {other}")
    for target in WIKILINK.findall(body):
        target = target.strip().rstrip("\\")
        if ATTACHMENT.search(target) or target in stems:
            continue
        if target in pending:
            warnings.append(f"{rel}: link [[{target}]] is to a draft still in outbox/: publish both together")
            continue
        msg = f"{rel}: link [[{target}]] does not resolve"
        (errors if strict_links else warnings).append(msg + ("" if strict_links else " (an arm is not synced here)"))
    return fm


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keeper", action="store_true", help="check keeper/locks/ against the files")
    ap.add_argument("--draft", type=Path, help="check one draft file (e.g. in outbox/)")
    ap.add_argument("--dest", type=Path, help="with --draft: where /publish would put it")
    ap.add_argument("--skeleton", action="store_true",
                    help="check the rules and templates only, not the notes (as the GitHub check does)")
    args = ap.parse_args()

    conv = yaml.safe_load((ROOT / "conventions.yaml").read_text())
    sources = yaml.safe_load((ROOT / "sources.yaml").read_text()) if (ROOT / "sources.yaml").exists() else {}
    pins = {r["name"]: str(r["commit"]) for r in (sources or {}).get("repositories", [])}
    v = Vault(conv)
    errors: list[str] = []
    warnings: list[str] = []
    check_skeleton(conv, errors)

    notes = [] if args.skeleton else v.notes()
    missing = v.missing_arms() if v.live.exists() and not args.skeleton else []
    if v.live.exists() and missing:
        warnings.append(f"arms not synced on this machine: {', '.join(missing)} (links into them are warnings)")
    by_stem: dict[str, list[Path]] = defaultdict(list)
    for p in notes:
        by_stem[p.stem].append(p)
    stems = {s: v.place(ps[0])[0] for s, ps in by_stem.items()}

    if args.draft:                                   # one draft, checked at its destination
        if not args.dest:
            ap.error("--draft needs --dest")
        dest = (ROOT / args.dest).resolve()
        rel = f"{args.draft} (as {args.dest})"
        if dest.exists():
            errors.append(f"{rel}: {args.dest} exists already — never overwrite a note (one writer per file)")
        elif dest.stem in stems:
            errors.append(f"{rel}: a note named '{dest.stem}' exists already "
                          f"({by_stem[dest.stem][0].relative_to(ROOT)})")
        outbox = ROOT / conv["outbox_dir"]
        pending = frozenset(p.stem for p in outbox.rglob("*.md")) if outbox.exists() else frozenset()
        check_note(v, dest, rel, (ROOT / args.draft).read_text(encoding="utf-8"), dest,
                   {**stems, dest.stem: v.place(dest)[0]}, not missing, errors, warnings, pending)
        checked = 1
    else:
        for stem, paths in by_stem.items():
            if len(paths) > 1:
                errors.append(f"file name '{stem}' is used more than once: "
                              + "; ".join(str(p.relative_to(ROOT)) for p in paths))
        ids: dict[str, list[str]] = defaultdict(list)
        for path in notes:
            rel = str(path.relative_to(ROOT))
            fm = check_note(v, path, rel, path.read_text(encoding="utf-8"), path,
                            stems, not missing, errors, warnings)
            if not fm:
                continue
            if fm.get("type") == "paper":
                for key in ("bibcode", "arxiv", "doi"):
                    if fm.get(key):
                        ids[f"{key} {fm[key]}"].append(rel)
            if fm.get("type") == "lesson":
                for pin in as_list(fm.get("applies_to")):
                    m = re.match(r"repo:([^@]+)@(\w+)", str(pin))
                    if m and m.group(1) in pins and not pins[m.group(1)].startswith(m.group(2)) \
                            and not m.group(2).startswith(pins[m.group(1)]):
                        warnings.append(f"{rel}: applies to {m.group(1)}@{m.group(2)}, "
                                        f"pin is now {pins[m.group(1)]}; review the lesson")
        for key, rels in ids.items():
            if len(rels) > 1:
                errors.append(f"two paper notes have {key}: {'; '.join(rels)}")
        checked = len(notes)

    if args.keeper:
        roles = v.keeper / conv.get("roles_file", "roles.yaml")
        if not roles.exists():
            warnings.append(f"keeper/{roles.name} is missing: only the owner counts as a curator")
        else:
            try:
                r = yaml.safe_load(roles.read_text()) or {}
                assert isinstance(r, dict) and isinstance(r.get("curators", []), list)
            except (yaml.YAMLError, AssertionError):
                errors.append(f"keeper/{roles.name}: unreadable (expected 'curators: [<github user>, ...]')")
        locks = v.keeper / "locks"
        locked = set()
        for lf in sorted(locks.rglob("*.json")) if locks.exists() else []:
            try:
                lock = json.loads(lf.read_text())
                rel, size, sha = lock["path"], int(lock["size"]), lock["sha256"]
            except (ValueError, KeyError) as e:
                errors.append(f"{lf.relative_to(ROOT)}: unreadable lock ({e})")
                continue
            locked.add(rel)
            f = v.keeper / rel
            if not f.exists():
                errors.append(f"keeper/{rel}: has a lock but is missing (still syncing?)")
            elif f.stat().st_size != size or hashlib.sha256(f.read_bytes()).hexdigest() != sha:
                errors.append(f"keeper/{rel}: differs from its lock")
        for folder in ("pdfs", "data"):
            for f in sorted((v.keeper / folder).rglob("*")) if (v.keeper / folder).exists() else []:
                if f.is_file() and not f.name.startswith(".") and f.relative_to(v.keeper).as_posix() not in locked:
                    warnings.append(f"keeper/{f.relative_to(v.keeper)}: no lock (added without /ingest?)")

    for w in warnings:
        print("warning:", w)
    for e in errors:
        print("error:", e)
    where = "draft" if args.draft else ("notes" if v.live.exists() and not args.skeleton else "notes (skeleton only)")
    print(f"{checked} {where} checked, rules version {conv['version']}: "
          f"{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
