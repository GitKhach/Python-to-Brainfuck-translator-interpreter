#!/usr/bin/env python3
"""py2bf - компилятор подмножества Python в brainfuck.

Использование:  python3 py2bf.py программа.py [выход.bf]

Поддерживается:
  * переменные - целые 0..255 (8-битные ячейки, арифметика с заворотом по модулю 256)
  * + - * // %  и  += -= *= //= %=
  * сравнения == != < > <= >=, а также and / or / not (результат 0 или 1)
  * if / elif / else, while, for i in range(n) / range(a, b) / range(a, b, шаг-константа)
  * print(...) со строками, числами, f-строками, sep= и end=
Не поддерживается: float, списки, функции, break/continue, ввод, деление на 0 (даёт 0).
"""
import ast
import sys

HIDDEN = ["__v", "__h", "__t", "__o"]   # служебные переменные для вывода чисел

# Вывод числа 0..255 в десятичном виде - написан на самом подмножестве Python
# и компилируется тем же компилятором.
PRINT_NUM = """
__h = 0
__t = __v
while __t >= 100:
    __t -= 100
    __h += 1
__o = 0
while __t >= 10:
    __t -= 10
    __o += 1
if __h:
    __putc(__h + 48)
if __h + __o:
    __putc(__o + 48)
__putc(__t + 48)
"""


class CompileError(Exception):
    pass


def const_int(n):
    """The value of an integer constant (with a unary minus) or None."""
    if isinstance(n, ast.Constant) and isinstance(n.value, (bool, int)):
        return int(n.value)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = const_int(n.operand)
        if v is not None:
            return -v if isinstance(n.op, ast.USub) else v
    return None


class ForDesugar(ast.NodeTransformer):
    """for i in range(a, b, s): ...  ->  заранее считаем число итераций и крутим счётчик.

    (Сравнение i < b ненадёжно: в 8-битной ячейке i + s может переполниться.)
    """

    def __init__(self):
        self.n = 0

    def visit_For(self, node):
        self.generic_visit(node)
        it = node.iter
        ok = (isinstance(node.target, ast.Name) and isinstance(it, ast.Call)
              and isinstance(it.func, ast.Name) and it.func.id == "range"
              and 1 <= len(it.args) <= 3 and not it.keywords and not node.orelse)
        if not ok:
            raise CompileError(f"line {node.lineno}: it is supported only for i in range(...)")
        a = it.args
        start = a[0] if len(a) > 1 else ast.Constant(0)
        stop = a[1] if len(a) > 1 else a[0]
        step = 1
        if len(a) == 3:
            step = const_int(a[2])
            if not step:
                raise CompileError(f"line {node.lineno}: the range step must be a non-zero constant")
        n = self.n
        self.n += 1
        k = abs(step)
        lo, hi = (f"__s{n}", f"__e{n}") if step > 0 else (f"__e{n}", f"__s{n}")
        count = f"__d{n}" if k == 1 else f"__d{n} // {k} + (__d{n} % {k} != 0)"
        stmts = ast.parse(f"""
__s{n} = 0
__e{n} = 0
__c{n} = 0
if {lo} < {hi}:
    __d{n} = {hi} - {lo}
    __c{n} = {count}
__i{n} = __s{n}
while __c{n}:
    pass
""").body
        stmts[0].value = start
        stmts[1].value = stop
        loop = stmts[-1]
        loop.body = (ast.parse(f"{node.target.id} = __i{n}").body
                     + node.body
                     + ast.parse(f"__i{n} += {step}\n__c{n} -= 1").body)
        for s in stmts:
            ast.copy_location(s, node)
        return stmts


