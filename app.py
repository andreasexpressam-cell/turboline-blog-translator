import os
import re
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from deep_translator import GoogleTranslator

APP_TITLE = "TurboLine Blog Translator"
GLOSSARY_FILE = "glossary.txt"
POST_RULES_FILE = "post_rules.txt"

SRT_TIME_RE = re.compile(r"^\d{2}:\d{2}:\d{2},\d{3}\s*-->\s*\d{2}:\d{2}:\d{2},\d{3}")

LANG_MAP = {
    "auto": "auto",
    "el": "el",
    "en": "en",
    "fr": "fr",
    "it": "it",
    "de": "de",
    "es": "es",
    "pt": "pt",
    "ar": "ar",
    "nl": "nl",
    "ja": "ja",
    "ru": "ru",
    "tr": "tr",
    "zh-CN": "zh-CN",
    "ko": "ko",
    "sv": "sv",
    "pl": "pl",
}

SMART_MODE = True
USE_GLOSSARY = True
USE_POST_RULES = True
FIX_CASING = True

SRT_BATCH_SIZE = 80
TEXT_BATCH_SIZE = 20


def load_map_file(path: str):
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, "r", encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            sep = None
            for candidate in ("=>", "=", "->", "\t"):
                if candidate in line:
                    sep = candidate
                    break
            if not sep:
                continue
            src, tgt = line.split(sep, 1)
            src, tgt = src.strip(), tgt.strip()
            if not src or not tgt:
                continue
            pat = re.compile(re.escape(src), re.IGNORECASE)
            entries.append((src, tgt, pat))
    return entries


def apply_map(text: str, entries):
    hits = 0
    for _src, tgt, pat in entries:
        matches = list(pat.finditer(text))
        if not matches:
            continue
        hits += len(matches)
        text = pat.sub(tgt, text)
    return text, hits


def looks_like_srt(text: str) -> bool:
    return any(SRT_TIME_RE.match(line.strip()) for line in text.splitlines())


def safe_translate_text(text: str, src_lang: str, tgt_lang: str, retries: int = 2):
    if not text.strip():
        return ""
    src_lang = LANG_MAP.get(src_lang, src_lang)
    tgt_lang = LANG_MAP.get(tgt_lang, tgt_lang)
    for _ in range(retries + 1):
        try:
            tr = GoogleTranslator(source=src_lang, target=tgt_lang)
            out = tr.translate(text)
            if out is None:
                raise RuntimeError("Translator returned None")
            return str(out)
        except Exception:
            pass
    return text


def safe_translate_batch(lines, src_lang: str, tgt_lang: str):
    if not lines:
        return []
    src_lang = LANG_MAP.get(src_lang, src_lang)
    tgt_lang = LANG_MAP.get(tgt_lang, tgt_lang)
    try:
        tr = GoogleTranslator(source=src_lang, target=tgt_lang)
        out = tr.translate_batch(lines)
        if out and len(out) == len(lines):
            return [str(x) if x is not None else "" for x in out]
    except Exception:
        pass
    return [safe_translate_text(x, src_lang, tgt_lang) for x in lines]


def chunk_list(items, n):
    for i in range(0, len(items), n):
        yield items[i:i + n]


_UPPER_GR = "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩΆΈΉΊΌΎΏΪΫ"
_LOWER_GR = "αβγδεζηθικλμνξοπρστυφχψωάέήίόύώϊϋ"
_GR_TRANS = str.maketrans(_UPPER_GR, _LOWER_GR)


def lower_first_letter(token: str) -> str:
    if not token:
        return token
    ch = token[0]
    if ch in _UPPER_GR:
        return ch.translate(_GR_TRANS) + token[1:]
    if "A" <= ch <= "Z":
        return ch.lower() + token[1:]
    return token


