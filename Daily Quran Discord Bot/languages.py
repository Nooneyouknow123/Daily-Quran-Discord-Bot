import json
from pathlib import Path

LANGUAGE_DIR = Path("quranlanguages")
REGISTRY_FILE = LANGUAGE_DIR / "languages.json"

LANGUAGES = {}
VERSE_MAPS = {}
VERSE_LINES = {}


def load_languages():
    global LANGUAGES, VERSE_MAPS, VERSE_LINES

    if not REGISTRY_FILE.exists():
        raise FileNotFoundError(
            f"Language registry not found: {REGISTRY_FILE}"
        )

    with open(REGISTRY_FILE, "r", encoding="utf-8") as file:
        LANGUAGES = json.load(file)

    if "en" not in LANGUAGES:
        raise ValueError("The language registry must contain English (en).")

    if "ar" not in LANGUAGES:
        raise ValueError("The language registry must contain Arabic (ar).")

    loaded_maps = {}
    loaded_lines = {}

    for code, details in LANGUAGES.items():
        filename = details.get("file")
        language_name = details.get("name")

        if not filename or not language_name:
            raise ValueError(
                f"Invalid language registry entry: {code}"
            )

        file_path = LANGUAGE_DIR / filename

        if not file_path.is_file():
            raise FileNotFoundError(
                f"Translation file for {language_name} not found: "
                f"{file_path}"
            )

        verse_map = {}
        verse_lines = []

        with open(file_path, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()

                if not line or line.startswith("#"):
                    continue

                parts = line.split("|", 2)

                if len(parts) != 3:
                    raise ValueError(
                        f"Invalid verse format in {filename}: {line}"
                    )

                reference = f"{parts[0]}|{parts[1]}"

                if reference in verse_map:
                    raise ValueError(
                        f"Duplicate verse reference {reference} "
                        f"in {filename}"
                    )

                verse_map[reference] = parts[2]
                verse_lines.append(line)

        if not verse_map:
            raise ValueError(
                f"No verses found in translation file: {filename}"
            )

        loaded_maps[code] = verse_map
        loaded_lines[code] = verse_lines

    english_references = set(loaded_maps["en"])

    for code, verse_map in loaded_maps.items():
        if set(verse_map) != english_references:
            missing = english_references - set(verse_map)
            extra = set(verse_map) - english_references

            raise ValueError(
                f"Verse references in {LANGUAGES[code]['file']} "
                f"do not match quran.txt. "
                f"Missing: {len(missing)}, Extra: {len(extra)}"
            )

    VERSE_MAPS = loaded_maps
    VERSE_LINES = loaded_lines


def get_verse(language, reference):
    """Get a complete verse line for a language."""
    if language not in VERSE_MAPS:
        language = "en"

    text = VERSE_MAPS.get(language, {}).get(reference)

    if text is None:
        return None

    surah, verse = reference.split("|", 1)
    return f"{surah}|{verse}|{text}"


def get_verse_text(language, reference):
    """Get only the translated text."""
    if language not in VERSE_MAPS:
        language = "en"

    return VERSE_MAPS.get(language, {}).get(reference)


def get_language_name(language):
    return LANGUAGES.get(language, LANGUAGES["en"])["name"]


def get_language_lines(language):
    if language not in VERSE_LINES:
        language = "en"

    return VERSE_LINES[language]


def get_language_choices(current=""):
    current = current.lower()

    return [
        (code, details["name"])
        for code, details in LANGUAGES.items()
        if current in code.lower()
        or current in details["name"].lower()
    ][:25]


# Load and validate all translations when this module is imported.
load_languages()