#!/usr/bin/env python3
import sys

def gen(text):
    out, cur = [], 0
    for ch in text:
        d = ord(ch) - cur
        sign = "+" if d > 0 else "-"
        n = abs(d)
        if d == 0:
            out.append(".")
        elif n <= 12:
            out.append(sign * n + ".")
        else:
            best = min(((a + b + abs(n - a * b), a, b)
                        for a in range(2, 20) for b in range(2, 20)))
            _, a, b = best
            c = n - a * b
            csign = sign if c >= 0 else ("-" if sign == "+" else "+")
            out.append(">" + "+" * a + "[<" + sign * b + ">-]<" + csign * abs(c) + ".")
        cur = ord(ch)
    return "".join(out)

if __name__ == "__main__":
    text = open(sys.argv[1], encoding="utf-8").read()
    open(sys.argv[2], "w").write(gen(text) + "\n")
