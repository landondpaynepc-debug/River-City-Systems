import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import verification as v

async def run():
    assert v.parse_roblox_id({'robloxID':'123'}) == 123
    for invalid in ({}, {'robloxID':True}, {'robloxID':0}, {'robloxID':'invalid'}):
        assert v.parse_roblox_id(invalid) is None
    with patch.dict(v.os.environ, {'BLOXLINK_API_KEY':''}):
        try:
            await v.Bloxlink().lookup(123)
            raise AssertionError('Missing key should block verification')
        except v.VerificationUnavailable:
            pass
    pending, verified = SimpleNamespace(id=v.JOIN_ROLE,name='Unverified',managed=False,permissions=SimpleNamespace(administrator=False),is_assignable=lambda:True), SimpleNamespace(id=v.VERIFIED_ROLE,name='Community Member')
    member=SimpleNamespace(roles=[pending], add_roles=AsyncMock(), remove_roles=AsyncMock())
    member.add_roles.side_effect = lambda role, **kw: member.roles.append(role)
    member.remove_roles.side_effect = lambda role, **kw: member.roles.remove(role)
    guild=SimpleNamespace(id=v.GUILD, roles=[pending,verified], fetch_member=AsyncMock(return_value=member))
    interaction=SimpleNamespace(guild=guild, user=SimpleNamespace(id=42,bot=False),
        response=SimpleNamespace(defer=AsyncMock()), followup=SimpleNamespace(send=AsyncMock()))
    service=SimpleNamespace(busy=set(),cooldowns={},accounts=SimpleNamespace(lookup=AsyncMock(return_value=None)))
    view=v.VerificationView(service)
    assert view.is_persistent()
    with patch.object(v,'roles_for',return_value=(pending,verified)):
        await view.check.callback(interaction)
        member.add_roles.assert_not_called()
        service.cooldowns.clear()
        service.accounts.lookup.return_value=456
        await view.check.callback(interaction)
        member.remove_roles.assert_awaited_once()
        member.add_roles.assert_awaited_once_with(verified,reason='Bloxlink verified Roblox ID 456')
    import app
    assert app.JOIN_ROLE == 1572082428678373436
    assert app.bot.get_command('cmds')
    await app.bot.add_cog(v.Verification(app.bot))
    assert app.bot.get_command('verify')
    await app.bot.remove_cog('Verification')
    print('PASS: missing-key and unlinked-account gates, strict account IDs, verified role transition, persistent buttons, command registration')

asyncio.run(run())
