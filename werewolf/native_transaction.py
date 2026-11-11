"""Atomic, seat-local native tool transactions with explicit rejection feedback.

No argument repair: only the documented confirm=True transport field is removed.
All calls execute on a draft capability; a rejected transaction changes nothing.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

MAX_FEEDBACK = 2


@dataclass
class Transaction:
    harness: object
    results: list
    action: dict | None
    utilities: int
    execution_order: list
    rejection: dict | None = None


def execute(harness, calls, offered, *, remaining_utilities):
    from .providers import ProviderError, validate_action
    definitions = {t['function']['name']: t['function']['parameters'] for t in offered}
    actions = [c for c in calls if harness.is_action(c['function']['name'])]
    utilities = sum(not harness.is_action(c['function']['name']) for c in calls)
    bad_index, reason, fields = 0, None, []
    if len(actions) > 1 or (actions and any(c['function']['name'] != 'write_my_notes' and c not in actions for c in calls)):
        reason = 'mixed_terminal_tools'
    elif actions and len(calls) > 2:
        reason = 'mixed_terminal_tools'
    elif utilities > remaining_utilities:
        reason = 'utility_budget_exceeded'
    draft, results, terminal = deepcopy(harness), [], None
    ordered = sorted(enumerate(calls), key=lambda pair: harness.is_action(pair[1]['function']['name'])) if actions else list(enumerate(calls))
    for index, call in ordered:
        if reason:
            break
        bad_index = index
        name, raw = call['function']['name'], call['function']['arguments']
        definition = definitions.get(name)
        if definition is None:
            reason = 'tool_not_offered'
            break
        fields = list(definition.get('properties', {}))
        try:
            arguments = draft._arguments(raw)
            if set(arguments) != set(fields):
                raise ValueError('Use the declared top-level fields.')
            for field, spec in definition.get('properties', {}).items():
                if 'pattern' in spec and (not isinstance(arguments[field], str) or re.fullmatch(spec['pattern'], arguments[field]) is None):
                    raise ValueError('Field does not match its declared pattern.')
            if fields == ['confirm']:
                if arguments != {'confirm': True} or arguments['confirm'] is not True:
                    raise ValueError('confirm must be true.')
                arguments = {}
            result = draft.call(name, arguments)
            if draft.is_action(name):
                validate_action(result, draft._decision)
                terminal = result
            results.append({'name': name, 'arguments': raw, 'result': result})
        except (ValueError, ProviderError):
            reason = 'invalid_tool_arguments'
            break
    if reason:
        results = []
        for index, call in enumerate(calls):
            error = {'code': reason if index == bad_index else 'transaction_rejected',
                     'message': 'No calls in this transaction were applied. Use exactly the offered top-level argument fields; submit a new native call.'}
            if index == bad_index and fields:
                error['expected_fields'] = fields
            results.append({'name': call['function']['name'], 'arguments': call['function']['arguments'],
                            'result': {'error': error, 'action_accepted': False}})
        return Transaction(harness, results, None, utilities, [], {'code': reason, 'call_index': bad_index})
    return Transaction(draft, results, terminal, utilities,
                       [c['function']['name'] for _, c in ordered])