def split_balanced_subtitle_line(s: str, max_chars: int = 42) -> str:
    s = " ".join(part.strip() for part in s.splitlines() if part.strip())
    s = re.sub(r"\s{2,}", " ", s).strip()
    if not s or len(s) <= max_chars:
        return s

    mid = len(s) // 2
    preferred_markers = [
        ", αλλά", ", όμως", ", ενώ", ", γιατί", ", καθώς", ", όταν", ", αφού",
        " αλλά ", " όμως ", " ενώ ", " γιατί ", " καθώς ", " όταν ", " αφού ",
        " και ", " ή "
    ]

    best_cut = -1
    best_score = 10**9

    for m in preferred_markers:
        start = 0
        while True:
            idx = s.find(m, start)
            if idx == -1:
                break
            cut = idx + 1 if m.startswith(",") else idx
            if cut < 10 or cut > len(s) - 10:
                start = idx + 1
                continue
            score = abs(cut - mid)
            if score < best_score:
                best_score = score
                best_cut = cut
            start = idx + 1

    if best_cut == -1:
        for i in range(mid, max(0, mid - 24), -1):
            if s[i] == " ":
                best_cut = i
                break
    if best_cut == -1:
        for i in range(mid, min(len(s), mid + 24)):
            if s[i] == " ":
                best_cut = i
                break
    if best_cut == -1:
        return s

    left = s[:best_cut].rstrip(" ,")
    right = s[best_cut:].lstrip(" ,")
    if right and left and not re.search(r"[.!?;:]$", left):
        right = lower_first_letter(right)
    return left + "\n" + right


