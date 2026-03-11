"""
Advanced SRT Comparison Module
Supports:
- Global time shift detection
- Split detection
- Merge detection
- Time tolerance matching
- Addition / Removal detection
"""

import re
import csv
import io
from typing import List, Dict, Optional, Tuple, Any

TIME_RE = re.compile(r"(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,\.]\d{3})")


# =========================
# Time Utilities
# =========================

def time_to_ms(t: str) -> int:
    t = t.strip().replace('.', ',')
    hh, mm, ss_ms = t.split(':')
    ss, ms = ss_ms.split(',')
    return (int(hh) * 3600 + int(mm) * 60 + int(ss)) * 1000 + int(ms)


def ms_to_time(ms: int) -> str:
    hours = ms // 3600000
    minutes = (ms % 3600000) // 60000
    seconds = (ms % 60000) // 1000
    millis = ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def normalize_text(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s


def _is_predominantly_latin(s: str) -> bool:
    """Return True if the string is predominantly Latin/ASCII letters."""
    if not s or not s.strip():
        return False
    letters = sum(1 for c in s if c.isalpha())
    if letters == 0:
        return False
    latin = sum(1 for c in s if ord(c) < 128 and c.isalpha())
    return latin / letters >= 0.5


def get_english_for_comparison(text: str) -> str:
    """
    Extract the English (base) text from a segment for version comparison.
    Segments may contain:
    - English only
    - English followed by translated text (other language)
    - Translated text followed by English (legacy)
    Version tracking is performed only on the English content.
    """
    if not text or not text.strip():
        return ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return ""
    if len(lines) == 1:
        return lines[0]
    # Multiple lines: pick the line that is predominantly Latin (English)
    for line in lines:
        if _is_predominantly_latin(line):
            return line
    return lines[0]


# =========================
# SRT Parsing
# =========================

def parse_srt(path: str) -> List[Dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().strip()
    except UnicodeDecodeError:
        with open(path, "r", encoding="utf-8-sig") as f:
            content = f.read().strip()

    if not content:
        return []

    blocks = re.split(r'\n\s*\n', content)
    subs = []

    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue

        ts_idx = None
        for i, ln in enumerate(lines):
            if '-->' in ln:
                ts_idx = i
                break
        if ts_idx is None:
            continue

        index = None
        if ts_idx > 0 and lines[ts_idx - 1].isdigit():
            index = int(lines[ts_idx - 1])

        m = TIME_RE.search(lines[ts_idx])
        if not m:
            continue

        start = m.group(1).replace('.', ',')
        end = m.group(2).replace('.', ',')

        text_lines = lines[ts_idx + 1:]
        text = "\n".join(text_lines).strip()
        english_text = get_english_for_comparison(text)

        subs.append({
            "index": index,
            "start": start,
            "end": end,
            "start_ms": time_to_ms(start),
            "end_ms": time_to_ms(end),
            "text": text,
            "english_text": english_text or text,
        })

    subs.sort(key=lambda x: (x["start_ms"], x["end_ms"]))
    return subs


# =========================
# SRT Translation (English + translation below)
# =========================

def translate_srt_content(
    path_or_subs,
    translate_fn,
) -> str:
    """
    Produce SRT content with translated text directly below each English segment.
    translate_fn(english_text: str) -> str returns the translation.
    Output format per segment: English line(s) then translated line(s).
    """
    if isinstance(path_or_subs, str):
        subs = parse_srt(path_or_subs)
    else:
        subs = path_or_subs

    out_lines = []
    for i, seg in enumerate(subs):
        idx = seg.get("index") or (i + 1)
        start = seg["start"]
        end = seg["end"]
        text = seg.get("text", "")
        english = seg.get("english_text") or get_english_for_comparison(text) or text
        translated = translate_fn(english) if english.strip() else ""
        # Save as: English first, then translated text below (per workflow)
        segment_text = english.strip()
        if translated.strip():
            segment_text += "\n" + translated.strip()
        out_lines.append(str(idx))
        out_lines.append(f"{start} --> {end}")
        out_lines.append(segment_text)
        out_lines.append("")
    return "\n".join(out_lines).strip() + "\n" if out_lines else ""


# =========================
# Global Time Shift Detection
# =========================

def detect_global_time_shift(s1, s2, tolerance_ms=50, sample_size=50):
    if not s1 or not s2:
        return False, 0

    samples = min(sample_size, len(s1), len(s2))
    offsets = [s2[i]["start_ms"] - s1[i]["start_ms"] for i in range(samples)]

    avg_shift = sum(offsets) // len(offsets)

    consistent = all(abs(o - avg_shift) <= tolerance_ms for o in offsets)

    return consistent, avg_shift


# =========================
# Split / Merge Detection
# =========================

def detect_split(A, s2, j, lookahead, normalize):
    text_a = A.get("english_text", A["text"])
    combined = ""
    end_j = min(len(s2), j + lookahead)

    for jj in range(j, end_j):
        text_b = s2[jj].get("english_text", s2[jj]["text"])
        combined += " " + text_b
        if normalize_text(combined.strip()) == normalize_text(text_a):
            return jj
    return None


def detect_merge(B, s1, i, lookahead, normalize):
    text_b = B.get("english_text", B["text"])
    combined = ""
    end_i = min(len(s1), i + lookahead)

    for ii in range(i, end_i):
        text_a = s1[ii].get("english_text", s1[ii]["text"])
        combined += " " + text_a
        if normalize_text(combined.strip()) == normalize_text(text_b):
            return ii
    return None


# =========================
# Main Comparison
# =========================

def compare_srts(
    file1: str,
    file2: str,
    time_tolerance_ms: int = 0,
    shift_window_ms: int = 30000,
    lookahead: int = 10,
    normalize_dialogue: bool = True
) -> List[Tuple]:

    s1 = parse_srt(file1)
    s2 = parse_srt(file2)

    results = []
    i = j = 0

    is_shifted, global_shift = detect_global_time_shift(s1, s2)

    while i < len(s1) or j < len(s2):

        if i >= len(s1):
            results.append((None, "Addition", {"file1": None, "file2": s2[j]}))
            j += 1
            continue

        if j >= len(s2):
            results.append((s1[i]["index"], "Removal", {"file1": s1[i], "file2": None}))
            i += 1
            continue

        A = s1[i]
        B = s2[j]

        adjusted_start_B = B["start_ms"] - global_shift if is_shifted else B["start_ms"]
        adjusted_end_B = B["end_ms"] - global_shift if is_shifted else B["end_ms"]

        time_match = (
            abs(A["start_ms"] - adjusted_start_B) <= time_tolerance_ms and
            abs(A["end_ms"] - adjusted_end_B) <= time_tolerance_ms
        )

        # Version tracking is performed only on English content
        text_a = A.get("english_text", A["text"])
        text_b = B.get("english_text", B["text"])
        text_match = (
            normalize_text(text_a) == normalize_text(text_b)
            if normalize_dialogue
            else text_a.strip() == text_b.strip()
        )

        # Exact match
        if time_match and text_match:
            results.append((A["index"], "Match", {"file1": A, "file2": B}))
            i += 1
            j += 1
            continue

        # Dialogue difference
        if time_match and not text_match:
            results.append((A["index"], "Dialogue Difference", {"file1": A, "file2": B}))
            i += 1
            j += 1
            continue

        # Time difference
        if not time_match and text_match:
            status = "Global Time Shift" if is_shifted else "Time Difference"
            results.append((A["index"], status, {"file1": A, "file2": B}))
            i += 1
            j += 1
            continue

        # Split detection
        split_end = detect_split(A, s2, j, lookahead, normalize_dialogue)
        if split_end is not None:
            results.append((A["index"], "Split", {
                "file1": A,
                "file2": s2[j:split_end+1]
            }))
            i += 1
            j = split_end + 1
            continue

        # Merge detection
        merge_end = detect_merge(B, s1, i, lookahead, normalize_dialogue)
        if merge_end is not None:
            results.append((s1[i]["index"], "Merge", {
                "file1": s1[i:merge_end+1],
                "file2": B
            }))
            i = merge_end + 1
            j += 1
            continue

        # Fallback decision
        if A["start_ms"] < B["start_ms"]:
            results.append((A["index"], "Removal", {"file1": A, "file2": None}))
            i += 1
        else:
            results.append((None, "Addition", {"file1": None, "file2": B}))
            j += 1

    return results


# =========================
# JSON Output (flattened for frontend)
# =========================

def results_to_json(results: List[Tuple]) -> Dict[str, Any]:
    output = {
        "matches": [],
        "dialogue_differences": [],
        "time_differences": [],
        "global_time_shifts": [],
        "splits": [],
        "merges": [],
        "additions": [],
        "removals": [],
    }

    for _, status, pair in results:
        if status == "Match":
            a, b = pair.get("file1"), pair.get("file2")
            output["matches"].append({
                "index": a.get("index") if a else (b.get("index") if b else None),
                "time_start": (a or b).get("start"),
                "time_end": (a or b).get("end"),
                "dialogue": (a or b).get("text", ""),
            })
        elif status == "Dialogue Difference":
            a, b = pair.get("file1"), pair.get("file2")
            output["dialogue_differences"].append({
                "index_1": a.get("index") if a else None,
                "index_2": b.get("index") if b else None,
                "time_start_1": a.get("start") if a else None,
                "time_end_1": a.get("end") if a else None,
                "time_start_2": b.get("start") if b else None,
                "time_end_2": b.get("end") if b else None,
                "dialogue_1": a.get("text", "") if a else "",
                "dialogue_2": b.get("text", "") if b else "",
            })
        elif status in ("Time Difference", "Global Time Shift"):
            a, b = pair.get("file1"), pair.get("file2")
            output["time_differences"].append({
                "index_1": a.get("index") if a else None,
                "index_2": b.get("index") if b else None,
                "time_start_1": a.get("start") if a else None,
                "time_end_1": a.get("end") if a else None,
                "time_start_2": b.get("start") if b else None,
                "time_end_2": b.get("end") if b else None,
                "dialogue": (a or b).get("text", ""),
            })
        elif status == "Split":
            output["splits"].append(pair)
        elif status == "Merge":
            output["merges"].append(pair)
        elif status == "Addition":
            b = pair.get("file2")
            output["additions"].append({
                "index": b.get("index") if b else None,
                "time_start": b.get("start") if b else None,
                "time_end": b.get("end") if b else None,
                "dialogue": b.get("text", "") if b else "",
            })
        elif status == "Removal":
            a = pair.get("file1")
            output["removals"].append({
                "index": a.get("index") if a else None,
                "time_start": a.get("start") if a else None,
                "time_end": a.get("end") if a else None,
                "dialogue": a.get("text", "") if a else "",
            })

    total_file1 = (
        len([r for r in results if r[1] in ("Removal", "Match", "Dialogue Difference", "Time Difference", "Global Time Shift")])
        + sum(1 for r in results if r[1] == "Merge" and isinstance(r[2].get("file1"), list))
    )
    total_file2 = (
        len([r for r in results if r[1] in ("Addition", "Match", "Dialogue Difference", "Time Difference", "Global Time Shift")])
        + sum(1 for r in results if r[1] == "Split" and isinstance(r[2].get("file2"), list))
    )
    matches_count = len(output["matches"])
    total_entries = max(total_file1, total_file2, 1)
    match_percentage = round((matches_count / total_entries) * 100, 2)

    output["summary"] = {
        "matches": len(output["matches"]),
        "dialogue_differences": len(output["dialogue_differences"]),
        "time_differences": len(output["time_differences"]),
        "global_time_shifts": len(output["global_time_shifts"]),
        "splits": len(output["splits"]),
        "merges": len(output["merges"]),
        "additions": len(output["additions"]),
        "removals": len(output["removals"]),
        "total_file1": total_file1,
        "total_file2": total_file2,
        "match_percentage": match_percentage,
    }

    return output

def results_to_csv(results: Dict[str, Any]) -> str:
    """
    Convert comparison results to CSV format.
    
    Returns CSV string with all differences (excludes matches).
    """
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Header
    writer.writerow([
        "Type", "Index_File1", "Index_File2", 
        "Time_Start_1", "Time_End_1", "Time_Start_2", "Time_End_2",
        "Dialogue_File1", "Dialogue_File2"
    ])
    
    # Dialogue differences
    for d in results.get("dialogue_differences", []):
        writer.writerow([
            "Dialogue Difference",
            d.get("index_1"),
            d.get("index_2"),
            d.get("time_start_1"),
            d.get("time_end_1"),
            d.get("time_start_2"),
            d.get("time_end_2"),
            d.get("dialogue_1"),
            d.get("dialogue_2")
        ])
    
    # Time differences
    for d in results.get("time_differences", []):
        writer.writerow([
            "Time Difference",
            d.get("index_1"),
            d.get("index_2"),
            d.get("time_start_1"),
            d.get("time_end_1"),
            d.get("time_start_2"),
            d.get("time_end_2"),
            d.get("dialogue"),
            d.get("dialogue")
        ])
    
    # Additions
    for d in results.get("additions", []):
        writer.writerow([
            "Addition",
            "",
            d.get("index"),
            "",
            "",
            d.get("time_start"),
            d.get("time_end"),
            "",
            d.get("dialogue")
        ])
    
    # Removals
    for d in results.get("removals", []):
        writer.writerow([
            "Removal",
            d.get("index"),
            "",
            d.get("time_start"),
            d.get("time_end"),
            "",
            "",
            d.get("dialogue"),
            ""
        ])
    
    return output.getvalue()


# For backwards compatibility
def pretty_print(results: List[Tuple]):
    """Print comparison results in a human-readable format."""
    for r in results:
        idx, status, detail = r
        A = detail.get("file1")
        B = detail.get("file2")
        
        if status == "Match":
            print(f"[{idx}] ✅ Match: {A['text']}")
        elif status == "Dialogue Difference":
            print(f"[{idx}] ⚠️  Dialogue difference:")
            print(f"    File1: {A['text'] if A else 'N/A'}")
            print(f"    File2: {B['text'] if B else 'N/A'}")
        elif status == "Time Difference":
            print(f"[{idx}] ⏱️  Time difference:")
            print(f"    File1: {A['start']} --> {A['end']}")
            print(f"    File2: {B['start']} --> {B['end']}")
        elif status == "Addition":
            print(f"[+] ➕ Added in File2: {B['text']}")
        elif status == "Removal":
            print(f"[{idx}] ❌ Removed (not in File2): {A['text']}")
    
    print(f"\nTotal entries: {len(results)}")


def generate_bilingual_srt(results_dict):
    """
    Generate a bilingual SRT file from comparison results.
    Combines all entries, sorts by timestamp, and creates proper SRT format.
    For Match and Time Difference entries, add the second language from base file.
    """
    import re
    all_entries = []
    
    # Collect all entries with their timestamps for sorting
    for entry in results_dict.get("matches", []):
        all_entries.append({
            'time_start': entry['time_start'],
            'time_end': entry['time_end'],
            'dialogue': entry['dialogue'],
            'second_language': entry.get('second_language'),
            'type': 'match'
        })
    
    for entry in results_dict.get("time_differences", []):
        all_entries.append({
            'time_start': entry['time_start_2'],
            'time_end': entry['time_end_2'],
            'dialogue': entry['dialogue'],
            'second_language': entry.get('second_language'),
            'type': 'time_difference'
        })
    
    for entry in results_dict.get("dialogue_differences", []):
        all_entries.append({
            'time_start': entry['time_start_2'],
            'time_end': entry['time_end_2'],
            'dialogue': entry['dialogue_2'],
            'second_language': None,
            'type': 'dialogue_difference'
        })
    
    for entry in results_dict.get("additions", []):
        all_entries.append({
            'time_start': entry['time_start'],
            'time_end': entry['time_end'],
            'dialogue': entry['dialogue'],
            'second_language': None,
            'type': 'addition'
        })
    
    # Sort all entries by timestamp
    def time_to_ms_local(time_str):
        if not time_str:
            return 0
        match = re.match(r'(\d+):(\d+):(\d+)[,\.](\d+)', time_str)
        if match:
            h, m, s, ms = match.groups()
            return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)
        return 0
    
    all_entries.sort(key=lambda x: time_to_ms_local(x['time_start']))
    
    # Generate SRT content
    output_lines = []
    for counter, entry in enumerate(all_entries, start=1):
        output_lines.append(str(counter))
        output_lines.append(f"{entry['time_start']} --> {entry['time_end']}")
        output_lines.append(entry['dialogue'])
        
        if entry.get('second_language'):
            output_lines.append("")
            output_lines.append(entry['second_language'])
        
        output_lines.append("")
    
    return "\n".join(output_lines)
