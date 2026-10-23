#!/usr/bin/env python3
import sys


def compile_bf(code):
    toks = [c for c in code if c in "+-<>.,[]"]
    ops, stack, i = [], [], 0
    while i < len(toks):
        c = toks[i]
        if c in "+-<>":
            grp = "+-" if c in "+-" else "<>"
            n = 0
            while i < len(toks) and toks[i] in grp:
                n += 1 if toks[i] in "+>" else -1
                i += 1
            if n:
                ops.append([0 if grp == "+-" else 1, n])
            continue
        if c == ".":
            ops.append([2, 0])
        elif c == ",":
            ops.append([3, 0])
        elif c == "[":
            stack.append(len(ops))
            ops.append([4, 0])
        else:
            k = stack.pop()
            body = ops[k + 1:]
            if all(o[0] in (0, 1) for o in body):
                off, coef = 0, {}
                for o, n in body:
                    if o == 1:
                        off += n
                    else:
                        coef[off] = coef.get(off, 0) + n
                if off == 0 and coef.get(0, 0) % 256 == 255:
                    del ops[k:]
                    ops.append([6, [(o, n) for o, n in coef.items() if o != 0]])
                    i += 1
                    continue
            ops.append([5, k])
            ops[k][1] = len(ops) - 1
        i += 1
    return ops


def run(code, inp=b""):
    ops = compile_bf(code)
    tape = [0] * 30000
    ptr = pc = ip = 0
    out = bytearray()
    n = len(ops)
    while pc < n:
        op, a = ops[pc]
        if op == 0:
            tape[ptr] = (tape[ptr] + a) & 255
        elif op == 1:
            ptr += a
        elif op == 6:
            v = tape[ptr]
            if v:
                for o, k in a:
                    tape[ptr + o] = (tape[ptr + o] + v * k) & 255
                tape[ptr] = 0
        elif op == 4:
            if not tape[ptr]:
                pc = a
        elif op == 5:
            if tape[ptr]:
                pc = a
        elif op == 2:
            out.append(tape[ptr])
        else:
            tape[ptr] = inp[ip] if ip < len(inp) else 0
            ip += 1
        pc += 1
    return bytes(out)


if __name__ == "__main__":
    prog = open(sys.argv[1]).read()
    data = sys.stdin.buffer.read() if "," in prog else b""
    sys.stdout.buffer.write(run(prog, data))
