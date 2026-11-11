"""Bad native calls receive feedback, not action repair or private-note commits."""
from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from werewolf import providers as p
from werewolf.native_transaction import execute
from scripts.audit_tools import audit_records
import test_thinking_tools as thinking


def call(name,args,identifier='call'):
    return {'id':identifier,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}


class NativeTransactionTests(unittest.TestCase):
    def request(self,decision=None):
        fixture=thinking.ThinkingToolsTests();config=fixture.config()
        old=fixture.assembled(config)['tool_context']
        return config,p.build_request(config,old['observation'],decision or old['decision'],'original notes',tool_prompt_version='player-tools-v14')

    def test_empty_function_has_explicit_confirm_and_wrappers_are_rejected_atomically(self):
        config,request=self.request()
        harness=p._seat_harness(request);tools=p.wire_request(config,request)['tools']
        offered=next(t for t in tools if t['function']['name']=='action_pass')
        self.assertEqual(['confirm'],offered['function']['parameters']['required'])
        calls=[call('write_my_notes',{'notes':'MUST_ROLL_BACK'},'n'),call('action_pass',{'parameters':{}})]
        result=execute(harness,calls,tools,remaining_utilities=12)
        self.assertIsNotNone(result.rejection);self.assertIsNone(result.action)
        self.assertEqual({'notes':'original notes'},result.harness.call('read_my_notes',{}))
        self.assertFalse(result.results[-1]['result']['action_accepted'])
        accepted=execute(result.harness,[call('action_pass',{'confirm':True})],tools,remaining_utilities=11)
        self.assertIsNone(accepted.rejection)
        self.assertEqual({'type':'pass'},accepted.action)
        first=execute(harness,[call('write_my_notes',{'notes':'earlier staged plan'})],tools,remaining_utilities=12)
        bad=execute(first.harness,calls,tools,remaining_utilities=11)
        final=execute(bad.harness,[call('action_pass',{'confirm':True})],tools,remaining_utilities=10)
        self.assertEqual('earlier staged plan',final.action['notes'])

    def test_model_corrects_its_own_call_after_exact_feedback_and_audit_catches_tampering(self):
        config,request=self.request()
        count=0
        def send(config,body,**kwargs):
            nonlocal count
            count+=1
            if count==1:
                result=thinking.response('action_pass',{'parameters':{}},'PRIVATE_FIRST')
            else:
                errors=[m for m in body['messages'] if m['role']=='tool']
                self.assertEqual('invalid_tool_arguments',json.loads(errors[-1]['content'])['error']['code'])
                self.assertEqual('PRIVATE_FIRST',[m for m in body['messages'] if m['role']=='assistant'][-1]['reasoning_content'])
                result=thinking.response('action_pass',{'confirm':True},'PRIVATE_SECOND')
            return result
        with patch.object(p,'_send_http',side_effect=send):
            result=p.decide(config,request)
        self.assertEqual(2,count);self.assertEqual({'type':'pass'},dict(result))
        record={'seat':1,'request':request,'response':dict(result),'accepted':True,'tool_trace':result.tool_trace}
        report=audit_records({1:config},[record]);self.assertEqual(1,report['validation_rejections'])
        self.assertEqual('{"parameters": {}}',record['tool_trace'][0]['assistant']['tool_calls'][0]['function']['arguments'])
        self.assertNotIn('PRIVATE_FIRST',json.dumps(result.tool_trace))
        altered=deepcopy(record);altered['tool_trace'][0]['tool_results'][0]['result']={'secret':'another seat'}
        with self.assertRaisesRegex(AssertionError,'transaction results'):
            audit_records({1:config},[altered])

    def test_private_dump_or_multiple_actions_never_commit_and_feedback_is_bounded(self):
        config,request=self.request({'kind':'speech','options':[{'type':'speak'}]})
        def send(config,body,**kwargs):
            return thinking.response('action_speak',{'text':'public</text><parameter name="notes">PRIVATE'},'not archived')
        with patch.object(p,'_send_http',side_effect=send) as network:
            with self.assertRaises(p.ProviderError) as error:p.decide(config,request)
        self.assertEqual(3,network.call_count)
        self.assertEqual('tool_validation_budget',error.exception.validation_details['category'])
        for hop in error.exception.tool_trace:
            self.assertFalse(hop['tool_results'][0]['result']['action_accepted'])
        record={'seat':1,'request':request,'response':{},'accepted':False,'error':str(error.exception),
                'validation_details':error.exception.validation_details,'tool_trace':error.exception.tool_trace}
        self.assertEqual(3,audit_records({1:config},[record])['validation_rejections'])
        h=p._seat_harness(request);tools=p.wire_request(config,request)['tools']
        result=execute(h,[call('action_speak',{'text':'first'},'a'),call('action_speak',{'text':'second'},'b')],tools,remaining_utilities=12)
        self.assertEqual('mixed_terminal_tools',result.rejection['code']);self.assertIsNone(result.action)


if __name__=='__main__':unittest.main()
