#!/usr/bin/env python3
"""Concierge v1 — opens a signup page, fills in what it can from profile.json, and
waits for you to review and submit manually. It never clicks submit itself."""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

AGENT_DIR = Path(__file__).resolve().parent
PROFILE_PATH = AGENT_DIR / "profile.json"
LOG_DIR = AGENT_DIR / "logs"

# Ordered most-specific first so e.g. "first_name" wins over the generic "full_name" catch-all.
FIELD_SYNONYMS = [
    ("first_name", ["first name", "firstname", "fname", "given name"]),
    ("last_name", ["last name", "lastname", "lname", "surname", "family name"]),
    ("email", ["email", "e-mail", "emailaddress"]),
    ("phone", ["phone", "telephone", "mobile", "cell number"]),
    ("address_line2", ["address line 2", "address 2", "apt", "suite", "unit", "addr2"]),
    ("address_line1", ["address line 1", "street address", "address", "street", "addr1"]),
    ("city", ["city", "town"]),
    ("zip", ["zip", "postal code", "postcode"]),
    ("state", ["state", "province", "region"]),
    ("country", ["country"]),
    ("job_title", ["job title", "position", "role"]),
    ("company", ["company", "organization", "organisation", "business name", "employer"]),
    ("website", ["website", "web site", "homepage", "url"]),
    ("birthday", ["birthday", "birth date", "date of birth", "dob"]),
    ("username_preference", ["username", "user name", "handle"]),
    ("full_name", ["full name", "your name", "name"]),
]

SKIP_INPUT_TYPES = {"submit", "button", "hidden", "file", "checkbox", "radio", "password", "image", "reset"}


def load_profile():
    if not PROFILE_PATH.exists():
        sys.exit(f"No profile found at {PROFILE_PATH}")
    with open(PROFILE_PATH) as f:
        return json.load(f)


def match_field(signature, profile):
    signature = signature.lower()
    for profile_key, synonyms in FIELD_SYNONYMS:
        value = profile.get(profile_key)
        if not value:
            continue
        for synonym in synonyms:
            if re.search(r"\b" + re.escape(synonym) + r"\b", signature):
                return profile_key, value
    return None, None


def label_text_for(page, element_handle):
    try:
        el_id = element_handle.get_attribute("id")
        if el_id:
            label = page.query_selector(f'label[for="{el_id}"]')
            if label:
                return label.inner_text().strip()
        # fall back to a wrapping <label>
        wrapping = element_handle.evaluate_handle(
            "el => el.closest('label')"
        )
        if wrapping:
            text = wrapping.as_element().inner_text().strip() if wrapping.as_element() else ""
            if text:
                return text
    except Exception:
        pass
    return ""


def collect_candidates(page):
    candidates = []
    for tag, selector in (("input", "input"), ("textarea", "textarea"), ("select", "select")):
        for el in page.query_selector_all(selector):
            try:
                if not el.is_visible():
                    continue
                input_type = (el.get_attribute("type") or "text").lower()
                if tag == "input" and input_type in SKIP_INPUT_TYPES:
                    continue
                name = el.get_attribute("name") or ""
                el_id = el.get_attribute("id") or ""
                placeholder = el.get_attribute("placeholder") or ""
                aria_label = el.get_attribute("aria-label") or ""
                label_text = label_text_for(page, el)
                signature = " ".join([name, el_id, placeholder, aria_label, label_text])
                candidates.append((el, tag, signature))
            except Exception:
                continue
    return candidates


def fill_field(el, tag, value):
    if tag == "select":
        try:
            el.select_option(label=str(value))
            return True
        except Exception:
            try:
                el.select_option(value=str(value))
                return True
            except Exception:
                return False
    else:
        try:
            el.fill(str(value))
            return True
        except Exception:
            return False


def main():
    if len(sys.argv) != 2:
        sys.exit("Usage: python concierge.py <signup-url>")

    url = sys.argv[1]
    profile = load_profile()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        print(f"Opening {url} ...")
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(1500)  # let dynamic form fields render

        candidates = collect_candidates(page)
        filled = []
        skipped = []

        for el, tag, signature in candidates:
            profile_key, value = match_field(signature, profile)
            if profile_key and fill_field(el, tag, value):
                filled.append({"field_signature": signature.strip(), "matched_profile_key": profile_key, "value": value})
            else:
                skipped.append(signature.strip() or "(unlabeled field)")

        print(f"\nFilled {len(filled)} field(s):")
        for f in filled:
            print(f"  - {f['matched_profile_key']} -> \"{f['field_signature']}\"")

        if skipped:
            print(f"\n{len(skipped)} field(s) not matched (left blank):")
            for s in skipped:
                print(f"  - {s}")

        LOG_DIR.mkdir(exist_ok=True)
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "url": url,
            "filled": filled,
            "skipped_count": len(skipped),
            "skipped_fields": skipped,
        }
        log_file = LOG_DIR / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        with open(log_file, "w") as f:
            json.dump(log_entry, f, indent=2)
        print(f"\nLog saved to {log_file}")

        print("\nReview the form in the browser window. Concierge will NOT submit it for you.")
        input("Press Enter here when you're done reviewing (this closes the browser)... ")

        browser.close()


if __name__ == "__main__":
    main()
