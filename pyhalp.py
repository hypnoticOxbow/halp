#!/usr/bin/env python
"""
Run a Halp-extended .py sourcefile from stdin; write to stdout the
same sourcefile with evaluation results placed inline.
"""

import sys
import traceback


# Evaluation

def halp(string_):
    input = [line for line in string_.split('\n')
             if not line.startswith('#| ')]
    return format_part(eval_module(input))

def eval_module(input):
    mod_dict = {'__name__': '', '__file__': '<stdin>', '__doc__': None}
    try:
        exec '\n'.join(input) in mod_dict
    except:
        lineno = get_lineno(sys.exc_info())
        parts = map(InputPart, input)
        parts.insert(lineno, format_exc())
    else:
        parts = []
        for line in input:
            parts.append(InputPart(line))
            if line.startswith('## '):
                code = line[len('## '):]
                parts.append(eval_line(code, mod_dict))
    return CompoundPart(parts)

def eval_line(code, globals):
    """Given a string that may be either an expression or a statement,
    evaluate it and return a part for output."""
    try:
        return OutputPart(repr(eval(code, globals)))
    except SyntaxError:
        try:
            exec code in globals
            return EmptyPart()
        except:
            return format_exc()
    except:
        return format_exc()


# Exception capture

def format_exc(limit=None):
    """Like traceback.format_exc() but reformatted/renumbered."""
    try:
        etype, value, tb = sys.exc_info()
        return format_exception(etype, value, tb, limit)
    finally:
        etype = value = tb = None

def format_exception(etype, value, tb, limit=None):
    exc_lines = traceback.format_exception_only(etype, value)
    exc_only = ''.join(exc_lines).rstrip('\n')
    parts = [OutputPart('Traceback (most recent call last):'),
             TracebackPart(traceback.extract_tb(tb, limit)[1:]),
             OutputPart(exc_only)]
    return CompoundPart(parts)

def get_lineno((etype, value, tb)):
    if isinstance(value, SyntaxError) and value.filename == '<string>':
        return value.lineno
    items = traceback.extract_tb(tb)
    if items:
        filename, lineno, func_name, text = items[-1]
        if filename == '<string>':
            return lineno
    return 1


# Output formatting with traceback line-number fixup

def format_part(part):
    lnmap = LineNumberMap()
    part.count_lines(lnmap)
    return part.format(lnmap)

class LineNumberMap:
    # TODO: faster algorithm
    def __init__(self):
        self.n_input = 1
        self.inserts = []
    def count_input_line(self):
        self.n_input += 1
    def count_output(self, n_lines):
        self.inserts.append((self.n_input, n_lines))
    def fix_lineno(self, lineno):
        delta = sum(n for i, n in self.inserts if i < lineno)
        return lineno + delta

class EmptyPart:
    def count_lines(self, lnmap):
        pass
    def format(self, lnmap):
        return ''

class CompoundPart:
    def __init__(self, parts):
        self.parts = parts
    def count_lines(self, lnmap):
        for part in self.parts:
            part.count_lines(lnmap)
    def format(self, lnmap):
        return '\n'.join(part.format(lnmap) for part in self.parts
                         if not isinstance(part, EmptyPart)) # ugh

class InputPart:
    def __init__(self, text):
        self.text = text
    def count_lines(self, lnmap):
        lnmap.count_input_line()
    def format(self, lnmap):
        return self.text

class OutputPart:
    def __init__(self, text):
        self.text = text
    def count_lines(self, lnmap):
        lnmap.count_output(1 + self.text.count('\n'))
    def format(self, lnmap):
        return format_result(self.text)

class TracebackPart:
    def __init__(self, tb_items):
        self.items = tb_items
    def count_lines(self, lnmap):
        def item_len((filename, lineno, name, line)):
            return 2 if line else 1
        lnmap.count_output(sum(map(item_len, self.items)))
    def format(self, lnmap):
        def fix_item((filename, lineno, name, line)):
            if filename == '<string>':
                lineno = lnmap.fix_lineno(lineno) 
            return (filename, lineno, name, line)
        return format_result(format_traceback(map(fix_item, self.items)))

def format_result(s):
    return '#| %s' % s.replace('\n', '\n#| ')

def format_traceback(tb_items):
    return ''.join(traceback.format_list(tb_items)).rstrip('\n')


# Main program

if __name__ == '__main__':
    sys.stdout.write(halp(sys.stdin.read()))
