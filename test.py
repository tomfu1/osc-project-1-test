#!/usr/bin/env python3

import collections
from concurrent.futures import ThreadPoolExecutor
import glob
import json
import logging
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile

COMPILE_FLAGS = '-Wall -Werror -O -std=gnu99'
PROGRAM = 'dash'
TEST_DIR = 'test'
TEST_TIMEOUT = 10

if sys.stdout.isatty():
    GREEN = '\033[1;32m'
    RED = '\033[1;31m'
    RESET = '\033[0m'
else:
    GREEN = ''
    RED = ''
    RESET = ''


Result = collections.namedtuple('Result', 'id errors')
Testcase = collections.namedtuple('Testcase', 'desc id input out err code sort stdin')
Testcase.__new__.__defaults__ = (0, False, False)

def run(args):
    logging.info('Preparing test directory ...')
    os.makedirs(TEST_DIR, exist_ok=True)

    try:
        for i in range(1, 5):
            with open(os.path.join(TEST_DIR, f'test{i}'), 'w'):
                pass

        logging.info(f'Compiling `{PROGRAM}` ...')
        results = [compile_program()]

        testcases = get_testcases(args.config)
        logging.info(f'Found {len(testcases)} testcases.')

        with ThreadPoolExecutor(max_workers=min(multiprocessing.cpu_count(), len(testcases))) as e:
            results.extend(e.map(run_testcase, testcases))

        for result in results:
            if result.errors:
                print(result_summary(result))
                for error in result.errors:
                    if isinstance(error['expected'], str):
                        expected = '\n      '.join(error['expected'].splitlines())
                        received = '\n      '.join(error['received'].splitlines())
                    else:
                        expected = error['expected']
                        received = error['received']
                    print(f'  {error["kind"]}\n    expected\n      {expected}\n    received\n      {received}\n')

        for result in results:
            print(result_summary(result))

    finally:
        shutil.rmtree(TEST_DIR, ignore_errors=True)

def compile_program():
    code, out, err = shell(f'gcc -o {PROGRAM} {PROGRAM}.c {COMPILE_FLAGS}')

    return Result(id=0, errors=mk_errors(
        code=code,
        out=out,
        err=err,
        expected_code=0,
        expected_out='',
        expected_err='',
    ))

def get_testcases(config):
    with open(config) as fd:
        return [Testcase(**kwargs) for kwargs in json.load(fd)]

def mk_errors(code, out, err, expected_code, expected_out, expected_err):
    errors = []

    if code != expected_code:
        errors.append({ 'kind': 'code', 'expected': expected_code, 'received': code })

    if out != expected_out:
        errors.append({ 'kind': 'stdout', 'expected': expected_out, 'received': out })

    if err != expected_err:
        errors.append({ 'kind': 'stderr', 'expected': expected_err, 'received': err })
    
    return errors

def result_summary(result):
    if result.errors:
        kinds = ', '.join([e['kind'] for e in result.errors])
        return f'Testcase {result.id}: {RED}FAIL{RESET} ({kinds})'
    return f'Testcase {result.id}: {GREEN}PASS{RESET}'

def shell(command):
    try:
        process = subprocess.run(
            command,
            check=True,
            encoding='utf8',
            shell=True,
            stderr=subprocess.PIPE,
            stdout=subprocess.PIPE,
            timeout=TEST_TIMEOUT
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
        out = e.stdout.strip()
        err = e.stderr.strip()
        try:
            code = e.returncode
        except AttributeError:
            code = -1
    else:
        out = process.stdout.strip()
        err = process.stderr.strip()
        code = process.returncode

    return code, out, err

def run_testcase(testcase):
    logging.info(f'Executing testcase {testcase.id} ...')

    if 'FAKE_FILE' in testcase.input:
        args = 'some_non_existent_file'
        if 'MULTIPLE' in testcase.input: args += ' another_non_existent_file'

        code, out, err = shell(f'./{PROGRAM} {args}')
        return Result(id=testcase.id, errors=mk_errors(
            code=code,
            out=out,
            err=err,
            expected_code=testcase.code,
            expected_out=testcase.out.strip(),
            expected_err=testcase.err.strip(),
        ))

    with tempfile.NamedTemporaryFile() as tmp:
        tmp.write(testcase.input.encode())
        tmp.flush()

        redirection = '< ' if testcase.stdin else ''
        code, out, err = shell(f'./{PROGRAM} {redirection}{tmp.name}')

        if testcase.sort:
            out = '\n'.join(sorted(out.splitlines()))
            expected_out = '\n'.join(sorted(testcase.out.splitlines()))
            err = '\n'.join(sorted(err.splitlines()))
            expected_err = '\n'.join(sorted(testcase.err.splitlines()))
        else:
            expected_out = testcase.out.strip()
            expected_err = testcase.err.strip()

        return Result(id=testcase.id, errors=mk_errors(
            code=code,
            out=out,
            err=err,
            expected_code=testcase.code,
            expected_out=expected_out,
            expected_err=expected_err,
        ))

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--config', default='test.json')
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    run(args)
