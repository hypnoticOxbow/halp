#!/usr/bin/env python
"""
Run a Halp-extended .py sourcefile from stdin; write to stdout an
encoding of the same sourcefile with evaluation results placed inline.
The encoding is a kind of diff against the input, expected by halp.el.
"""

import bisect
try:
    from StringIO import StringIO ## for Python 2
except ImportError:
    from io import StringIO ## for Python 3
import difflib
import os
import sys
import traceback


# Evaluation

source_filename = '<string>'  # Default

current_line_number = None

def halp(module_text):
    """Given a module's code as a string, produce the Halp output as a
    string."""
    input_lines = module_text.splitlines()
    input, old_outputs = strip_old_outputs(input_lines)
    env = set_up_globals(Halp(old_outputs))
    output = format_part(eval_module(input, env))
    return diff(output.splitlines(), input_lines)

def set_up_globals(halp_object):
    if source_filename.endswith('.py'):
        module_name = source_filename[:-3]
    else:
        module_name = '<string>'
    return {'__name__': module_name,
            '__file__': source_filename,
            '__doc__': None,
            'halp': halp_object}

def eval_module(input, module_dict):
    """Given a module's code as a list of lines, produce the Halp
    output as a 'part'."""
    global current_line_number
    current_line_number = None

    # The "+ '\n'" seems to fix a weird bug where we'd get a
    # syntax error sometimes if the last line was a '## ' line not
    # ending in a newline character. I still don't understand it.
    def thunk():
        exec( ('\n'.join(input) + '\n'), module_dict)
    output, _, exc_info, is_syn  = capturing_stdout(thunk)
    if exc_info is not None:
        lineno = get_lineno(exc_info)
        parts = [InputPart(x) for x in input ]
        parts.insert(lineno, format_exception(exc_info))
    else:
        parts = []
        for i, line in enumerate(input):
            parts.append(InputPart(line))
            if line.startswith('## '):
                code = line[len('## '):]
                current_line_number = i + 1
                parts.extend(eval_line(code, module_dict))
        if output:
            parts.append(OutputPart(output))
    return CompoundPart(parts)

def eval_line(code, module_dict):
    """Given a string that may be either an expression or a statement,
    evaluate it and return a list of parts for output."""
    output, result, exc_info, is_syn = \
        capturing_stdout(lambda: eval(code, module_dict))
    if exc_info is not None:
        if is_syn:
            def thunk(): exec(code,module_dict)
            output, result, exc_info, is_syn = capturing_stdout(thunk)
    parts = []
    if output: parts.append(OutputPart(output))
    if result is not None: parts.append(OutputPart(repr(result)))
    if exc_info is not None: parts.append(format_exception(exc_info))
    return parts

def capturing_stdout(thunk):
    """Run thunk() and return either (output, result, None, None) or
    (output, None, exc_info, is_syntax_error) -- the latter if thunk
    raised an exception."""
    # XXX ugly interface to preserve tricky exception/traceback
    #  capture logic to do with stack frames and line numbers.
    #  Come back to this -- hopefully could be cleaner.
    stdout = sys.stdout
    sys.stdout = stringio = StringIO()
    try:
        result = thunk()
    except SyntaxError:
        return stringio.getvalue(), None, sys.exc_info(), True
    except:
        return stringio.getvalue(), None, sys.exc_info(), False
    else:
        return stringio.getvalue(), result, None, None
    finally:
        sys.stdout = stdout

## strip_old_outputs('hello\n#. world\n#. universe'.split('\n'))
#. (['hello'], {1: ['world', 'universe']})

def strip_old_outputs(input_lines):
    stripped = []
    old_outputs = {}
    for line in input_lines:
        if line.startswith('#. '):
            old_outputs.setdefault(len(stripped), []).append(line[len('#. '):])
        else:
            stripped.append(line)
    return stripped, old_outputs


# Halp "system-call interface"
# This lets you feed back your command's previous output with 'halp.read()'.

class Halp:
    def __init__(self, old_outputs):
        self._old_outputs = old_outputs
    def read(self):
        return '\n'.join(self._old_outputs.get(current_line_number, []))


# Exception capture

def format_exception(params, limit=None):
    "Like traceback.format_exception() but returning a 'part'."
    exc_lines = traceback.format_exception_only(params[0], params[1])
    exc_only = ''.join(exc_lines).rstrip('\n')
    items = extract_censored_tb(params[2], limit)
    if items:
        return CompoundPart([OutputPart('Traceback (most recent call last):'),
                             TracebackPart(items),
                             OutputPart(exc_only)])
    else:
        return OutputPart(exc_only)

def extract_censored_tb(tb, limit=None):
    """Like traceback.extract_tb() but with Halp internals
    bowdlerized. (We assume the top-level halp() call is the top of
    our traceback.)"""
    # [3:] drops the top frames (which are Halp internals).
    items = traceback.extract_tb(tb, limit)[3:]
    if items and current_line_number:
        # The top item came from a '## ' line; fix its line number:
        filename, lineno, func_name, text = items[0]
        if filename == '<string>' and lineno == 1: # (should always be true)
            items[0] = filename, current_line_number, func_name, None
    return items