def fix_casing_punctuation_text(text: str, tgt_lang: str) -> str:
    if not text:
        return text

    text = re.sub(r"\s*\.,\s*", ", ", text)
    text = re.sub(r"\s*,\.\s*", ", ", text)
    text = re.sub(r"\s*;\s*,\s*", "; ", text)
    text = re.sub(r"\s*:\s*,\s*", ": ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"([,.;:!?])([^\s\n])", r"\1 \2", text)
    text = re.sub(r"([,.;:!?])\s{2,}", r"\1 ", text)
    text = text.replace("…", "...")

    if tgt_lang == "el":
        def _lc_after_sep(m):
            return m.group(1) + " " + lower_first_letter(m.group(2))

        def _lc_after_sep_nl(m):
            return m.group(1) + "\n" + lower_first_letter(m.group(2))

        text = re.sub(r"([,;:])\s+([A-ZΑ-ΩΆΈΉΊΌΎΏ])", _lc_after_sep, text)
        text = re.sub(r"([,;:])\s*\n\s*([A-ZΑ-ΩΆΈΉΊΌΎΏ])", _lc_after_sep_nl, text)

    return text


def fix_casing_punctuation_srt(srt_text: str, tgt_lang: str) -> str:
    blocks = re.split(r"\n{2,}", srt_text.replace("\r\n", "\n").replace("\r", "\n").strip())
    out_blocks = []

    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 3:
            out_blocks.append(block)
            continue

        idx = lines[0]
        timing = lines[1]
        content = [ln.strip() for ln in lines[2:] if ln.strip()]
        if not idx.strip().isdigit() or not SRT_TIME_RE.match(timing.strip()):
            out_blocks.append(block)
            continue

        merged = " ".join(content)
        merged = fix_casing_punctuation_text(merged, tgt_lang)
        merged = split_balanced_subtitle_line(merged, max_chars=42)
        out_blocks.append("\n".join([idx, timing] + merged.splitlines()))

    return "\n\n".join(out_blocks) + "\n"


def humanize_greek(text: str) -> str:
    t = text or ""
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\s+([,.;:!?])", r"\1", t)
    t = re.sub(r"\.{4,}", "...", t)

    replacements = [
        (r"\bΘα μπορούσες να το πεις αυτό\b", "Θα έλεγες"),
        (r"\bΜακρή μέρα\b", "Μεγάλη μέρα"),
        (r"\bΗ κυρά\b", "Η γυναίκα"),
        (r"\bμόλις έκανες μωρό\b", "μόλις απέκτησες μωρό"),
        (r"\bέκανε μωρό\b", "απέκτησε μωρό"),
        (r"\bκάνει βόλτες αυτή τη στιγμή\b", "κάνει βόλτα τώρα"),
        (r"\bπακέτ[αες]\b", "αγέλη"),
        (r"\bκάνει ευθανασία\b", "προχωρά σε ευθανασία"),
        (r"\bεκτελούνταν σε ευθανασία\b", "υποβάλλονταν σε ευθανασία"),
        (r"\bκαρδιάστατα\b", "συντετριμμένο"),
        (r"\bκαρδιασμένο\b", "συντετριμμένο"),
        (r"\bπρόνοια των ζώων\b", "ευημερία των ζώων"),
        (r"\bαπειλητικά τραυματισμούς\b", "απειλητικούς τραυματισμούς"),
        (r"\bκλιμακωμένη σύγκρουση\b", "κλιμακούμενη σύγκρουση"),
        (r"\bρούτερ\b", "διαδρομή"),
    ]
    for pat, repl in replacements:
        t = re.sub(pat, repl, t, flags=re.IGNORECASE)

    if looks_like_srt(t):
        blocks = re.split(r"\n{2,}", t.strip())
        out_blocks = []
        for block in blocks:
            lines = block.splitlines()
            if len(lines) < 3:
                out_blocks.append(block)
                continue
            idx = lines[0]
            timing = lines[1]
            content = [ln for ln in lines[2:] if ln.strip()]
            if content:
                merged = " ".join(content)
                merged = split_balanced_subtitle_line(merged, max_chars=42)
                content = merged.splitlines()
            out_blocks.append("\n".join([idx, timing] + content))
        t = "\n\n".join(out_blocks) + "\n"

    return t.strip()


def translate_srt(text: str, src_lang: str, tgt_lang: str):
    blocks = re.split(r"\n{2,}", text.replace("\r\n", "\n").replace("\r", "\n").strip())
    parsed = []
    dialogue_lines = []

    for block in blocks:
        lines = block.splitlines()
        if len(lines) < 2:
            parsed.append(("raw", block))
            continue

        idx = lines[0].strip()
        timing = lines[1].strip()
        content = lines[2:]

        if not idx.isdigit() or not SRT_TIME_RE.match(timing):
            parsed.append(("raw", block))
            continue

        clean_dialogue = []
        for ln in content:
            s = ln.strip()
            if s:
                clean_dialogue.append(s)
                dialogue_lines.append(s)

        parsed.append(("srt", idx, timing, len(clean_dialogue)))

    translated_lines = []
    for part in chunk_list(dialogue_lines, SRT_BATCH_SIZE):
        translated_lines.extend(safe_translate_batch(part, src_lang, tgt_lang))

    out_blocks = []
    pos = 0
    for item in parsed:
        if item[0] == "raw":
            out_blocks.append(item[1])
            continue

        _, idx, timing, count = item
        lines = translated_lines[pos:pos + count]
        pos += count

        merged = " ".join(lines).strip()
        if tgt_lang == "el" and SMART_MODE:
            merged = humanize_greek(merged)

        merged = split_balanced_subtitle_line(merged, max_chars=42)
        out_blocks.append("\n".join([idx, timing] + merged.splitlines()))

    result = "\n\n".join(out_blocks) + "\n"
    if FIX_CASING:
        result = fix_casing_punctuation_srt(result, tgt_lang)
    return result


def translate_text_fast(text: str, src_lang: str, tgt_lang: str):
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    if not paragraphs:
        return safe_translate_text(text, src_lang, tgt_lang)

    translated_parts = []
    for part in chunk_list(paragraphs, TEXT_BATCH_SIZE):
        translated_parts.extend(safe_translate_batch(part, src_lang, tgt_lang))

    result = "\n\n".join(translated_parts)
    if tgt_lang == "el" and SMART_MODE:
        result = humanize_greek(result)
    if FIX_CASING:
        result = fix_casing_punctuation_text(result, tgt_lang)
    return result


app = Flask(__name__)
CORS(
    app,
    resources={r"/api/*": {"origins": "*"}},
    allow_headers=["Content-Type"],
    methods=["GET", "POST", "OPTIONS"]
)

GLOSSARY = load_map_file(GLOSSARY_FILE)
POST_RULES = load_map_file(POST_RULES_FILE)


@app.get("/")
def home():
    return render_template("index.html", title=APP_TITLE)


@app.route("/api/translate", methods=["POST", "OPTIONS"])
def api_translate():
    if request.method == "OPTIONS":
        return jsonify({"ok": True})

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    src = data.get("src_lang", "auto")
    tgt = data.get("tgt_lang", "el")

    if src not in LANG_MAP:
        src = "auto"
    if tgt not in LANG_MAP:
        tgt = "el"

    if not text:
        return jsonify({"ok": True, "result": "", "glossary_hits": 0, "post_hits": 0})

    work = text
    glossary_hits = 0
    post_hits = 0

    if USE_GLOSSARY and GLOSSARY:
        work, glossary_hits = apply_map(work, GLOSSARY)

    if looks_like_srt(work):
        translated = translate_srt(work, src, tgt)
    else:
        translated = translate_text_fast(work, src, tgt)

    if USE_POST_RULES and POST_RULES:
        translated, post_hits = apply_map(translated, POST_RULES)

    if FIX_CASING:
        if looks_like_srt(translated):
            translated = fix_casing_punctuation_srt(translated, tgt)
        else:
            translated = fix_casing_punctuation_text(translated, tgt)

    return jsonify({
        "ok": True,
        "result": translated,
        "glossary_hits": glossary_hits,
        "post_hits": post_hits
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)