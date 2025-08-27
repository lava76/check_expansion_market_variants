#!/usr/bin/env python

"""check_expansion_market_variants

Checks and optionally fixes Expansion Market and Traders configuration JSON files.
"""

__author__ = "lava76"
__version__ = "1.2.1"
__license__ = "GPL-3.0-or-later"


import sys
import os
import json
import datetime
import shutil
import traceback
from collections import defaultdict

try:
    from anyascii import anyascii
except ImportError:
    print(
        "WARNING: Could not import anyascii module! Use `pip install anyascii` to install"
    )

    def anyascii(s: str) -> str:
        return s


class Issue(str):
    critical = False
    fixed = False


class Issues(list[Issue]):
    fixed_count = 0


class IssuesDict(defaultdict[Issues]):
    def clear_noncritical(self):
        for key, issues in self.copy().items():
            for issue in list(issues):
                if not issue.critical:
                    issues.remove(issue)

            if not issues:
                self.pop(key)


class App:
    def __init__(self) -> None:
        self.folders = defaultdict(dict)
        self.categories = defaultdict(dict)
        self.files_count = 0
        self.modified_files = {}
        self.all_parents = {}
        self.all_variants = defaultdict(list[str])
        self.issues = IssuesDict(Issues)
        self.issues_count = 0
        self.fixed_count = 0
        self.item_name_to_file_path = {}
        self.item_name_to_data = {}
        self.exitcode = 0

    def load_items(self, folder_path: str) -> bool:
        if not os.path.exists(folder_path):
            print(f"[E] Path does not exist: {folder_path}")
            return False

        if not os.path.isdir(folder_path):
            print(f"[E] Not a directory: {folder_path}")
            return False

        print(f"Recursively looking for JSON files in: {folder_path}")

        folder_files_count = 0

        for root, dirs, files in os.walk(folder_path):
            for filename in files:
                if filename.lower().endswith(".json"):
                    file_path = os.path.join(root, filename)
                    file_path_rel = os.path.relpath(file_path, folder_path)

                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            data = json.load(f)

                    except Exception as e:
                        print(f"Error processing file {file_path}: {e}")
                        continue

                    self.folders[folder_path][file_path_rel] = data
                    category, ext = os.path.splitext(file_path_rel)
                    self.categories[folder_path][category.lower()] = data
                    self.files_count += 1
                    folder_files_count += 1

        print(f"Found {folder_files_count} files")

        return True

    def process_items(self, options: dict) -> tuple[defaultdict[Issues], int]:
        self.options = options
        self.all_parents.clear()
        self.all_variants.clear()
        self.issues.clear_noncritical()
        self.issues_count = 0
        self.fixed_count = 0
        self.item_name_to_file_path.clear()
        self.item_name_to_data.clear()

        try:
            self._process_items()

        except Exception:
            traceback.print_exc()

            if not options["--noninteractive"]:
                print("")
                input("Press ENTER to exit")

            sys.exit(1)

        issues = defaultdict(Issues)

        for key, values in self.issues.items():
            for issue in values:
                issues[key].append(issue)

        return (issues, self.issues_count)

    def _process_items(self) -> None:
        # 1) populate global arrays
        for folder_path, categories in self.folders.items():
            for file_path_rel, data in categories.items():
                if type(data) is not dict:
                    self._add_issue(
                        folder_path,
                        file_path_rel,
                        f"[E] CRITICAL: Data {i} in '{file_path_rel}' is not a JSON object. Removing.",
                        critical=True,
                    )
                    self._fix(folder_path, file_path_rel, data)
                    data.clear()
                    continue

                trader_categories = data.get("Categories")

                if trader_categories is not None:
                    continue

                items = data.get("Items", [])

                if type(items) is not list:
                    self._add_issue(
                        folder_path,
                        file_path_rel,
                        f"[E] CRITICAL: Items in '{file_path_rel}' is not a JSON list. Removing.",
                        critical=True,
                    )
                    self._fix(folder_path, file_path_rel, data)
                    data["Items"] = []
                    continue

                if len(items) > 0:
                    item = items[0]

                    if type(item) is list and len(item) > 0 and type(item[0]) is dict:
                        self._add_issue(
                            folder_path,
                            file_path_rel,
                            f"[E] CRITICAL: Items in '{file_path_rel}' are improperly nested.",
                        )
                        self._fix(folder_path, file_path_rel, data)
                        items = item
                        data["Items"] = items

                for i, item in enumerate(list(items)):
                    if type(item) is not dict:
                        self._add_issue(
                            folder_path,
                            file_path_rel,
                            f"[E] CRITICAL: Item {i} in '{file_path_rel}' is not a JSON object. Removing.",
                            critical=True,
                        )
                        self._fix(folder_path, file_path_rel, data)
                        items.remove(item)
                        continue

                    parent = item.get("ClassName", "")

                    if not parent.strip():
                        self._add_issue(
                            folder_path,
                            file_path_rel,
                            f"[E] Item with empty ClassName in '{file_path_rel}'",
                        )
                        if self._confirm_fix(folder_path, file_path_rel, data):
                            items.remove(item)
                        continue

                    decoded = self._fix_nonascii(
                        data, parent, folder_path, file_path_rel
                    )

                    if decoded != parent:
                        parent = decoded
                        item["ClassName"] = parent

                    parent_lower = parent.lower()

                    variants_orig = item.get("Variants", [])

                    if type(variants_orig) is not list:
                        self._add_issue(
                            folder_path,
                            file_path_rel,
                            f"[E] CRITICAL: Variants of item {parent} in '{file_path_rel}' is not a JSON list. Removing.",
                            critical=True,
                        )
                        self._fix(folder_path, file_path_rel, data)
                        variants_orig.clear()
                        continue

                    atts_orig = item.get("SpawnAttachments", [])

                    if type(atts_orig) is not list:
                        self._add_issue(
                            folder_path,
                            file_path_rel,
                            f"[E] CRITICAL: Attachments of item {parent} in '{file_path_rel}' is not a JSON list. Removing.",
                            critical=True,
                        )
                        self._fix(folder_path, file_path_rel, data)
                        atts_orig.clear()
                        continue

                    existing = self.all_parents.get(parent_lower)

                    if existing:
                        if len(existing.get("Variants", [])) < len(
                            variants_orig
                        ) or len(existing.get("SpawnAttachments", [])) < len(atts_orig):
                            # if the existing item has less variants or attachments, remove it
                            duplicate_data = self.item_name_to_data[parent_lower]
                            duplicate_items = duplicate_data.get("Items", [])
                            duplicate_file_path_rel = self.item_name_to_file_path[
                                parent_lower
                            ]
                            duplicate_item = existing
                        else:
                            duplicate_data = data
                            duplicate_items = items
                            duplicate_file_path_rel = file_path_rel
                            duplicate_item = item

                        self._add_issue(
                            folder_path,
                            duplicate_file_path_rel,
                            f"[E] '{parent_lower}' is a duplicate",
                        )

                        if self._confirm_fix(
                            folder_path, duplicate_file_path_rel, duplicate_data
                        ):
                            for i, tmp in enumerate(duplicate_items):
                                if tmp is duplicate_item:
                                    duplicate_items.pop(i)
                                    break

                        continue

                    self.all_parents[parent_lower] = item
                    self.item_name_to_file_path[parent_lower] = file_path_rel
                    self.item_name_to_data[parent_lower] = data

                    variants = []

                    for variant in variants_orig:
                        if not variant.strip():
                            self._add_issue(
                                folder_path,
                                file_path_rel,
                                f"[E] Empty variant for item `{parent}` in '{file_path_rel}'",
                            )
                            if self._confirm_fix(folder_path, file_path_rel, data):
                                continue

                        decoded = self._fix_nonascii(
                            data, variant, folder_path, file_path_rel
                        )

                        if decoded != variant:
                            variant = decoded

                        variants.append(variant)

                        variant_lower = variant.lower()
                        self.all_variants[variant_lower].append(parent_lower)

                    if variants != variants_orig:
                        item["Variants"] = variants

        # 2) process
        for folder_path, categories in self.folders.items():
            attachments_to_add = {}

            for file_path_rel, data in categories.items():
                trader_categories = data.get("Categories")

                if trader_categories is not None:
                    self._process_trader_categories(
                        data,
                        trader_categories,
                        data.get("Items", {}),
                        folder_path,
                        file_path_rel,
                    )
                    continue

                items = data.get("Items", [])

                for item in items:
                    parent = item.get("ClassName", "")
                    parent_lower = parent.lower()
                    variants = item.get("Variants", [])

                    # self._process_item_parents(data, parent_lower, folder_path, file_path_rel)

                    for variant in variants:
                        variant_lower = variant.lower()
                        self._process_variant(
                            data,
                            item,
                            variant_lower,
                            self.all_variants[variant_lower],
                            folder_path,
                            file_path_rel,
                        )

                    atts_orig = item.get("SpawnAttachments", [])

                    atts = []

                    for attachment_name in atts_orig:
                        if not attachment_name.strip():
                            self._add_issue(
                                folder_path,
                                file_path_rel,
                                f"[E] Empty attachment for item `{parent}` in '{file_path_rel}'",
                            )
                            if self._confirm_fix(folder_path, file_path_rel, data):
                                continue

                        decoded = self._fix_nonascii(
                            data, attachment_name, folder_path, file_path_rel
                        )

                        if decoded != attachment_name:
                            attachment_name = decoded

                        atts.append(attachment_name)

                        attachment_name_lower = attachment_name.lower()

                        if (
                            attachment_name_lower not in self.all_parents
                            and attachment_name_lower not in self.all_variants
                            and attachment_name_lower not in attachments_to_add
                        ):
                            self._add_issue(
                                folder_path,
                                file_path_rel,
                                f"[E] Attachment '{attachment_name}' on {parent} does not exist in market",
                            )

                            if self._confirm_fix(folder_path, file_path_rel, data):
                                attachments_to_add[attachment_name_lower] = {
                                    "ClassName": attachment_name,
                                    "MaxPriceThreshold": 0,
                                    "MinPriceThreshold": 0,
                                    "SellPricePercent": 0.0,
                                    "MaxStockThreshold": 1,
                                    "MinStockThreshold": 1,
                                    "QuantityPercent": -1,
                                    "SpawnAttachments": [],
                                    "Variants": [],
                                }
                            else:
                                attachments_to_add[attachment_name_lower] = (
                                    None  # don't repeat the error for the same attachment
                                )

                    if atts != atts_orig:
                        item["SpawnAttachments"] = atts

            if attachments_to_add:
                items = []
                data = {
                    "m_Version": 12,
                    "DisplayName": "Missing attachments added by Expansion Market and Trader configuration checker (https://github.com/lava76/check_expansion_market_variants)",
                    "Icon": "",
                    "Color": "",
                    "IsExchange": 0,
                    "InitStockPercent": 75,
                    "Items": items,
                }

                for attachment in attachments_to_add.values():
                    if attachment:
                        items.append(attachment)

                num = 1
                while True:
                    file_path_rel = f"Missing_Attachments_{num}.json"
                    file_path = os.path.join(folder_path, file_path_rel)
                    if not os.path.exists(file_path):
                        categories[file_path_rel] = data
                        self.modified_files[file_path] = data
                        break
                    num += 1

        if self.issues_count > 0:
            print("")

    def _fix_nonascii(
        self, data: dict, name: str, folder_path: str, file_path_rel: str
    ) -> str:
        decoded = anyascii(name)

        if decoded != name:
            self._add_issue(
                folder_path,
                file_path_rel,
                f"[E] Non-ASCII characters in '{name}'",
            )
            if self._confirm_fix(folder_path, file_path_rel, data):
                return decoded

        return name

    def _process_item_parents(
        self, data: dict, item_lower: str, folder_path: str, file_path_rel: str
    ) -> None:
        for parent_lower in self.all_variants.get(item_lower, []):
            for parent_parent_lower in self.all_variants.get(parent_lower, []):
                if parent_parent_lower != item_lower:
                    self._add_issue(
                        folder_path,
                        file_path_rel,
                        f"[W] '{item_lower}' is a variant of '{parent_lower}'\n      which is itself a variant of '{parent_parent_lower}'",
                    )

                    if self._confirm_fix(folder_path, file_path_rel, data):
                        self._update_variants(
                            item_lower, self.all_parents[parent_lower]
                        )

    def _process_variant(
        self,
        data: dict,
        item: dict,
        variant_lower: str,
        parents: list[str],
        folder_path: str,
        file_path_rel: str,
    ) -> None:
        same_parent_counts = {}

        for parent_lower in parents:
            if variant_lower == parent_lower:
                self._add_issue(
                    folder_path,
                    file_path_rel,
                    f"[W] '{variant_lower}' lists itself as a variant",
                )
                parents.remove(
                    parent_lower
                )  # don't repeat the error for the same variant

                if self._confirm_fix(folder_path, file_path_rel, data):
                    self._update_variants(variant_lower, item)
            else:
                same_parent_count = same_parent_counts.get(parent_lower, 0)
                same_parent_counts[parent_lower] = same_parent_count + 1

        variants = self.all_parents.get(variant_lower, {}).get("Variants", [])

        if variants:
            for parent_lower in parents:
                if parent_lower != variant_lower:
                    self._add_issue(
                        folder_path,
                        file_path_rel,
                        f"[W] '{variant_lower}' lists own variants but is a variant of '{parent_lower}'",
                    )

                    if self._confirm_fix(folder_path, file_path_rel, data):
                        self._update_variants(
                            variant_lower, self.all_parents[parent_lower]
                        )

        if len(parents) > 1:
            for parent_lower, same_parent_count in same_parent_counts.items():
                if same_parent_count > 1:
                    self._add_issue(
                        folder_path,
                        file_path_rel,
                        f"[E] '{parent_lower}' lists variant '{variant_lower}' {same_parent_count} times",
                    )

                    while same_parent_count > 1:
                        parents.remove(
                            parent_lower
                        )  # don't repeat the error for the same variant
                        same_parent_count -= 1

                    if self._confirm_fix(folder_path, file_path_rel, data):
                        self._update_variants(
                            variant_lower, self.all_parents[parent_lower], True
                        )

            if len(parents) > 1:
                self._add_issue(
                    folder_path,
                    file_path_rel,
                    f"[E] '{variant_lower}' is a variant of more than one item:\n      '{"', '".join(parents)}'",
                )

                if self._confirm_fix(folder_path, file_path_rel, data):
                    for parent_lower in parents[1:]:
                        self._update_variants(
                            variant_lower, self.all_parents[parent_lower]
                        )

                parents[1:] = []  # don't repeat the error for the same variant

        if parents:
            variant_file_path_rel = self.item_name_to_file_path.get(variant_lower)
            if variant_file_path_rel and variant_file_path_rel != file_path_rel:
                self._add_issue(
                    folder_path,
                    file_path_rel,
                    f"[E] Variant '{variant_lower}' of '{parents[0]}' is in a different category '{variant_file_path_rel}'",
                )

                if self._confirm_fix(folder_path, file_path_rel, data):
                    # remove variant from category where it was originally defined and add to this category
                    variant_data = self.item_name_to_data[variant_lower]
                    variant = self.all_parents[variant_lower]
                    variant_data["Items"].remove(variant)
                    self._fix(folder_path, variant_file_path_rel, variant_data)
                    data["Items"].append(variant)
                    # self._update_variants(variant_lower, item)

    def _process_trader_categories(
        self,
        data: dict,
        trader_categories: list[str],
        trader_items: dict,
        folder_path: str,
        file_path_rel: str,
    ) -> None:
        category_names_lower = []

        for trader_category in trader_categories:
            if ":" in trader_category:
                category_name, buy_sell = trader_category.split(":", 1)
            else:
                category_name, buy_sell = trader_category, 1

            category_names_lower.append(category_name.lower())

        trader_items_copy = trader_items.copy()
        item_names_lower = []

        for trader_item_name, buy_sell in trader_items_copy.items():
            item_name_lower = trader_item_name.lower()

            if (
                item_name_lower not in self.all_parents
                and item_name_lower not in self.all_variants
            ):
                self._add_issue(
                    folder_path,
                    file_path_rel,
                    f"[E] Item '{trader_item_name}' does not exist in market",
                )

                if self._confirm_fix(folder_path, file_path_rel, data):
                    trader_items.pop(trader_item_name)
                    continue

            item_names_lower.append(trader_item_name.lower())

        for category_name_lower in category_names_lower:
            for category_folder_path, categories in self.categories.items():
                category_data = categories.get(category_name_lower, {})

                if category_data.get("Categories"):
                    continue

                items = category_data.get("Items", [])

                for item in items:
                    self._check_add_trader_categories(
                        item,
                        1,
                        False,
                        False,
                        0,
                        category_names_lower,
                        item_names_lower,
                        data,
                        trader_categories,
                        trader_items,
                        folder_path,
                        file_path_rel,
                    )

    def _check_add_trader_categories(
        self,
        item: dict,
        buy_sell: int,
        is_variant: bool,
        is_attachment: bool,
        level: int,
        category_names_lower: list[str],
        item_names_lower: list[str],
        data: dict,
        trader_categories: list[str],
        trader_items: dict,
        folder_path: str,
        file_path_rel: str,
    ) -> None:
        variants = item.get("Variants", [])

        for variant_name in variants:
            self._check_add_trader_category(
                variant_name,
                buy_sell,
                True,
                is_attachment,
                level,
                category_names_lower,
                item_names_lower,
                data,
                trader_categories,
                trader_items,
                folder_path,
                file_path_rel,
            )

        atts = item.get("SpawnAttachments", [])

        for attachment_name in atts:
            attachment_name_lower = attachment_name.lower()
            is_variant = attachment_name_lower in self.all_variants
            self._check_add_trader_category(
                attachment_name,
                3,
                is_variant,
                True,
                level + 1,
                category_names_lower,
                item_names_lower,
                data,
                trader_categories,
                trader_items,
                folder_path,
                file_path_rel,
            )
            att = self.all_parents.get(attachment_name_lower)
            if att:
                self._check_add_trader_categories(
                    att,
                    3,
                    is_variant,
                    True,
                    level + 1,
                    category_names_lower,
                    item_names_lower,
                    data,
                    trader_categories,
                    trader_items,
                    folder_path,
                    file_path_rel,
                )

    def _check_add_trader_category(
        self,
        item_name: str,
        buy_sell: int,
        is_variant: bool,
        is_attachment: bool,
        level: int,
        category_names_lower: list[str],
        item_names_lower: list[str],
        data: dict,
        trader_categories: list[str],
        trader_items: dict,
        folder_path: str,
        file_path_rel: str,
    ) -> None:
        if not is_variant or not is_attachment:
            return

        item_name_lower = item_name.lower()

        parents = self.all_variants[item_name_lower]

        for parent_lower in parents:
            if parent_lower in item_names_lower:
                return

            data_file_path_rel = self.item_name_to_file_path[parent_lower]
            category, ext = os.path.splitext(data_file_path_rel)

            category_lower = category.lower()

            if category_lower not in category_names_lower:
                self._add_issue(
                    folder_path,
                    file_path_rel,
                    f"[E] Category '{category}' is missing from trader '{file_path_rel}'",
                )
                category_names_lower.append(
                    category_lower
                )  # don't repeat the error for the same category

                if self._confirm_fix(folder_path, file_path_rel, data):
                    trader_categories.append(f"{category}:{buy_sell}")

        # if item_name_lower not in item_names_lower:
        # self._add_issue(folder_path, file_path_rel, f"[E] Item {name} in category '{category}' is missing from trader '{file_path_rel}'")
        # item_names_lower.append(item_name_lower)  # don't repeat the error for the same item

        # if self._confirm_fix(folder_path, file_path_rel, data):
        # trader_items[item_name_lower] = buy_sell

    def _add_issue(
        self,
        folder_path: str,
        file_path_rel: str,
        errormsg: str,
        critical: bool = False,
    ) -> None:
        issue = Issue(errormsg)
        issue.critical = critical
        self.issues[(folder_path, file_path_rel)].append(issue)
        self.issues_count += 1

    def _confirm_fix(self, folder_path: str, file_path_rel: str, data: dict) -> bool:
        if self.options["--dry-run"]:
            return False

        issue = list(self.issues.values())[-1][-1]

        if not self.options["--noninteractive"]:
            print(issue)

            if input("Automatically fix this issue (y/n)?").lower() != "y":
                return False

        else:
            print("Fixing", issue)
            issue.fixed = True

        self._fix(folder_path, file_path_rel, data)

        return True

    def _fix(self, folder_path: str, file_path_rel: str, data: dict) -> None:
        file_path = os.path.join(folder_path, file_path_rel)
        self.modified_files[file_path] = data

        if not self.options["--dry-run"]:
            key = (folder_path, file_path_rel)
            issues = self.issues.get(key)
            if issues:
                issues.fixed_count += 1
                self.fixed_count += 1

    def _update_variants(
        self, variant_lower: str, parent: dict, add: bool = False
    ) -> None:
        variants = []

        for i, variant in enumerate(parent.get("Variants", [])):
            if variant.lower() != variant_lower or add:
                variants.append(variant)
                add = False

        parent["Variants"] = variants

    def save_changes(self) -> None:
        for file_path, data in self.modified_files.items():
            if os.path.exists(file_path):
                timestamp = datetime.datetime.fromtimestamp(
                    os.path.getmtime(file_path)
                ).strftime("%Y-%m-%dT%H-%M-%S")
                backup = f"{file_path}.{timestamp}.bak"

                print(f"Creating backup {backup}")

                if not shutil.copyfile(file_path, backup):
                    print(
                        "ERROR: Couldn't create backup file - not overwriting existing file"
                    )
                    continue

            print(f"Saving {file_path}")

            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=4, ensure_ascii=False)
                # print(json.dumps(data, indent=4))

            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                continue

        if self.modified_files:
            print("")

    def dump_details(self) -> None:
        if self.issues:
            for (folder_path, file_path_rel), issues in self.issues.items():
                if issues.fixed_count > 0:
                    print(
                        f"! Fixed {issues.fixed_count}/{len(issues)} issue(s) in file: {os.path.basename(folder_path)}/{file_path_rel}"
                    )
                else:
                    print(
                        f"! Found {len(issues)} issue(s) in file: {os.path.basename(folder_path)}/{file_path_rel}"
                    )

                if issues.fixed_count < len(issues):
                    for issue in issues:
                        if not issue.fixed:
                            print("-", issue)

                print("")

    def dump_summary(self) -> None:
        if self.fixed_count > 0:
            print(
                f"Fixed {self.fixed_count}/{self.issues_count} issue(s) in {len(self.issues)} file(s)"
            )
        else:
            print(f"Found {self.issues_count} issue(s) in {len(self.issues)} file(s)")

    def main(self, args: list[str]) -> None:
        # https://docs.python.org/3/library/signal.html#note-on-sigpipe
        try:
            self._main(args)

            # flush output here to force SIGPIPE to be triggered
            # while inside this try block.
            sys.stdout.flush()

        except BrokenPipeError:
            # Python flushes standard streams on exit; redirect remaining output
            # to devnull to avoid another BrokenPipeError at shutdown
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
            sys.exit(1)  # Python exits with error code 1 on EPIPE

    def _main(self, args: list[str]) -> None:
        if "--help" in args:
            print(
                f"Usage: {sys.argv[0]} [--noninteractive] [--dry-run] [ExpansionMod folder path]"
            )
            print("Uses current working directory if no folder path given")
            sys.exit(1)

        options = {"--noninteractive": not sys.stdout.isatty(), "--dry-run": False}

        folder_paths = []
        invalid_arg = None

        for i, arg in enumerate(args):
            if arg in options:
                options[arg] = True
            else:
                arg = arg.strip('"')

                for c in "<>|":
                    if c in arg:
                        print(f"[E] Invalid character {c} in argument {i + 1}:")
                        print(f"    {arg}")
                        print("   ", "-" * arg.index(c) + "^")
                        invalid_arg = arg
                        break
                else:
                    if os.path.isdir(arg):
                        folder_paths.append(arg)
                    else:
                        print(f"Unknown option {arg}")

        if not folder_paths and not invalid_arg:
            cwd = os.getcwd()
            if os.path.basename(cwd).lower() in (
                "expansionmod",
                "market",
                "traders",
            ):
                folder_paths.append(cwd)

        if not options["--noninteractive"]:
            while not folder_paths:
                print("Drag & drop ExpansionMod folder here, then press ENTER")
                folder_path = input()

                if not folder_path:
                    sys.exit(1)

                folder_path = folder_path.strip().strip('"')

                if os.path.isdir(folder_path):
                    folder_paths.append(folder_path)
                    break
                else:
                    print("Not a valid folder path!")

        if len(folder_paths) == 1:
            folder_path = folder_paths[0]
            folder_name_lower = os.path.basename(folder_path).lower()

            if folder_name_lower == "market":
                trader_folder_path = os.path.abspath(
                    os.path.join(folder_path, "..", "Traders")
                )

                if os.path.isdir(trader_folder_path):
                    folder_paths.append(trader_folder_path)

            elif folder_name_lower == "traders":
                market_folder_path = os.path.abspath(
                    os.path.join(folder_path, "..", "Market")
                )

                if os.path.isdir(market_folder_path):
                    folder_paths.append(market_folder_path)

            else:
                market = os.path.join(folder_path, "Market")
                traders = os.path.join(folder_path, "Traders")

                if os.path.isdir(market):
                    folder_paths.append(market)

                if os.path.isdir(traders):
                    folder_paths.append(traders)

                if len(folder_paths) > 1:
                    folder_paths.pop(0)

        results = []

        for folder_path in sorted(folder_paths):
            results.append(self.load_items(folder_path))

        print(f"Total {self.files_count} files")

        if not options["--noninteractive"] and not options["--dry-run"]:
            tmp = options.copy()
            tmp["--dry-run"] = True

            issues, issues_count = self.process_items(tmp)

            if self.issues_count > 0:
                self.dump_details()
                self.dump_summary()

                print("")

            if self.issues_count > 0:
                if input("Automatically fix these issues (y/n)?").lower() == "y":
                    tmp["--noninteractive"] = True
                    tmp["--dry-run"] = False
                    self.process_items(tmp)
                else:
                    sys.exit(1)

        else:
            issues, issues_count = self.process_items(options)

            if self.issues_count > 0 and self.fixed_count == 0:
                self.dump_details()

        # do additional passes if not all originally detected issues were fixed
        # TODO should probably try and figure out why corner cases exist were
        # not all issues are fixed in one pass
        if not options["--dry-run"] and issues_count > self.fixed_count:
            self.issues_count = issues_count
            self.dump_summary()

            print("WARNING: Not all issues fixed in 1st pass")

            tmp["--noninteractive"] = True

            while self.fixed_count > 0:
                print("Doing additional pass...")
                self.process_items(tmp)

            self.issues = issues
            self.issues_count = issues_count
            self.fixed_count = issues_count

        if self.exitcode == 0:
            if not options["--dry-run"]:
                self.save_changes()

            if not options["--dry-run"] and self.fixed_count < self.issues_count:
                self.dump_details()

            if any(results):
                self.dump_summary()

        if not options["--noninteractive"]:
            print("")
            input("Press ENTER to exit")

        if not results or not all(results):
            sys.exit(1)

        sys.exit(self.exitcode)


if __name__ == "__main__":
    app = App()
    app.main(sys.argv[1:])
