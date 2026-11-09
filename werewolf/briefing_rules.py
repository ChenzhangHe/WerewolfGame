"""Compact public rules; never derived from secret assignments."""

CORE_RULES = {
    'en': [
        'Lineup: four Wolves, four Villagers, one Seer, Witch, Hunter and Idiot. No Guard or White Wolf King. Claims are not referee reveals.',
        'Wolves jointly attack one living seat each night, including a teammate or themselves, or abstain. Night actions finish before deaths are announced. A player alive at night start can act even if attacked that night.',
        'Witch has one antidote and one poison, at most one potion per night, never self-save. Only while antidote remains does she see the current wolf target. Spending antidote does not spend poison. Seer learns good/wolf privately, not an exact role.',
        'Day-one election precedes dawn. Only those who originally declined nomination can vote for Sheriff; withdrawing does not create voting rights. No eligible voters or no votes means no Sheriff. One runoff; a second tie means no Sheriff.',
        'Sheriff has a 1.5-weight exile ballot, chooses the legal speech direction and speaks last. Badge transfer on death is not automatic sharing of private Seer results. Without Sheriff the public speech order is seeded.',
        'Ordinary exile is simultaneous, published only after all votes lock. Self-vote and abstention are legal. Tied candidates speak, then voters except those candidates vote again; a second tie means no exile.',
        'Only first exile formally reveals the Idiot and prevents that death, then permanently removes voting and exile eligibility. Self-claiming Idiot does none of this. A living revealed Idiot still speaks and counts as a living special role.',
        'Death never automatically reveals role or cause. Public ability events reveal only their actor. Hunter can shoot after attack/exile, not poison. First-night and ordinary daytime exile victims have last words; later night victims do not. Dead players get no later results or actions beyond permitted death abilities/last words.',
        'Self-explosion only in offered windows: actor reveals Wolf and permanently dies, remaining day speech/exile is skipped after required resolution. No last words, future wolf chat, attack participation or bonus kill. Two explosions during an unfinished election destroy the badge; explosions after election do not swallow an absent badge.',
        'Good wins when all Wolves die. Wolves win when all four Villagers OR all four special roles die; parity is not victory. A living Idiot is not dead. Attack-first victory can end the game before poison or Hunter shooting. No automatic early win for a proposed future kill path.',
    ],
    'zh': [
        '配置：四狼、四民、预言家、女巫、猎人、白痴各一；没有守卫或白狼王。玩家自称身份不等于法官翻牌。',
        '每夜狼队共同袭击一名存活者（可刀队友或自己），或空刀。夜间行动全部完成后才公布死讯；夜初存活者即使当夜被刀仍可行动。',
        '女巫各一瓶解药与毒药，每夜至多一药、不能自救。仅解药尚存时知道本夜刀口；用掉解药不等于用掉毒药。预言家只私下得到好人或狼人结果，不得知精确角色。',
        '首日警长竞选在天亮死讯之前。仅最初未上警者可投警徽票；退水不产生投票权。没有选民或有效票则无警长；一次平票PK，再平票无警长。',
        '警长放逐票1.5票，选择合法发言方向并最后发言。出局移交警徽不自动共享预言家私密验人。无警长时法官以公开的种子顺序安排发言。',
        '正常放逐同时投票，全部锁票后才公布；允许自投与弃票。同票者PK后，除同票候选人外的选民再投；再次同票无人出局。',
        '白痴首次真正被放逐才由法官翻牌免死，此后不能投票或被放逐，仍存活、能发言并算存活神职。自称或自行“亮牌”不会触发免死或失去投票权。',
        '死亡不自动公布身份或死因；公开技能只确认发动者。猎人被刀或放逐可开枪，中毒不能开枪。首夜死者和正常白天放逐者有遗言，后续夜死者没有。死者完成允许的技能与遗言后不再接收新结果或行动。',
        '仅提供窗口时可自爆：本人公开狼人并永久死亡，必要结算后跳过本日剩余发言与放逐；无遗言、不能以后狼聊刀人、没有额外一刀。未完成竞选中双爆吞徽；竞选结束后自爆没有吞掉已不存在警徽的收益。',
        '狼全死则好人胜；四民全死或四神全死则狼胜，人数相等不判胜，活着的白痴不算死亡。狼刀在先可能在毒药、猎人开枪前结束游戏；设想的未来刀路不等于已经获胜。',
    ],
}
