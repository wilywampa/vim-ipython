"""
Monitor for IPython/Jupyter console commands run from Vim.

Usage:
    1. Run jupyter/ipython console
    2. Run python monitor.py
    3. Connect Vim to console kernel using IPython command
"""
from __future__ import print_function
import ast
import logging
import os
import re
import sys
import textwrap
try:
    from jupyter_client import KernelManager, find_connection_file
except ImportError:
    from IPython.kernel import KernelManager, find_connection_file
try:
    from queue import Empty
except ImportError:
    from Queue import Empty
from glob import glob
from highlighter import highlight

logger = logging.getLogger(__name__)

colors = {k: i for i, k in enumerate([
    'black', 'red', 'green', 'yellow', 'blue', 'magenta', 'cyan', 'white'])}

parts = re.compile(r'^(\s*)(.*?)(\s*)$', flags=re.DOTALL)
strip_escapes_sub = re.compile(r"""
    \x1b     # literal ESC
    \[       # literal [
    [;\d]*   # zero or more digits or semicolons
    [A-Za-z] # a letter
    """, re.VERBOSE).sub


def paths():
    for fullpath in glob(os.path.join(os.path.dirname(filename), 'kernel*')):
        if not re.match('^(.*/)?kernel-[0-9]+.json', fullpath):
            continue
        yield fullpath


def strip_escapes(s):
    return strip_escapes_sub("", s)


def colorize(string, color, bold=False, bright=False):
    if isinstance(color, str):
        code = ''.join(('\033[', str(colors[color] + (90 if bright else 30))))
    else:
        code = '\033[38;5;%d' % color
    return ''.join((code, ';1' if bold else '', 'm', string, '\033[0m'))


def get_msgs():
    try:
        kc.iopub_channel.flush()
        return kc.iopub_channel.get_msgs()
    except AttributeError:
        msgs = []
        while True:
            try:
                msgs.append(kc.iopub_channel.get_msg(timeout=0.001))
            except Empty:
                return msgs


def write(text):
    return sys.stdout.write(str(text).encode())