def get_lineno(exec_info):
    "Return the line number where this exception should be reported."
    if isinstance(exec_info[1], SyntaxError) and exec_info[1].filename == '<string>':
        return exec_info[1].lineno
    items = traceback.extract_tb(exec_info[2])
    if items:
        filename, lineno, func_name, text = items[-1]
        if filename == '<string>':
            return lineno
    return 0


# Formatting output with tracebacks fixed up

def format_part(part):
    "Return part expanded into a string, with line numbers corrected."
    lnmap = LineNumberMap()
    part.count_lines(lnmap)
    return '\n'.join(part.format(lnmap))

class LineNumberMap:
    "Tracks line-number changes and applies them to old line numbers."
    def __init__(self):
        self.input_lines = []
        self.output_positions = [0] # The line numbers where output is inserted
        self.fixups = [0]
        # self.fixups[i] is the count of all output lines preceding input lines
        # numbered in the range
        #   self.output_positions[i] < lineno <= self.output_positions[i+1]
        # Invariant:
        #   len(self.output_positions) == len(self.fixups)
        #   self.output_positions is sorted
    def add_input_line(self, line):
        self.input_lines.append(line)
    def get_input_line(self, lineno):
        """Tracebacks sometimes have None for the text of a line,
        so we have to supply it ourselves."""
        try: return self.input_lines[lineno - 1]
        except IndexError: return None
    def count_output(self, n_lines):
        self.output_positions.append(1 + len(self.input_lines))
        self.fixups.append(self.fixups[-1] + n_lines)
    def fix_lineno(self, lineno):
        i = bisect.bisect_right(self.output_positions, lineno) - 1
        return lineno + self.fixups[i]

class CompoundPart:
    "A part that's a sequence of subparts."
    def __init__(self, parts):
        self.parts = parts
    def count_lines(self, lnmap):
        for part in self.parts:
            part.count_lines(lnmap)
    def format(self, lnmap):
        return sum((part.format(lnmap) for part in self.parts), [])

class InputPart:
    "An input line, passed to the output unchanged."
    def __init__(self, text):
        self.text = text
    def count_lines(self, lnmap):
        lnmap.add_input_line(self.text)
    def format(self, lnmap):
        return [self.text]

class OutputPart:
    "Some output lines, with a #. prefix."
    def __init__(self, text):
        self.lines = text.splitlines()
    def count_lines(self, lnmap):
        lnmap.count_output(len(self.lines))
    def format(self, lnmap):
        return ['#. ' + line for line in self.lines]

class TracebackPart:
    """An output traceback with a #. prefix and with the stack frames
    corrected when they refer to the code being halped."""
    def __init__(self, tb_items):
        self.items = tb_items
    def count_lines(self, lnmap):
        def item_len(item_params):
            # XXX how to make sure this count is consistent with format_traceback()?
            if item_params[3]: return 2
            else: return 1
        lnmap.count_output(sum(map(item_len, self.items)))
    def format(self, lnmap):
        def fix_item(item_params):
            if item_params[0] == '<string>':
                filename = source_filename
                line = lnmap.get_input_line(item_params[1])
                lineno = lnmap.fix_lineno(item_params[1])
                name = item_params[2]
                return (filename,lineno,name,line)
            else:
                return item_params
        return format_traceback(map(fix_item, self.items))

def format_traceback(tb_items):
    "Turn a list of traceback items into a string."
    return ['#. ' + line.rstrip('\n').replace('\n', '\n#. ')
            for line in traceback.format_list(tb_items)]


# Producing a diff between input and output

def diff(new_lines, old_lines):
    return format_diff(compute_diff(None, new_lines, old_lines))

def format_diff(triples):
    return ''.join('%d %d %d\n%s' % (lo+1, hi-lo, len(lines),
                                     ''.join(line + '\n' for line in lines))
                   for lines, lo, hi in triples)

def compute_diff(is_junk, a, b):
    """
    Pre: is_junk: None or (string -> bool)
         a, b: [string]
    Return a list of triples (lines, lo, hi) representing the edits
    to convert b to a. The ranges (lo,hi) are disjoint and in
    descending order. Setting each b[lo:hi] = lines, in order, yields a.
    """
    sm = difflib.SequenceMatcher(is_junk, a, b)
    i = j = 0
    triples = []
    for ai, bj, size in sm.get_matching_blocks():
        # Invariant:
        #  triples is the diff for a[:i], b[:j]
        #  and the next matching block is a[ai:ai+size] == b[bj:bj+size].
        if i < ai or j < bj:
            triples.append((a[i:ai], j, bj))
        i, j = ai+size, bj+size
    triples.reverse()
    return triples


# Main program

if __name__ == '__main__':
    if 2 <= len(sys.argv): source_filename = sys.argv[1]
    if 3 <= len(sys.argv): sys.path[0] = os.path.dirname(sys.argv[2])
    sys.stdout.write(halp(sys.stdin.read()))
