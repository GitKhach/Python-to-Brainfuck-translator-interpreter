# py2bf

A small compiler from a **subset of Python** to [brainfuck](https://en.wikipedia.org/wiki/Brainfuck),
plus a fast brainfuck interpreter to run the result.

```python
# fizzbuzz.py
for i in range(1, 31):
    if i % 15 == 0:
        print("FizzBuzz")
    elif i % 3 == 0:
        print("Fizz")
    elif i % 5 == 0:
        print("Buzz")
    else:
        print(i)
```

```console
$ python3 py2bf.py fizzbuzz.py fizzbuzz.bf
$ python3 bfrun.py fizzbuzz.bf
1
2
Fizz
4
Buzz
...
```

This is a real compiler: the source is parsed with Python's `ast` module, and every
statement and expression is translated into brainfuck code that actually computes
it (loops, comparisons, multiplication, division, decimal output of numbers).
It is not a program that just prints a pre-computed text.

## Contents

| File         | Purpose                                                                 |
|--------------|-------------------------------------------------------------------------|
| `py2bf.py`   | the compiler: Python subset → brainfuck                                 |
| `bfrun.py`   | fast brainfuck interpreter                                              |
| `make_bf.py` | tiny helper: turns a text file into a brainfuck program that prints it  |

No dependencies, only the Python 3 standard library (Python 3.8+).

## Usage

Compile a program and run it:

```console
python3 py2bf.py program.py program.bf
python3 bfrun.py program.bf
```

If the output file is omitted, `py2bf.py` prints the brainfuck code to stdout.

Optionally make the scripts executable and put them on your `PATH`:

```console
chmod +x py2bf.py bfrun.py
mkdir -p ~/.local/bin
ln -s "$PWD/py2bf.py" ~/.local/bin/py2bf
ln -s "$PWD/bfrun.py" ~/.local/bin/bfrun

py2bf program.py program.bf && bfrun program.bf
```

### `make_bf.py`

```console
python3 make_bf.py input.txt output.bf
```

Generates brainfuck that prints the contents of `input.txt` (ASCII only). Note that it
works on the *text* of the file and does not execute anything: giving it a `.py` file
produces a program that prints the source code, not the program's output.

## Supported Python subset

| Feature        | Details                                                                  |
|----------------|--------------------------------------------------------------------------|
| Variables      | integers `0..255` (one 8-bit brainfuck cell each)                        |
| Arithmetic     | `+  -  *  //  %` and `+=  -=  *=  //=  %=`, unary `-`                    |
| Comparisons    | `==  !=  <  >  <=  >=` (one comparison at a time, no `a < b < c`)        |
| Logic          | `and`, `or`, `not` (they yield `0` or `1`)                               |
| Conditions     | `if` / `elif` / `else`                                                   |
| Loops          | `while`, `for i in range(n)`, `range(a, b)`, `range(a, b, step)` (constant non-zero step) |
| Output         | `print(...)` with strings, numbers, expressions and f-strings (`{expr}` only), `sep=` and `end=` |
| Text           | string literals may contain any Unicode, they are written as UTF-8      |

Anything else is rejected with a message that contains the line number, for example
`line 2: unsupported construction (Break)`.

Not supported: floats, lists, dicts, user-defined functions, `break` / `continue`,
`input()`, string variables, `while ... else`, tuple unpacking.

## Limitations

Brainfuck cells hold a single byte, and this shows through:

- **Numbers wrap around modulo 256.** `250 + 10` gives `4`, `3 - 5` gives `254`,
  `16 * 16` gives `0`. Keep all intermediate values within `0..255`.
- `range` bounds must also fit in a byte, so `range(0, 256)` does not work.
- Division and modulo by zero do not raise an error: `x // 0` is `0` and `x % 0` is `x`.
- `and` / `or` return `0` / `1`, not one of their operands as real Python does.
- The loop variable of a `for` loop is re-assigned on every iteration, so changing it
  inside the body does not affect the iteration (same as in Python).
- Generated code is large. `print("Hello World!")` is about 220 commands, and every
  `print(<number expression>)` inlines a digit-splitting routine of around a thousand
  commands.

Constants are printed exactly as written (`print(-1)` prints `-1`), while a variable
holding `-1` is stored as `255` and prints `255`.

## How it works

- **Memory layout.** Every variable gets its own cell on the tape; temporary cells are
  allocated above them (and always cleared before use).
- **Expressions** are evaluated "into" a destination cell. Addition and subtraction move
  values between cells with loops such as `[->+<]`, multiplication is a loop of additions,
  comparisons subtract both operands by one until one reaches zero, and division is
  repeated subtraction.
- **`if` / `while`** become `[ ... ]` loops over a flag cell; `if/else` uses a second flag
  cell that is cleared when the first branch runs.
- **`for i in range(...)`** is rewritten to a `while` loop with a precomputed iteration
  counter, because comparing `i < end` is unreliable when `i` can overflow a byte.
- **Printing numbers** is implemented in the same Python subset (split into hundreds,
  tens and ones with `while` loops, then print `digit + 48`) and compiled by the same
  compiler.
- **Peephole step:** pairs like `+-`, `-+`, `<>`, `><` are removed from the output.

### The interpreter

`bfrun.py` has 30000 8-bit cells with wrap-around. It is faster than a naive interpreter
because it merges runs of `+ - < >` into single operations and replaces loops such as
`[->+<]`, `[->++>+++<<]` and `[-]` with a single multiply-and-add step. The `,` command reads
from stdin (stdin is only read if the program contains `,`). Output is written as raw
bytes, so UTF-8 text prints correctly.

## Example programs

Hello World:

```python
print("Hello World!")
```

Squares and a loop:

```python
for i in range(1, 6):
    print(i, "squared =", i * i)
```

Greatest common divisor:

```python
a = 48
b = 18
while a != b:
    if a > b:
        a -= b
    else:
        b -= a
print("gcd =", a)
```

Primes below 60:

```python
for n in range(2, 60):
    p = 1
    d = 2
    while d * d <= n:
        if n % d == 0:
            p = 0
        d += 1
    if p:
        print(n, end=" ")
print()
```
