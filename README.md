# py2bf

A small compiler from a **subset of Python to Brainfuck** using unsigned
16-bit integers. It parses Python source with Python's `ast` module and
generates Brainfuck code that performs the program's calculations at
runtime.

``` python
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

``` console
$ python3 py2bf.py fizzbuzz.py fizzbuzz.bf
$ python3 bfrun.py fizzbuzz.bf
1
2
Fizz
4
Buzz
...
```

## Contents

  -----------------------------------------------------------------------
  File                                Purpose
  ----------------------------------- -----------------------------------
  `py2bf.py`                          Compiler: supported Python subset →
                                      Brainfuck

  `bfrun.py`                          Brainfuck interpreter

  `make_bf.py`                        Helper that generates Brainfuck
                                      code to print a text file
  -----------------------------------------------------------------------

No external dependencies are required; the scripts use the Python 3
standard library. Python 3.8+ is recommended.

## Usage

Compile a program and run the generated Brainfuck:

``` console
python3 py2bf.py program.py program.bf
python3 bfrun.py program.bf
```

If the output filename is omitted, `py2bf.py` writes the Brainfuck code
to standard output.

Optionally make the scripts executable and put them on your `PATH`:

``` console
chmod +x py2bf.py bfrun.py
mkdir -p ~/.local/bin
ln -s "$PWD/py2bf.py" ~/.local/bin/py2bf
ln -s "$PWD/bfrun.py" ~/.local/bin/bfrun

py2bf program.py program.bf && bfrun program.bf
```

`chmod +x` makes the scripts executable; `mkdir -p` creates the local
bin directory if needed; the `ln -s` commands create command-name
symlinks.

### `make_bf.py`

``` console
python3 make_bf.py input.txt output.bf
```

Generates Brainfuck that prints the contents of `input.txt` as UTF-8
text. It does not execute the file: passing a `.py` file makes a
Brainfuck program that prints the Python source code itself.

## Supported Python subset

  -----------------------------------------------------------------------
  Feature                             Details
  ----------------------------------- -----------------------------------
  Numbers                             Unsigned 16-bit integers,
                                      `0..65535`

  Variables                           Numeric variables and compile-time
                                      string variables

  Arithmetic                          `+`, `-`, `*`, `//`, `%`, `**`;
                                      unary `+` and `-`

  Augmented assignment                `+=`, `-=`, `*=`, `//=`, `%=`,
                                      `**=`

  Comparisons                         `==`, `!=`, `<`, `>`, `<=`, `>=`;
                                      one comparison at a time

  Logic                               `and`, `or`, `not`; results are `0`
                                      or `1`

  Conditions                          `if`, `elif`, `else`

  Loops                               `while`; `for i in range(...)` with
                                      one to three arguments and a
                                      constant non-zero step

  Built-ins                           `min(...)`, `max(...)` with at
                                      least two arguments

  Output                              `print(...)` with strings, numbers,
                                      expressions, f-strings, `sep=` and
                                      `end=`

  String expressions                  String literals, string-variable
                                      references, concatenation with `+`,
                                      and constant f-strings

  Low-level output                    `__putc(expr)` writes the low byte
                                      of the expression

  Text encoding                       String literals are emitted as
                                      UTF-8
  -----------------------------------------------------------------------

Unsupported constructs produce a compilation error with a line number
when available.

Not supported: floats, lists, dictionaries, user-defined functions,
`break`, `continue`, `input()`, chained comparisons such as `a < b < c`,
tuple unpacking, and `while ... else`.

### String variables

Strings are currently handled **at compile time**, not stored as mutable
strings in Brainfuck memory:

``` python
name = "Brainfuck"
greeting = "Hello, " + name + "!"
value = 123

print(name)
print(greeting)
print(f"Hello, {name}! Value: {value}")
```

Supported string assignments are string literals, references to other
string variables, concatenations of supported string expressions, and
f-strings whose interpolations can be resolved at compile time. In
`print()` f-strings can also interpolate numeric expressions evaluated
at runtime.

String variables cannot be changed dynamically at runtime, and `input()`
or runtime string manipulation is not supported.

## Limitations

-   **Numbers wrap around modulo 65536.** For example, `65535 + 1`
    becomes `0`, and `0 - 1` becomes `65535`.
-   Values are unsigned. Negative values are represented modulo 65536;
    they are not signed integers.
-   `range` uses a constant, non-zero step. Its loop counter is
    generated separately to avoid relying only on a wrapping comparison
    against the end value.
-   Division and modulo by zero return `0` in this implementation.
-   `and` and `or` return `0` or `1`, rather than returning one of their
    operands as Python does.
-   `__putc(expr)` outputs only the low 8 bits as a byte.
-   Numeric output is decimal. Dynamic number formatting is implemented
    in Brainfuck and can be slow, especially for large values.
-   Generated Brainfuck can be large, and operations such as
    multiplication, division, comparisons, and decimal output may run
    slowly in a simple interpreter.

## How it works

-   **Memory layout:** each numeric variable uses two Brainfuck cells: a
    low byte and a high byte. Temporary cells are allocated above the
    variables.
-   **Arithmetic:** expressions are evaluated into temporary two-cell
    values. Addition and subtraction propagate carry and borrow;
    multiplication uses repeated addition; division and modulo use
    repeated subtraction.
-   **Control flow:** `if` and `while` are translated into Brainfuck
    loops over flag cells.
-   **`for` loops:** `for i in range(...)` is transformed into a loop
    with a separately calculated iteration count.
-   **Output:** strings are emitted as UTF-8 bytes. Numeric values are
    converted to decimal digits by generated Brainfuck code.
-   **Optimization:** a peephole pass removes cancelling command pairs
    such as `+-`, `-+`, `<>`, and `><`.

## The interpreter

`bfrun.py` is the companion interpreter. It runs Brainfuck code with
30,000 8-bit cells and wraps each cell modulo 256. It merges runs of
`+`, `-`, `<`, and `>` and optimizes common loops such as `[-]` and
transfer loops. The `,` command reads from standard input if the program
uses it. Output is written as raw bytes, so UTF-8 text displays
correctly.

## Example programs

### Hello World

``` python
print("Hello World!")
```

### Squares

``` python
for i in range(1, 6):
    print(i, "squared =", i * i)
```

### Greatest common divisor

``` python
a = 48
b = 18

while a != b:
    if a > b:
        a -= b
    else:
        b -= a

print("gcd =", a)
```

### Primes below 60

``` python
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
