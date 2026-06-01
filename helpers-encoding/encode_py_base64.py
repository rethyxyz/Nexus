#!/usr/bin/env python3
'''
python encode_py_base64.py script.py [output_script.py](optional arg)

Creates an executable wrapper whose only payload is a script stored as Base64 text.
'''

import argparse, base64, pathlib, stat, textwrap

# boiler plate payload wrapper.
TEMPLATE = textwrap.dedent("""\
    import base64, sys
    _src = base64.b64decode({encoded!r})
    g = {{'__name__': '__main__', '__file__': '<embedded>'}}
    exec(compile(_src, '<embedded>', 'exec'), g)
""")

def main():
    p = argparse.ArgumentParser()
    p.add_argument("source", help="Input .py file")
    p.add_argument("output", nargs="?", help="Output .py file (default: <source>_b64.py)")
    args = p.parse_args()

    src_path  = pathlib.Path(args.source).resolve()
    out_path  = pathlib.Path(args.output) if args.output else src_path.with_suffix("").with_name(src_path.stem + "_b64.py")

    encoded   = base64.b64encode(src_path.read_bytes()).decode("ascii")

    out_path.write_text(TEMPLATE.format(encoded=encoded))
    out_path.chmod(out_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)  # make it executable (UNIX)

    print(f"[X] Created {out_path}`")

if __name__ == "__main__":
    main()
