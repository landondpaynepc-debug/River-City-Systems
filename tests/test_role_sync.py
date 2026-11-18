import asyncio, os
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import verification as v

async def test():
    role=NS(id=v.JOIN_ROLE,name='Unverified')
    member=NS(id=42,bot=False,roles=[role],get_role=lambda n:role if n==v.JOIN_ROLE else None)
    guild=NS(id=v.GUILD,members=[member])
    service=object.__new__(v.Verification)
    service.bot=NS(is_ready=lambda:True,get_guild=lambda n:guild)
    service.busy=set();service.sync_due={};service.sync_queue=set()
    service.accounts=NS(lookup=AsyncMock(return_value=None))
    with patch.dict(os.environ,{'BLOXLINK_API_KEY':'test'}), patch.object(v,'apply_verified_roles',AsyncMock()) as apply:
        await v.Verification.sync_roles.coro(service)
        apply.assert_not_called()
        assert service.sync_due[42]>0
        service.accounts.lookup.return_value=123
        await service.on_member_update(NS(roles=[]),NS(**{**member.__dict__,'guild':guild}))
        assert 42 in service.sync_queue and service.sync_due[42]==0
        await v.Verification.sync_roles.coro(service)
        apply.assert_awaited_once_with(guild,42,123)
        assert not service.busy
    print('PASS: pending members scanned, unlinked users blocked, Bloxlink role changes trigger recheck, linked members reconciled')
asyncio.run(test())
