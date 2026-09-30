"""Check that the Kieker probe was woven into every method of every Edition module and layer.

Woven:    the 'weaveinfo Join point ...-execution(...)' lines that AspectJ writes to the application log when Edition is
          started with -Dorg.aspectj.weaver.showWeaveInfo=true (one line per advised method or constructor).
Declared: every method and constructor in Edition's production source (<edition>/*/src/main/java), parsed with
          javalang, plus the implicit default constructor of classes that declare none.

Load-time weaving instruments a class when the JVM loads it, so methods of classes that were never loaded are reported
separately: they are not woven, and they cannot appear in a trace either.

Usage: python check_instrumentation.py <edition project dir> <application log> <output dir>
Needs: pip install javalang
"""
import collections, csv, glob, os, re, sys
import javalang

STATUSES = ["woven", "NOT woven although its class was loaded", "class never loaded", "no body (abstract/interface)"]


def declared_methods(project):
    methods = []
    for f in sorted(glob.glob(os.path.join(project, "*", "src", "main", "java", "**", "*.java"), recursive=True)):
        code = open(f, encoding="utf-8", errors="replace").read()
        try:
            tree = javalang.parse.parse(code)
        except Exception:  # javalang cannot parse array-constructor references (X[]::new); they do not declare methods
            tree = javalang.parse.parse(re.sub(r"[\w.]+(\[\])*::new\b", "null", code))
        pkg = tree.package.name if tree.package else ""
        for path, node in tree.filter(javalang.tree.TypeDeclaration):
            outer = [p.name for p in path if isinstance(p, javalang.tree.TypeDeclaration)]
            cls = ".".join(filter(None, [pkg, "$".join(outer + [node.name])]))
            if "TestTagLoggingFilter" in cls:  # trace-tagging filter (and its nested record class), not Edition code
                continue
            members = node.body.declarations if isinstance(node, javalang.tree.EnumDeclaration) else node.body
            ctors = [m for m in members if isinstance(m, javalang.tree.ConstructorDeclaration)]
            if isinstance(node, (javalang.tree.ClassDeclaration, javalang.tree.EnumDeclaration)) and not ctors:
                methods.append((cls, "<init>", 0, False))  # implicit default constructor
            for m in members:
                if isinstance(m, javalang.tree.ConstructorDeclaration):
                    methods.append((cls, "<init>", len(m.parameters), False))
                elif isinstance(m, javalang.tree.MethodDeclaration):
                    methods.append((cls, m.name, len(m.parameters), m.body is None))
    return methods


def woven_join_points(log):
    pat = re.compile(r"weaveinfo Join point '(?:method|constructor)-execution\((?:[\w.$\[\]<>, ]+ )?([\w.$]+)\.([\w$<>]+)\((.*?)\)\)'")
    woven = set()
    for line in open(log, encoding="utf-8", errors="replace"):
        m = pat.search(line)
        if m:
            cls, name, params = m.groups()
            woven.add((cls, name, 0 if not params.strip() else params.count(",") + 1))
    return woven


def module_and_layer(cls):
    p = cls.split(".")
    if len(p) > 5 and p[4] == "ldod":  # front-end: pt.ist.socialsoftware.edition.ldod.frontend.<area>
        return "front-end", ".".join(p[5:7]) if len(p) > 7 else p[5]
    return (p[4], p[5] if len(p) > 6 else "(root)") if len(p) > 5 else (cls, "")


def main(project, log, out):
    os.makedirs(out, exist_ok=True)
    woven = woven_join_points(log)
    woven_classes = {c for c, _, _ in woven}
    ctor_classes = {c for c, n, _ in woven if n == "<init>"}
    per_module, per_layer, rows = collections.defaultdict(collections.Counter), collections.defaultdict(collections.Counter), []
    methods = declared_methods(project)
    for cls, name, nparams, no_body in methods:
        if no_body:
            status = STATUSES[3]
        elif (cls, name, nparams) in woven or (name == "<init>" and cls in ctor_classes):
            status = STATUSES[0]
        elif cls in woven_classes:
            status = STATUSES[1]
        else:
            status = STATUSES[2]
        mod, layer = module_and_layer(cls)
        per_module[mod][status] += 1
        per_layer[(mod, layer)][status] += 1
        rows.append([mod, layer, cls, name, nparams, status])
    with open(os.path.join(out, "instrumentation_check.csv"), "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["module", "layer", "class", "method", "parameters", "status"])
        w.writerows(rows)
    short = ["woven", "NOT woven (loaded)", "class not loaded", "no body"]
    lines = [f"woven join points in log: {len(woven)}; declared methods: {len(methods)}", "", "PER MODULE",
             f"{'module':16s}" + "".join(f"{s:>20s}" for s in short)]
    lines += [f"{m:16s}" + "".join(f"{per_module[m][s]:20d}" for s in STATUSES) for m in sorted(per_module)]
    lines += ["", "PER LAYER (module / package)", f"{'layer':40s}" + "".join(f"{s:>20s}" for s in short)]
    lines += [f"{m + ' / ' + l:40s}" + "".join(f"{per_layer[(m, l)][s]:20d}" for s in STATUSES) for (m, l) in sorted(per_layer)]
    text = "\n".join(lines) + "\n"
    open(os.path.join(out, "instrumentation_check.txt"), "w").write(text)
    print(text)


if __name__ == "__main__":
    main(*sys.argv[1:4])
