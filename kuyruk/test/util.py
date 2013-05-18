import os
import sys
import errno
import signal
import logging
import subprocess
from time import time, sleep
from functools import partial
from contextlib import contextmanager

from what import What

from kuyruk.channel import LazyChannel
from kuyruk.queue import Queue as RabbitQueue

TIMEOUT = 10

logger = logging.getLogger(__name__)


def delete_queue(*queues):
    """Delete queues from RabbitMQ"""
    with LazyChannel() as channel:
        for name in queues:
            RabbitQueue(name, channel).delete()


def is_empty(queue):
    with LazyChannel() as channel:
        queue = RabbitQueue(queue, channel)
        return len(queue) == 0


@contextmanager
def run_kuyruk(queue='kuyruk', save_failed_tasks=False, terminate=True,
               process='worker'):
    assert not_running()
    args = [
        sys.executable, '-u',
        '-m', 'kuyruk.__main__',  # run main module
        '--max-load', '999',  # do not pause because of load
    ]
    args.extend(['--logging-level=DEBUG'])
    if save_failed_tasks:
        args.extend(['--save-failed-tasks', 'True'])

    args.append(process)
    if process == 'worker':
        args.extend(['--queue', queue])

    environ = os.environ.copy()
    environ['COVERAGE_PROCESS_START'] = 'kuyruk/test/coveragerc'

    popen = What(*args, preexec_fn=os.setsid, env=environ)
    popen.timeout = TIMEOUT
    try:
        yield popen

        if terminate:
            # Send SIGTERM to worker for gracefull shutdown
            popen.terminate()
            popen.expect("End run %s" % process)

        popen.expect_exit()

    finally:
        # We need to make sure that not any process of kuyruk is running
        # after the test is finished.

        # Kill master process and wait until it is dead
        try:
            popen.kill()
            popen.wait()
        except OSError as e:
            if e.errno != errno.ESRCH:  # No such process
                raise

        logger.debug('Worker return code: %s', popen.returncode)

        # Kill worker processes by sending SIGKILL to their process group id
        try:
            logger.info('Killing process group: %s', popen.pid)
            os.killpg(popen.pid, signal.SIGTERM)
        except OSError as e:
            if e.errno != errno.ESRCH:  # No such process
                raise

        try:
            wait_while(lambda: get_pids('kuyruk:'))
        except KeyboardInterrupt:
            print popen.get_output()
            # Do not raise KeyboardInterrupt here because nose does not print
            # captured stdout and logging on KeyboardInterrupt
            raise Exception


def not_running():
    return not is_running()


def is_running():
    return bool(get_pids('kuyruk:'))


def run_requeue():
    args = [
        sys.executable, '-u',
        '-m', 'kuyruk.__main__',
        '--logging-level=DEBUG',
        'requeue'
    ]
    w = What(*args)
    w.expect_exit(0, TIMEOUT)


def get_pids(pattern):
    logger.debug('get_pids: %s', pattern)
    cmd = "pgrep -fl '%s'" % pattern
    p = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE)
    out = p.communicate()[0]
    logger.debug("\n%s", out)
    lines = out.splitlines()
    # filter pgrep itself. travis runs it like: "/bin/sh -c pgrep -fl 'kuyruk:'"
    lines = filter(lambda x: not cmd in x, lines)
    pids = [int(l.split()[0]) for l in lines]  # take first column
    logger.debug('pids: %s', pids)
    return pids


def get_pid(pattern):
    pids = get_pids(pattern)
    assert len(pids) == 1
    return pids[0]


def wait_until(f, timeout=None):
    return wait_while(lambda: not f(), timeout)


def wait_while(f, timeout=None):
    do_while(partial(sleep, 0.1), f, timeout)


def do_until(f_do, f_cond, timeout=None):
    do_while(f_do, lambda: not f_cond(), timeout)


def do_while(f_do, f_condition, timeout=None):
    def should_do():
        if timeout and timeout < 0:
            raise Timeout
        return f_condition()

    original_timeout = timeout
    start = time()
    while should_do():
        f_do()
        if timeout:
            passed = time() - start
            timeout = original_timeout - passed


class Timeout(Exception):
    pass
