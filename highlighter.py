from __future__ import print_function
import logging
import pygments
import re
import six
from IPython import get_ipython
from IPython.core import formatters
from IPython.core.events import available_events
from pygments.formatters import TerminalFormatter
from pygments.lexer import Lexer, RegexLexer, bygroups, using
from pygments.lexers import (BashLexer, ClassNotFound, CythonLexer,
                             Python3Lexer, PythonLexer)
from pygments.token import Keyword, Name, Operator, String, Text

default_fmt = "[%(name)s] %(levelname)s | %(asctime)s | %(message)s"
TYPES = set(('Ellipsis', 'False', 'None', 'True', 'basestring', 'bool',
             'buffer', 'bytearray', 'bytes', 'chr', 'complex', 'complex128',
             'complex256', 'complex64', 'dict', 'file', 'float', 'float128',
             'float16', 'float32', 'float64', 'format', 'frozenset', 'help',
             'int', 'int16', 'int32', 'int64', 'int8', 'list', 'long',
             'object', 'set', 'str', 'super', 'tuple', 'type', 'uint16',
             'uint32', 'uint64', 'uint8', 'unichr', 'unicode', 'void'))
PyLexer = Python3Lexer if six.PY3 else PythonLexer


class IPythonLexer(RegexLexer):

    tokens = PyLexer.tokens.copy()

    # Improve highlighting of IPython's formatter output
    extra_tokens = [
        (r"(<)((?:class|type)\s+')([^']*)('>)",
         bygroups(Operator, Keyword, Name.Class, Operator)),
        (r"(<)(function\s+')([^']*)('>)",
         bygroups(Operator, Keyword, Name.Function, Operator)),
        (r"(<)(class|classmethod|staticmethod|bound method|function)",
         bygroups(Operator, Keyword)),
        (r"(<)([a-zA-Z_.]*)( object )(at )",
         bygroups(Operator, Name.Class, Keyword, Text)),
    ]
    index = next(i for i, item in enumerate(
        tokens['root']) if 'and' in item[0])
    tokens['root'][index:index] = extra_tokens

    # Highlight IPython magics
    Percent = Name.Decorator
    Bang = String.Escape
    tokens['root'] = [
        (r'(?s)(^\s*)(%%)(cython)([^\n]*\n)(.*)',
         bygroups(Text, Percent, Name.Class, Text, using(CythonLexer))),
        (r"(%%?)(\w+)(\?\??)$", bygroups(Percent, Name.Class, Operator)),
        (r"(\s*%%)(!)", bygroups(Percent, Bang), ('shell_magic', 'magic_args')),
        (r"(\s*%%)((sx|sc|system|script[ \t]+\w*sh)\b)",
         bygroups(Percent, Name.Class), ('shell_magic', 'magic_args')),
        (r"(\s*%%)(\w+[ \t]*)", bygroups(Percent, Name.Class), 'magic_args'),
        (r"\b(\?\??)(\s*)$", bygroups(Operator, Text)),
        (r'(%)(sx|sc|system)(.*)(\n)',
         bygroups(Percent, Name.Class, using(BashLexer), Text)),
        (r'(%)(\w+[ \t]*)', bygroups(Percent, Name.Class), 'magic_args'),
        (r'^(!!)(.+)(\n)', bygroups(Bang, using(BashLexer), Text)),
        (r'(!)(?!=)(.+)(\n)', bygroups(Bang, using(BashLexer), Text)),
        (r'^(\s*)(\?\??)(\s*%{0,2}[\w\.\*]*)', bygroups(Text, Percent, Text)),
    ] + tokens['root']

    tokens['magic_args'] = [
        (r'[ \t]*\n', Text, '#pop'),
        (r'[ \t]+{(?=.*}[ \n\t])', Percent, 'brackets'),
        (r'[ \t]+', Text),
        (r'`', Percent, 'backquotes'),
        (r'{', Percent, 'brackets'),
        ('(?:[rR]|[uU][rR]|[rR][uU])?"', String, 'dqs'),
        ("(?:[rR]|[uU][rR]|[rR][uU])?'", String, 'sqs'),
        (r'.', Text),
    ]

    tokens['shell_magic'] = [
        (r'(?s).*', using(BashLexer), '#pop'),
    ]

    # Highlight Python code between `...` in IPython magics
    tokens['backquotes'] = [
        (r'[^`\n]*?\n', Text, '#pop'),
        (r'([^`]*)(`)', bygroups(using(PyLexer), Percent), '#pop'),
    ]
    tokens['brackets'] = [
        (r'}[ \t]+', Percent, '#pop'),
        (r'}\n', Percent, '#pop:2'),
        (r'(.*?)(}[ \n\t])+', bygroups(using(PyLexer), Percent), '#pop'),
        (r'.', Text),
    ]

    # Color preferences
    if six.PY3:
        for i, rule in enumerate(tokens['fromimport']):
            if isinstance(rule, tuple) and 'import' in rule[0]:
                tokens['fromimport'][i] = rule[0], bygroups(
                    Text, Keyword.Namespace), '#pop'

    index, builtins = next((i, t) for i, t in enumerate(tokens['builtins'])
                           if isinstance(t, tuple) and t[-1] == Name.Builtin)
    keywords = tokens['keywords'][0][0]
    try:
        builtins[0].words = tuple(set(builtins[0].words) - TYPES)
        keywords.words = tuple(set(keywords.words) - TYPES)
    except AttributeError:

        def split(source):
            prefix, words, suffix = re.search(
                r'(^.*?)((?:\w+\|)+\w+)(.*?$)', source).groups()
            return prefix, words.split('|'), suffix

        def join(split, words):
            prefix, _, suffix = split
            return prefix + '|'.join(words) + suffix

        tokens['builtins'][index] = (join(split(builtins[0]),
                                          set(split(builtins[0])[1]) - TYPES),
                                     Name.Builtin)
        tokens['keywords'][0] = (join(split(keywords),
                                      set(split(keywords)[1]) - TYPES), Keyword)
    try:
        from pygments.lexer import words
        tokens['builtins'].insert(
            0, (words(TYPES, prefix=r'(?<!\.)', suffix=r'\b'), Name.Constant))
    except ImportError:
        tokens['builtins'].insert(
            0, (r'(?<!\.)(' + '|'.join(TYPES) + r')\b', Name.Constant))
    index = next(i for i, t in enumerate(tokens['builtins'])
                 if isinstance(t, tuple) and t[-1] == Name.Builtin.Pseudo)
    tokens['builtins'][index] = (r'(?<!\.)(self|NotImplemented)\b',
                                 Name.Builtin.Pseudo)
    tokens['name'] = [
        (r'(@)([\w.]+)', bygroups(Name.Decorator, Name.Function)),
        (Python3Lexer.uni_name if six.PY3 else '[a-zA-Z_]\w*', Name),
    ]


