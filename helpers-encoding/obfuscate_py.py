'''
obfuscate_py.py

Renames identifiers, strips doc-strings, and wraps normal string literals in Base64.
'''

import ast, argparse, base64, builtins, keyword, pathlib, random, string, sys

def build_name_map(tree):
    reserved = set(keyword.kwlist) | set(dir(builtins))
    user = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            user.add(n.name)
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            user.add(n.id)

    alpha = string.ascii_letters
    counter = 0
    def gen():
        nonlocal counter
        counter += 1
        return f"_{''.join(random.choices(alpha,k=5))}_{counter-1}"

    return {n: gen() for n in user
            if n not in reserved and not n.startswith("__")}

class ObfuscateNames(ast.NodeTransformer):
    def __init__(self, m): self.m = m
    def visit_Name(self, n):
        n.id = self.m.get(n.id, n.id); return n
    def visit_FunctionDef(self, n):
        n.name = self.m.get(n.name, n.name); self.generic_visit(n); return n
    def visit_ClassDef(self, n):
        n.name = self.m.get(n.name, n.name); self.generic_visit(n); return n

class StripDocstrings(ast.NodeTransformer):
    @staticmethod
    def _strip(body):
        if (body and isinstance(body[0], ast.Expr) and
                isinstance(body[0].value, ast.Constant) and
                isinstance(body[0].value.value, str)):
            return body[1:] or [ast.Pass()]
        return body
    def visit_Module(self, n):
        n.body = self._strip(n.body); self.generic_visit(n); return n
    def visit_FunctionDef(self, n):
        n.body = self._strip(n.body); self.generic_visit(n); return n
    def visit_ClassDef(self, n):
        n.body = self._strip(n.body); self.generic_visit(n); return n

class ObfuscateStrings(ast.NodeTransformer):
    def __init__(self): self._stack = []
    def generic_visit(self, node):
        self._stack.append(node)
        new = super().generic_visit(node)
        self._stack.pop()
        return new
    def visit_Constant(self, node):
        if (isinstance(node.value, str) and
            not any(isinstance(p, ast.JoinedStr) for p in self._stack)):
            b64 = base64.b64encode(node.value.encode()).decode()
            return ast.Call(
                func=ast.Attribute(
                    value=ast.Call(
                        func=ast.Attribute(
                            value=ast.Name(id="base64", ctx=ast.Load()),
                            attr="b64decode", ctx=ast.Load()),
                        args=[ast.Constant(value=b64)], keywords=[]),
                    attr="decode", ctx=ast.Load()),
                args=[], keywords=[])
        return node

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("output", nargs="?", help="default: <source>_obf.py")
    a = ap.parse_args()

    src = pathlib.Path(a.source).resolve()
    out = pathlib.Path(a.output) if a.output \
          else src.with_suffix("").with_name(src.stem + "_obf.py")

    tree = ast.parse(src.read_text())

    tree = StripDocstrings().visit(tree)
    tree = ObfuscateNames(build_name_map(tree)).visit(tree)
    tree = ObfuscateStrings().visit(tree)
    ast.fix_missing_locations(tree)

    # import base64 if needed
    if any(isinstance(n, ast.Call) and
           isinstance(n.func, ast.Attribute) and
           getattr(n.func.value, "id", None) == "base64"
           for n in ast.walk(tree)):
        if not any(isinstance(n, ast.Import) and
                   any(a.name == "base64" for a in n.names)
                   for n in tree.body):
            tree.body.insert(0, ast.Import(names=[ast.alias(name="base64")]))

    #NOTE: out.write_text("#!/usr/bin/env python3\n" + ast.unparse(tree))
    # Modified the above. Test this.
    out.write_text(ast.unparse(tree))
    out.chmod(0o755)
    print("[X] Obfuscated", out)

if __name__ == "__main__":
    # This check doesn't really need to be here. If it fails it fails. NOTE:
    # Remove this.
    if sys.version_info < (3, 9):
        sys.exit("Python 3.9+ required.")
    random.seed()
    main()
