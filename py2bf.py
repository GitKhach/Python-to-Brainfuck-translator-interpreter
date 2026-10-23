#!/usr/bin/env python3
"""Python subset to Brainfuck compiler with 16-bit unsigned integers.

Usage: python3 py2bf.py program.py [output.bf]
Values and arithmetic operate modulo 65536. Each number occupies two
Brainfuck cells: low and high bytes.
"""
import ast
import sys


class CompileError(Exception):
    pass


def const_int(n):
    if isinstance(n, ast.Constant) and isinstance(n.value, (bool, int)):
        return int(n.value)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        v = const_int(n.operand)
        if v is not None:
            return -v if isinstance(n.op, ast.USub) else v
    return None


class ForDesugar(ast.NodeTransformer):

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
        step_stmt = f"__i{n} += {step}" if step > 0 else f"__i{n} -= {abs(step)}"
        loop.body = (ast.parse(f"{node.target.id} = __i{n}").body
                     + node.body
                     + ast.parse(f"{step_stmt}\n__c{n} -= 1").body)
        for s in stmts:
            ast.copy_location(s, node)
        return stmts


def optimize(code):
    prev = None
    while prev != code:
        prev = code
        for pair in ("><", "<>", "+-", "-+"):
            code = code.replace(pair, "")
    return code