python_lexer = IPythonLexer()
formatter = TerminalFormatter()


def highlight(text, lexer_or_filename=python_lexer,
              formatter=formatter, language=None):
    """
    Highlight text using IPythonLexer and default formatter.

    If lexer_or_filename is None, guess lexer based on text. If
    lexer_or_filename is a string, guess lexer based on text and
    lexer_or_filename as a filename.
    """
    lexer = lexer_or_filename
    try:
        if lexer is None:
            lexer = pygments.lexer.guess_lexer(text)
        elif isinstance(lexer, six.string_types):
            lexer = pygments.lexers.guess_lexer_for_filename(lexer, text)
        elif language is not None:
            lexer = pygments.lexers.get_lexer_by_name(language)
        elif isinstance(lexer, type) and issubclass(lexer, Lexer):
            lexer = lexer()
    except ClassNotFound:
        pass
    return pygments.highlight(text, lexer, formatter)


class HighlightTextFormatter(formatters.PlainTextFormatter):

    """Add syntax highlighting of output from PlainTextFormatter."""

    def __init__(self, *args, **kwargs):
        super(HighlightTextFormatter, self).__init__(*args, **kwargs)
        self.color = False
        for event in available_events:
            if event != 'pre_run_cell':
                get_ipython().events.register(event, self.disable_color)
        get_ipython().events.register('pre_run_cell', self.enable_color)

    def __call__(self, obj):
        from IPython.core.displaypub import CapturingDisplayPublisher
        ip = get_ipython()
        if ip and isinstance(ip.display_pub, CapturingDisplayPublisher):
            self.color = False
        value = super(HighlightTextFormatter, self).__call__(obj)
        if self.pprint and self.color:
            try:
                return pygments.highlight(
                    value, python_lexer, formatter).strip()
            except Exception:
                pass
        return value

    def disable_color(self):
        self.color = False

    def enable_color(self):
        self.color = True


class LogHighlighter(logging.Formatter):

    """A logging formatter that highlights Python objects."""

    def __init__(self, fmt=default_fmt, datefmt='%a %H:%M', **kwargs):
        return super(LogHighlighter, self).__init__(
            fmt=fmt, datefmt=datefmt, **kwargs
        )

    def format(self, record):
        if not record.args:
            if not isinstance(record.msg, six.string_types):
                record.msg = hl(str(record.getMessage()))
        else:
            record.args = tuple(arg if isinstance(arg, six.string_types)
                                else hl(str(arg)) for arg in record.args)
        return super(LogHighlighter, self).format(record)


def add_handler(file_or_stream, logger=None, level=logging.INFO):
    if not isinstance(logger, logging.Logger):
        logger = logging.getLogger(logger)
    if level is not None:
        logger.setLevel(level)
    if isinstance(file_or_stream, six.string_types):
        handler = logging.FileHandler(file_or_stream)
    else:
        handler = logging.StreamHandler(file_or_stream)
    handler.setFormatter(LogHighlighter())
    logger.addHandler(handler)
    return handler


def hl(*objs):
    text = str(objs[0] if len(objs) == 1 else objs)
    return pygments.highlight(text, python_lexer, formatter).strip()
