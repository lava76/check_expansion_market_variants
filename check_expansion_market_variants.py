import sys
import os
import json
import datetime
import shutil
from collections import defaultdict


class Issues(list):
    fixed_count = 0


class App:
    def __init__(self):
        self.folders = defaultdict(dict)
        self.files_count = 0
        self.modified_categories = {}
        self.all_parents = {}
        self.all_variants = defaultdict(list)
        self.issues = defaultdict(Issues)
        self.issues_count = 0
        self.fixed_count = 0
    
    def load_items(self, folder_path):
        for i, c in enumerate('"<>|'):
            if c in folder_path:
                print(f"[E] Invalid character {c} in folder path:")
                print(f"    {folder_path}")
                print( "   ", "-" * folder_path.index(c) + "^")
                return False
        
        if not os.path.exists(folder_path):
            print(f"[E] Path does not exist: {folder_path}")
            return False
        
        if not os.path.isdir(folder_path):
            print(f"[E] Not a directory: {folder_path}")
            return False
        
        print(f"Recursively looking for JSON files in: {folder_path}")
        
        for (root, dirs, files) in os.walk(folder_path):
            for filename in files:
                if filename.lower().endswith(".json"):
                    file_path = os.path.join(root, filename)
                    
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    
                    except Exception as e:
                        print(f"Error processing file {file_path}: {e}")
                        continue
                    
                    self.folders[folder_path][file_path] = data
                    self.files_count += 1
        
        print(f"Found {self.files_count} files")
        
        return True
    
    def process_items(self, options):
        self.options = options
        self.all_parents.clear()
        self.all_variants.clear()
        self.issues.clear()
        self.issues_count = 0
        self.fixed_count = 0
        
        # 1) populate global arrays
        for folder_path, categories in self.folders.items():
            for file_path, data in categories.items():
                items = data.get("Items", [])
                
                for item in items:
                    parent_lower = item.get("ClassName", "").lower()
                    
                    if parent_lower in self.all_parents:
                        # Market system deals with duplicates
                        continue
                    
                    self.all_parents[parent_lower] = item
                    variants = item.get("Variants", [])
                    
                    for variant in variants:
                        variant_lower = variant.lower()
                        self.all_variants[variant_lower].append(parent_lower)
        
        # 2) process
        for folder_path, categories in self.folders.items():
            for file_path, data in categories.items():
                file_path_rel = os.path.relpath(file_path, folder_path)
                items = data.get("Items", [])
                
                for item in items:
                    parent_lower = item.get("ClassName", "").lower()
                    variants = item.get("Variants", [])
                    
                    #self._process_item_parents(data, parent_lower, folder_path, file_path_rel)
                    
                    for variant in variants:
                        variant_lower = variant.lower()
                        self._process_variant(data, item, variant_lower, self.all_variants[variant_lower], folder_path, file_path_rel)
        
        if self.issues_count > 0:
            print("")
    
    def _process_item_parents(self, data, item_lower, folder_path, file_path_rel):
        for parent_lower in self.all_variants.get(item_lower, []):
            for parent_parent_lower in self.all_variants.get(parent_lower, []):
                if parent_parent_lower != item_lower:
                    self._add_issue(folder_path, file_path_rel, f"[W] '{item_lower}' is a variant of '{parent_lower}'\n      which is itself a variant of '{parent_parent_lower}'")
                    
                    if self._confirm_fix(folder_path, file_path_rel, data):
                        self._update_variants(item_lower, self.all_parents[parent_lower])
    
    def _process_variant(self, data, item, variant_lower, parents, folder_path, file_path_rel):
        same_parent_counts = {}
        
        for parent_lower in parents:
            if variant_lower == parent_lower:
                self._add_issue(folder_path, file_path_rel, f"[W] '{variant_lower}' lists itself as a variant")
                parents.remove(parent_lower)  # don't repeat the error for the same variant
                
                if self._confirm_fix(folder_path, file_path_rel, data):
                    self._update_variants(variant_lower, item)
            else:
                same_parent_count = same_parent_counts.get(parent_lower, 0)
                same_parent_counts[parent_lower] = same_parent_count + 1
        
        variants = self.all_parents.get(variant_lower, {}).get("Variants", [])
        
        if variants:
            for parent_lower in parents:
                if parent_lower != variant_lower:
                    self._add_issue(folder_path, file_path_rel, f"[W] '{variant_lower}' lists own variants but is a variant of '{parent_lower}'")
                    
                    if self._confirm_fix(folder_path, file_path_rel, data):
                        self._update_variants(variant_lower, self.all_parents[parent_lower])
        
        if len(parents) > 1:
            for parent_lower, same_parent_count in same_parent_counts.items():
                if same_parent_count > 1:
                    self._add_issue(folder_path, file_path_rel, f"[E] '{parent_lower}' lists variant '{variant_lower}' {same_parent_count} times")
                    
                    while same_parent_count:
                        parents.remove(parent_lower)  # don't repeat the error for the same variant
                        same_parent_count -= 1
                        
                    if self._confirm_fix(folder_path, file_path_rel, data):
                        self._update_variants(variant_lower, self.all_parents[parent_lower], True)
            
            if parents:
                self._add_issue(folder_path, file_path_rel, f"[E] '{variant_lower}' is a variant of more than one item:\n      '{'\', \''.join(parents)}'")
                
                if self._confirm_fix(folder_path, file_path_rel, data):
                    for parent_lower in parents[1:]:
                        self._update_variants(variant_lower, self.all_parents[parent_lower])
                
                parents.clear()  # don't repeat the error for the same variant
    
    def _add_issue(self, folder_path, file_path_rel, errormsg):
        self.issues[(folder_path, file_path_rel)].append(errormsg)
        self.issues_count += 1
    
    def _confirm_fix(self, folder_path, file_path_rel, data):
        if self.options["--dry-run"]:
            return False
        
        if not self.options["--noninteractive"]:
            print(list(self.issues.values())[-1][-1])
            
            if input("Automatically fix this issue (y/n)?").lower() != "y":
                return False
            
        else:
            print("Fixing", list(self.issues.values())[-1][-1])
        
        file_path = os.path.join(folder_path, file_path_rel)
        self.modified_categories[file_path] = data
        self.issues[(folder_path, file_path_rel)].fixed_count += 1
        self.fixed_count += 1

        return True
    
    def _update_variants(self, variant_lower, parent, add=False):
        variants = []
        
        for i, variant in enumerate(parent.get("Variants", [])):
            if variant.lower() != variant_lower or add:
                variants.append(variant)
                add = False
        
        parent["Variants"] = variants
    
    def save_changes(self):
        for file_path, data in self.modified_categories.items():
            timestamp = datetime.datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%dT%H-%M-%S')
            backup = f"{file_path}.{timestamp}.bak"
            
            print(f"Creating backup {backup}")
            
            if not shutil.copyfile(file_path, backup):
                print("ERROR: Couldn't create backup file - not overwriting existing file")
                continue
            
            print(f"Saving {file_path}")
            
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=4)
                # print(json.dumps(data, indent=4))
            
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
                continue
        
        if self.modified_categories:
            print("")
        
    def dump_details(self):
        if self.issues:
            for (folder_path, file_path_rel), issues in self.issues.items():
                if issues.fixed_count > 0:
                    print(f"! Fixed {issues.fixed_count}/{len(issues)} issue(s) in file: {file_path_rel}")
                else:
                    print(f"! Found {len(issues)} issue(s) in file: {file_path_rel}")
                
                for errormsg in issues:
                    print('-', errormsg)
                
                print("")
    
    def dump_summary(self):
        if self.fixed_count > 0:
            print(f"Fixed {self.fixed_count}/{self.issues_count} issue(s) in {len(self.issues)} file(s)")
        else:
            print(f"Found {self.issues_count} issue(s) in {len(self.issues)} file(s)")
    
    def main(self, args):
        if "--help" in args:
            print(f"Usage: {sys.argv[0]} [--noninteractive] [--dry-run] [market folder path]")
            print("Uses current working directory if no market folder path given")
            sys.exit()
        
        options = {"--noninteractive": False,
                   "--dry-run": False}
        
        original_args = args[:]
        
        for i, arg in enumerate(original_args):
            if arg in options:
                options[arg] = True
                args.remove(arg)
            elif i < len(original_args) - 1:
                print(f"Unknown option {arg}")
                args.remove(arg)
        
        result = True
        
        if args:
            for arg in args:
                result &= self.load_items(arg)
        else:
            result &= self.load_items(os.getcwd())
        
        if not options["--dry-run"]:
            tmp = options.copy()
            tmp["--dry-run"] = True
            
            self.process_items(tmp)
            
            if self.issues_count > 0:
                self.dump_details()
                self.dump_summary()
            
                print("")
        
        if not options["--noninteractive"]:
            if self.issues_count > 0:
                if input("Automatically fix these issues (y/n)?").lower() == "y":
                    tmp["--noninteractive"] = True
                    tmp["--dry-run"] = False
                    self.process_items(tmp)
                else:
                    sys.exit()

        else:
            self.process_items(options)
            
            if self.issues_count > 0 and self.fixed_count == 0:
                self.dump_details()
        
        self.save_changes()
        
        if self.fixed_count > 0 and self.fixed_count < self.issues_count:
            self.dump_details()
        
        if result:
            self.dump_summary()
        
        if not options["--noninteractive"]:
            print("")
            input("Press ENTER to exit")
        
        if not result:
            sys.exit(1)


if __name__ == "__main__":
    app = App()
    app.main(sys.argv[1:])
