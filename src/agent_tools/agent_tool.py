"""Shared entry point for the individual agent-facing tools."""
import argparse
import json
import sys
import time

import agent_cli


def main(operation, argv=None):
    parser = argparse.ArgumentParser(description=agent_cli.OPERATIONS[operation]['description'])
    parser.add_argument('--input', help='UTF-8 JSON input file; default stdin')
    parser.add_argument('--pretty', action='store_true', help='Indent the JSON response')
    parser.add_argument('--describe', action='store_true', help='Describe this tool and its arguments')
    args = parser.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except (AttributeError, OSError):
        pass
    try:
        if args.describe:
            request = {'operation': 'describe', 'arguments': {'operation': operation}}
        else:
            if args.input:
                with open(args.input, encoding='utf-8-sig') as file:
                    data = json.load(file)
            else:
                data = json.load(sys.stdin)
            if not isinstance(data, dict):
                raise ValueError('Input must be a JSON object')
            # A simple object is the arguments; the envelope form additionally
            # permits request_id and limits without reserving argument names.
            if 'arguments' in data:
                unknown = set(data) - {'arguments', 'limits', 'request_id', 'interface_version'}
                if unknown:
                    raise ValueError('Unknown envelope keys: ' + ', '.join(sorted(unknown)))
                request = dict(data, operation=operation)
            else:
                request = {'operation': operation, 'arguments': data}
        response = agent_cli.run_request(request)
    except (ValueError, OSError) as exc:
        response = agent_cli._error_response(None, operation, 'invalid_request', str(exc), time.monotonic())
    print(json.dumps(agent_cli._clean(response), ensure_ascii=False, allow_nan=False,
                     indent=2 if args.pretty else None))
    if response['status'] == 'error':
        return 1 if response['error']['code'] in ('invalid_request', 'unknown_operation') else 2
    return 0
