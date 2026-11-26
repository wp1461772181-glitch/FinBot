import test from 'node:test';
import assert from 'node:assert/strict';
import {dispatchAgentAction} from '../src/agent-client-actions.mjs';
test('client action is validated, dispatched once and deduplicates a stream replay',()=>{
 const values=new Map(),events=[];
 const host={sessionStorage:{getItem:k=>values.get(k),setItem:(k,v)=>values.set(k,v)},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},dispatchEvent:e=>events.push(e)};
 const data={id:'11111111-1111-4111-8111-111111111111',action:'queue_add',symbol:'MU'};
 assert.equal(dispatchAgentAction(data,host),true);
 assert.equal(dispatchAgentAction(data,host),false);
 assert.equal(events.length,1);
 assert.equal(events[0].detail.symbol,'MU');
 assert.equal(dispatchAgentAction({...data,id:'22222222-2222-4222-8222-222222222222',symbol:'<script>'},host),false);
 assert.equal(dispatchAgentAction({...data,id:'33333333-3333-4333-8333-333333333333',action:'delete_database'},host),false);
});
test('stream replay stays idempotent when session storage is unavailable',()=>{
 const events=[];
 const host={sessionStorage:{getItem(){throw Error('disabled')},setItem(){throw Error('disabled')}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},dispatchEvent:e=>events.push(e)};
 const action={id:'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',action:'queue_remove',symbol:'AMD'};
 assert.equal(dispatchAgentAction(action,host),true);
 assert.equal(dispatchAgentAction(action,host),false);
 assert.equal(events.length,1);
});
test('open_page can name the memory page (4e) and still refuses a page it does not know',()=>{
 const events=[];
 const host={sessionStorage:{getItem(){return null},setItem(){}},CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail}},dispatchEvent:e=>events.push(e)};
 assert.equal(dispatchAgentAction({id:'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',action:'open_page',page:'memory'},host),true);
 assert.equal(events[0].detail.page,'memory');
 assert.equal(dispatchAgentAction({id:'cccccccc-cccc-4ccc-8ccc-cccccccccccc',action:'open_page',page:'passwords'},host),false);
});
