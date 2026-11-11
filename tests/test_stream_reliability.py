"""Streaming accepts only complete responses; retries never expose partial actions."""
import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from werewolf import providers as p
from werewolf.chat_stream import read_chat_stream, StreamError
from werewolf.strict_tools import strict_tools
import test_thinking_tools as thinking
response = thinking.response


def stream(chunks, done=True):
    return io.BytesIO(b': heartbeat\n\n'+b''.join(b'data: '+json.dumps(c).encode()+b'\n\n' for c in chunks)+(b'data: [DONE]\n\n' if done else b''))


def chunks_for(calls, reasoning='secret reasoning'):
    return [{'model':'deepseek-flash','choices':[{'index':0,'delta':{
        'reasoning_content':reasoning,'tool_calls':[{**call,'index':i} for i,call in enumerate(calls)]}}]},
        {'choices':[{'index':0,'delta':{},'finish_reason':'tool_calls'}],
         'usage':{'prompt_tokens':10,'completion_tokens':8}}]


class StreamReliabilityTests(unittest.TestCase):
    def test_fragmented_tools_and_usage_are_assembled_only_after_done(self):
        parts=[{'choices':[{'delta':{'tool_calls':[{'index':0,'id':'c','type':'function','function':{'name':'action_','arguments':'{"te'}}]}}]},
               {'choices':[{'delta':{'reasoning_content':'PRIVATE','tool_calls':[{'index':0,'function':{'name':'speak','arguments':'xt":"你好"}'}}]}}]},
               {'choices':[{'delta':{},'finish_reason':'tool_calls'}],'usage':{'prompt_tokens':9,'completion_tokens':3}}]
        result=read_chat_stream(stream(parts),1e30)
        call=result['choices'][0]['message']['tool_calls'][0]
        self.assertEqual('action_speak',call['function']['name'])
        self.assertEqual({'text':'你好'},json.loads(call['function']['arguments']))
        self.assertEqual(9,result['usage']['prompt_tokens'])
        self.assertNotIn('PRIVATE',json.dumps(result['_transport']))
        with self.assertRaises(StreamError):read_chat_stream(stream(parts,False),1e30)
        with self.assertRaises(TimeoutError):read_chat_stream(stream(parts),0)

    def test_transport_retries_are_logged_but_auth_is_not_retried(self):
        config=p.deepseek_flash_config(1,'P')
        request={'model':'deepseek-flash','stream':True,'tools':[{'function':{'strict':True}}]}
        reply=response('action_pass',{},'private')
        calls=reply['choices'][0]['message']['tool_calls']
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'KEY_NEVER_LOG'}),patch.object(p.time,'sleep'), \
             patch.object(p.http,'urlopen',side_effect=[TimeoutError('SECRET'),stream(chunks_for(calls))]) as network:
            result=p._send_http(config,request,attempts=3)
        self.assertEqual(2,network.call_count)
        self.assertEqual(2,len(result['_transport']['attempts']))
        self.assertNotIn('SECRET',json.dumps(result['_transport']))
        with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'KEY_NEVER_LOG'}), \
             patch.object(p.http,'urlopen',side_effect=HTTPError('url',401,'SECRET',{},None)) as network:
            with self.assertRaises(p.ProviderError) as failure:p._send_http(config,request,attempts=3)
        self.assertEqual(1,network.call_count)
        self.assertNotIn('SECRET',str(failure.exception))
        self.assertEqual(401,failure.exception.validation_details['transport']['attempts'][0]['http_status'])

    def test_strict_schemas_require_declared_fields_and_constrain_public_text(self):
        fixture=thinking.ThinkingToolsTests();config=fixture.config()
        request=fixture.assembled(config)
        tools=strict_tools(p._seat_harness(request).tools())
        for tool in tools:
            f=tool['function'];self.assertTrue(f['strict'])
            self.assertEqual(list(f['parameters']['properties']),f['parameters']['required'])
            self.assertFalse(f['parameters']['additionalProperties'])
        v13=p.build_request(config,request['tool_context']['observation'],{'kind':'speech','options':[{'type':'speak'}]},)
        self.assertEqual('player-tools-v13',v13['prompt_version'])
        wire=p.wire_request(config,v13)
        self.assertTrue(wire['stream'])
        text=next(t for t in wire['tools'] if t['function']['name']=='action_speak')['function']['parameters']['properties']['text']
        self.assertIn('pattern',text);self.assertNotIn('maxLength',text)

    def test_action_note_pair_is_atomic_in_either_native_order_and_auditable(self):
        from scripts.audit_tools import audit_records
        fixture=thinking.ThinkingToolsTests();config=fixture.config()
        old=fixture.assembled(config)
        for reverse in (False,True):
            request=p.build_request(config,old['tool_context']['observation'],old['tool_context']['decision'],tool_prompt_version='player-tools-v13')
            action=response('action_pass',{},'')['choices'][0]['message']['tool_calls'][0]
            note=response('write_my_notes',{'notes':'private plan'},'')['choices'][0]['message']['tool_calls'][0]
            note['id']='note'
            calls=[action,note] if reverse else [note,action]
            with patch.dict(os.environ,{'DEEPSEEK_API_KEY':'synthetic'}), \
                 patch.object(p.http,'urlopen',return_value=stream(chunks_for(calls))):
                result=p.decide(config,request)
            self.assertEqual({'type':'pass','notes':'private plan'},dict(result))
            audit=audit_records({1:config},[{'request':request,'seat':1,'accepted':True,'response':dict(result),'tool_trace':result.tool_trace}])
            self.assertEqual(1,audit['action_calls'])
            self.assertNotIn('secret reasoning',json.dumps(result.tool_trace))


if __name__=='__main__':unittest.main()