class Compiler16:
    """16-bit compiler: each integer is represented by low/high 8-bit cells."""
    def __init__(self):
        self.code = []
        self.vars = {}
        self.str_vars = {}
        self.pos = 0
        self.next_cell = 0

    def emit(self, code): self.code.append(code)

    def goto(self, target):
        self.emit(('>' * (target - self.pos)) if target >= self.pos else ('<' * (self.pos - target)))
        self.pos = target

    def zero(self, c): self.goto(c); self.emit('[-]')

    def alloc(self):
        c = self.next_cell
        self.next_cell += 1
        self.zero(c)
        return c

    def pair(self): return (self.alloc(), self.alloc())

    def set_cell(self, c, value):
        self.zero(c)
        value %= 256
        if value: self.goto(c); self.emit('+' * value)

    def set_pair(self, p, value):
        value %= 65536
        self.set_cell(p[0], value & 255)
        self.set_cell(p[1], value >> 8)

    def alloc_var(self, name):
        if name not in self.vars:
            self.vars[name] = self.next_cell, self.next_cell + 1
            self.next_cell += 2
        return self.vars[name]

    def var(self, name, node=None):
        if name not in self.vars:
            raise CompileError(f"line {getattr(node, 'lineno', '?')}: variable {name!r} is not defined")
        return self.vars[name]

    def copy_cell(self, src, dst):
        tmp = self.alloc()
        self.zero(dst)
        self.goto(src); self.emit('['); self.emit('-')
        self.goto(dst); self.emit('+')
        self.goto(tmp); self.emit('+')
        self.goto(src); self.emit(']')
        self.goto(tmp); self.emit('['); self.emit('-')
        self.goto(src); self.emit('+')
        self.goto(tmp); self.emit(']')

    def add_cell(self, src, dst):
        tmp = self.alloc(); self.copy_cell(src, tmp)
        self.goto(tmp); self.emit('['); self.emit('-')
        self.goto(dst); self.emit('+'); self.goto(tmp); self.emit(']')

    def is_zero(self, src, dst):
        tmp = self.alloc(); self.copy_cell(src, tmp)
        self.set_cell(dst, 1)
        self.goto(tmp); self.emit('['); self.emit('-')
        self.goto(dst); self.emit('[-]')
        self.goto(tmp); self.emit(']')

    def truth16(self, p, dst):
        self.set_cell(dst, 0)
        for c in p:
            tmp = self.alloc(); self.copy_cell(c, tmp)
            self.goto(tmp); self.emit('['); self.emit('[-]')
            self.goto(dst); self.emit('[-]+')
            self.goto(tmp); self.emit(']')

    def if_cell(self, flag, body):
        self.goto(flag); self.emit('['); self.emit('-')
        body()
        self.goto(flag); self.emit(']')

    def move_cell(self, src, dst, sign='+'):
        self.goto(src); self.emit('['); self.emit('-')
        self.goto(dst); self.emit(sign); self.goto(src); self.emit(']')

    def add16(self, src, dst):
        sl, sh = src; dl, dh = dst
        t = self.alloc(); self.copy_cell(sl, t)
        self.goto(t); self.emit('['); self.emit('-')
        test = self.alloc(); self.copy_cell(dl, test); self.goto(test); self.emit('+')
        carry = self.alloc(); self.is_zero(test, carry)
        no_carry = self.alloc(); self.is_zero(carry, no_carry)
        self.if_cell(carry, lambda: (self.zero(dl), self.goto(dh), self.emit('+')))
        self.if_cell(no_carry, lambda: (self.goto(dl), self.emit('+')))
        self.goto(t); self.emit(']')
        t = self.alloc(); self.copy_cell(sh, t)
        self.goto(t); self.emit('['); self.emit('-'); self.goto(dh); self.emit('+'); self.goto(t); self.emit(']')

    def dec16(self, p):
        lo, hi = p
        flag = self.alloc(); self.is_zero(lo, flag)
        def borrow():
            self.set_cell(lo, 255); self.goto(hi); self.emit('-')
        nonzero = self.alloc(); self.is_zero(flag, nonzero)
        self.if_cell(flag, borrow)
        self.if_cell(nonzero, lambda: (self.goto(lo), self.emit('-')))

    def sub16(self, src, dst):
        sl, sh = src; dl, dh = dst
        t = self.alloc(); self.copy_cell(sl, t)
        self.goto(t); self.emit('['); self.emit('-')
        self.dec16(dst)
        self.goto(t); self.emit(']')
        t = self.alloc(); self.copy_cell(sh, t)
        self.goto(t); self.emit('['); self.emit('-'); self.goto(dh); self.emit('-'); self.goto(t); self.emit(']')

    def lt8(self, a, b, dst):
        """Overwrite dst with 1 iff byte a < byte b; preserve a and b."""
        x, y, flag, zx, zy = (self.alloc() for _ in range(5))
        self.copy_cell(a, x); self.copy_cell(b, y)
        self.set_cell(dst, 0); self.set_cell(flag, 1)
        def iteration():
            self.is_zero(x, zx)
            def x_is_zero():
                self.is_zero(y, zy)
                ynz = self.alloc(); self.set_cell(ynz, 1)
                self.is_zero(zy, ynz)
                self.if_cell(ynz, lambda: self.set_cell(dst, 1))
            self.goto(zx); self.emit('['); self.emit('-'); x_is_zero(); self.goto(zx); self.emit(']')
            def x_nonzero():
                self.is_zero(y, zy)
                ynz = self.alloc(); self.set_cell(ynz, 1)
                self.if_cell(zy, lambda: self.zero(ynz))
                def step_both():
                    self.goto(x); self.emit('-'); self.goto(y); self.emit('-'); self.goto(flag); self.emit('+')
                self.if_cell(ynz, step_both)
            self.is_zero(x, zx)
            self.goto(zx); self.emit('['); self.emit('-'); self.goto(zx); self.emit(']')
            gate = self.alloc(); self.copy_cell(x, gate)
            self.goto(gate); self.emit('['); self.emit('[-]'); x_nonzero(); self.goto(gate); self.emit(']')
        self.goto(flag); self.emit('['); self.emit('-'); iteration(); self.goto(flag); self.emit(']')

    def lt16(self, a, b, dst):
        ah, bh = a[1], b[1]
        hi_lt, hi_gt, lo_lt, eqhi = (self.alloc() for _ in range(4))
        self.lt8(ah, bh, hi_lt); self.lt8(bh, ah, hi_gt); self.lt8(a[0], b[0], lo_lt)
        self.set_cell(dst, 0); self.add_cell(hi_lt, dst)
        self.set_cell(eqhi, 1)
        self.if_cell(hi_lt, lambda: self.zero(eqhi))
        self.if_cell(hi_gt, lambda: self.zero(eqhi))
        self.goto(eqhi); self.emit('['); self.emit('-'); self.add_cell(lo_lt, dst); self.goto(eqhi); self.emit(']')

    def compare(self, a, b, op, dst):
        ab, ba = self.alloc(), self.alloc()
        self.lt16(a, b, ab); self.lt16(b, a, ba)
        self.set_cell(dst[0], 0); self.set_cell(dst[1], 0)
        if isinstance(op, ast.Lt): self.add_cell(ab, dst[0])
        elif isinstance(op, ast.Gt): self.add_cell(ba, dst[0])
        elif isinstance(op, ast.Eq):
            self.set_cell(dst[0], 1)
            self.if_cell(ab, lambda: self.zero(dst[0]))
            self.if_cell(ba, lambda: self.zero(dst[0]))
        elif isinstance(op, ast.NotEq):
            self.add_cell(ab, dst[0]); self.add_cell(ba, dst[0])
        elif isinstance(op, ast.LtE):
            self.set_cell(dst[0], 1); self.if_cell(ba, lambda: self.zero(dst[0]))
        elif isinstance(op, ast.GtE):
            self.set_cell(dst[0], 1); self.if_cell(ab, lambda: self.zero(dst[0]))
        else: raise CompileError('unsupported comparison')

    def constant(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, bool)):
            return int(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            v = self.constant(node.operand) % 65536
            if isinstance(node.op, ast.USub): return (-v) % 65536
            if isinstance(node.op, ast.UAdd): return v
            return int(v == 0)
        if isinstance(node, ast.BinOp):
            a, b = self.constant(node.left) % 65536, self.constant(node.right) % 65536
            if isinstance(node.op, ast.Add): return (a + b) % 65536
            if isinstance(node.op, ast.Sub): return (a - b) % 65536
            if isinstance(node.op, ast.Mult): return (a * b) % 65536
            if isinstance(node.op, ast.FloorDiv): return 0 if b == 0 else a // b
            if isinstance(node.op, ast.Mod): return 0 if b == 0 else a % b
            if isinstance(node.op, ast.Pow): return pow(a, b, 65536)
        raise CompileError('not a constant expression')

    def expr_into(self, node, dst):
        try:
            self.set_pair(dst, self.constant(node))
            return
        except CompileError:
            pass
        if isinstance(node, ast.Name):
            src = self.var(node.id, node)
            self.copy_cell(src[0], dst[0]); self.copy_cell(src[1], dst[1]); return
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.USub):
                tmp = self.pair(); self.expr_into(node.operand, tmp)
                self.set_pair(dst, 0); self.sub16(tmp, dst); return
            if isinstance(node.op, ast.Not):
                t = self.pair(); self.expr_into(node.operand, t)
                flag = self.alloc(); self.truth16(t, flag)
                self.set_pair(dst, 1)
                self.if_cell(flag, lambda: self.set_pair(dst, 0))
                return
            if isinstance(node.op, ast.UAdd): self.expr_into(node.operand, dst); return
        if isinstance(node, ast.BinOp):
            left, right = self.pair(), self.pair()
            self.expr_into(node.left, left); self.expr_into(node.right, right)
            if isinstance(node.op, ast.Add): self.copy_cell(left[0], dst[0]); self.copy_cell(left[1], dst[1]); self.add16(right, dst); return
            if isinstance(node.op, ast.Sub): self.copy_cell(left[0], dst[0]); self.copy_cell(left[1], dst[1]); self.sub16(right, dst); return
            if isinstance(node.op, ast.Mult):
                self.set_pair(dst, 0); counter = self.pair(); self.copy_cell(right[0], counter[0]); self.copy_cell(right[1], counter[1])
                flag = self.alloc(); self.truth16(counter, flag)
                self.goto(flag); self.emit('['); self.emit('-'); self.add16(left, dst); self.dec16(counter); self.truth16(counter, flag); self.goto(flag); self.emit(']'); return
            if isinstance(node.op, (ast.FloorDiv, ast.Mod)):
                self.divmod16(left, right, dst, isinstance(node.op, ast.FloorDiv)); return
            if isinstance(node.op, ast.Pow):
                self.set_pair(dst, 1); counter = self.pair(); self.copy_cell(right[0], counter[0]); self.copy_cell(right[1], counter[1])
                flag = self.alloc(); self.truth16(counter, flag)
                self.goto(flag); self.emit('['); self.emit('-')
                product = self.pair(); self.multiply_pairs(dst, left, product)
                self.copy_cell(product[0], dst[0]); self.copy_cell(product[1], dst[1])
                self.dec16(counter); self.truth16(counter, flag); self.goto(flag); self.emit(']'); return
        if isinstance(node, ast.Compare):
            if len(node.ops) != 1: raise CompileError(f'line {node.lineno}: comparison chains are not supported')
            a, b = self.pair(), self.pair(); self.expr_into(node.left, a); self.expr_into(node.comparators[0], b)
            self.compare(a, b, node.ops[0], dst); return
        if isinstance(node, ast.BoolOp):
            result = self.alloc(); self.set_cell(result, 1 if isinstance(node.op, ast.And) else 0)
            for item in node.values:
                p = self.pair(); self.expr_into(item, p); truth = self.alloc(); self.truth16(p, truth)
                if isinstance(node.op, ast.And):
                    z = self.alloc(); self.is_zero(truth, z); self.if_cell(z, lambda: self.zero(result))
                else: self.if_cell(truth, lambda: self.set_cell(result, 1))
            self.set_pair(dst, 0); self.copy_cell(result, dst[0]); return
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in ('min', 'max') and len(node.args) >= 2:
                vals = [self.pair() for _ in node.args]
                for arg, p in zip(node.args, vals): self.expr_into(arg, p)
                cur = vals[0]
                for nxt in vals[1:]:
                    cond = self.alloc(); self.lt16(nxt, cur, cond) if node.func.id == 'min' else self.lt16(cur, nxt, cond)
                    self.if_cell(cond, lambda cur=cur, nxt=nxt: (self.copy_cell(nxt[0], cur[0]), self.copy_cell(nxt[1], cur[1])))
                self.copy_cell(cur[0], dst[0]); self.copy_cell(cur[1], dst[1]); return
        raise CompileError(f'line {getattr(node, "lineno", "?")}: unsupported 16-bit expression {type(node).__name__}')

    def multiply_pairs(self, a, b, dst):
        self.set_pair(dst, 0); counter = self.pair(); self.copy_cell(b[0], counter[0]); self.copy_cell(b[1], counter[1])
        flag = self.alloc(); self.truth16(counter, flag)
        self.goto(flag); self.emit('['); self.emit('-'); self.add16(a, dst); self.dec16(counter); self.truth16(counter, flag); self.goto(flag); self.emit(']')

    def divmod16(self, a, b, dst, want_q):
        rem = self.pair(); self.copy_cell(a[0], rem[0]); self.copy_cell(a[1], rem[1])
        divisor = self.pair(); self.copy_cell(b[0], divisor[0]); self.copy_cell(b[1], divisor[1])
        quotient = self.pair(); self.set_pair(quotient, 0)
        nz = self.alloc(); self.truth16(divisor, nz)
        lt = self.alloc(); self.lt16(rem, divisor, lt)
        run = self.alloc(); self.set_cell(run, 1)
        self.goto(run); self.emit('['); self.emit('-')
        self.is_zero(nz, self.alloc())
        active = self.alloc(); self.truth16(divisor, active)
        smaller = self.alloc(); self.lt16(rem, divisor, smaller)
        stop = self.alloc(); self.set_cell(stop, 1)
        self.if_cell(active, lambda: self.zero(stop))
        self.if_cell(smaller, lambda: self.set_cell(stop, 1))
        go = self.alloc(); self.set_cell(go, 1); self.if_cell(stop, lambda: self.zero(go))
        self.if_cell(go, lambda: (self.sub16(divisor, rem), self.inc_pair(quotient), self.set_cell(run, 1)))
        self.goto(run); self.emit(']')
        self.set_pair(dst, 0)
        chosen = quotient if want_q else rem
        self.copy_cell(chosen[0], dst[0]); self.copy_cell(chosen[1], dst[1])
        if not want_q:
            nz_copy = self.alloc(); self.truth16(divisor, nz_copy)
            zero_divisor = self.alloc(); self.is_zero(nz_copy, zero_divisor)
            self.if_cell(zero_divisor, lambda: self.set_pair(dst, 0))

    def inc_pair(self, p):
        lo, hi = p; test = self.alloc(); self.copy_cell(lo, test); self.goto(test); self.emit('+')
        flag = self.alloc(); self.is_zero(test, flag)
        no_carry = self.alloc(); self.is_zero(flag, no_carry)
        self.if_cell(flag, lambda: (self.zero(lo), self.goto(hi), self.emit('+')))
        self.if_cell(no_carry, lambda: (self.goto(lo), self.emit('+')))

    def print_text(self, value):
        cell = self.alloc(); prev = 0
        for byte in value.encode('utf-8'):
            self.set_cell(cell, byte); self.goto(cell); self.emit('.')

    def print_number_expr(self, expr):
        value = self.pair(); self.expr_into(expr, value)
        started = self.alloc(); self.set_cell(started, 0)
        for power in (10000, 1000, 100, 10, 1):
            digit = self.alloc(); self.set_cell(digit, 0)
            pwr = self.pair(); self.set_pair(pwr, power)
            flag = self.alloc(); self.lt16(value, pwr, flag)
            run = self.alloc(); self.set_cell(run, 1)
            self.goto(run); self.emit('['); self.emit('-')
            smaller = self.alloc(); self.lt16(value, pwr, smaller)
            ge = self.alloc(); self.set_cell(ge, 1); self.if_cell(smaller, lambda: self.zero(ge))
            self.if_cell(ge, lambda: (self.sub16(pwr, value), self.goto(digit), self.emit('+'), self.goto(run), self.emit('+')))
            self.goto(run); self.emit(']')
            zero_digit = self.alloc(); self.is_zero(digit, zero_digit)
            nonzero = self.alloc(); self.set_cell(nonzero, 1)
            self.if_cell(zero_digit, lambda: self.zero(nonzero))
            self.if_cell(nonzero, lambda: self.set_cell(started, 1))
            output = self.alloc(); self.copy_cell(started, output)
            if power == 1: self.set_cell(output, 1)
            self.if_cell(output, lambda: (self.goto(digit), self.emit('+' * 48), self.goto(digit), self.emit('.')))

    def string_expr(self, node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id in self.str_vars:
            return self.str_vars[node.id]
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            left = self.string_expr(node.left)
            right = self.string_expr(node.right)
            if left is not None and right is not None:
                return left + right
        if isinstance(node, ast.JoinedStr):
            parts = []
            for value in node.values:
                if isinstance(value, ast.Constant):
                    parts.append(str(value.value))
                elif isinstance(value, ast.FormattedValue) and not value.format_spec and value.conversion == -1:
                    if isinstance(value.value, ast.Name) and value.value.id in self.str_vars:
                        parts.append(self.str_vars[value.value.id])
                    else:
                        try:
                            parts.append(str(self.constant(value.value) % 65536))
                        except CompileError:
                            return None
                else:
                    return None
            return ''.join(parts)
        return None

    def print_value(self, arg, line):
        string_value = self.string_expr(arg)
        if string_value is not None:
            self.print_text(string_value)
            return
        if isinstance(arg, ast.JoinedStr):
            for value in arg.values:
                if isinstance(value, ast.Constant):
                    self.print_text(str(value.value))
                elif isinstance(value, ast.FormattedValue) and not value.format_spec and value.conversion == -1:
                    if isinstance(value.value, ast.Name) and value.value.id in self.str_vars:
                        self.print_text(self.str_vars[value.value.id])
                    else:
                        try:
                            self.print_text(str(self.constant(value.value) % 65536))
                        except CompileError:
                            self.print_number_expr(value.value)
                else:
                    raise CompileError(f'line {line}: unsupported f-string format')
            return
        try:
            self.print_text(str(self.constant(arg) % 65536))
        except CompileError:
            self.print_number_expr(arg)

    def do_print(self, node):
        end, sep = '\n', ' '
        for kw in node.keywords:
            if kw.arg in ('end', 'sep') and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                if kw.arg == 'end': end = kw.value.value
                else: sep = kw.value.value
            else: raise CompileError(f'line {node.lineno}: only string sep= and end= are supported')
        for i, arg in enumerate(node.args):
            if i: self.print_text(sep)
            self.print_value(arg, node.lineno)
        self.print_text(end)

    def assign(self, name, expr, node):
        dst = self.var(name, node); tmp = self.pair(); self.expr_into(expr, tmp)
        self.copy_cell(tmp[0], dst[0]); self.copy_cell(tmp[1], dst[1])

    def body(self, statements):
        for stmt in statements: self.stmt(stmt)

    def stmt(self, node):
        if isinstance(node, ast.Assign):
            if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name): raise CompileError(f'line {node.lineno}: only simple assignments are supported')
            name = node.targets[0].id
            if name in self.str_vars:
                value = self.string_expr(node.value)
                if value is None:
                    raise CompileError(f'line {node.lineno}: string variables can only be assigned string literals, string variables, concatenations, or constant f-strings')
                self.str_vars[name] = value
            else:
                value = self.string_expr(node.value)
                if value is not None:
                    self.str_vars[name] = value
                else:
                    self.assign(name, node.value, node)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            name = node.target.id; dst = self.var(name, node); rhs = self.pair(); self.expr_into(node.value, rhs)
            if isinstance(node.op, ast.Add): self.add16(rhs, dst)
            elif isinstance(node.op, ast.Sub): self.sub16(rhs, dst)
            elif isinstance(node.op, ast.Mult):
                left = self.pair(); self.copy_cell(dst[0], left[0]); self.copy_cell(dst[1], left[1]); self.multiply_pairs(left, rhs, dst)
            elif isinstance(node.op, (ast.FloorDiv, ast.Mod)):
                left = self.pair(); self.copy_cell(dst[0], left[0]); self.copy_cell(dst[1], left[1]); self.divmod16(left, rhs, dst, isinstance(node.op, ast.FloorDiv))
            elif isinstance(node.op, ast.Pow):
                left = self.pair(); self.copy_cell(dst[0], left[0]); self.copy_cell(dst[1], left[1]); tmp = self.pair(); self.expr_into(ast.BinOp(left=ast.Name(id=name, ctx=ast.Load()), op=ast.Pow(), right=node.value), tmp); self.copy_cell(tmp[0], dst[0]); self.copy_cell(tmp[1], dst[1])
            else: raise CompileError(f'line {node.lineno}: unsupported augmented operation')
        elif isinstance(node, ast.If):
            condp = self.pair(); self.expr_into(node.test, condp); cond = self.alloc(); self.truth16(condp, cond)
            if node.orelse:
                other = self.alloc(); self.set_cell(other, 1)
                cond_copy = self.alloc(); self.copy_cell(cond, cond_copy)
                self.if_cell(cond_copy, lambda: self.zero(other))
                self.if_cell(cond, lambda: self.body(node.body))
                self.if_cell(other, lambda: self.body(node.orelse))
            else: self.if_cell(cond, lambda: self.body(node.body))
        elif isinstance(node, ast.While):
            if node.orelse: raise CompileError(f'line {node.lineno}: while-else is not supported')
            condp = self.pair(); cond = self.alloc(); self.expr_into(node.test, condp); self.truth16(condp, cond)
            self.goto(cond); self.emit('['); self.emit('-'); self.body(node.body)
            self.set_pair(condp, 0); self.expr_into(node.test, condp); self.truth16(condp, cond); self.goto(cond); self.emit(']')
        elif isinstance(node, ast.For):
            raise CompileError(f'line {node.lineno}: for loops should be transformed before compilation')
        elif isinstance(node, ast.Expr):
            val = node.value
            if isinstance(val, ast.Constant): return
            if isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == 'print': self.do_print(val)
            elif isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and val.func.id == '__putc' and len(val.args) == 1 and not val.keywords:
                p = self.pair(); self.expr_into(val.args[0], p); self.goto(p[0]); self.emit('.')
            else: raise CompileError(f'line {node.lineno}: unsupported expression statement')
        elif isinstance(node, ast.Pass): return
        else: raise CompileError(f'line {getattr(node, "lineno", "?")}: unsupported statement {type(node).__name__}')

    def compile(self, source):
        tree = ast.parse(source)
        tree = ForDesugar().visit(tree)
        ast.fix_missing_locations(tree)
        changed = True
        while changed:
            changed = False
            for n in ast.walk(tree):
                if not isinstance(n, ast.Assign) or len(n.targets) != 1 or not isinstance(n.targets[0], ast.Name):
                    continue
                name = n.targets[0].id
                if name in self.str_vars:
                    continue
                value = self.string_expr(n.value)
                if value is not None:
                    self.str_vars[name] = value
                    changed = True
        for n in ast.walk(tree):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id not in self.str_vars:
                self.alloc_var(n.id)
        self.body(tree.body)
        return optimize(''.join(self.code))


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print("Usage: python3 py2bf.py input.py [output.bf]")
        print("Compiler uses unsigned 16-bit integers (0..65535), wrapping modulo 65536.")
        sys.exit(0 if args else 1)
    try:
        src = open(args[0], encoding="utf-8").read()
        code = Compiler16().compile(src)
    except (CompileError, SyntaxError, ZeroDivisionError) as e:
        print("Compilation error:", e, file=sys.stderr)
        sys.exit(1)
    output = "\n".join(code[i:i + 100] for i in range(0, len(code), 100)) + "\n"
    if len(args) > 1:
        with open(args[1], "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Done: {args[1]} ({len(code)} brainfuck commands)")
    else:
        sys.stdout.write(output)


if __name__ == "__main__":
    main()
