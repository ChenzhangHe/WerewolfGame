"""DeepSeek beta strict schema adapter; host validation remains authoritative."""
from copy import deepcopy


def strict_tools(tools):
    def schema(value):
        result = {k: deepcopy(v) for k, v in value.items() if k not in ('minLength', 'maxLength', 'minItems', 'maxItems')}
        if result.get('type') == 'object':
            result['properties'] = {k: schema(v) for k, v in result.get('properties', {}).items()}
            result['required'] = list(result['properties'])
            result['additionalProperties'] = False
        if 'items' in result:
            result['items'] = schema(result['items'])
        if 'anyOf' in result:
            result['anyOf'] = [schema(v) for v in result['anyOf']]
        return result
    result = deepcopy(tools)
    for tool in result:
        function = tool['function']
        function['strict'] = True
        function['parameters'] = schema(function['parameters'])
        for field, limit in (('notes', 2000), ('query', 200)):
            if field in function['parameters']['properties']:
                function['parameters']['properties'][field]['pattern'] = r'^[\s\S]{'+('0' if field == 'notes' else '1')+','+str(limit)+'}$'
        if function['name'] in ('action_speak', 'action_discuss'):
            function['parameters']['properties']['text']['pattern'] = '^[^<>]{1,1200}$'
    return result
