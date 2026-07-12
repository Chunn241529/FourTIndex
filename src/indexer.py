import os
import re
import sys
import yaml
import ast
import hashlib
import json
import pathspec
from src.config import Config

EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".swift": "swift",
    ".cs": "c_sharp",
    ".cpp": "cpp",
    ".h": "cpp",
    ".gd": "gdscript",
    ".lua": "lua",
}

class Indexer:
    def __init__(self, config: Config):
        self.config = config
        self.hashes_file = os.path.join(os.path.dirname(self.config.db_persist_directory), "file_hashes.json")
        self.file_hashes = self.load_file_hashes()

    def load_file_hashes(self) -> dict:
        """Loads file hashes from local json file to avoid re-indexing unchanged files."""
        if os.path.exists(self.hashes_file):
            try:
                with open(self.hashes_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                sys.stderr.write(f"Warning: Failed to load file hashes: {e}\n")
        return {}

    def save_file_hashes(self):
        """Saves current file hashes to local json file."""
        os.makedirs(os.path.dirname(self.hashes_file), exist_ok=True)
        try:
            with open(self.hashes_file, "w", encoding="utf-8") as f:
                json.dump(self.file_hashes, f, indent=2)
        except Exception as e:
            sys.stderr.write(f"Warning: Failed to save file hashes: {e}\n")

    def compute_file_hash(self, file_path: str) -> str:
        """Computes SHA256 hash of a file's content."""
        hasher = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                while chunk := f.read(8192):
                    hasher.update(chunk)
            return hasher.hexdigest()
        except Exception:
            return ""

    def scan_files(self, project_root: str) -> list[str]:
        """Recursively scans the project directory for supported files, applying exclusion rules."""
        project_root = os.path.abspath(project_root)
        matched_files = []
        ignore_lines = list(self.config.exclude_globs)
        default_ignores = [
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "bun.lockb",
            "*.min.js",
            "*.min.css",
            "*.map"
        ]
        for item in default_ignores:
            if item not in ignore_lines:
                ignore_lines.append(item)
        if self.config.respect_gitignore:
            for ignore_name in (".gitignore", ".fourtindexignore"):
                ignore_path = os.path.join(project_root, ignore_name)
                if os.path.exists(ignore_path):
                    try:
                        with open(ignore_path, "r", encoding="utf-8", errors="replace") as file:
                            ignore_lines.extend(file.read().splitlines())
                    except OSError:
                        pass
        ignore_spec = pathspec.GitIgnoreSpec.from_lines(ignore_lines)
        
        exclude_dirs = [os.path.normpath(os.path.join(project_root, d)) for d in self.config.exclude_dirs]
        exclude_names = set(self.config.exclude_dirs)

        for root, dirs, files in os.walk(project_root):
            # Prune directory search path in-place to ignore excluded folders
            dirs[:] = [
                d for d in dirs 
                if d not in exclude_names
                and os.path.abspath(os.path.join(root, d)) not in exclude_dirs
                and not ignore_spec.match_file(
                    os.path.relpath(os.path.join(root, d), project_root).replace("\\", "/") + "/"
                )
            ]

            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.config.supported_extensions:
                    full_path = os.path.join(root, file)
                    relative_path = os.path.relpath(full_path, project_root).replace("\\", "/")
                    try:
                        file_size = os.path.getsize(full_path)
                    except OSError:
                        continue
                    if (
                        not ignore_spec.match_file(relative_path)
                        and file_size <= self.config.max_file_size_bytes
                    ):
                        matched_files.append(full_path)
                    
        return matched_files

    def parse_with_tree_sitter(self, content: str, file_path: str, relative_path: str, lang_name: str) -> list[dict]:
        """Parses a file using tree-sitter to extract class/container outlines and functions/methods."""
        from src.tree_sitter_compat import get_tree_sitter_parser

        parser = get_tree_sitter_parser(lang_name)
        if not parser:
            raise ValueError(f"Failed to load tree-sitter parser for {lang_name}")

        tree = parser.parse(bytes(content, "utf-8"))
        
        lines = content.splitlines()
        total_lines = len(lines)
        chunks = []
        covered_lines = set()

        # Classification matchers
        def is_container_node(node) -> bool:
            return any(sub in node.type for sub in [
                "class_specifier", "struct_specifier", "interface_declaration", 
                "trait_item", "enum_definition", "class_definition", 
                "class_declaration", "struct_declaration", "struct_definition", 
                "enum_declaration"
            ])

        def is_functional_node(node) -> bool:
            return any(sub in node.type for sub in [
                "function", "method", "procedure", "arrow_function", 
                "method_specifier", "function_item"
            ])

        def extract_name(node) -> str:
            name_node = node.child_by_field_name("name")
            if name_node and name_node.text:
                return name_node.text.decode("utf-8", errors="replace")
            
            for child in node.children:
                if child.type in ("identifier", "type_identifier", "property_identifier", "field_identifier"):
                    if child.text:
                        return child.text.decode("utf-8", errors="replace")
            
            def find_first_ident(n):
                if n.type in ("identifier", "type_identifier", "property_identifier"):
                    return n.text.decode("utf-8", errors="replace") if n.text else None
                for c in n.children:
                    res = find_first_ident(c)
                    if res:
                        return res
                return None
            return find_first_ident(node) or ""

        def get_container_name(node) -> str:
            parts = []
            curr = node
            while curr:
                if is_container_node(curr):
                    name = extract_name(curr) or f"Anonymous_{curr.start_point[0]+1}"
                    parts.append(name)
                curr = curr.parent
            return ".".join(reversed(parts))

        def get_parent_container(node):
            curr = node.parent
            while curr:
                if is_container_node(curr):
                    return curr
                curr = curr.parent
            return None

        def get_function_name(node) -> str:
            parts = []
            curr = node
            while curr:
                if is_functional_node(curr):
                    name = extract_name(curr) or f"func_{curr.start_point[0]+1}"
                    parts.append(name)
                elif is_container_node(curr):
                    break
                curr = curr.parent
            return ".".join(reversed(parts))

        # Traverse tree to collect definitions
        containers = []
        functions = []

        def collect(node):
            if node.type == "ERROR":
                # Isolate error node, do not recurse into its children
                return
            if is_container_node(node):
                containers.append(node)
            elif is_functional_node(node):
                functions.append(node)
                
            for child in node.children:
                collect(child)

        collect(tree.root_node)

        # 1. Process Containers
        for c in containers:
            c_start = c.start_point[0] + 1
            c_end = c.end_point[0] + 1
            covered_lines.update(range(c_start, c_end + 1))

            c_fullname = get_container_name(c)
            c_name = extract_name(c) or c_fullname
            
            # Find methods directly inside this container (where this container is the closest container parent)
            methods = []
            for f in functions:
                if get_parent_container(f) == c:
                    methods.append(f)

            outline_content = [
                f"# File: {relative_path}",
                f"# Class Outline: class {c_name}",
                f"# Lines: {c_start}-{c_end}"
            ]
            for f in methods:
                f_name = extract_name(f) or "anonymous_method"
                f_start = f.start_point[0] + 1
                f_end = f.end_point[0] + 1
                outline_content.append(f"  def {f_name}(...) # Lines {f_start}-{f_end}")

            chunks.append({
                "content": "\n".join(outline_content),
                "chunk_type": "class_outline",
                "symbol_name": c_fullname,
                "start_line": c_start,
                "end_line": c_end
            })

        # 2. Process Functions/Methods
        for f in functions:
            f_start = f.start_point[0] + 1
            f_end = f.end_point[0] + 1
            covered_lines.update(range(f_start, f_end + 1))

            f_name = extract_name(f) or f"func_{f_start}"
            parent_c = get_parent_container(f)
            
            if parent_c:
                c_fullname = get_container_name(parent_c)
                f_fullname = f"{c_fullname}.{f_name}"
                header = (
                    f"# [CONTEXT] File: {relative_path} | Class: {c_fullname} (Lines {parent_c.start_point[0]+1}-{parent_c.end_point[0]+1})\n"
                    f"# Method: {f_name} | Lines: {f_start}-{f_end}\n"
                    f"--------------------------------------------------\n"
                )
            else:
                f_fullname = get_function_name(f) or f_name
                header = (
                    f"# [CONTEXT] File: {relative_path} (Global Scope)\n"
                    f"# Function: {f_fullname} | Lines: {f_start}-{f_end}\n"
                    f"--------------------------------------------------\n"
                )

            method_code = "\n".join(lines[f_start - 1 : f_end])
            chunks.append({
                "content": header + method_code,
                "chunk_type": "function",
                "symbol_name": f_fullname,
                "start_line": f_start,
                "end_line": f_end
            })

        # 3. Collect Global Scope / Remaining Lines
        global_lines = []
        global_start = None
        
        for idx, line in enumerate(lines, 1):
            if idx not in covered_lines:
                if global_start is None:
                    global_start = idx
                global_lines.append((idx, line))
            else:
                if global_lines:
                    self._add_global_chunk(chunks, global_lines, global_start, idx - 1, relative_path)
                    global_lines = []
                    global_start = None
                    
        if global_lines:
            self._add_global_chunk(chunks, global_lines, global_start, len(lines), relative_path)

        return chunks

    def parse_python_file(self, content: str, file_path: str, relative_path: str) -> list[dict]:
        """Parses a Python file using AST to extract functions, class outlines, and global scopes."""
        try:
            tree = ast.parse(content, filename=file_path)
        except SyntaxError:
            # Fallback to general line-based parser if python syntax is invalid
            return self.parse_generic_file(content, relative_path)

        lines = content.splitlines()
        chunks = []

        # Keep track of lines covered by classes and functions to find "global scope" lines
        covered_lines = set()

        # 1. Parse Class Definitions
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                start = node.lineno
                end = node.end_lineno if hasattr(node, "end_lineno") else len(lines)
                covered_lines.update(range(start, end + 1))

                # Extract Class Outline (Class definition and docstring/fields, without method bodies)
                class_lines = lines[start - 1 : end]
                
                # Create a mini outline representation for embedding
                class_doc = ast.get_docstring(node) or ""
                class_signature = f"class {node.name}"
                if node.bases:
                    bases_list = [ast.unparse(b) for b in node.bases]
                    class_signature += f"({', '.join(bases_list)})"
                
                outline_content = [
                    f"# File: {relative_path}",
                    f"# Class Outline: {class_signature}",
                    f"# Lines: {start}-{end}",
                    f'"""{class_doc}"""' if class_doc else ""
                ]
                
                # Collect method signatures
                methods_list = []
                for subnode in node.body:
                    if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sig = f"  def {subnode.name}(...)"
                        if isinstance(subnode, ast.AsyncFunctionDef):
                            sig = f"  async {sig.strip()}"
                        methods_list.append(sig)
                
                outline_content.extend(methods_list)
                outline_text = "\n".join([line for line in outline_content if line])
                
                chunks.append({
                    "content": outline_text,
                    "chunk_type": "class_outline",
                    "symbol_name": node.name,
                    "start_line": start,
                    "end_line": end
                })

                # Extract each method in the Class as an independent semantic chunk
                for subnode in node.body:
                    if isinstance(subnode, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        sub_start = subnode.lineno
                        sub_end = subnode.end_lineno if hasattr(subnode, "end_lineno") else end
                        method_code = "\n".join(lines[sub_start - 1 : sub_end])
                        
                        # Generate enriched header for the method
                        decorator_list = []
                        for dec in subnode.decorator_list:
                            try:
                                decorator_list.append(f"@{ast.unparse(dec)}")
                            except Exception:
                                pass
                        
                        dec_str = "\n".join(decorator_list) + "\n" if decorator_list else ""
                        
                        header = (
                            f"# [CONTEXT] File: {relative_path} | Class: {node.name} (Lines {start}-{end})\n"
                            f"# Method: {subnode.name} | Lines: {sub_start}-{sub_end}\n"
                            f"--------------------------------------------------\n"
                        )
                        
                        chunks.append({
                            "content": header + dec_str + method_code,
                            "chunk_type": "function",
                            "symbol_name": f"{node.name}.{subnode.name}",
                            "start_line": sub_start,
                            "end_line": sub_end
                        })

        # 2. Parse Top-level Functions
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start = node.lineno
                end = node.end_lineno if hasattr(node, "end_lineno") else len(lines)
                covered_lines.update(range(start, end + 1))
                
                func_code = "\n".join(lines[start - 1 : end])
                
                header = (
                    f"# [CONTEXT] File: {relative_path} (Global Scope)\n"
                    f"# Function: {node.name} | Lines: {start}-{end}\n"
                    f"--------------------------------------------------\n"
                )
                
                chunks.append({
                    "content": header + func_code,
                    "chunk_type": "function",
                    "symbol_name": node.name,
                    "start_line": start,
                    "end_line": end
                })

        # 3. Collect Global Scope / Remaining Lines (Imports, Global vars)
        global_lines = []
        global_start = None
        
        for idx, line in enumerate(lines, 1):
            if idx not in covered_lines:
                if global_start is None:
                    global_start = idx
                global_lines.append((idx, line))
            else:
                if global_lines:
                    self._add_global_chunk(chunks, global_lines, global_start, idx - 1, relative_path)
                    global_lines = []
                    global_start = None
                    
        if global_lines:
            self._add_global_chunk(chunks, global_lines, global_start, len(lines), relative_path)

        return chunks

    def _add_global_chunk(self, chunks: list, line_tuples: list[tuple[int, str]], start: int, end: int, relative_path: str):
        """Helper to format and append a global/generic code block."""
        code = "\n".join([lt[1] for lt in line_tuples])
        # Skip chunks that are purely whitespace or empty
        if not code.strip():
            return
            
        header = (
            f"# [CONTEXT] File: {relative_path} (Global Scope / Imports / Constants)\n"
            f"# Lines: {start}-{end}\n"
            f"--------------------------------------------------\n"
        )
        chunks.append({
            "content": header + code,
            "chunk_type": "global_scope",
            "symbol_name": "",
            "start_line": start,
            "end_line": end
        })

    def parse_generic_file(self, content: str, relative_path: str, chunk_size_lines: int = 50, overlap_lines: int = 10) -> list[dict]:
        """Line-based window splitter for non-Python or configuration files with Context Headers."""
        lines = content.splitlines()
        chunks = []
        
        if not lines:
            return []

        total_lines = len(lines)
        start = 0
        
        while start < total_lines:
            end = min(start + chunk_size_lines, total_lines)
            chunk_code = "\n".join(lines[start:end])
            
            header = (
                f"# [CONTEXT] File: {relative_path}\n"
                f"# Lines: {start + 1}-{end}\n"
                f"--------------------------------------------------\n"
            )
            
            chunks.append({
                "content": header + chunk_code,
                "chunk_type": "generic",
                "symbol_name": "",
                "start_line": start + 1,
                "end_line": end
            })
            
            # Step forward with overlap
            start += (chunk_size_lines - overlap_lines)
            if start >= total_lines or (end == total_lines):
                break
                
        return chunks

    def parse_file(self, file_path: str, relative_path: str) -> list[dict]:
        """Reads and routes a file to the appropriate parser depending on its extension."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            sys.stderr.write(f"Error reading file {file_path}: {e}\n")
            return []

        ext = os.path.splitext(file_path)[1].lower()
        
        # Route through tree-sitter if supported
        tree_sitter_lang = EXTENSION_TO_LANGUAGE.get(ext)
        if tree_sitter_lang:
            try:
                return self.parse_with_tree_sitter(content, file_path, relative_path, tree_sitter_lang)
            except Exception as e:
                sys.stderr.write(f"Warning: Tree-sitter failed for {relative_path} ({tree_sitter_lang}): {e}. Falling back.\n")

        if ext == ".py":
            return self.parse_python_file(content, file_path, relative_path)
        else:
            return self.parse_generic_file(content, relative_path)
            
    def generate_file_outline_summary(self, chunks: list[dict], relative_path: str) -> str:
        """Generates a high-level string outline of the file's components for structural search."""
        outline = [f"File: {relative_path}"]
        classes_info = []
        functions_info = []
        
        for c in chunks:
            if c["chunk_type"] == "class_outline":
                classes_info.append(f"  class {c['symbol_name']} (Lines {c['start_line']}-{c['end_line']})")
            elif c["chunk_type"] == "function" and "." not in c["symbol_name"]:
                functions_info.append(f"  def {c['symbol_name']} (Lines {c['start_line']}-{c['end_line']})")
                
        if classes_info:
            outline.append("Classes/Containers defined:\n" + "\n".join(classes_info))
        if functions_info:
            outline.append("Global Functions defined:\n" + "\n".join(functions_info))
            
        return "\n".join(outline)

    def parse_skill_file(self, file_path: str, relative_path: str) -> tuple[dict, list[dict]]:
        """Parses a SKILL.md file, extracting YAML frontmatter and splitting body by headings."""
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
        except Exception as e:
            sys.stderr.write(f"Error reading skill file {file_path}: {e}\n")
            return {}, []

        # Find frontmatter
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", content, re.DOTALL)
        if match:
            frontmatter_text = match.group(1)
            markdown_body = match.group(2)
            try:
                metadata = yaml.safe_load(frontmatter_text) or {}
            except Exception:
                metadata = {}
        else:
            metadata = {}
            markdown_body = content

        skill_name = metadata.get("name", os.path.basename(os.path.dirname(file_path)))
        skill_desc = metadata.get("description", "")

        lines = markdown_body.splitlines()
        chunks = []
        current_heading = "Overview"
        current_lines = []
        start_line = 1
        
        for idx, line in enumerate(lines, start=1):
            h_match = re.match(r"^(#+)\s+(.*)$", line)
            if h_match:
                if current_lines:
                    chunk_text = "\n".join(current_lines).strip()
                    if chunk_text:
                        header = (
                            f"# [SKILL CONTEXT] Skill: {skill_name} | Section: {current_heading}\n"
                            f"# Description: {skill_desc}\n"
                            f"--------------------------------------------------\n"
                        )
                        chunks.append({
                            "content": header + chunk_text,
                            "heading": current_heading,
                            "start_line": start_line,
                            "end_line": idx - 1
                        })
                current_heading = h_match.group(2).strip()
                current_lines = [line]
                start_line = idx
            else:
                current_lines.append(line)

        if current_lines:
            chunk_text = "\n".join(current_lines).strip()
            if chunk_text:
                header = (
                    f"# [SKILL CONTEXT] Skill: {skill_name} | Section: {current_heading}\n"
                    f"# Description: {skill_desc}\n"
                    f"--------------------------------------------------\n"
                )
                chunks.append({
                    "content": header + chunk_text,
                    "heading": current_heading,
                    "start_line": start_line,
                    "end_line": len(lines)
                })

        return metadata, chunks