class IPythonMonitor(object):

    def __init__(self):
        self.clients = set()
        self.execution_count_id = None
        self.last_msg_type = None  # Only set when text written to stdout
        self.last_execution_count = 0
        self.at_eol = False

    def wrap(self, text, include_blank_lines=True, prompt=False):
        leading, text, trailing = parts.search(text).groups()
        max_width = os.get_terminal_size().columns
        prompt_width = len('Out []: ' + str(self.last_execution_count + 1))
        output = []
        for i, line in enumerate(text.splitlines()):
            s = strip_escapes(line).rstrip()
            w = max_width
            if prompt and i == 0:
                w -= prompt_width
            if len(s) > w and (include_blank_lines or s.strip()):
                output.extend(textwrap.wrap(s, w))
            else:
                output.append(line)
        return leading + '\n'.join(output).strip() + trailing

    def print_prompt(self, start='In', color=28, num_color=10, count_offset=0):
        count = str(self.last_execution_count + count_offset)
        write(colorize(start.rstrip() + ' [', color))
        write(colorize(count, num_color, bold=True))
        write(colorize(']: ', color))
        return '%s [%s]: ' % (start.strip(), count)

    def listen(self):
        while socket.recv():
            for msg in get_msgs():
                msg_type = msg['msg_type']
                logger.info('received %s', msg_type)
                logger.debug(msg)

                if msg_type == 'shutdown_reply':
                    sys.exit(0)

                client = msg['parent_header'].get('session', '')
                if (client and msg_type in ('execute_input', 'pyin') and
                        msg['content']['code'] == '"_vim_client";_=_;__=__'):
                    self.clients.add(client)
                    continue
                if client not in self.clients:
                    continue

                getattr(self, msg_type, self.other)(msg)

    def pyin(self, msg):
        self.last_execution_count = msg['content']['execution_count']
        write('\r')
        dots = ' ' * (len(self.print_prompt().rstrip()) - 1) + ': '
        code = highlight(msg['content']['code'])
        output = code.rstrip().replace('\n', '\n' + colorize(dots, 28))
        write(self.wrap(output, prompt=True))
        self.execution_count_id = msg['parent_header']['msg_id']
        self.last_msg_type = msg['msg_type']

    def pyout(self, msg, prompt=True, spaces=''):
        if 'execution_count' in msg['content']:
            self.last_execution_count = msg['content']['execution_count']
            self.execution_count_id = msg['parent_header']['msg_id']
        output = msg['content']['data']['text/plain']
        output = self.wrap(output, prompt=prompt and '\n' not in output)
        if prompt:
            self.print_prompt('\nOut', 9, 9)
            write(('\n' if '\n' in output else '') + output)
        else:
            write(output)
        self.last_msg_type = msg['msg_type']

    def display_data(self, msg):
        write('\n')
        self.pyout(msg, prompt=False)

    def pyerr(self, msg):
        write('\n' + self.wrap('\n'.join(msg['content']['traceback'])) + '\n')
        logger.debug('last_msg_type: %s', self.last_msg_type)
        if self.last_msg_type not in ('execute_input', 'pyin'):
            self.print_prompt('In')
        self.last_msg_type = msg['msg_type']

    def stream(self, msg):
        if self.last_msg_type not in ('pyerr', 'error', 'stream'):
            write('\n')
        try:
            data = msg['content']['text']
        except KeyError:
            data = msg['content']['data']
        if self.at_eol and not data.startswith('\r'):
            write('\n')
        write(colorize(self.wrap(data, include_blank_lines=False),
                       'cyan', bright=True))
        if msg['content']['name'] == 'stderr':
            sys.stderr.flush()
        else:
            sys.stdout.flush()
        self.last_msg_type = msg['msg_type']
        self.at_eol = bool(re.match('[\r][^\n]*$', data))

    def status(self, msg):
        if (msg['content']['execution_state'] == 'idle' and
                msg['parent_header']['msg_id'] == self.execution_count_id):
            self.print_prompt('\nIn', count_offset=1)
            self.execution_count_id = None

    def clear_output(self, msg):
        if self.last_msg_type in ('execute_input', 'pyin'):
            write('\n\n')
        write('\033[2K\r')

    def other(self, msg):
        write('msg_type = %s\n' % str(msg['msg_type']))
        write('msg = %s\n' % str(msg))

    execute_input = pyin
    execute_result = pyout
    error = pyerr


connected = False
if __name__ == '__main__':
    while not connected:
        try:
            filename = find_connection_file('kernel*')
        except IOError:
            continue

        for fullpath in paths():
            km = KernelManager(connection_file=fullpath)
            km.load_connection_file()

            kc = km.client()
            kc.start_channels()
            try:
                send = kc.execute
            except AttributeError:
                send = kc.shell_channel.execute
            if not hasattr(kc, 'iopub_channel'):
                kc.iopub_channel = kc.sub_channel

            send('', silent=True)
            try:
                msg = kc.shell_channel.get_msg(timeout=1)
                connected = True
                socket = km.connect_iopub()
                print('IPython monitor connected successfully')
                break
            except KeyboardInterrupt:
                sys.exit(0)
            except (Empty, KeyError):
                continue
            except Exception as e:
                import traceback
                traceback.print_exc()
            finally:
                if not connected:
                    kc.stop_channels()

    if len(sys.argv) > 1:
        term = open(sys.argv[1], 'wb+', buffering=0)
        sys.stdout = term
    else:
        msg_id = send('import os as _os; _tty = _os.ttyname(1)', silent=True,
                      user_expressions=dict(_tty='_tty'))
        while True:
            try:
                msg = kc.shell_channel.get_msg(timeout=1.0)
                if msg['parent_header']['msg_id'] == msg_id:
                    tty = ast.literal_eval(
                        msg['content']['user_expressions']
                        ['_tty']['data']['text/plain'])
                    sys.stdout = open(tty, 'wb+', buffering=0)
                    break
            except Empty:
                continue

    monitor = IPythonMonitor()
    monitor.print_prompt(count_offset=1)
    monitor.listen()
