import asyncio, json, time, os
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import voice_guard as v

async def test():
    member=NS(id=55, voice=None)
    channel=NS(id=v.LOG_CHANNEL)
    guild=NS(get_channel=lambda n:channel, get_member=lambda n:member)
    service=NS(accounts=NS(lookup=AsyncMock(return_value=123)))
    stored=[]
    class Message:
        def __init__(self,content): self.content=content; self.author=NS(id=1)
        async def edit(self,**kw): self.content=kw['content']
    async def send(content,**kw):
        m=Message(content)
        if content.startswith(v.PREFIX): stored.insert(0,m)
        return m
    async def history(**kw):
        for m in stored: yield m
    room=NS(send=send, history=history)
    bot=NS(is_ready=lambda:True,get_guild=lambda n:guild,intents=NS(voice_states=True),
           receipt_channel=AsyncMock(return_value=room),user=NS(id=1),get_cog=lambda n:service)
    g=object.__new__(v.VoiceGuard)
    g.bot=bot;g.owner='test';g.missing={};g.links={};g.backoff=0;g.started=False
    g.linked_member=AsyncMock(return_value=member)
    g.audit=AsyncMock()
    async def api(path,params=None,command=None):
        return {'Players':[{'Player':'Tester:123'}], 'CommandLogs':[]} if not command else {'message':'Success'}
    g.api=AsyncMock(side_effect=api)
    with patch.dict(os.environ,{'BLOXLINK_API_KEY':'test','ERLC_SERVER_KEY':'test'}):
        await v.VoiceGuard.poll.coro(g)
        assert not any(c.kwargs.get('command') for c in g.api.call_args_list), 'grace failed'
        g.missing[123]=time.monotonic()-65
        await v.VoiceGuard.poll.coro(g)
        assert [c.kwargs.get('command') for c in g.api.call_args_list if c.kwargs.get('command')]==[':jail Tester']
        row=json.loads(stored[0].content[len(v.PREFIX):]);assert row['state']=='active'
        await v.VoiceGuard.poll.coro(g)
        assert len([c for c in g.api.call_args_list if c.kwargs.get('command')])==1
        row['due']=time.time()-1;await g.save(stored[0],row)
        # Simulate restart: no local missing state is needed to release.
        g.missing.clear()
        await v.VoiceGuard.poll.coro(g)
        assert g.api.call_args_list[-1].kwargs.get('command')==':unjail Tester'
        await v.VoiceGuard.poll.coro(g)
        assert len([c for c in g.api.call_args_list if c.kwargs.get('command')])==2, 'repeated punishment'
        member.voice=NS(channel=NS(id=99))
        await v.VoiceGuard.poll.coro(g)
        assert await g.records(room)=={}, 'cleared record resurrected'
        await v.VoiceGuard.poll.coro(g)
        assert not g.missing
    assert v.manual_override({'started':100,'name':'Tester'},[{'Timestamp':150,'Command':':jail Test'}])
    assert not v.manual_override({'started':100,'name':'Tester'},[{'Timestamp':101,'Command':':jail Tester'}])
    assert v.player_map({'Players':[{'Player':'all:123;bad'}]})=={}
    print('PASS: grace, jail, duplicate prevention, restart release, no repeat until compliance, VC exemption, durable clear, staff override, target validation')
asyncio.run(test())