class Gen:
    def __init__(self, names):
        self.vars = {n: i for i, n in enumerate(names)}
        self.out = []
        self.pos = 0                 # где сейчас указатель (известно статически)
        self.top = len(names)        # первая свободная временная ячейка
        self.print_stmts = ast.parse(PRINT_NUM).body

    # ---------- низкий уровень ----------
    def err(self, node, msg):
        return CompileError(f"line {getattr(node, 'lineno', '?')}: {msg}")

    def emit(self, s):
        self.out.append(s)

    def goto(self, c):
        if c > self.pos:
            self.emit(">" * (c - self.pos))
        elif c < self.pos:
            self.emit("<" * (self.pos - c))
        self.pos = c

    def loop_open(self, c):
        self.goto(c)
        self.emit("[")

    def loop_close(self, c):
        self.goto(c)
        self.emit("]")

    def zero(self, c):
        self.goto(c)
        self.emit("[-]")

    def alloc(self):
        """Temporary cell (always zeroed)"""
        c = self.top
        self.top += 1
        self.zero(c)
        return c

    def var(self, node, name):
        if name not in self.vars:
            raise self.err(node, f"the {name} variable is not defined")
        return self.vars[name]

    def add_const(self, c, n):
        n %= 256
        if n == 0:
            return
        sign = "+"
        if n > 128:
            sign, n = "-", 256 - n
        if n <= 12:
            self.goto(c)
            self.emit(sign * n)
            return
        _, a, b = min((a + b + abs(n - a * b), a, b)
                      for a in range(2, 17) for b in range(2, 17))
        r = n - a * b
        mark = self.top
        t = self.alloc()
        self.goto(t)
        self.emit("+" * a + "[")
        self.goto(c)
        self.emit(sign * b)
        self.goto(t)
        self.emit("-]")
        self.goto(c)
        if r:
            opp = "-" if sign == "+" else "+"
            self.emit((sign if r > 0 else opp) * abs(r))
        self.top = mark

    def move(self, src, dst, sign="+"):
        """dst += src (or -=), src is reset to zero"""
        self.loop_open(src)
        self.emit("-")
        self.goto(dst)
        self.emit(sign)
        self.loop_close(src)

    def addcopy(self, src, dst, sign="+"):
        """dst += src (or -=), src is saved"""
        mark = self.top
        t = self.alloc()
        self.loop_open(src)
        self.emit("-")
        self.goto(dst)
        self.emit(sign)
        self.goto(t)
        self.emit("+")
        self.loop_close(src)
        self.move(t, src)
        self.top = mark

    def lt_cells(self, a, b, dst):
        """dst += (a < b), a and b are saved"""
        mark = self.top
        x = self.alloc(); y = self.alloc()
        self.addcopy(a, x); self.addcopy(b, y)
        f = self.alloc(); c1 = self.alloc(); c2 = self.alloc()
        self.goto(f); self.emit("+")
        self.loop_open(f)
        self.emit("-")
        self.addcopy(x, c1)
        self.loop_open(c1); self.emit("[-]")
        self.addcopy(y, c2)
        self.loop_open(c2); self.emit("[-]")
        self.goto(x); self.emit("-")
        self.goto(y); self.emit("-")
        self.goto(f); self.emit("+")
        self.loop_close(c2)
        self.loop_close(c1)
        self.loop_close(f)
        # a < b  <=>  после взаимного вычитания у y что-то осталось
        self.loop_open(y); self.emit("[-]")
        self.goto(dst); self.emit("+")
        self.loop_close(y)
        self.top = mark

    def divmod_(self, left, right, dst, want_q):
        mark = self.top
        r = self.alloc(); self.ev(left, r)
        b = self.alloc(); self.ev(right, b)
        q = self.alloc()
        bb = self.alloc(); self.addcopy(b, bb)
        self.loop_open(bb); self.emit("[-]")           # только если делитель != 0
        ln = self.alloc(); g = self.alloc()
        self.lt_cells(r, b, ln)
        self.goto(g); self.emit("+"); self.move(ln, g, "-")   # g = (r >= b)
        self.loop_open(g); self.emit("[-]")
        self.addcopy(b, r, "-")
        self.goto(q); self.emit("+")
        self.lt_cells(r, b, ln)
        self.goto(g); self.emit("+"); self.move(ln, g, "-")
        self.loop_close(g)
        self.loop_close(bb)
        self.move(q if want_q else r, dst)
        self.top = mark

    # ---------- выражения: dst += значение ----------
    def ev(self, node, dst):
        mark = self.top
        c = const_int(node)
        if c is not None:
            self.add_const(dst, c)
        elif isinstance(node, ast.Name):
            self.addcopy(self.var(node, node.id), dst)
        elif isinstance(node, ast.UnaryOp):
            t = self.alloc(); self.ev(node.operand, t)
            if isinstance(node.op, ast.Not):
                self.goto(dst); self.emit("+")
                self.loop_open(t); self.emit("[-]")
                self.goto(dst); self.emit("-")
                self.loop_close(t)
            elif isinstance(node.op, ast.USub):
                self.move(t, dst, "-")
            else:
                raise self.err(node, "unsupported unary operation")
        elif isinstance(node, ast.BinOp):
            op = node.op
            if isinstance(op, ast.Add):
                self.ev(node.left, dst); self.ev(node.right, dst)
            elif isinstance(op, ast.Sub):
                self.ev(node.left, dst)
                t = self.alloc(); self.ev(node.right, t); self.move(t, dst, "-")
            elif isinstance(op, ast.Mult):
                ta = self.alloc(); self.ev(node.left, ta)
                tb = self.alloc(); self.ev(node.right, tb)
                self.loop_open(ta); self.emit("-")
                self.addcopy(tb, dst)
                self.loop_close(ta)
            elif isinstance(op, ast.FloorDiv):
                self.divmod_(node.left, node.right, dst, True)
            elif isinstance(op, ast.Mod):
                self.divmod_(node.left, node.right, dst, False)
            else:
                raise self.err(node, "unsupported arithmetic operation")
        elif isinstance(node, ast.Compare):
            if len(node.ops) != 1:
                raise self.err(node, "comparison chains a < b < c are not supported")
            op = node.ops[0]
            ta = self.alloc(); self.ev(node.left, ta)
            tb = self.alloc(); self.ev(node.comparators[0], tb)
            if isinstance(op, (ast.Eq, ast.NotEq)):
                self.loop_open(tb); self.emit("-")
                self.goto(ta); self.emit("-")
                self.loop_close(tb)                      # ta = ta - tb
                if isinstance(op, ast.NotEq):
                    self.loop_open(ta); self.emit("[-]")
                    self.goto(dst); self.emit("+")
                    self.loop_close(ta)
                else:
                    self.goto(dst); self.emit("+")
                    self.loop_open(ta); self.emit("[-]")
                    self.goto(dst); self.emit("-")
                    self.loop_close(ta)
            elif isinstance(op, ast.Lt):
                self.lt_cells(ta, tb, dst)
            elif isinstance(op, ast.Gt):
                self.lt_cells(tb, ta, dst)
            elif isinstance(op, (ast.LtE, ast.GtE)):
                r = self.alloc()
                if isinstance(op, ast.LtE):
                    self.lt_cells(tb, ta, r)             # a <= b  <=>  not (b < a)
                else:
                    self.lt_cells(ta, tb, r)             # a >= b  <=>  not (a < b)
                self.goto(dst); self.emit("+")
                self.move(r, dst, "-")
            else:
                raise self.err(node, "unsupported comparation")
        elif isinstance(node, ast.BoolOp):
            f = self.alloc()
            if isinstance(node.op, ast.And):
                self.goto(f); self.emit("+")
                for v in node.values:
                    t = self.alloc(); self.ev(v, t)
                    nt = self.alloc()
                    self.goto(nt); self.emit("+")
                    self.loop_open(t); self.emit("[-]")
                    self.goto(nt); self.emit("-")
                    self.loop_close(t)
                    self.loop_open(nt); self.emit("[-]")
                    self.zero(f)
                    self.loop_close(nt)
            else:
                for v in node.values:
                    t = self.alloc(); self.ev(v, t)
                    self.loop_open(t); self.emit("[-]")
                    self.zero(f); self.goto(f); self.emit("+")
                    self.loop_close(t)
            self.move(f, dst)
        else:
            raise self.err(node, f"unsupported expression ({type(node).__name__})")
        self.top = mark

    # ---------- вывод ----------
    def text(self, s):
        mark = self.top
        p = self.alloc()
        cur = 0
        for byte in s.encode("utf-8"):
            self.add_const(p, byte - cur)
            self.goto(p); self.emit(".")
            cur = byte
        self.top = mark

    def do_print(self, node):
        end, sep = "\n", " "
        for kw in node.keywords:
            if kw.arg in ("end", "sep") and isinstance(kw.value, ast.Constant) \
                    and isinstance(kw.value.value, str):
                if kw.arg == "end":
                    end = kw.value.value
                else:
                    sep = kw.value.value
            else:
                raise self.err(node, "for print, only end='...' and sep='...' are allowed")
        items = []                      # ("s", строка) или ("n", выражение)

        def add_s(s):
            if items and items[-1][0] == "s":
                items[-1] = ("s", items[-1][1] + s)
            else:
                items.append(("s", s))

        for i, a in enumerate(node.args):
            if i:
                add_s(sep)
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                add_s(a.value)
            elif isinstance(a, ast.JoinedStr):
                for v in a.values:
                    if isinstance(v, ast.Constant):
                        add_s(v.value)
                    elif isinstance(v, ast.FormattedValue) and not v.format_spec and v.conversion == -1:
                        c = const_int(v.value)
                        if c is not None:
                            add_s(str(c))
                        else:
                            items.append(("n", v.value))
                    else:
                        raise self.err(node, "only {expression} are allowed in the f-string")
            else:
                c = const_int(a)
                if c is not None:
                    add_s(str(c))
                else:
                    items.append(("n", a))
        add_s(end)
        for kind, val in items:
            if kind == "s":
                self.text(val)
            else:
                self.print_num(val)

    def print_num(self, expr):
        self.assign("__v", expr, expr)
        self.body(self.print_stmts)

    # ---------- операторы ----------
    def assign(self, name, value, node):
        v = self.var(node, name)
        c = const_int(value)
        if c is not None:
            self.zero(v)
            self.add_const(v, c)
            return
        mark = self.top
        t = self.alloc()
        self.ev(value, t)
        self.zero(v)
        self.move(t, v)
        self.top = mark

    def body(self, stmts):
        for s in stmts:
            self.stmt(s)

    def stmt(self, s):
        mark = self.top
        if isinstance(s, ast.Assign):
            if len(s.targets) != 1 or not isinstance(s.targets[0], ast.Name):
                raise self.err(s, "only assignment of the form x = expression is supported.")
            self.assign(s.targets[0].id, s.value, s)
        elif isinstance(s, ast.AugAssign):
            if not isinstance(s.target, ast.Name):
                raise self.err(s, "only variables are supported")
            name = s.target.id
            v = self.var(s, name)
            c = const_int(s.value)
            if isinstance(s.op, (ast.Add, ast.Sub)):
                sign = "+" if isinstance(s.op, ast.Add) else "-"
                if c is not None:
                    self.add_const(v, c if sign == "+" else -c)
                else:
                    t = self.alloc(); self.ev(s.value, t); self.move(t, v, sign)
            elif isinstance(s.op, (ast.Mult, ast.FloorDiv, ast.Mod)):
                self.assign(name, ast.BinOp(left=ast.Name(id=name, ctx=ast.Load()),
                                            op=s.op, right=s.value), s)
            else:
                raise self.err(s, "unsupported operation")
        elif isinstance(s, ast.If):
            t = self.alloc(); self.ev(s.test, t)
            if s.orelse:
                e = self.alloc()
                self.goto(e); self.emit("+")
                self.loop_open(t); self.emit("[-]")
                self.goto(e); self.emit("-")
                self.body(s.body)
                self.loop_close(t)
                self.loop_open(e); self.emit("[-]")
                self.body(s.orelse)
                self.loop_close(e)
            else:
                self.loop_open(t); self.emit("[-]")
                self.body(s.body)
                self.loop_close(t)
        elif isinstance(s, ast.While):
            if s.orelse:
                raise self.err(s, "while ... else is not supported")
            t = self.alloc(); self.ev(s.test, t)
            self.loop_open(t); self.emit("[-]")
            self.body(s.body)
            self.ev(s.test, t)
            self.loop_close(t)
        elif isinstance(s, ast.Expr):
            v = s.value
            if isinstance(v, ast.Constant):
                pass                                    # докстринг / комментарий
            elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "print":
                self.do_print(v)
            elif isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "__putc":
                t = self.alloc(); self.ev(v.args[0], t)
                self.goto(t); self.emit(".")
            else:
                raise self.err(s, "only print(...) calls are allowed")
        elif isinstance(s, ast.Pass):
            pass
        else:
            raise self.err(s, f"unsupported construction ({type(s).__name__})")
        self.top = mark


def optimize(code):
    prev = None
    while prev != code:
        prev = code
        for pair in ("><", "<>", "+-", "-+"):
            code = code.replace(pair, "")
    return code


def compile_source(src):
    tree = ast.parse(src)
    tree = ForDesugar().visit(tree)
    ast.fix_missing_locations(tree)
    names = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id not in names:
            names.append(n.id)
    for h in HIDDEN:
        if h not in names:
            names.append(h)
    g = Gen(names)
    g.body(tree.body)
    return optimize("".join(g.out))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    try:
        src = open(sys.argv[1], encoding="utf-8").read()
        code = compile_source(src)
    except (CompileError, SyntaxError) as e:
        print("Ошибка компиляции:", e, file=sys.stderr)
        sys.exit(1)
    text = "\n".join(code[i:i + 100] for i in range(0, len(code), 100)) + "\n"
    if len(sys.argv) > 2:
        open(sys.argv[2], "w").write(text)
        print(f"Done: {sys.argv[2]} ({len(code)} brainfuck commands)")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
